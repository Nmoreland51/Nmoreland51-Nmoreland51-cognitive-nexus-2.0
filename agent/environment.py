"""An environment of its own for a task: a virtual environment with the packages the repository asks for.

A task whose tests need packages that are not installed could not be worked on at all. This sets
one up, under a policy the owner chooses (setting `agent_package_policy`):

    declared   (default) install only what the repository's own requirement files list, as they
               were before the task started; from the package index only; ready-built packages
               only, so nothing from a package is run in order to install it
    any        also accept requirement files the task changed, and lines that point at URLs,
               version-control repositories or other indexes
    off        install nothing

What an installed package does when the tests import it is the same risk as running the
repository's own code, and is contained the same way: the environment is created and used inside
the sandbox (agent/sandbox.py).

Reproducible: the environment is keyed by the content of the requirement files, the interpreter
version and the index. Asked again with nothing changed, it is reused without touching the network,
and what was installed is recorded with exact versions. Downloads are kept in a cache per repository.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

from agent import sandbox
from agent.registry import Tool, ToolContext, ToolError, ToolRegistry, ToolResult
from agent.store import AGENT_DIR

ENVS_DIR = Path(os.environ.get("COGNITIVE_NEXUS_AGENT_ENVS", "").strip() or (AGENT_DIR / "envs"))
CACHE_DIR = AGENT_DIR / "cache" / "pip"
PACKAGE_POLICIES = ("declared", "any", "off")
MARKER = "agent-environment.json"
# Looked for, in this order, when a task does not say which files to install from.
USUAL_FILES = ("requirements.txt", "requirements/dev.txt", "requirements-dev.txt", "requirements/test.txt", "requirements-test.txt", "dev-requirements.txt")
MISSING_MODULE = re.compile(r"ModuleNotFoundError: No module named ['\"]([\w.]+)['\"]|ImportError: No module named ([\w.]+)")
_INCLUDE = re.compile(r"^\s*(?:-r|--requirement|-c|--constraint)[=\s]+(\S+)")
# Lines that fetch from somewhere other than the package index, or change where the index is.
_OUTSIDE_THE_INDEX = re.compile(
    r"^\s*(?:-e\b|--editable\b|-i\b|--index-url\b|--extra-index-url\b|-f\b|--find-links\b|--trusted-host\b|--pre\b|--no-binary\b|--prefer-binary\b)"
    r"|://|^\s*(?:git|hg|svn|bzr)\+|^\s*[./\\]|^\s*[A-Za-z]:[\\/]|\s@\s",
    re.IGNORECASE,
)


def package_policy(settings: dict[str, Any]) -> str:
    value = str(settings.get("agent_package_policy") or "declared").strip().lower()
    return value if value in PACKAGE_POLICIES else "declared"


def environment_dir(task_id: str, root: Path | None = None) -> Path:
    return Path(root or ENVS_DIR) / re.sub(r"[^A-Za-z0-9_.-]", "_", task_id)


def python_in(folder: Path) -> Path:
    return folder / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")


def environment_for(task_id: str, root: Path | None = None) -> dict[str, Any] | None:
    """The record of a task's environment when one was set up and its interpreter is still there."""

    folder = environment_dir(task_id, root)
    try:
        record = json.loads((folder / MARKER).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return record if Path(str(record.get("python", ""))).is_file() else None


def usual_requirement_files(workspace: Path) -> list[str]:
    return [name for name in USUAL_FILES if (Path(workspace) / name).is_file()][:1]


def read_requirements(workspace: Path, relative: str, _seen: set[str] | None = None) -> list[tuple[str, int, str]]:
    """Every meaningful line of a requirement file and of the files it includes, as (file, line number, text)."""

    seen = _seen if _seen is not None else set()
    workspace = Path(workspace).resolve()
    target = (workspace / relative).resolve()
    if workspace not in target.parents:
        raise ToolError(f"{relative} is outside the task's folder.")
    name = target.relative_to(workspace).as_posix()
    if name in seen:
        return []
    seen.add(name)
    try:
        text = target.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        raise ToolError(f"{name} cannot be read: {exc}") from exc
    lines: list[tuple[str, int, str]] = []
    for number, raw in enumerate(text.splitlines(), 1):
        line = raw.split(" #", 1)[0].strip()
        if not line or line.startswith("#"):
            continue
        included = _INCLUDE.match(line)
        if included:
            nested = (target.parent / included.group(1)).resolve()
            if workspace not in nested.parents:
                raise ToolError(f"{name} line {number} includes a file outside the task's folder.")
            lines.extend(read_requirements(workspace, nested.relative_to(workspace).as_posix(), seen))
            continue
        lines.append((name, number, line))
    return lines


def lines_outside_the_index(lines: list[tuple[str, int, str]]) -> list[str]:
    """Requirement lines that fetch from somewhere other than the package index, described for a person."""

    return [f"{name} line {number}: {text[:80]}" for name, number, text in lines if _OUTSIDE_THE_INDEX.search(text)]


def changed_since_start(context: ToolContext, files: set[str]) -> list[str]:
    """Requirement files that are new or different from the commit the task started from."""

    manager, checkout = context.workspaces, context.checkout
    changed = []
    for name in sorted(files):
        same = manager.git(checkout, ["diff", "--quiet", checkout.base_commit, "--", name], check=False).returncode == 0
        known = manager.git(checkout, ["cat-file", "-e", f"{checkout.base_commit}:{name}"], check=False).returncode == 0
        if not (same and known):
            changed.append(name)
    return changed


def environment_key(lines: list[tuple[str, int, str]], index: str) -> str:
    body = "\n".join(text for _name, _number, text in lines)
    return hashlib.sha256(f"{sys.version_info[:3]}\x00{index}\x00{body}".encode("utf-8")).hexdigest()[:20]


def site_packages_of(folder: Path) -> Path:
    if sys.platform == "win32":
        return folder / "Lib" / "site-packages"
    return folder / "lib" / f"python{sys.version_info.major}.{sys.version_info.minor}" / "site-packages"


def inherit_from_the_app(folder: Path) -> list[str]:
    """Let the task's environment also use what the app's own Python has installed.

    A new virtual environment is empty: it would not even have the test runner the acceptance
    tests are started with. The app's packages are added after the environment's own, so anything
    the repository's requirements install takes precedence over them. (Setting
    agent_environment_inherits = false leaves the environment empty apart from the requirements.)
    """

    import site

    own = site_packages_of(folder).resolve()
    parents = [str(Path(path).resolve()) for path in site.getsitepackages() if Path(path).name == "site-packages" and Path(path).is_dir()]
    parents = [path for path in dict.fromkeys(parents) if Path(path) != own]
    if parents and own.is_dir():
        (own / "_cognitive_nexus_app_packages.pth").write_text("\n".join(parents) + "\n", encoding="utf-8")
    return parents


def _index_arguments(index: str) -> list[str]:
    if not index:
        return []
    if Path(index).is_dir():
        return ["--no-index", "--find-links", str(Path(index).resolve())]
    return ["--index-url", index]


def setup_environment(context: ToolContext, requirements: list[str] | None = None) -> ToolResult:
    """Create (or reuse) the task's virtual environment and install the repository's requirements into it."""

    if context.workspaces is None or context.checkout is None:
        raise ToolError("This tool needs a task workspace, and none is open.")
    settings = context.settings
    policy = package_policy(settings)
    if policy == "off":
        raise ToolError("Installing packages is switched off (setting agent_package_policy). The task has to work with what is installed.")
    workspace = Path(context.checkout.path)
    files = [str(name) for name in (requirements or usual_requirement_files(workspace))]
    if not files:
        raise ToolError(f"The repository has no requirement file ({', '.join(USUAL_FILES[:3])}, ...), and none was named.")
    seen: set[str] = set()
    lines: list[tuple[str, int, str]] = []
    for name in files:
        lines.extend(read_requirements(workspace, name, seen))
    if not lines:
        raise ToolError(f"{', '.join(files)} lists no packages.")
    if policy == "declared":
        changed = changed_since_start(context, seen)
        if changed:
            raise ToolError(
                f"{', '.join(changed)} is new or was changed in this task. Under the 'declared' policy only requirements that were in the "
                "repository before the task started are installed. A person can install them, or set agent_package_policy to 'any'."
            )
        outside = lines_outside_the_index(lines)
        if outside:
            raise ToolError(
                "These lines fetch from somewhere other than the package index, which the 'declared' policy does not do: " + "; ".join(outside[:5])
            )
    index = str(settings.get("agent_package_index") or "").strip()
    key = environment_key(lines, index)
    folder = environment_dir(context.task_id, settings.get("agent_environments_dir"))
    python = python_in(folder)
    existing = environment_for(context.task_id, settings.get("agent_environments_dir"))
    if existing and existing.get("key") == key:
        settings["agent_python"] = str(python)
        return ToolResult(
            ok=True,
            output=f"The task's environment is already set up from {', '.join(files)} ({len(existing.get('installed', []))} packages). Nothing was downloaded.",
            data={**existing, "reused": True},
        )

    limits = sandbox.Limits(
        seconds=float(settings.get("agent_install_seconds", 900)),
        memory_mb=int(settings.get("agent_memory_mb", 2048)),
        processes=int(settings.get("agent_processes", 64)),
        output_chars=int(settings.get("agent_output_chars", 200_000)),
    )
    cache = CACHE_DIR / hashlib.sha256(str(context.checkout.repo).encode("utf-8")).hexdigest()[:16]
    for writable in (folder, cache):
        sandbox.prepare_workspace(writable)  # the sandboxed installer may write here, and only here and in the task's folder

    def run(argv: list[str], network: bool) -> sandbox.RunResult:
        try:
            return sandbox.run(argv, workspace, limits=limits, allow_network=network, cancel=context.cancel)
        except sandbox.SandboxError as exc:
            raise ToolError(str(exc)) from exc

    if not python.is_file():
        made = run([str(settings.get("agent_base_python") or sys.executable), "-m", "venv", str(folder)], network=False)
        if not made.ok or not python.is_file():
            raise ToolError(f"The virtual environment could not be created: {made.combined()[-800:]}")
        if settings.get("agent_environment_inherits", True):
            inherit_from_the_app(folder)
    command = [
        str(python), "-m", "pip", "install", "--isolated", "--no-input", "--disable-pip-version-check",
        "--cache-dir", str(cache), *_index_arguments(index),
    ]  # fmt: skip
    if policy == "declared":
        command.append("--only-binary=:all:")  # ready-built packages only: nothing from a package runs to install it
    for name in files:
        command += ["-r", name]
    installed = run(command, network=not (index and Path(index).is_dir()))
    if context.cancel.is_set():
        return ToolResult(ok=False, status="cancelled", error="Cancelled while installing.")
    if not installed.ok:
        why = installed.combined()[-1500:]
        hint = ""
        if "No matching distribution" in why or "Could not find a version" in why:
            hint = " A package may have no ready-built version for this Python; under the 'declared' policy packages are not built from source."
        return ToolResult(ok=False, error=f"pip could not install the requirements ({installed.stopped or 'exit code ' + str(installed.exit_code)}).{hint}\n{why}")
    # --local: only what is in the task's own environment, not what it can see of the app's.
    frozen = run([str(python), "-m", "pip", "freeze", "--local", "--isolated", "--disable-pip-version-check"], network=False)
    packages = sorted(line.strip() for line in frozen.stdout.splitlines() if line.strip() and not line.startswith("#"))
    record = {
        "key": key,
        "python": str(python),
        "folder": str(folder),
        "requirement_files": files,
        "policy": policy,
        "index": index or "the default package index",
        "installed": packages,
        "seconds": round(installed.seconds, 1),
        "isolation": installed.isolation,
    }
    (folder / MARKER).write_text(json.dumps(record, indent=1), encoding="utf-8")
    settings["agent_python"] = str(python)
    return ToolResult(
        ok=True,
        output=f"Set up the task's environment from {', '.join(files)}: {len(packages)} packages installed in {installed.seconds:.0f} s.\n" + "\n".join(packages[:60]),
        data={**record, "reused": False},
    )


def _environment_ready(context: ToolContext, arguments: dict[str, Any], result: ToolResult) -> tuple[bool, str]:
    """Believed only when the environment's own interpreter starts and reports its folder."""

    python = Path(str(result.data.get("python", "")))
    if not python.is_file() or context.checkout is None:
        return False, "the environment's interpreter is not there"
    probe = sandbox.run([str(python), "-c", "import sys; print(sys.prefix)"], Path(context.checkout.path), limits=sandbox.Limits(seconds=60))
    inside = probe.ok and Path(probe.stdout.strip()).resolve() == Path(str(result.data.get("folder", ""))).resolve()
    return inside, "the environment's interpreter runs" if inside else "the environment's interpreter does not run from its folder"


def register_environment_tools(registry: ToolRegistry) -> ToolRegistry:
    registry.register(
        Tool(
            "setup_environment",
            "Create the task's own virtual environment and install the repository's requirement files into it, under the owner's installation policy.",
            {
                "type": "object",
                "properties": {"requirements": {"type": "array", "items": {"type": "string", "maxLength": 300}, "maxItems": 8}},
                "additionalProperties": False,
            },
            "network",
            setup_environment,
            adapter="environment",
            verify=_environment_ready,
            summarize=lambda arguments: "install the repository's requirements into the task's own environment",
        )
    )
    return registry


def missing_module(test_output: str) -> str:
    """The module a test run could not import, or "" when the failure is something else."""

    match = MISSING_MODULE.search(test_output or "")
    return (match.group(1) or match.group(2) or "") if match else ""


__all__ = [
    "ENVS_DIR",
    "PACKAGE_POLICIES",
    "environment_for",
    "missing_module",
    "package_policy",
    "read_requirements",
    "register_environment_tools",
    "setup_environment",
    "usual_requirement_files",
]
