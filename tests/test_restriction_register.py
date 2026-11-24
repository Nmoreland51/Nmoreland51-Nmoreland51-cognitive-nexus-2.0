"""The register of restrictions: it must describe the code as it is, and notice when it stops doing so."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import restriction_register as register  # noqa: E402


def test_the_register_matches_the_code():
    """Every quoted line of an active mechanism is in its file, every removed one is gone, every
    file that mentions a restriction is accounted for, and the document is up to date."""

    assert register.check() == []


def test_every_layer_is_present_and_the_one_content_rule_is_the_only_one():
    data = register.load()
    entries = data["entries"]

    assert {entry["category"] for entry in entries} == set(register.CATEGORIES)
    active_conversation = [entry for entry in entries if entry["category"] == "A" and entry["status"] != "removed"]
    keeps_back = ("not answered", "never to write", "stops the request")
    refusing = [entry["id"] for entry in active_conversation if any(phrase in entry["effect"].lower() for phrase in keeps_back)]
    # Of everything the app does in conversation, only the one rule, its check, and the line for
    # pictures keep something from being written or drawn.
    assert refusing == ["R-A11", "R-A12", "R-A21"]
    # The line for pictures is not the owner's and is not recorded as if it were.
    pictures = next(entry for entry in entries if entry["id"] == "R-A21")
    assert pictures["owner_requested"].startswith("No.") and pictures["owner_decision"].startswith("Pending")
    # What the owner asked to be removed is recorded as removed, with the code that was there.
    removed = {entry["id"] for entry in entries if entry["status"] == "removed"}
    assert {"R-A01", "R-A02", "R-A03", "R-A04", "R-A05", "R-A06", "R-A07", "R-A08", "R-A09", "R-D02"} <= removed
    assert all(entry.get("gone") for entry in entries if entry["status"] == "removed")


def test_a_decision_is_never_recorded_as_the_owners_when_the_owner_did_not_make_it():
    for entry in register.load()["entries"]:
        decision = entry["owner_decision"]
        assert decision.startswith(("Decided by the owner on ", "Pending")), entry["id"]
        if decision.startswith("Decided"):
            assert entry.get("decision_date"), entry["id"]


def test_the_check_notices_a_mechanism_that_moved_a_removal_that_came_back_and_an_unlisted_file(tmp_path, monkeypatch):
    data = register.load()
    broken = json.loads(json.dumps(data))
    broken["entries"][0]["gone"] = [{"file": "modules/behavior_policy.py", "anchor": "CONTENT_RULE = ("}]  # "removed", yet it is there
    moved = next(entry for entry in broken["entries"] if entry["id"] == "R-A11")
    moved["locations"] = [{"file": "modules/behavior_policy.py", "anchor": "THIS LINE IS NOT IN THE FILE"}]
    broken["reviewed_files"].pop("agent/store.py")
    fake = tmp_path / "restrictions.json"
    fake.write_text(json.dumps(broken), encoding="utf-8")
    monkeypatch.setattr(register, "DATA_FILE", fake)

    problems = "\n".join(register.check())

    assert "recorded as removed, but still in modules/behavior_policy.py" in problems
    assert "R-A11: not found in modules/behavior_policy.py" in problems
    assert "agent/store.py: mentions restriction-related terms" in problems


def test_the_search_covers_the_app_and_skips_only_what_cannot_shape_behaviour():
    found = register.scan()

    for name in ("app.py", "modules/nexus_core.py", "modules/behavior_policy.py", "core/reality_grounding/prompt_firewall.py", "agent/approvals.py", "nexus_router.py"):
        assert name in found
    assert not [name for name in found if name.startswith(("tests/", "legacy/", "docs/"))]
