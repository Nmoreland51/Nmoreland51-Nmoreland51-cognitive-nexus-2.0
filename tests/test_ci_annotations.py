"""On CI a failed test is reported where it can be seen without opening the log."""

from __future__ import annotations

from types import SimpleNamespace

from conftest import failure_annotations


def test_a_failure_becomes_one_escaped_error_line_with_the_test_name_and_the_end_of_its_text():
    report = SimpleNamespace(
        nodeid="tests/test_x.py::test_adds[1, 2]",
        location=("tests/test_x.py", 11, "test_adds"),
        longreprtext="def test_adds():\n>       assert add(1, 2) == 4\nE       assert 3 == 4 (100% wrong)\n\ntests\test_x.py:12: AssertionError",
    )

    lines = failure_annotations([report] * 12)

    assert len(lines) == 10  # GitHub shows ten per step; more would be dropped silently
    assert lines[0].startswith("::error file=tests/test_x.py,line=12,title=tests/test_x.py%3A%3Atest_adds[1%2C 2]::")
    assert "assert 3 == 4 (100%25 wrong)%0A" in lines[0] and "\n" not in lines[0]


def test_a_failure_without_text_still_gets_a_line():
    report = SimpleNamespace(nodeid="tests/test_y.py::test_z", location=("tests/test_y.py", None, "test_z"), longreprtext="")
    assert failure_annotations([report]) == ["::error file=tests/test_y.py,line=1,title=tests/test_y.py%3A%3Atest_z::failed"]
