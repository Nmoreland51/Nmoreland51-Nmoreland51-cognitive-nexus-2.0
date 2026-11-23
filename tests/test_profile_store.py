"""Saved facts: where they came from, what replaces what, what expires, what forgetting removes,
how older files are migrated, and that two writers do not lose each other's facts."""

from __future__ import annotations

import json
import multiprocessing
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from cognitive_nexus.adaptation import AdaptiveMemoryManager
from modules import event_log, profile_store
from modules.context_manager import (
    build_context_bundle,
    forget_user_fact,
    handle_local_memory_command,
    load_user_fact_records,
    load_user_facts,
    load_user_profile_summary,
    remember_user_fact,
    split_expiry,
)
from modules.file_lock import read_json
from modules.profile_store import classify_statement, fact_id

REPO_ROOT = str(Path(__file__).resolve().parents[1])


@pytest.fixture
def profile(tmp_path) -> Path:
    return tmp_path / "user_profile.json"


def _remember_many(path: str, worker: int, count: int, repo_root: str) -> None:
    """Runs in a separate process."""

    if repo_root not in sys.path:
        sys.path.insert(0, repo_root)
    from modules.profile_store import remember

    for index in range(count):
        remember(f"Worker {worker} note number {index} about item {worker * 100 + index}", path=Path(path))


# --- what kind of statement is it ------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "kind"),
    [
        ("Call me Sam", "instruction"),
        ("Always answer in metric units", "instruction"),
        ("never use emojis", "instruction"),
        ("From now on keep answers short", "instruction"),
        ("You should address me as Doctor", "instruction"),
        ("I prefer dark mode", "preference"),
        ("My favorite color is teal", "preference"),
        ("I really like hiking", "preference"),
        ("My sister lives in Seattle", "fact"),
        ("I never eat meat", "fact"),  # about the user, not an order to the assistant
        ("The deploy script is in tools/", "fact"),
    ],
)
def test_statements_are_classified(text, kind):
    assert classify_statement(text)["kind"] == kind


@pytest.mark.parametrize(
    ("text", "attribute", "value"),
    [
        ("My favorite color is teal", "favorite color", "teal"),
        ("My favourite colour is red.", "favorite colour", "red"),
        ("My name is Robert", "name", "Robert"),
        ("Call me Bob", "preferred name", "Bob"),
        ("My cat is named Pixel", "cat name", "Pixel"),
        ("My dog's name is Rex", "dog name", "Rex"),
        ("I live in Austin", "home", "Austin"),
        ("I work at Initech", "employer", "Initech"),
        ("I work as an electrician", "job", "electrician"),
        ("I'm 34 years old", "age", "34"),
        ("My email is sam@example.com", "email", "sam@example.com"),
        # Not single-valued: several statements about a project can all be true.
        ("My project is behind schedule", "", ""),
        ("My sister lives in Seattle", "", ""),
    ],
)
def test_single_valued_attributes_are_recognised(text, attribute, value):
    info = classify_statement(text)
    assert (info["attribute"], info["value"]) == (attribute, value)


# --- remembering -----------------------------------------------------------------------------------


def test_a_saved_fact_records_where_it_came_from(profile):
    result = remember_user_fact("My preferred editor is VS Code", path=profile)

    fact = result["fact"]
    assert result["success"] and result["message"].startswith("I'll remember that: My preferred editor is VS Code")
    assert fact["id"] == fact_id("my preferred editor is vs code")
    assert (fact["kind"], fact["source"], fact["confidence"], fact["status"]) == ("preference", "user_statement", "stated", "active")
    assert fact["created_at"] == fact["updated_at"] == fact["last_verified_at"]
    assert datetime.fromisoformat(fact["created_at"]).tzinfo is not None
    assert read_json(profile)["schema_version"] == 2


def test_saying_it_again_confirms_it_instead_of_adding_a_copy(profile):
    first = remember_user_fact("My cat is named Pixel", path=profile)["fact"]
    saved = read_json(profile)
    saved["facts"][0]["last_verified_at"] = saved["facts"][0]["created_at"] = "2026-01-01T00:00:00+00:00"
    profile.write_text(json.dumps(saved), encoding="utf-8")

    again = remember_user_fact("  my CAT is named pixel! ", path=profile)

    assert again["duplicate"] is True
    assert "already had that" in again["message"]
    facts = read_json(profile)["facts"]
    assert len(facts) == 1 and facts[0]["id"] == first["id"]
    assert facts[0]["created_at"] == "2026-01-01T00:00:00+00:00"  # when it was first said is kept
    assert facts[0]["last_verified_at"] > "2026-01-01T00:00:00+00:00"


def test_a_new_value_replaces_the_old_one_and_keeps_it_as_history(profile):
    old = remember_user_fact("My favorite color is teal", path=profile)["fact"]
    result = remember_user_fact("My favorite color is red", path=profile)

    assert result["replaced"] == [old["id"]]
    assert 'This replaces what I had before: "My favorite color is teal"' in result["message"]
    assert load_user_facts(profile) == ["My favorite color is red"]
    records = {fact["text"]: fact for fact in read_json(profile)["facts"]}
    assert records["My favorite color is teal"]["status"] == "superseded"
    assert records["My favorite color is teal"]["superseded_by"] == result["fact"]["id"]
    assert records["My favorite color is red"]["supersedes"] == [old["id"]]
    assert result["fact_count"] == 1


def test_remember_also_keeps_both_values(profile):
    handle_local_memory_command("remember my cat is named Pixel", path=profile)
    result = handle_local_memory_command("remember also: my cat is named Luna", path=profile)

    assert result["replaced"] == []
    assert load_user_facts(profile) == ["my cat is named Pixel", "my cat is named Luna"]


def test_statements_that_can_both_be_true_do_not_replace_each_other(profile):
    remember_user_fact("My project is behind schedule", path=profile)
    result = remember_user_fact("My project is written in Python", path=profile)

    assert result["replaced"] == []
    assert len(load_user_facts(profile)) == 2


def test_memory_reports_when_it_is_full_instead_of_dropping_old_facts(profile, monkeypatch):
    monkeypatch.setattr(profile_store, "MAX_ACTIVE_FACTS", 3)
    for index in range(3):
        remember_user_fact(f"Note number {index}", path=profile)

    result = remember_user_fact("One note too many", path=profile)

    assert result["success"] is False and "full" in result["message"]
    assert load_user_facts(profile) == ["Note number 0", "Note number 1", "Note number 2"]


# --- expiry -----------------------------------------------------------------------------------------


def test_split_expiry_reads_durations_and_dates():
    now = datetime(2026, 11, 23, 12, 0, tzinfo=timezone.utc)

    assert split_expiry("for 3 days that the office is closed", now) == ("the office is closed", "2026-11-26T12:00:00+00:00")
    assert split_expiry("for a week: I am travelling", now) == ("I am travelling", "2026-11-30T12:00:00+00:00")
    assert split_expiry("until 2026-12-01 that the build is frozen", now) == ("the build is frozen", "2026-12-01T23:59:59+00:00")
    assert split_expiry("my cat is named Pixel", now) == ("my cat is named Pixel", None)
    # "for" at the start of an ordinary fact is not a duration.
    assert split_expiry("for dinner I like pasta", now) == ("for dinner I like pasta", None)


def test_a_temporary_fact_is_saved_with_an_end_date_and_stops_being_used(profile):
    result = handle_local_memory_command("remember for 2 days that the office is closed", path=profile)

    assert result["fact"]["text"] == "the office is closed"
    expires = datetime.fromisoformat(result["fact"]["expires_at"])
    assert timedelta(days=1, hours=23) < expires - datetime.now(timezone.utc) <= timedelta(days=2)
    assert "stop using it after" in result["message"]
    assert load_user_facts(profile) == ["the office is closed"]

    saved = read_json(profile)
    saved["facts"][0]["expires_at"] = "2026-01-01T00:00:00+00:00"
    profile.write_text(json.dumps(saved), encoding="utf-8")

    assert load_user_facts(profile) == []
    assert load_user_profile_summary(profile)["expired_count"] == 1
    assert "do not have any saved" in handle_local_memory_command("what do you remember?", path=profile)["message"]


def test_old_history_and_long_expired_facts_are_removed_on_the_next_change(profile):
    remember_user_fact("My favorite color is teal", path=profile)
    remember_user_fact("My favorite color is red", path=profile)
    remember_user_fact("the office is closed", path=profile, expires_at="2026-01-01T00:00:00+00:00")
    saved = read_json(profile)
    for fact in saved["facts"]:
        if fact["status"] == "superseded":
            fact["updated_at"] = "2026-01-01T00:00:00+00:00"
    profile.write_text(json.dumps(saved), encoding="utf-8")

    remember_user_fact("I live in Austin", path=profile)

    assert [fact["text"] for fact in read_json(profile)["facts"]] == ["My favorite color is red", "I live in Austin"]


# --- forgetting -------------------------------------------------------------------------------------


def test_forgetting_removes_the_earlier_values_too(profile):
    remember_user_fact("My favorite color is teal", path=profile)
    remember_user_fact("My favorite color is red", path=profile)
    remember_user_fact("My sister lives in Seattle", path=profile)

    result = forget_user_fact("favorite color", path=profile)

    assert (result["removed"], result["removed_history"]) == (1, 1)
    saved = read_json(profile)
    assert [fact["text"] for fact in saved["facts"]] == ["My sister lives in Seattle"]
    assert "teal" not in profile.read_text(encoding="utf-8")
    # Only ids are kept as a record of what was forgotten, never the text.
    assert {item["id"] for item in saved["forgotten"]} == {fact_id("My favorite color is teal"), fact_id("My favorite color is red")}
    assert "chat history still shows" in result["message"]


def test_remembering_again_after_forgetting_works(profile):
    remember_user_fact("My cat is named Pixel", path=profile)
    forget_user_fact("cat", path=profile)

    remember_user_fact("My cat is named Pixel", path=profile)

    saved = read_json(profile)
    assert load_user_facts(profile) == ["My cat is named Pixel"]
    assert saved["forgotten"] == []


def test_forgetting_reaches_preferences_and_candidates(tmp_path):
    manager = AdaptiveMemoryManager(tmp_path)
    manager.handle_memory_command("remember that I prefer short answers")
    for _ in range(2):
        manager.observe_turn("tell me more", manager.extract_turn_signals("tell me more"))
    assert manager.profile.preferences["detail_level"]["statement"] == "that I prefer short answers"
    assert read_json(tmp_path / "memory_candidates.json")

    result = forget_user_fact("short answers", path=tmp_path / "user_profile.json")

    assert result["success"] and result["removed_related"] >= 1
    assert "detail_level" not in read_json(tmp_path / "user_profile.json")["preferences"]

    # A candidate ("detail_level:detailed") is forgotten when the request names its value.
    forget_user_fact("detailed", path=tmp_path / "user_profile.json")
    assert read_json(tmp_path / "memory_candidates.json") == {}


@pytest.mark.parametrize("vague", ["it", "a", "that thing", "", "everything about me"])
def test_a_vague_forget_request_deletes_nothing(profile, vague):
    facts = ["My favorite color is teal", "I work as an electrician", "My cat is named Pixel"]
    for fact in facts:
        remember_user_fact(fact, path=profile)

    result = forget_user_fact(vague, path=profile)

    assert result["success"] is False and result["removed"] == 0
    assert load_user_facts(profile) == facts


def test_adaptive_memory_forget_no_longer_matches_parts_of_words(tmp_path):
    manager = AdaptiveMemoryManager(tmp_path)
    for fact in ("My favorite hobby is knitting", "I visit Italy every summer"):
        manager.remember_text(fact)

    # "it" is inside "favorITe", "knITting", "visIT" and "ITaly"; this used to erase everything.
    reply = manager.forget_text("it")

    assert "Tell me which saved memory" in reply
    assert len(load_user_facts(tmp_path / "user_profile.json")) == 2


# --- one store, two users of it ---------------------------------------------------------------------


def test_adaptive_memory_no_longer_overwrites_facts_saved_by_the_chat_commands(tmp_path):
    """The manager used to keep a copy of the profile from start-up and write it back whole."""

    path = tmp_path / "user_profile.json"
    manager = AdaptiveMemoryManager(tmp_path)  # loads the (empty) profile

    remember_user_fact("My cat is named Pixel", path=path)  # saved behind the manager's back
    manager.observe_turn("keep it short", manager.extract_turn_signals("keep it short"))
    manager.record_feedback("turn_1", "down", "be shorter next time")

    assert load_user_facts(path) == ["My cat is named Pixel"]
    assert read_json(path)["preferences"]["detail_level"]["value"] == "short"
    assert [fact["text"] for fact in manager.get_memory_overview()["facts"]] == ["My cat is named Pixel"]


def test_adaptive_memory_and_chat_commands_share_ids_and_rules(tmp_path):
    path = tmp_path / "user_profile.json"
    manager = AdaptiveMemoryManager(tmp_path)

    manager.remember_text("My favorite color is teal")
    remember_user_fact("My favorite color is red", path=path)

    assert load_user_facts(path) == ["My favorite color is red"]
    assert read_json(path)["facts"][0]["id"] == fact_id("My favorite color is teal")


def test_two_processes_remembering_at_once_lose_nothing(profile):
    workers, per_worker = 3, 12
    context = multiprocessing.get_context("spawn")
    processes = [context.Process(target=_remember_many, args=(str(profile), worker, per_worker, REPO_ROOT)) for worker in range(workers)]
    for process in processes:
        process.start()
    for process in processes:
        process.join(timeout=180)
        assert process.exitcode == 0

    assert len(load_user_facts(profile)) == workers * per_worker


# --- older files ------------------------------------------------------------------------------------

VERSION_1 = {
    "facts": [
        "Legacy plain-text fact",
        {"id": "fact_-812345678901234567", "text": "My cat is named Pixel", "kind": "explicit", "source": "explicit_chat_memory", "updated_at": "2026-05-02T10:00:00"},
        {"id": "fact_1a2b3c4d", "text": "I prefer dark mode", "kind": "preference", "source": "explicit_memory", "updated_at": "2026-06-01T09:30:00"},
        {"text": "", "source": "test"},
        {"id": "fact_dup", "text": "my cat is named pixel", "source": "explicit_memory", "updated_at": "2026-07-01T00:00:00"},
    ],
    "preferences": {"tone": {"value": "casual", "source": "explicit_signal", "updated_at": "2026-05-01T00:00:00"}},
    "custom_key_from_another_tool": {"keep": True},
    "updated_at": "2026-07-01T00:00:00",
}


def test_a_version_1_profile_is_migrated_with_a_backup(profile):
    original = json.dumps(VERSION_1, indent=2)
    profile.write_text(original, encoding="utf-8")

    facts = load_user_fact_records(profile)

    assert [fact["text"] for fact in facts] == ["Legacy plain-text fact", "my cat is named pixel", "I prefer dark mode"]
    by_text = {fact["text"]: fact for fact in facts}
    assert by_text["Legacy plain-text fact"]["source"] == "legacy"
    assert by_text["Legacy plain-text fact"]["last_verified_at"] is None  # nobody recorded who said it
    assert by_text["I prefer dark mode"]["source"] == "user_statement"
    assert by_text["I prefer dark mode"]["kind"] == "preference"
    assert by_text["I prefer dark mode"]["created_at"] == "2026-06-01T09:30:00"
    assert by_text["my cat is named pixel"]["id"] == fact_id("My cat is named Pixel")  # stable id, duplicates merged
    assert all(fact["migrated_from"] == 1 for fact in facts)

    saved = read_json(profile)
    assert saved["schema_version"] == 2
    assert saved["preferences"]["tone"]["value"] == "casual"
    assert saved["custom_key_from_another_tool"] == {"keep": True}  # unknown keys survive
    backup = profile.with_name("user_profile.v1.backup.json")
    assert backup.read_text(encoding="utf-8") == original


def test_migration_runs_once_and_never_overwrites_its_backup(profile):
    profile.write_text(json.dumps(VERSION_1), encoding="utf-8")
    load_user_facts(profile)
    backup = profile.with_name("user_profile.v1.backup.json")
    first_backup = backup.read_text(encoding="utf-8")
    saved_after_first = profile.read_text(encoding="utf-8")

    load_user_facts(profile)
    remember_user_fact("I live in Austin", path=profile)

    assert backup.read_text(encoding="utf-8") == first_backup
    assert json.loads(saved_after_first)["schema_version"] == 2
    assert len(load_user_facts(profile)) == 4


def test_a_profile_from_a_newer_app_is_left_untouched(profile):
    newer = json.dumps({"schema_version": 99, "facts": [{"text": "from the future"}]})
    profile.write_text(newer, encoding="utf-8")

    with pytest.raises(ValueError, match="newer than this app understands"):
        profile_store.load_profile(profile)
    with pytest.raises(ValueError):
        profile_store.remember("anything", path=profile)

    assert profile.read_text(encoding="utf-8") == newer
    assert load_user_facts(profile) == []


def test_a_damaged_profile_is_set_aside_not_overwritten(profile):
    damaged = '{"facts": [{"text": "important and half-writ'
    profile.write_text(damaged, encoding="utf-8")

    result = remember_user_fact("My cat is named Pixel", path=profile)

    assert result["success"]
    kept = list(profile.parent.glob("user_profile.json.damaged-*"))
    assert len(kept) == 1 and kept[0].read_text(encoding="utf-8") == damaged
    assert load_user_facts(profile) == ["My cat is named Pixel"]
    assert event_log.event_counts()["error"] >= 1


# --- how facts reach the model ----------------------------------------------------------------------


def test_prompt_labels_how_each_fact_is_known_and_always_includes_instructions(profile):
    remember_user_fact("Call me Sam", path=profile)
    remember_user_fact("My sister lives in Seattle", path=profile)
    profile_store.remember("Usually asks for short answers", path=profile, source="inferred_from_chat")

    bundle = build_context_bundle(
        user_message="where does my sister live and how short should answers be",
        messages=[],
        system_prompt="System prompt",
        route_label="Standard Conversation",
        user_facts=load_user_fact_records(profile),
    )

    assert "[instruction from the user] Call me Sam" in bundle.prompt
    assert "[stated by the user] My sister lives in Seattle" in bundle.prompt
    assert "[inferred, not confirmed by the user] Usually asks for short answers" in bundle.prompt

    unrelated = build_context_bundle(
        user_message="what is the boiling point of water",
        messages=[],
        system_prompt="System prompt",
        route_label="Standard Conversation",
        user_facts=load_user_fact_records(profile),
    )

    assert "Call me Sam" in unrelated.prompt  # a standing instruction applies to every turn
    assert "Seattle" not in unrelated.prompt  # an unrelated fact is left out


def test_an_inferred_fact_never_replaces_what_the_user_stated(profile):
    remember_user_fact("My favorite color is teal", path=profile)

    profile_store.remember("My favorite color is red", path=profile, source="inferred_from_chat")

    records = {fact["text"]: fact for fact in load_user_fact_records(profile)}
    assert records["My favorite color is teal"]["status"] == "active"
    assert records["My favorite color is red"]["kind"] == "inferred"
    assert records["My favorite color is red"]["confidence"] == "inferred"
    assert records["My favorite color is red"]["last_verified_at"] is None


def test_recall_lists_facts_with_how_they_are_known(profile):
    remember_user_fact("Call me Sam", path=profile)
    remember_user_fact("the office is closed", path=profile, expires_at="2999-01-01T00:00:00+00:00")

    message = handle_local_memory_command("what do you remember about me?", path=profile)["message"]

    assert "- Call me Sam (instruction from the user)" in message
    assert "- the office is closed (stated by the user, until 2999-01-01)" in message


def test_profile_summary_reports_provenance(profile):
    remember_user_fact("My favorite color is teal", path=profile)
    remember_user_fact("My favorite color is red", path=profile)

    summary = load_user_profile_summary(profile)

    assert (summary["fact_count"], summary["replaced_count"], summary["schema_version"]) == (1, 1, 2)
    row = summary["facts"][0]
    assert (row["text"], row["kind"], row["source"], row["confidence"]) == ("My favorite color is red", "preference", "user_statement", "stated")
    assert row["created_at"] and row["last_confirmed"]
