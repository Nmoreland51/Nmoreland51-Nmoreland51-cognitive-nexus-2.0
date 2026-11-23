"""The ways a small model gets an edit almost right, and what the harness does about each.

Every case here was seen in a live run with the local 8B model (the replies are quoted as it
wrote them, shortened). None of the tolerances decides that a change is correct: that stays with
the tests. They only stop a usable change from being thrown away for the way it was written.
"""

from __future__ import annotations

import subprocess

import pytest

from agent.coder import closest_lines, default_agent, gather_context, locate_block, normalise_path, parse_reply, reindent, tidy_failure
from agent.model import ScriptedModel
from agent.store import AgentStore
from agent.workspace import WorkspaceManager

PYTEST = ["python", "-m", "pytest", "-q", "-p", "no:cacheprovider"]


def git(repo, *arguments):
    done = subprocess.run(["git", *arguments], cwd=repo, capture_output=True, text=True, encoding="utf-8")
    assert done.returncode == 0, done.stderr
    return done.stdout.strip()


def make_repo(tmp_path, files):
    folder = tmp_path / "project"
    folder.mkdir()
    git(folder, "init", "-q", "-b", "main")
    for key, value in (("user.name", "Test User"), ("user.email", "test@example.org"), ("commit.gpgsign", "false")):
        git(folder, "config", key, value)
    for name, content in files.items():
        target = folder / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8", newline="\n")
    git(folder, "add", "-A")
    git(folder, "commit", "-q", "-m", "first")
    return folder


def run(tmp_path, files, replies, test_file, **task_options):
    repo = make_repo(tmp_path, files)
    store = AgentStore(tmp_path / "agent.db")
    model = ScriptedModel(replies, name="author")
    agent = default_agent(store, model, model_review=False, workspaces=WorkspaceManager(tmp_path / "ws"))
    task = agent.run(store.create_task("Fix it", "", repo=str(repo), acceptance=[PYTEST + [test_file]], **task_options).id)
    return type("Done", (), {"task": task, "repo": repo, "model": model, "store": store, "first": task.state["attempts"][0]})


PEOPLE = {
    "people.py": 'ADULT_AGE = 18\n\n\ndef is_adult(age):\n    """True for people who have reached the adult age."""\n    return age > ADULT_AGE\n\n\ndef describe(age):\n    return "adult" if is_adult(age) else "minor"\n',
    "test_people.py": 'from people import describe, is_adult\n\n\ndef test_eighteen_is_adult():\n    assert is_adult(18) is True\n\n\ndef test_seventeen_is_not():\n    assert is_adult(17) is False\n\n\ndef test_describe():\n    assert describe(18) == "adult"\n',
}
WORDS = {
    "words.py": 'def word_count(text):\n    """How often each word occurs in a text."""\n    counts = {}\n    for word in text.lower().split():\n        counts[word] += 1\n    return counts\n',
    "test_words.py": "from words import word_count\n\n\ndef test_counts():\n    assert word_count('a b a') == {'a': 2, 'b': 1}\n\n\ndef test_empty():\n    assert word_count('') == {}\n",
}


# ---- reading replies whose markers are incomplete -----------------------------------------------


def test_an_edit_without_the_divider_is_read():
    reply = "The slice is one too short.\n\nFILE: listtools.py\n<<<<<<< SEARCH\nreturn items[-n + 1 :]\n>>>>>>> REPLACE\n\nreturn items[-n:]\n"
    plan, edits = parse_reply(reply)
    assert plan == "The slice is one too short."
    assert [(edit.path, edit.search, edit.replace) for edit in edits] == [("listtools.py", "return items[-n + 1 :]", "return items[-n:]")]
    with_prose = reply + "\nThis should make the tests pass.\n"
    assert parse_reply(with_prose)[1][0].replace == "return items[-n:]"  # the sentence after a blank line is not code


def test_an_edit_without_the_closing_marker_is_read():
    reply = "FILE: a.py\n<<<<<<< SEARCH\nx = 1\n=======\nx = 2\n\nFILE: b.py\n```python\n<<<<<<< SEARCH\ny = 1\n=======\ny = 2\n```\n"
    assert [(edit.path, edit.search, edit.replace) for edit in parse_reply(reply)[1]] == [("a.py", "x = 1", "x = 2"), ("b.py", "y = 1", "y = 2")]


def test_well_formed_edits_are_read_exactly_as_before():
    reply = "FILE: a.py\n<<<<<<< SEARCH\n    if x:\n\n        return 1\n=======\n    if x:\n        return 2\n>>>>>>> REPLACE\nDone.\n"
    edit = parse_reply(reply)[1][0]
    assert (edit.search, edit.replace) == ("    if x:\n\n        return 1", "    if x:\n        return 2")
    assert parse_reply("<<<<<<< SEARCH\nonly a marker, no file and no end")[1] == []


@pytest.mark.parametrize(
    "given, expected",
    [
        ("calc.py", "calc.py"),
        ("./src\\calc.py", "src/calc.py"),
        ("`pkg/mod.py`", "pkg/mod.py"),
        ("C:/work/ws/abc123/pkg/mod.py", "pkg/mod.py"),
        ("c:\\WORK\\ws\\abc123\\mod.py", "mod.py"),
        ("b/pkg/mod.py", "pkg/mod.py"),
        ("a/b/c.py", "a/b/c.py"),
    ],
)
def test_file_names_from_a_reply_are_made_relative_to_the_project(given, expected):
    assert normalise_path(given, "C:\\work\\ws\\abc123") == expected


# ---- finding the lines ---------------------------------------------------------------------------


def test_one_line_copied_without_its_indentation_takes_the_whole_line():
    text = "def f():\n    for w in ws:\n        counts[w] += 1\n    return counts\n"
    exact, in_file, in_block = locate_block(text, "counts[w] += 1")
    assert (exact, in_file, in_block) == ("        counts[w] += 1", "        ", "")
    new = reindent("if w in counts:\n    counts[w] += 1\nelse:\n    counts[w] = 1", in_file, in_block)
    assert text.replace(exact, new) == "def f():\n    for w in ws:\n        if w in counts:\n            counts[w] += 1\n        else:\n            counts[w] = 1\n    return counts\n"
    # Part of a line is replaced in place, as before.
    assert locate_block(text, "+= 1") == ("+= 1", "", "")


def test_a_block_that_differs_only_in_blank_lines_is_found():
    text = "import re\n\n\ndef slugify(title):\n    cleaned = title\n\n    return cleaned.strip()\n"
    found = locate_block(text, "import re\n\ndef slugify(title):\n    cleaned = title\n    return cleaned.strip()")
    assert found is not None and found[0] == text.rstrip("\n")
    assert locate_block(text, "import re\ndef slugify(name):") is None  # a different word is a different line


def test_the_nearest_lines_are_offered_when_a_block_is_not_in_the_file():
    text = 'from shop.money import rounded\n\n\ndef format_price(amount, currency="EUR"):\n    return f"{rounded(amount)} {currency}"\n'
    wrong = 'def format_price(amount, currency="EUR"):\n    return f"{amount} {currency}"'
    assert locate_block(text, wrong) is None
    assert closest_lines(text, wrong) == 'def format_price(amount, currency="EUR"):\n    return f"{rounded(amount)} {currency}"'
    assert closest_lines(text, "class Unrelated(Base):\n    pass") == ""


# ---- applying what can be applied ------------------------------------------------------------------


def test_a_good_edit_is_not_lost_because_another_edit_in_the_reply_does_not_apply(tmp_path):
    """Seen live: the right fix, followed by an edit whose SEARCH was never in the file."""

    reply = (
        "The comparison is wrong.\n\nFILE: people.py\n<<<<<<< SEARCH\n    return age > ADULT_AGE\n=======\n    return age >= ADULT_AGE\n>>>>>>> REPLACE\n\n"
        'FILE: people.py\n<<<<<<< SEARCH\n    return "minor"\n=======\n    return "adult" if is_adult(age) else "minor"\n>>>>>>> REPLACE\n'
    )
    done = run(tmp_path, PEOPLE, [reply], "test_people.py")
    assert done.task.status == "review" and done.task.result["attempts"] == 1
    assert len(done.first["left_out"]) == 1 and "the lines in its SEARCH are not in that file" in done.first["left_out"][0]
    assert git(done.repo, "show", "--format=", done.task.result["commit"]).count("\n+") == 2  # one changed line (and the +++ header)


def test_a_multi_line_replacement_for_an_unindented_line_keeps_the_file_s_indentation(tmp_path):
    """Seen live: this reply was right, and was applied in a way that broke the indentation."""

    reply = "A missing key.\n\nFILE: words.py\n<<<<<<< SEARCH\ncounts[word] += 1\n=======\nif word in counts:\n    counts[word] += 1\nelse:\n    counts[word] = 1\n>>>>>>> REPLACE\n"
    done = run(tmp_path, WORDS, [reply], "test_words.py")
    assert done.task.status == "review" and done.task.result["attempts"] == 1
    assert "        if word in counts:\n            counts[word] += 1\n        else:\n            counts[word] = 1\n" in git(done.repo, "show", f"{done.task.branch}:words.py")


def test_the_right_change_addressed_to_the_test_file_s_name_is_applied_where_its_lines_are(tmp_path):
    """Seen live: FILE named the test, SEARCH was copied from the code."""

    reply = "Fix the comparison.\n\nFILE: test_people.py\n<<<<<<< SEARCH\n    return age > ADULT_AGE\n=======\n    return age >= ADULT_AGE\n>>>>>>> REPLACE\n"
    done = run(tmp_path, PEOPLE, [reply], "test_people.py")
    assert done.task.status == "review"
    assert done.first["left_out"] == ["An edit addressed to test_people.py was applied to people.py, where its lines are."]
    assert git(done.repo, "show", "--name-only", "--format=", done.task.result["commit"]) == "people.py"


def test_an_edit_to_the_tests_is_left_out_and_the_rest_of_the_reply_is_used(tmp_path):
    """Seen live: the function was added correctly, and the test's import was rewritten as well."""

    files = {
        "mathutil.py": "def square(value):\n    return value * value\n",
        "test_mathutil.py": "from mathutil import clamp, square\n\n\ndef test_clamp():\n    assert clamp(5, 0, 3) == 3\n\n\ndef test_square():\n    assert square(3) == 9\n",
    }
    reply = (
        "Add clamp.\n\nFILE: test_mathutil.py\n<<<<<<< SEARCH\nfrom mathutil import clamp, square\n=======\nfrom mathutil import square\n>>>>>>> REPLACE\n\n"
        "FILE: mathutil.py\n<<<<<<< SEARCH\ndef square(value):\n    return value * value\n=======\ndef square(value):\n    return value * value\n\n\ndef clamp(value, low, high):\n    return max(low, min(high, value))\n>>>>>>> REPLACE\n"
    )
    done = run(tmp_path, files, [reply], "test_mathutil.py")
    assert done.task.status == "review"
    assert done.first["left_out"] == ["An edit to test_mathutil.py was left out: tests and project configuration may not be edited. Change the code under test instead."]
    assert "from mathutil import clamp, square" in git(done.repo, "show", f"{done.task.branch}:test_mathutil.py")


def test_when_nothing_in_a_reply_can_be_applied_the_next_attempt_is_told_why(tmp_path):
    hopeless = "FILE: nowhere.py\n<<<<<<< SEARCH\nx = 1\n=======\nx = 2\n>>>>>>> REPLACE\n"
    good = "FILE: people.py\n<<<<<<< SEARCH\n    return age > ADULT_AGE\n=======\n    return age >= ADULT_AGE\n>>>>>>> REPLACE\n"
    done = run(tmp_path, PEOPLE, [hopeless, good], "test_people.py")
    assert done.task.status == "review" and done.task.result["attempts"] == 2
    assert done.first["problem"] == "None of the edits could be applied. An edit to nowhere.py was left out: there is no such file in the project. Edit one of the files shown."
    assert "there is no such file in the project" in done.model.prompts[1]


def test_an_absolute_path_into_the_workspace_is_understood_and_one_outside_is_not(tmp_path):
    repo = make_repo(tmp_path, PEOPLE)
    store = AgentStore(tmp_path / "agent.db")
    seen = {}

    def reply(prompt):
        workspace = next((tmp_path / "ws").iterdir()) if not seen else seen["ws"]
        seen["ws"] = workspace
        outside = tmp_path / "elsewhere.py"
        return (
            f"FILE: {outside}\n<<<<<<< SEARCH\n=======\nprint('created outside')\n>>>>>>> REPLACE\n\n"
            f"FILE: {workspace / 'people.py'}\n<<<<<<< SEARCH\n    return age > ADULT_AGE\n=======\n    return age >= ADULT_AGE\n>>>>>>> REPLACE\n"
        )

    agent = default_agent(store, ScriptedModel(reply, name="author"), model_review=False, workspaces=WorkspaceManager(tmp_path / "ws"))
    (tmp_path / "ws").mkdir(exist_ok=True)
    task = agent.run(store.create_task("Fix it", repo=str(repo), acceptance=[PYTEST + ["test_people.py"]]).id)
    assert task.status == "review"
    assert not (tmp_path / "elsewhere.py").exists()
    assert "not a path inside the workspace" in task.state["attempts"][0]["left_out"][0]
    store.close()


# ---- a correct edit spoiled by a second one --------------------------------------------------------


def test_edits_that_fail_together_are_tried_one_at_a_time(tmp_path):
    """Seen live, twice: the right fix, and with it a change of the constant that breaks another test."""

    reply = (
        "Two changes.\n\nFILE: people.py\n<<<<<<< SEARCH\nADULT_AGE = 18\n=======\nADULT_AGE = 20\n>>>>>>> REPLACE\n\n"
        "FILE: people.py\n<<<<<<< SEARCH\n    return age > ADULT_AGE\n=======\n    return age >= ADULT_AGE\n>>>>>>> REPLACE\n"
    )
    done = run(tmp_path, PEOPLE, [reply], "test_people.py")
    assert done.task.status == "review" and done.task.result["attempts"] == 1
    assert done.first["single_edit"] == 2
    assert "Only edit 2 of the reply was kept" in done.first["left_out"][-1]
    final = git(done.repo, "show", f"{done.task.branch}:people.py")
    assert "ADULT_AGE = 18" in final and "return age >= ADULT_AGE" in final
    # The evidence is the test run of the kept edit alone.
    evidence = next(item for item in done.store.actions(done.task.id) if item["id"] == done.first["tests_action"])
    assert evidence["data"]["passed"] is True
    assert done.task.result["changed_files"] == ["people.py"]


def test_when_no_single_edit_passes_either_the_attempt_fails_and_is_undone(tmp_path):
    reply = (
        "FILE: people.py\n<<<<<<< SEARCH\nADULT_AGE = 18\n=======\nADULT_AGE = 20\n>>>>>>> REPLACE\n\n"
        "FILE: people.py\n<<<<<<< SEARCH\n    return age > ADULT_AGE\n=======\n    return age < ADULT_AGE\n>>>>>>> REPLACE\n"
    )
    done = run(tmp_path, PEOPLE, [reply, reply], "test_people.py", budget={"attempts": 1})
    assert done.task.status == "escalated" and done.first["problem"].startswith("The tests still fail")
    assert "single_edit" not in done.first
    workspace = tmp_path / "ws" / done.task.id.split("_")[-1]
    assert (workspace / "people.py").read_text(encoding="utf-8") == PEOPLE["people.py"]


# ---- what the model is shown ------------------------------------------------------------------------


def test_a_file_imported_by_the_code_under_test_is_shown_too(tmp_path):
    """Seen live: the fault was in a module the tested file imports, and the model never saw it."""

    files = {
        "shop/__init__.py": "",
        "shop/money.py": 'DECIMALS = 1\n\n\ndef rounded(amount):\n    return f"{amount:.{DECIMALS}f}"\n',
        "shop/display.py": 'from shop.money import rounded\n\n\ndef format_price(amount, currency="EUR"):\n    return f"{rounded(amount)} {currency}"\n',
        "shop/unrelated.py": "def nothing():\n    return None\n",
        "test_display.py": "from shop.display import format_price\n\n\ndef test_whole_amount():\n    assert format_price(3) == '3.00 EUR'\n",
    }
    repo = make_repo(tmp_path, files)
    checkout = WorkspaceManager(tmp_path / "ws").create(repo, "task_0000000d0001")
    code, tests = gather_context(checkout, sorted(files), "FAILED test_display.py::test_whole_amount", ["test_display.py::test_whole_amount"], [PYTEST + ["test_display.py"]], "")
    assert [view.path for view in code] == ["shop/display.py", "shop/money.py"]
    assert "DECIMALS = 1" in code[1].text and [view.path for view in tests] == ["test_display.py"]


def test_test_output_is_shown_without_absolute_paths_or_the_interpreter_s_own_frames():
    root = "C:\\Users\\me\\data\\agent\\ws\\abc123"
    output = (
        "ImportError while importing test module 'C:\\Users\\me\\data\\agent\\ws\\abc123\\test_mathutil.py'.\n"
        "..\\..\\Programs\\Python\\Python313\\Lib\\importlib\\__init__.py:88: in import_module\n"
        "    return _bootstrap._gcd_import(name[level:], package, level)\n"
        "C:/Users/me/data/agent/ws/abc123/test_mathutil.py:1: in <module>\n"
        "    from mathutil import clamp, square\n"
        "E   ImportError: cannot import name 'clamp' from 'mathutil' (C:\\Users\\me\\data\\agent\\ws\\abc123\\mathutil.py)\n"
        "venv/lib/python3.13/site-packages/_pytest/python.py:498: in importtestmodule\n"
        "    mod = import_path(\n"
    )
    tidy = tidy_failure(output, root)
    assert "abc123" not in tidy and "importlib" not in tidy and "site-packages" not in tidy and "_gcd_import" not in tidy
    assert "test_mathutil.py:1: in <module>" in tidy and "    from mathutil import clamp, square" in tidy
    assert "cannot import name 'clamp' from 'mathutil' (mathutil.py)" in tidy
    assert tidy_failure("FAILED test_a.py::test_x - assert 1 == 2", root) == "FAILED test_a.py::test_x - assert 1 == 2"
