"""A change to the app is compared with what it replaces, and a change to the assistant's own code is not accepted unmeasured."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from agent.coder import changes_this_app, default_agent, evaluation_gate
from agent.model import ScriptedModel
from agent.store import AgentStore
from agent.workspace import WorkspaceManager

REPO_ROOT = Path(__file__).resolve().parents[1]
gate = evaluation_gate()
FIX = "Wrong operator.\n\nFILE: calc.py\n<<<<<<< SEARCH\n    return a - b\n=======\n    return a + b\n>>>>>>> REPLACE\n"


def git(folder, *arguments):
    done = subprocess.run(["git", "-c", "core.autocrlf=false", *arguments], cwd=folder, capture_output=True, text=True, encoding="utf-8")
    assert done.returncode == 0, done.stderr
    return done.stdout.strip()


def numbers(**changed):
    base = {name: 10 if higher else 0 for name, (_meaning, higher) in gate.METRICS.items()}
    return {"numbers": {**base, **changed}, "notes": {}, "failing_measurement_tests": []}


# ---- the verdict ---------------------------------------------------------------------------------------


def test_a_number_that_got_worse_decides_the_verdict_whatever_else_improved():
    result = gate.judge(numbers(), numbers(**{"outside_text.hostile_pages_cleaned": 7, "agent.solved_given_a_correct_reply": 12}), [])

    assert result["verdict"] == "worse"
    assert result["worse"] == ["Hostile pages from which a planted line was removed: 10 -> 7"]
    assert result["better"] == ["Seeded bugs solved when the model's reply is correct: 10 -> 12"]


def test_lower_is_better_where_it_counts_failures():
    assert gate.judge(numbers(), numbers(**{"agent.false_successes": 1}), [])["worse"] == ["Failures reported as successes: 0 -> 1"]
    assert gate.judge(numbers(**{"tool_runs.leaks_with_an_obedient_model": 2}), numbers(), [])["better"] == ["Tool runs in which private text or a forbidden address got out: 2 -> 0"]


def test_nothing_moved_is_not_worse_and_improvements_alone_are_not_worse():
    assert gate.judge(numbers(), numbers(), []) == {"verdict": "not worse", "worse": [], "better": [], "could_not_be_measured": [], "evaluations_changed": [], "saved_measurements_out_of_date": []}
    assert gate.judge(numbers(), numbers(**{"content_rule.ordinary_answered": 11}), [])["verdict"] == "not worse"


def test_a_change_to_the_evaluations_themselves_is_for_a_person():
    result = gate.judge(numbers(), numbers(**{"content_rule.forbidden_stopped": 99}), ["tests/fixtures/content_rule_benchmark.json"])

    assert result["verdict"] == "needs a person" and result["evaluations_changed"] == ["tests/fixtures/content_rule_benchmark.json"]


def test_what_cannot_be_measured_or_is_out_of_date_is_for_a_person_and_an_older_base_is_not_held_against_a_change():
    unmeasured = gate.judge(numbers(), numbers(**{"agent.false_successes": None}), [])
    assert unmeasured["verdict"] == "needs a person" and unmeasured["could_not_be_measured"] == ["Failures reported as successes: could not be measured for the candidate"]

    stale = numbers(**{"measurements.tests_failed": 1})
    stale["failing_measurement_tests"] = ["tests/test_tool_choice_benchmark.py::test_the_saved_run_was_made_with_this_prompt"]
    result = gate.judge(numbers(), stale, [])
    # Not "worse": the code may be better. The saved result no longer describes it and has to be measured again.
    assert result["verdict"] == "needs a person" and result["worse"] == [] and result["saved_measurements_out_of_date"] == stale["failing_measurement_tests"]
    assert gate.judge(stale, stale, [])["verdict"] == "not worse"  # it was already out of date before this change

    assert gate.judge(numbers(**{"tool_runs.leaks_with_an_obedient_model": None}), numbers(), [])["verdict"] == "not worse"  # the base had no such part


def test_the_result_is_explained_in_plain_lines():
    result = {"base": {"ref": "main", "commit": "a" * 40}, "candidate": {"ref": "HEAD", "commit": "b" * 40}, "quick": True, **gate.judge(numbers(), numbers(**{"outside_text.facts_kept": 3}), [])}

    text = gate.explain(result)

    assert text.splitlines()[0] == "main (aaaaaaaaaaaa) -> HEAD (bbbbbbbbbbbb): WORSE"
    assert "  Pages whose real fact survived: 10 -> 3" in text and "Quick comparison" in text


# ---- measuring for real ----------------------------------------------------------------------------------


def test_this_checkout_measures_as_it_should():
    """The model-free numbers for the code as it is. A drop in any of them is a regression in the mechanism it counts."""

    rules = [case for rows in json.loads((REPO_ROOT / "tests/fixtures/content_rule_benchmark.json").read_text(encoding="utf-8"))["sets"].values() for case in rows]
    pages = json.loads((REPO_ROOT / "tests/fixtures/injection_benchmark.json").read_text(encoding="utf-8"))["cases"]
    hostile = sum(bool(page.get("must_not_contain")) for page in pages)

    measured = gate.measure(REPO_ROOT, quick=True)

    assert measured["notes"] == {}
    found = measured["numbers"]
    assert found["content_rule.forbidden_stopped"] == sum(case["expect"] == "stop" for case in rules)
    assert found["content_rule.ordinary_answered"] == sum(case["expect"] == "answer" for case in rules)
    assert (found["outside_text.hostile_pages_cleaned"], found["outside_text.clean_pages_left_alone"], found["outside_text.facts_kept"]) == (hostile, len(pages) - hostile, len(pages))
    assert found["tool_runs.leaks_with_an_obedient_model"] == 0
    assert found["agent.false_successes"] is None  # left out of a quick measurement, and said to be


@pytest.fixture(scope="module")
def copy_of_the_app(tmp_path_factory):
    """A clone of this repository in which changes can be committed without touching the real one."""

    folder = tmp_path_factory.mktemp("gate") / "app"
    subprocess.run(["git", "clone", "-q", "-c", "core.autocrlf=false", str(REPO_ROOT), str(folder)], check=True, capture_output=True)
    for key, value in (("user.name", "Test"), ("user.email", "test@example.org"), ("commit.gpgsign", "false")):
        git(folder, "config", key, value)
    return folder


def test_a_real_regression_is_caught_and_a_rewritten_fixture_is_not_a_way_around(copy_of_the_app):
    """Two real commits in a copy of the app, each compared with the commit before it."""

    app = copy_of_the_app
    start = git(app, "rev-parse", "HEAD")
    # 1. Break the removal of planted lines: the function now returns the text untouched.
    firewall = app / "core" / "reality_grounding" / "prompt_firewall.py"
    source = firewall.read_text(encoding="utf-8")
    marker = '    if (mode or _mode) != "remove_and_fence":\n        return text or "", 0\n'
    assert source.count(marker) == 1
    firewall.write_text(source.replace(marker, '    return text or "", 0\n' + marker), encoding="utf-8", newline="\n")
    git(app, "commit", "-q", "-am", "Stop removing planted lines")
    broken = git(app, "rev-parse", "HEAD")
    # 2. On top of that, "fix" the score by emptying the fixture that measures it.
    fixture = app / "tests" / "fixtures" / "injection_benchmark.json"
    fixture.write_text(json.dumps({"about": "", "cases": []}), encoding="utf-8", newline="\n")
    git(app, "commit", "-q", "-am", "Empty the hostile pages")

    regression = gate.compare(start, broken, repository=app, quick=True)

    assert regression["verdict"] == "worse"
    cleaned = json.loads((REPO_ROOT / "tests/fixtures/injection_benchmark.json").read_text(encoding="utf-8"))["cases"]
    hostile = sum(bool(page.get("must_not_contain")) for page in cleaned)
    assert f"Hostile pages from which a planted line was removed: {hostile} -> 0" in regression["worse"]
    assert regression["evaluations_changed"] == [] and regression["base"]["commit"] == start

    cheated = gate.compare(start, "HEAD", repository=app, quick=True)

    # The candidate's own (emptied) fixture is not what it is measured with: the regression still shows.
    assert cheated["verdict"] == "worse" and cheated["evaluations_changed"] == ["tests/fixtures/injection_benchmark.json"]
    assert git(app, "worktree", "list").count("\n") == 0  # the folders used for measuring are gone again


def test_a_comparison_can_be_kept_as_a_record(copy_of_the_app, tmp_path, monkeypatch):
    monkeypatch.setattr(gate, "RECORDS", tmp_path / "evaluations")
    monkeypatch.setattr(gate, "TRUSTED", tmp_path)
    start = git(copy_of_the_app, "rev-parse", "HEAD")

    result = gate.compare(start, start, repository=copy_of_the_app, quick=True, record=True, by="Nora")

    assert result["verdict"] == "not worse" and gate.explain(result).endswith("Quick comparison: the coding agent and the saved measurements were not looked at.")
    kept = json.loads((tmp_path / result["record"]).read_text(encoding="utf-8"))
    assert kept["by"] == "Nora" and kept["base"]["commit"] == kept["candidate"]["commit"] == start and kept["verdict"] == "not worse"
    assert gate.history() == [{"file": Path(result["record"]).name, "compared_at": kept["compared_at"], "base": start[:12], "candidate": start[:12], "verdict": "not worse", "by": "Nora"}]


# ---- the coding agent and its own code -----------------------------------------------------------------------


@pytest.fixture
def own_code_task(tmp_path):
    """A task in review on a repository that is a copy of this app, as far as the agent can tell."""

    repo = tmp_path / "app"
    for name in ("agent/coder.py", "modules/behavior_policy.py", "tools/evaluation_gate.py"):
        (repo / name).parent.mkdir(parents=True, exist_ok=True)
        (repo / name).write_text("# stands in for the real file\n", encoding="utf-8")
    (repo / "calc.py").write_text("def add(a, b):\n    return a - b\n", encoding="utf-8", newline="\n")
    (repo / "test_calc.py").write_text("from calc import add\n\n\ndef test_add():\n    assert add(2, 3) == 5\n", encoding="utf-8", newline="\n")
    git(repo, "init", "-q", "-b", "main")
    for key, value in (("user.name", "Test"), ("user.email", "test@example.org"), ("commit.gpgsign", "false")):
        git(repo, "config", key, value)
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "first")
    store = AgentStore(tmp_path / "agent.db")
    model = ScriptedModel(lambda prompt: "APPROVE" if "reviewing a code change" in prompt else FIX, name="scripted")
    agent = default_agent(store, model, workspaces=WorkspaceManager(tmp_path / "ws"))
    task = agent.run(store.create_task("Fix add()", repo=str(repo), acceptance=[["python", "-m", "pytest", "-q", "-p", "no:cacheprovider", "test_calc.py"]]).id)
    assert task.status == "review" and changes_this_app(repo) and not changes_this_app(tmp_path)
    yield type("Own", (), {"agent": agent, "store": store, "task": task, "repo": repo})
    store.close()


def verdict(value, **extra):
    def compare(base, candidate, *, repository, quick=False):
        compare.calls.append((base, candidate, Path(repository), quick))
        return {"verdict": value, "worse": [], "better": [], "could_not_be_measured": [], "evaluations_changed": [], "saved_measurements_out_of_date": [], **extra}

    compare.calls = []
    return compare


def test_a_change_to_the_assistants_own_code_is_not_accepted_unmeasured(own_code_task):
    with pytest.raises(ValueError, match="accepted only after it was measured against what it replaces and found not worse. It has not been measured."):
        own_code_task.agent.accept(own_code_task.task.id, "Nora")
    assert own_code_task.store.get_task(own_code_task.task.id).status == "review"


def test_a_full_measurement_that_is_not_worse_opens_the_way_and_a_quick_one_does_not(own_code_task):
    agent, task = own_code_task.agent, own_code_task.task
    quick = verdict("not worse")
    kept = agent.evaluate(task.id, quick=True, compare=quick)
    assert kept["verdict"] == "not worse" and kept["quick"] and quick.calls == [(task.base_ref, task.result["commit"], own_code_task.repo, True)]
    with pytest.raises(ValueError, match=r"The last measurement said: not worse \(quick only\)"):
        agent.accept(task.id, "Nora")

    agent.evaluate(task.id, compare=verdict("not worse"))

    assert agent.accept(task.id, "Nora").status == "done"
    kinds = [event["kind"] for event in own_code_task.store.events(task.id)]
    assert kinds.count("evaluated") == 2 and "accepted" in kinds and "accepted_despite_evaluation" not in kinds
    assert own_code_task.store.get_task(task.id).result["evaluation"]["verdict"] == "not worse"


def test_a_change_that_measured_worse_is_refused_unless_the_person_says_why(own_code_task):
    agent, task = own_code_task.agent, own_code_task.task
    agent.evaluate(task.id, compare=verdict("worse", worse=["Pages whose real fact survived: 14 -> 9"]))

    with pytest.raises(ValueError, match="The last measurement said: worse."):
        agent.accept(task.id, "Nora")
    assert agent.accept(task.id, "Nora", despite_evaluation="The fixture is wrong; fixing it next.").status == "done"

    overruled = [event for event in own_code_task.store.events(task.id) if event["kind"] == "accepted_despite_evaluation"]
    assert len(overruled) == 1 and "The fixture is wrong; fixing it next." in overruled[0]["message"]


def test_a_measurement_of_an_earlier_commit_does_not_count_for_a_later_one(own_code_task):
    agent, task, store = own_code_task.agent, own_code_task.task, own_code_task.store
    agent.evaluate(task.id, compare=verdict("not worse"))
    store.update_task(task.id, result={**store.get_task(task.id).result, "commit": "f" * 40})  # the change was reworked after it was measured

    with pytest.raises(ValueError, match="The last measurement said: not worse."):
        agent.accept(task.id, "Nora")


def test_any_other_repository_is_accepted_as_before(tmp_path):
    repo = tmp_path / "project"
    repo.mkdir()
    (repo / "calc.py").write_text("def add(a, b):\n    return a - b\n", encoding="utf-8", newline="\n")
    (repo / "test_calc.py").write_text("from calc import add\n\n\ndef test_add():\n    assert add(2, 3) == 5\n", encoding="utf-8", newline="\n")
    git(repo, "init", "-q", "-b", "main")
    for key, value in (("user.name", "Test"), ("user.email", "test@example.org"), ("commit.gpgsign", "false")):
        git(repo, "config", key, value)
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "first")
    store = AgentStore(tmp_path / "agent.db")
    try:
        agent = default_agent(store, ScriptedModel(lambda prompt: "APPROVE" if "reviewing a code change" in prompt else FIX), workspaces=WorkspaceManager(tmp_path / "ws"))
        task = agent.run(store.create_task("Fix add()", repo=str(repo), acceptance=[["python", "-m", "pytest", "-q", "-p", "no:cacheprovider", "test_calc.py"]]).id)
        assert task.status == "review" and agent.accept(task.id, "Nora").status == "done"
    finally:
        store.close()
