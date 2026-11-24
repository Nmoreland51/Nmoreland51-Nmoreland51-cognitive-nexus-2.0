"""A task's own environment: what may be installed, that it really installs, and that it is reused.

The package comes from a folder of ready-built packages made in the test, so no network is used.
Creating a virtual environment takes several seconds, so the real installs share one module-wide setup.
"""

from __future__ import annotations

import base64
import hashlib
import subprocess
import threading
import zipfile
from pathlib import Path

import pytest

from agent import environment
from agent.approvals import ApprovalPolicy
from agent.coder import default_agent
from agent.environment import environment_for, lines_outside_the_index, missing_module, package_policy, read_requirements, register_environment_tools
from agent.model import ScriptedModel
from agent.registry import ToolContext, ToolRegistry
from agent.store import AgentStore
from agent.tools import register_coding_tools
from agent.workspace import WorkspaceManager

FIX = "The operator is wrong.\n\nFILE: calc.py\n<<<<<<< SEARCH\n    return tinyhelper.plus(a, b) - 1\n=======\n    return tinyhelper.plus(a, b)\n>>>>>>> REPLACE\n"


def git(folder: Path, *arguments: str) -> str:
    done = subprocess.run(["git", *arguments], cwd=folder, capture_output=True, text=True, check=True)
    return done.stdout.strip()


def make_wheel(folder: Path, name: str = "tinyhelper", version: str = "1.0") -> Path:
    """A ready-built package, written by hand: one module with one function."""

    folder.mkdir(parents=True, exist_ok=True)
    files = {
        f"{name}/__init__.py": "def plus(a, b):\n    return a + b\n",
        f"{name}-{version}.dist-info/METADATA": f"Metadata-Version: 2.1\nName: {name}\nVersion: {version}\n",
        f"{name}-{version}.dist-info/WHEEL": "Wheel-Version: 1.0\nGenerator: test\nRoot-Is-Purelib: true\nTag: py3-none-any\n",
    }
    record = []
    for path, text in files.items():
        digest = base64.urlsafe_b64encode(hashlib.sha256(text.encode()).digest()).rstrip(b"=").decode()
        record.append(f"{path},sha256={digest},{len(text.encode())}")
    record.append(f"{name}-{version}.dist-info/RECORD,,")
    files[f"{name}-{version}.dist-info/RECORD"] = "\n".join(record) + "\n"
    wheel = folder / f"{name}-{version}-py3-none-any.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        for path, text in files.items():
            archive.writestr(path, text)
    return wheel


def make_repo(folder: Path, requirements: str = "tinyhelper==1.0\n") -> Path:
    folder.mkdir(parents=True)
    (folder / "calc.py").write_text("import tinyhelper\n\n\ndef add(a, b):\n    return tinyhelper.plus(a, b) - 1\n", encoding="utf-8")
    (folder / "test_calc.py").write_text("from calc import add\n\n\ndef test_add():\n    assert add(2, 3) == 5\n", encoding="utf-8")
    if requirements:
        (folder / "requirements.txt").write_text(requirements, encoding="utf-8")
    git(folder, "init", "-q", "-b", "main")
    git(folder, "config", "user.email", "test@example.com")
    git(folder, "config", "user.name", "Test")
    git(folder, "add", "-A")
    git(folder, "commit", "-q", "-m", "start")
    return folder


class World:
    def __init__(self, base: Path, requirements: str = "tinyhelper==1.0\n", **settings):
        self.repo = make_repo(base / "repo", requirements)
        self.wheels = base / "wheels"
        make_wheel(self.wheels)
        self.store = AgentStore(base / "agent.db")
        self.workspaces = WorkspaceManager(base / "ws")
        self.settings = {"agent_package_index": str(self.wheels), "agent_environments_dir": str(base / "envs"), **settings}
        self.task = self.store.create_task("Fix add", repo=str(self.repo), acceptance=[["python", "-m", "pytest", "-q", "-p", "no:cacheprovider", "test_calc.py"]])
        self.checkout = self.workspaces.create(self.repo, self.task.id, "Fix add")
        self.registry = register_environment_tools(register_coding_tools(ToolRegistry()))
        self.context = ToolContext(
            store=self.store,
            policy=ApprovalPolicy("trusted"),
            workspace=self.checkout.path,
            task_id=self.task.id,
            session="s1",
            cancel=threading.Event(),
            settings=dict(self.settings, acceptance=self.task.acceptance),
            workspaces=self.workspaces,
            checkout=self.checkout,
        )

    def setup(self, **arguments):
        return self.registry.call("setup_environment", arguments, self.context)


@pytest.fixture(scope="module")
def installed(tmp_path_factory) -> World:
    """One world in which the environment was really created and the package really installed."""

    world = World(tmp_path_factory.mktemp("env"))
    world.first = world.setup()
    return world


# ---- the policy, without installing anything -------------------------------------------------------


def test_the_policy_is_declared_unless_the_owner_says_otherwise():
    assert package_policy({}) == "declared"
    assert package_policy({"agent_package_policy": "ANY"}) == "any"
    assert package_policy({"agent_package_policy": "whatever"}) == "declared"  # an unknown value is the careful one


def test_requirement_files_are_read_with_the_files_they_include(tmp_path):
    (tmp_path / "requirements").mkdir()
    (tmp_path / "requirements" / "base.txt").write_text("requests>=2\n# a comment\n\nrich  # trailing comment\n", encoding="utf-8")
    (tmp_path / "requirements" / "dev.txt").write_text("-r base.txt\npytest>=8\n-c base.txt\n", encoding="utf-8")

    lines = read_requirements(tmp_path, "requirements/dev.txt")

    assert [text for _file, _number, text in lines] == ["requests>=2", "rich", "pytest>=8"]
    assert lines[0][0] == "requirements/base.txt" and lines[2][:2] == ("requirements/dev.txt", 2)
    with pytest.raises(environment.ToolError):
        read_requirements(tmp_path, "../outside.txt")


def test_lines_that_leave_the_package_index_are_recognised():
    lines = [
        ("r.txt", 1, "requests>=2,<3"),
        ("r.txt", 2, "numpy==2.1 ; python_version >= '3.11'"),
        ("r.txt", 3, "git+https://example.org/evil.git"),
        ("r.txt", 4, "--extra-index-url https://example.org/simple"),
        ("r.txt", 5, "-e ."),
        ("r.txt", 6, "pkg @ https://example.org/pkg.whl"),
        ("r.txt", 7, "./local/pkg"),
        ("r.txt", 8, "--trusted-host example.org"),
    ]

    flagged = lines_outside_the_index(lines)

    assert [item.split(":")[0] for item in flagged] == [f"r.txt line {n}" for n in (3, 4, 5, 6, 7, 8)]


def test_a_missing_module_is_recognised_in_test_output():
    assert missing_module("E   ModuleNotFoundError: No module named 'tinyhelper'") == "tinyhelper"
    assert missing_module("ImportError: No module named yaml") == "yaml"
    assert missing_module("AssertionError: assert 4 == 5") == ""


def test_switched_off_nothing_is_installed(tmp_path):
    world = World(tmp_path, agent_package_policy="off")

    result = world.setup()

    assert not result.ok and "switched off" in result.error
    assert environment_for(world.task.id, world.settings["agent_environments_dir"]) is None


def test_requirements_the_task_itself_wrote_are_not_installed_under_the_default_policy(tmp_path):
    """The model could otherwise list any package it likes and have it installed."""

    world = World(tmp_path)
    (Path(world.checkout.path) / "requirements.txt").write_text("tinyhelper==1.0\nsomething-else\n", encoding="utf-8")

    changed = world.setup()
    assert not changed.ok and "changed in this task" in changed.error

    (Path(world.checkout.path) / "requirements.txt").write_text("tinyhelper==1.0\n", encoding="utf-8")
    (Path(world.checkout.path) / "extra.txt").write_text("anything\n", encoding="utf-8")
    new_file = world.setup(requirements=["extra.txt"])
    assert not new_file.ok and "new or was changed" in new_file.error


def test_requirements_that_leave_the_index_are_refused_under_the_default_policy(tmp_path):
    world = World(tmp_path, requirements="tinyhelper==1.0\ngit+https://example.org/evil.git\n")

    result = world.setup()

    assert not result.ok and "somewhere other than the package index" in result.error and "line 2" in result.error


def test_a_repository_without_requirements_says_so(tmp_path):
    world = World(tmp_path, requirements="")

    assert "no requirement file" in world.setup().error


def test_the_tool_is_a_network_action_with_a_schema_and_follows_the_owners_setting(tmp_path):
    registry = register_environment_tools(ToolRegistry())
    tool = registry.get("setup_environment")

    assert tool.effect == "network" and tool.adapter == "environment" and tool.verify is not None
    world = World(tmp_path)
    # "Ask before every change": it waits for the owner. "Read only": refused.
    world.context.policy = ApprovalPolicy.from_settings({"agent_autonomy": "ask_first"})
    assert world.setup().status == "needs_approval"
    world.context.policy = ApprovalPolicy.from_settings({"agent_autonomy": "read_only"})
    assert world.setup().status == "denied"


# ---- really installing -------------------------------------------------------------------------------


def test_the_environment_is_created_and_the_package_is_really_importable_in_it(installed):
    result = installed.first

    assert result.ok and result.verified is True, result.error
    assert result.data["installed"] == ["tinyhelper==1.0"] and result.data["policy"] == "declared"
    python = Path(result.data["python"])
    assert python.is_file() and Path(installed.settings["agent_environments_dir"]) in python.parents
    # The task's commands now use that interpreter, and the package is there.
    assert installed.context.settings["agent_python"] == str(python)
    ran = installed.registry.call("run_command", {"argv": ["python", "-c", "import tinyhelper; print(tinyhelper.plus(2, 3))"]}, installed.context)
    assert ran.ok and "5" in ran.output
    # The app's own interpreter does not have it: nothing was installed outside the task's environment.
    with pytest.raises(ModuleNotFoundError):
        __import__("tinyhelper")


def test_asking_again_with_nothing_changed_reuses_it_without_installing(installed):
    marker = Path(installed.first.data["folder"]) / environment.MARKER
    before = marker.stat().st_mtime_ns

    again = installed.setup(requirements=["requirements.txt"])

    assert again.ok and again.data["reused"] is True and "Nothing was downloaded" in again.output
    assert marker.stat().st_mtime_ns == before
    record = environment_for(installed.task.id, installed.settings["agent_environments_dir"])
    assert record["key"] == installed.first.data["key"] and record["installed"] == ["tinyhelper==1.0"]


def test_the_environment_and_what_was_installed_are_in_the_task_history(installed):
    actions = [action for action in installed.store.actions(installed.task.id) if action["tool"] == "setup_environment"]

    assert actions and actions[0]["status"] == "ok" and actions[0]["effect"] == "network"


def test_a_task_whose_tests_need_a_package_gets_it_installed_and_is_then_fixed(tmp_path):
    """The whole loop: the tests cannot import a package, the agent installs the repository's
    requirements into the task's own environment, the real failure shows, and it is fixed."""

    base = World(tmp_path)  # only for its repository and its folder of packages
    store = AgentStore(tmp_path / "loop.db")
    agent = default_agent(
        store,
        ScriptedModel([FIX]),
        model_review=False,
        workspaces=WorkspaceManager(tmp_path / "loop-ws"),
        settings={"agent_package_index": str(base.wheels), "agent_environments_dir": str(tmp_path / "loop-envs")},
    )
    task = store.create_task("Fix add", repo=str(base.repo), acceptance=[["python", "-m", "pytest", "-q", "-p", "no:cacheprovider", "test_calc.py"]])

    done = agent.run(task.id)

    assert done.status == "review", done.result
    kinds = [event["kind"] for event in store.events(task.id)]
    assert "environment" in kinds and kinds.index("environment") < kinds.index("reproduced")
    tools = {action["tool"] for action in store.actions(task.id)}
    assert {"setup_environment", "replace_in_file", "commit_changes"} <= tools
    assert "return tinyhelper.plus(a, b)\n" in git(base.repo, "show", f"{done.branch}:calc.py") + "\n"
    # The tests ran with the task's own interpreter, which has the app's test runner and the installed package.
    record = environment_for(task.id, str(tmp_path / "loop-envs"))
    assert record is not None and record["installed"] == ["tinyhelper==1.0"]


def test_with_installing_switched_off_the_task_goes_to_a_person_naming_the_missing_module(tmp_path):
    base = World(tmp_path)
    store = AgentStore(tmp_path / "off.db")
    agent = default_agent(
        store,
        ScriptedModel([FIX]),
        model_review=False,
        workspaces=WorkspaceManager(tmp_path / "off-ws"),
        settings={"agent_package_policy": "off", "agent_environments_dir": str(tmp_path / "off-envs")},
    )
    task = store.create_task("Fix add", repo=str(base.repo), acceptance=[["python", "-m", "pytest", "-q", "-p", "no:cacheprovider", "test_calc.py"]])

    done = agent.run(task.id)

    assert done.status == "escalated" and done.result["reason_code"] == "environment"
    assert "tinyhelper" in done.result["reason"] and "switched off" in done.result["reason"]
