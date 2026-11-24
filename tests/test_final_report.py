"""The final verification report says what the ledger, the register and the saved measurements say."""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "tools"))
import final_report  # noqa: E402


def test_the_report_on_disk_is_the_one_that_would_be_written_now():
    assert final_report.main(["check"]) == 0, "Run: python tools/final_report.py"


def test_every_item_is_counted_once_and_every_open_item_has_one_reason():
    items, status, sections = final_report.ledger()
    text = final_report.build()

    assert len(items) == 146 and sum(text.count(f"\n| {item_id} | ") >= 1 for item_id in items) == 146
    open_items = [item_id for item_id in items if status[item_id]["status"] in {"PARTIAL", "MISSING"}]
    reasons = {item_id: final_report.why_open(item_id, status[item_id]) for item_id in open_items}
    assert set(reasons.values()) <= {"your decision", "not finished"} | {f"needs {what}" for what in final_report.NEEDS_WHAT_THIS_MACHINE_LACKS.values()}
    # The two lists of outside reasons name only items that are in fact still open.
    assert final_report.NEEDS_THE_OWNER <= set(open_items) and set(final_report.NEEDS_WHAT_THIS_MACHINE_LACKS) <= set(open_items)
    assert not final_report.NEEDS_THE_OWNER & set(final_report.NEEDS_WHAT_THIS_MACHINE_LACKS)
    for item_id in final_report.NEEDS_THE_OWNER | set(final_report.NEEDS_WHAT_THIS_MACHINE_LACKS):
        assert status[item_id].get("needs"), f"{item_id} is listed as waiting for something, and the ledger does not say for what"
    assert all(final_report.why_open(item_id, status[item_id]) == "" for item_id in items if status[item_id]["status"] == "COMPLETE")
    assert len(sections) == 11 and all(f"### {number}. " in text for number in sections)


def test_the_report_does_not_claim_more_than_it_can_show():
    text = final_report.build()

    assert "The audit is not finished." in text and "Nothing in this work was ever run against a real outside service" in text
    assert "That line is mine, not yours" in text  # the stricter picture rule is named as the assistant's own
    for _title, result, name in final_report.measurements():
        assert (final_report.BENCHMARKS / name).exists() and result != "see the file", name
    assert len(final_report.limits_not_asked_for()) >= 10 and all(entry_id.startswith("R-") for entry_id, _name, _can in final_report.limits_not_asked_for())
