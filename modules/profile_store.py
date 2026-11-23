"""The single reader and writer of the saved user profile (data/user_profile.json).

Two modules used to write this file on their own: the chat memory commands re-read it for every
change, while the adaptive memory manager kept a copy in memory and wrote the whole copy back,
discarding anything saved in between. Both now go through this module, and every change is one
read-change-write under a cross-process lock (modules/file_lock.py).

A saved fact records where it came from and how far to trust it:

    kind        instruction  the user told the assistant how to behave ("call me Sam")
                preference   the user stated a like or dislike
                fact         the user stated something about themselves or their work
                inferred     the app guessed it from behaviour; never stated by the user
    source      user_statement | inferred_from_chat | imported | legacy
    confidence  stated | inferred
    created_at, updated_at, last_verified_at (the last time the user said it again)
    expires_at  optional; an expired fact is no longer used
    status      active | superseded (replaced by a newer statement about the same thing)

Schema changes are migrations (see migrate_profile); the file before a migration is kept beside
the profile as a backup.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

from modules.data_stores import DATA_ROOT
from modules.event_log import record_event
from modules.file_lock import locked, read_json, update_json
from modules.file_utils import atomic_write_json

logger = logging.getLogger(__name__)

PROFILE_FILE = DATA_ROOT / "user_profile.json"
SCHEMA_VERSION = 2
MAX_ACTIVE_FACTS = 500
SUPERSEDED_RETENTION_DAYS = 90
EXPIRED_RETENTION_DAYS = 30
MAX_TOMBSTONES = 500

KIND_LABELS = {
    "instruction": "instruction from the user",
    "preference": "preference stated by the user",
    "fact": "stated by the user",
    "inferred": "inferred, not confirmed by the user",
}

# Words that don't say which memory is meant. "forget it" or "forget a" used to match letters
# inside other words ("favorITe") and could delete every saved fact.
FORGET_FILLER = frozenset(
    """a about all am an and any anything are as at be been but by can did do does everything for from had has
    have i if in is it its me my of on or our please so some something stuff that the their them then these they
    thing things this those to up us was we were what when which who with you your""".split()
)

_INSTRUCTION = re.compile(
    r"^(?:please\s+)?(?:always|never|from now on|do not|don't|dont|stop|avoid|call me|address me|refer to me|"
    r"respond|reply|answer|speak|talk|write|use|keep|make sure|be)\b|\byou (?:should|must|need to|can|may)\b",
    re.IGNORECASE,
)
_PREFERENCE = re.compile(
    r"^(?:i|we)\s+(?:really\s+|also\s+)?(?:prefer|like|love|enjoy|hate|dislike|can't stand|cannot stand|would rather|'d rather)\b"
    r"|^my\s+(?:favorite|favourite|preferred)\b",
    re.IGNORECASE,
)
# Things a person has exactly one of, so a new value replaces the old one. Anything else
# ("my project is ...") can be true in several ways at once and is never treated as a conflict.
_SINGLE_VALUED = frozenset(
    {
        "name", "first name", "last name", "surname", "middle name", "nickname", "age", "birthday", "birthdate",
        "date of birth", "email", "email address", "phone", "phone number", "address", "home address", "job",
        "job title", "title", "role", "occupation", "profession", "employer", "company", "workplace", "location",
        "city", "town", "country", "state", "hometown", "timezone", "time zone", "pronouns", "language",
        "native language", "first language", "nationality", "height", "weight", "blood type", "username", "handle",
        "website", "major", "degree", "school", "university",
    }
)
_ATTRIBUTE_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"^my\s+(?P<attr>(?:favorite|favourite|preferred)\s+[\w' -]{1,40}?)\s+(?:is|are)\s+(?P<value>.+)$", re.I), "{attr}"),
    (re.compile(r"^my\s+(?P<attr>[\w' -]{1,30}?)\s+(?:is|are)\s+(?:named|called)\s+(?P<value>.+)$", re.I), "{attr} name"),
    (re.compile(r"^my\s+(?P<attr>[\w' -]{1,30}?)'s\s+name\s+is\s+(?P<value>.+)$", re.I), "{attr} name"),
    (re.compile(r"^my\s+(?P<attr>[\w' -]{1,30}?)\s+(?:is|are)\s+(?P<value>.+)$", re.I), "{attr}"),
    (re.compile(r"^(?:please\s+)?call\s+me\s+(?P<value>.+)$", re.I), "preferred name"),
    (re.compile(r"^i\s*(?:am|'m)\s+called\s+(?P<value>.+)$", re.I), "preferred name"),
    (re.compile(r"^i\s+live\s+in\s+(?P<value>.+)$", re.I), "home"),
    (re.compile(r"^i\s*(?:am|'m)\s+from\s+(?P<value>.+)$", re.I), "origin"),
    (re.compile(r"^i\s+work\s+(?:at|for)\s+(?P<value>.+)$", re.I), "employer"),
    (re.compile(r"^i\s+work\s+as\s+(?:an?\s+)?(?P<value>.+)$", re.I), "job"),
    (re.compile(r"^i\s*(?:am|'m)\s+(?P<value>\d{1,3})(?:\s+years?\s+old)?$", re.I), "age"),
)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def parse_time(value: Any) -> datetime | None:
    """Parse a stored timestamp. Older records have local time without a zone."""

    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.astimezone()


def normalize(text: Any) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", str(text or "").lower())).strip()


def fact_id(text: str) -> str:
    """Content hash: the same fact gets the same id in every run and on every device."""

    return f"fact_{hashlib.sha1(normalize(text).encode('utf-8')).hexdigest()[:12]}"


def classify_statement(text: str) -> dict[str, str]:
    """Kind of statement, and the attribute/value when it names something single-valued."""

    content = " ".join(str(text or "").split()).rstrip(".!")
    if _INSTRUCTION.search(content):
        kind = "instruction"
    elif _PREFERENCE.search(content):
        kind = "preference"
    else:
        kind = "fact"
    attribute = value = ""
    for pattern, template in _ATTRIBUTE_PATTERNS:
        match = pattern.match(content)
        if not match:
            continue
        groups = match.groupdict()
        attr = normalize(template.format(attr=groups.get("attr", ""))).replace("favourite", "favorite")
        single = attr in _SINGLE_VALUED or attr.startswith(("favorite ", "preferred ")) or attr.endswith(" name")
        if "{attr}" not in template:
            single = True  # "I live in ...", "call me ..." and the like
        if single:
            attribute, value = attr, groups["value"].strip()
        break
    return {"kind": kind, "attribute": attribute, "value": value}


def forget_terms(query: str) -> list[str]:
    """The distinctive words of a forget request."""

    return [term for term in dict.fromkeys(normalize(query).split()) if len(term) > 1 and term not in FORGET_FILLER]


def matches_terms(text: Any, terms: list[str]) -> bool:
    """True when `text` contains every term as a whole word."""

    words = set(normalize(text).split())
    return bool(terms) and all(term in words for term in terms)


def entry_matches(key: str, entry: Any, terms: list[str]) -> bool:
    """Whether a preference, pattern or candidate record is what a forget request means.

    It matches when the request's words all appear in the record, including the statement the
    preference came from ("I prefer short answers"). Older records have no statement, only a
    derived value such as "short"; those match when the request names the whole value.
    """

    if not terms:
        return False
    value = entry.get("value", "") if isinstance(entry, dict) else entry
    statement = entry.get("statement", "") if isinstance(entry, dict) else ""
    if matches_terms(f"{key} {value} {statement}", terms):
        return True
    value_words = set(normalize(value).split())
    return not statement and bool(value_words) and value_words <= set(terms)


def empty_profile() -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "facts": [],
        "forgotten": [],
        "preferences": {},
        "patterns": {},
        "recurring_topics": {},
        "recent_feedback": [],
        "updated_at": now_iso(),
    }


def _new_record(text: str, *, source: str, kind: str | None, expires_at: str | None, now: str) -> dict[str, Any]:
    info = classify_statement(text)
    resolved_kind = kind or ("inferred" if source == "inferred_from_chat" else info["kind"])
    return {
        "id": fact_id(text),
        "text": text,
        "kind": resolved_kind,
        "source": source,
        "confidence": "inferred" if resolved_kind == "inferred" else "stated",
        "attribute": info["attribute"],
        "value": info["value"],
        "status": "active",
        "created_at": now,
        "updated_at": now,
        "last_verified_at": now if resolved_kind != "inferred" else None,
        "expires_at": expires_at,
        "superseded_by": None,
        "supersedes": [],
    }


def migrate_profile(payload: Any) -> tuple[dict[str, Any], bool]:
    """Bring a saved profile of any earlier shape up to SCHEMA_VERSION.

    Returns (profile, changed). Version 1 had no version field: facts were plain strings or
    dicts with id/text/kind/source/updated_at, and ids could be random or process-dependent.
    """

    if not isinstance(payload, dict):
        payload = {"facts": payload if isinstance(payload, list) else []}
    version = int(payload.get("schema_version") or 1)
    if version > SCHEMA_VERSION:
        raise ValueError(
            f"The saved profile is version {version}, newer than this app understands ({SCHEMA_VERSION}). "
            "Update the app; the file was left untouched."
        )
    changed = version < SCHEMA_VERSION
    profile = dict(payload)
    for key, default in empty_profile().items():
        if key not in profile or (key != "updated_at" and not isinstance(profile[key], type(default))):
            profile[key] = default
            changed = changed or key not in {"updated_at"}
    if version < 2:
        now = now_iso()
        migrated: dict[str, dict[str, Any]] = {}
        for item in profile["facts"]:
            text = " ".join(str((item.get("text") or item.get("value") or "") if isinstance(item, dict) else item or "").split())
            if not text:
                continue
            old = item if isinstance(item, dict) else {}
            stamp = str(old.get("updated_at") or "") or now
            old_source = str(old.get("source") or "")
            record = _new_record(
                text,
                source="user_statement" if old_source.startswith("explicit") else "legacy",
                kind=None,
                expires_at=None,
                now=stamp,
            )
            # Whether the user said it or the app guessed it was not recorded before version 2.
            record["last_verified_at"] = stamp if old_source.startswith("explicit") else None
            record["migrated_from"] = 1
            migrated[record["id"]] = record  # the same text twice becomes one record
        profile["facts"] = list(migrated.values())
        profile["schema_version"] = 2
    return profile, changed


def _quarantine(path: Path, error: Exception) -> None:
    """Keep a damaged profile for recovery instead of overwriting it with an empty one."""

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    kept = path.with_name(f"{path.name}.damaged-{stamp}")
    try:
        shutil.copy2(path, kept)
    except OSError as exc:
        logger.error("Could not keep a copy of the damaged profile %s: %s", path, exc)
        raise
    record_event("error", f"{path.name} could not be read and was set aside as {kept.name}", error=str(error))
    logger.error("Saved profile %s is damaged (%s); a copy was kept as %s", path, error, kept)


def _backup_before_migration(path: Path, from_version: int) -> None:
    backup = path.with_name(f"{path.stem}.v{from_version}.backup{path.suffix}")
    if not backup.exists():
        shutil.copy2(path, backup)


def _load_locked(path: Path) -> tuple[dict[str, Any], bool]:
    """Read and migrate. Call with the lock held. Returns (profile, needs_saving)."""

    try:
        payload = read_json(path, None)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        _quarantine(path, exc)
        return empty_profile(), True
    if payload is None:
        return empty_profile(), False
    from_version = int(payload.get("schema_version") or 1) if isinstance(payload, dict) else 1
    profile, changed = migrate_profile(payload)
    if changed and from_version < SCHEMA_VERSION:
        _backup_before_migration(path, from_version)
    return profile, changed


def load_profile(path: Path | None = None) -> dict[str, Any]:
    """The current profile, migrated if it was saved by an older version."""

    resolved = Path(path or PROFILE_FILE)
    if not resolved.exists():
        return empty_profile()
    try:
        payload = read_json(resolved, None)
        if isinstance(payload, dict) and int(payload.get("schema_version") or 1) == SCHEMA_VERSION:
            profile, _changed = migrate_profile(payload)
            return profile
    except (json.JSONDecodeError, UnicodeDecodeError, ValueError):
        pass
    with locked(resolved):
        profile, changed = _load_locked(resolved)
        if changed:
            atomic_write_json(resolved, profile)
        return profile


def _prune(profile: dict[str, Any], now: datetime) -> None:
    """Drop history that has outlived its retention, and cap the tombstone list."""

    kept = []
    for fact in profile["facts"]:
        updated = parse_time(fact.get("updated_at")) or now
        if fact.get("status") == "superseded" and now - updated > timedelta(days=SUPERSEDED_RETENTION_DAYS):
            continue
        expires = parse_time(fact.get("expires_at"))
        if expires and now - expires > timedelta(days=EXPIRED_RETENTION_DAYS):
            continue
        kept.append(fact)
    profile["facts"] = kept
    profile["forgotten"] = profile["forgotten"][-MAX_TOMBSTONES:]


def update_profile(change: Callable[[dict[str, Any]], Any], path: Path | None = None) -> Any:
    """Apply `change` to the saved profile as one locked read-change-write. Returns its result."""

    resolved = Path(path or PROFILE_FILE)
    with locked(resolved):
        profile, _changed = _load_locked(resolved)
        result = change(profile)
        _prune(profile, datetime.now(timezone.utc))
        profile["updated_at"] = now_iso()
        atomic_write_json(resolved, profile)
        return result


def is_expired(fact: dict[str, Any], now: datetime | None = None) -> bool:
    expires = parse_time(fact.get("expires_at"))
    return bool(expires and expires <= (now or datetime.now(timezone.utc)))


def active_facts(profile: dict[str, Any], now: datetime | None = None) -> list[dict[str, Any]]:
    """Facts that should be used: not replaced by a newer statement and not expired."""

    return [fact for fact in profile.get("facts", []) if fact.get("status") == "active" and not is_expired(fact, now)]


def remember(
    text: str,
    *,
    path: Path | None = None,
    source: str = "user_statement",
    kind: str | None = None,
    expires_at: str | None = None,
    replace: bool = True,
) -> dict[str, Any]:
    """Save a fact. A new value for something single-valued replaces the old one (kept as history).

    replace=False keeps both ("remember also: my cat is named Luna").
    """

    content = " ".join(str(text or "").strip().split())
    if not content:
        return {"success": False, "action": "remember", "message": "Tell me what you want me to remember."}

    def change(profile: dict[str, Any]) -> dict[str, Any]:
        now = now_iso()
        record = _new_record(content, source=source, kind=kind, expires_at=expires_at, now=now)
        facts: list[dict[str, Any]] = profile["facts"]
        existing = next((fact for fact in facts if fact["id"] == record["id"] and fact.get("status") == "active"), None)
        if existing is not None:
            # Said again: the strongest confirmation there is.
            existing["updated_at"] = now
            if record["kind"] != "inferred":
                existing["last_verified_at"] = now
                if existing.get("kind") == "inferred":
                    existing.update(kind=record["kind"], source=source, confidence="stated")
            existing["expires_at"] = expires_at
            facts.remove(existing)
            facts.append(existing)
            return {"fact": existing, "duplicate": True, "replaced": [], "full": False}
        if len(active_facts(profile)) >= MAX_ACTIVE_FACTS:
            return {"fact": None, "duplicate": False, "replaced": [], "full": True}
        replaced: list[dict[str, Any]] = []
        if replace and record["attribute"] and record["kind"] != "inferred":
            for fact in facts:
                if (
                    fact.get("status") == "active"
                    and fact.get("attribute") == record["attribute"]
                    and normalize(fact.get("value")) != normalize(record["value"])
                ):
                    fact.update(status="superseded", superseded_by=record["id"], updated_at=now)
                    replaced.append(fact)
        record["supersedes"] = [fact["id"] for fact in replaced]
        # The user said it again, so an earlier "forget" no longer applies; and an old inactive
        # record with the same wording is replaced by this one.
        profile["forgotten"] = [item for item in profile["forgotten"] if item.get("id") != record["id"]]
        profile["facts"] = [fact for fact in facts if fact["id"] != record["id"]] + [record]
        return {"fact": record, "duplicate": False, "replaced": replaced, "full": False}

    outcome = update_profile(change, path)
    if outcome["full"]:
        return {
            "success": False,
            "action": "remember",
            "message": f"Saved memory is full ({MAX_ACTIVE_FACTS} items). Tell me what to forget first.",
        }
    message = f"I'll remember that: {content}"
    if outcome["replaced"]:
        old = "; ".join(f'"{fact["text"]}"' for fact in outcome["replaced"])
        message += f'\n\nThis replaces what I had before: {old}. If both are true, say "remember also: {content}".'
    elif outcome["duplicate"]:
        message += "\n\nI already had that; I've noted that you confirmed it."
    if expires_at:
        message += f"\n\nI'll stop using it after {expires_at[:16].replace('T', ' ')} UTC."
    profile = load_profile(path)
    return {
        "success": True,
        "action": "remember",
        "message": message,
        "fact": outcome["fact"],
        "duplicate": outcome["duplicate"],
        "replaced": [fact["id"] for fact in outcome["replaced"]],
        "fact_count": len(active_facts(profile)),
    }


def _forget_candidates(folder: Path, terms: list[str]) -> int:
    """Remove matching entries from the adaptive memory's candidate list."""

    candidates = folder / "memory_candidates.json"
    if not candidates.exists():
        return 0

    def change(data: Any) -> int:
        if not isinstance(data, dict):
            return 0
        doomed = [key for key, value in data.items() if entry_matches(key.replace(":", " "), value, terms)]
        for key in doomed:
            del data[key]
        return len(doomed)

    try:
        return int(update_json(candidates, change))
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Could not update %s while forgetting: %s", candidates, exc)
        return 0


def forget(query: str, *, path: Path | None = None) -> dict[str, Any]:
    """Remove saved facts that contain every distinctive word of the request, as whole words.

    Deletion reaches every copy this app keeps of the fact: earlier values it replaced, matching
    stated or inferred preferences, and the adaptive memory's candidates. A record of the deleted
    ids (not their text) stays so that a stale copy elsewhere cannot bring the fact back.
    """

    terms = forget_terms(query)
    if not terms:
        return {
            "success": False,
            "action": "forget",
            "message": "Tell me which saved memory to forget: give a word or phrase from it.",
            "removed": 0,
        }
    resolved = Path(path or PROFILE_FILE)

    def change(profile: dict[str, Any]) -> dict[str, int]:
        facts: list[dict[str, Any]] = profile["facts"]
        doomed = {fact["id"] for fact in facts if matches_terms(fact.get("text"), terms)}
        removed = sum(1 for fact in facts if fact["id"] in doomed and fact.get("status") == "active")
        # Follow the replacement history in both directions so no earlier value survives.
        grew = True
        while grew:
            grew = False
            for fact in facts:
                linked = fact.get("superseded_by") in doomed or any(old in doomed for old in fact.get("supersedes") or [])
                if fact["id"] not in doomed and linked and fact.get("status") == "superseded":
                    doomed.add(fact["id"])
                    grew = True
        now = now_iso()
        profile["facts"] = [fact for fact in facts if fact["id"] not in doomed]
        profile["forgotten"] = [item for item in profile["forgotten"] if item.get("id") not in doomed] + [
            {"id": fact_id_, "forgotten_at": now} for fact_id_ in sorted(doomed)
        ]
        extras = 0
        for section in ("preferences", "patterns"):
            entries = profile.get(section) or {}
            for key in [key for key, value in entries.items() if entry_matches(key, value, terms)]:
                del entries[key]
                extras += 1
        return {"removed": removed, "history": len(doomed) - removed, "extras": extras}

    counts = update_profile(change, resolved)
    counts["extras"] += _forget_candidates(resolved.parent, terms)
    fact_count = len(active_facts(load_profile(resolved)))
    if counts["removed"] or counts["history"] or counts["extras"]:
        message = f"I forgot {counts['removed']} matching saved memory item(s)."
        details = []
        if counts["history"]:
            details.append(f"{counts['history']} earlier value(s) it had replaced")
        if counts["extras"]:
            details.append(f"{counts['extras']} related preference or pattern record(s)")
        if details:
            message += " Also removed: " + " and ".join(details) + "."
        message += " The chat history still shows the messages where it was said; clear the chat to remove those too."
        return {
            "success": True,
            "action": "forget",
            "message": message,
            "removed": counts["removed"],
            "removed_history": counts["history"],
            "removed_related": counts["extras"],
            "fact_count": fact_count,
            "terms": terms,
        }
    return {
        "success": False,
        "action": "forget",
        "message": "I couldn't find a matching saved memory to forget.",
        "removed": 0,
        "fact_count": fact_count,
    }


def update_sections(sections: dict[str, Any], path: Path | None = None) -> None:
    """Replace whole profile sections other than the facts (preferences, patterns, topics,
    feedback). Facts are only changed through remember() and forget()."""

    allowed = {"preferences", "patterns", "recurring_topics", "recent_feedback"}

    def change(profile: dict[str, Any]) -> None:
        for key, value in sections.items():
            if key in allowed:
                profile[key] = value

    update_profile(change, path)


def wipe_profile(path: Path | None = None) -> None:
    """Remove every saved fact, preference and pattern. Permanent."""

    resolved = Path(path or PROFILE_FILE)
    with locked(resolved):
        atomic_write_json(resolved, empty_profile())
