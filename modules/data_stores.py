"""Where every kind of saved data lives.

The app keeps several separate kinds ("families") of data. They are listed once, here, and this
list drives the documentation (docs/DATA_STORES.md), export, backup, restore, selective wipe, the
start-up integrity check and test isolation. A module that saves something takes its path from
this file instead of spelling out "data/..." itself.

By default everything stays where it always was, inside the project folder. Set
COGNITIVE_NEXUS_HOME to keep all of it somewhere else (for example outside a Git checkout, so
private data cannot be committed by accident):

    COGNITIVE_NEXUS_HOME=D:\\NexusData   ->  D:\\NexusData\\data, \\knowledge_bank, \\logs, \\config

COGNITIVE_NEXUS_DATA_DIR, _KNOWLEDGE_DIR, _LOG_DIR and _CONFIG_DIR override single folders.

The Android app's chat sessions are not in this list: its backend keeps them in its own SQLite
database (see the cognitive-nexus-android repository). Everything else the phone backend reads or
writes goes through the same engine modules and therefore the same files and locks as below.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _folder(env_name: str, home_part: str, default: Path) -> Path:
    explicit = os.environ.get(env_name, "").strip()
    if explicit:
        return Path(explicit).expanduser()
    home = os.environ.get("COGNITIVE_NEXUS_HOME", "").strip()
    if home:
        return Path(home).expanduser() / home_part
    return default


# The data defaults are relative, as they always were: the app is started from the project
# folder, and paths saved inside data files (where an image is, for example) stay portable.
DATA_ROOT = _folder("COGNITIVE_NEXUS_DATA_DIR", "data", Path("data"))
KNOWLEDGE_ROOT = _folder("COGNITIVE_NEXUS_KNOWLEDGE_DIR", "knowledge_bank", Path("ai_system/knowledge_bank"))
LOG_ROOT = _folder("COGNITIVE_NEXUS_LOG_DIR", "logs", PROJECT_ROOT / "logs")
CONFIG_ROOT = _folder("COGNITIVE_NEXUS_CONFIG_DIR", "config", PROJECT_ROOT / "config")
# Example conversations shipped with the app. Read-only, never user data.
SEED_KNOWLEDGE_DIR = PROJECT_ROOT / "data" / "seed_knowledge"

_ROOT_NAMES = {"data": DATA_ROOT, "knowledge": KNOWLEDGE_ROOT, "logs": LOG_ROOT, "config": CONFIG_ROOT}


@dataclass(frozen=True)
class Store:
    """One family of saved data."""

    key: str
    title: str
    holds: str
    # (root name, path under that root). A path ending in "/" is a folder.
    locations: tuple[tuple[str, str], ...]
    # private: written by or about the user. learned: derived by the app from use.
    # settings: configuration. cache: can be rebuilt. log: diagnostics.
    sensitivity: str
    written_by: str
    in_backup: bool = True
    # Credentials: never copied into a backup, an export or a snapshot, even when asked for by
    # name, and never taken from an archive on restore. They can still be deleted (wipe).
    holds_credentials: bool = False
    # Extra files that belong to the store but are matched by pattern (backups, set-aside copies).
    companions: tuple[tuple[str, str], ...] = ()

    def paths(self) -> list[Path]:
        return [_ROOT_NAMES[root] / relative.rstrip("/") for root, relative in self.locations]

    def files(self) -> list[Path]:
        """Every existing file of this store."""

        found: list[Path] = []
        for path in self.paths():
            if path.is_dir():
                found.extend(sorted(item for item in path.rglob("*") if item.is_file() and not item.name.endswith(".lock")))
            elif path.is_file():
                found.append(path)
        for root, pattern in self.companions:
            found.extend(sorted(item for item in _ROOT_NAMES[root].glob(pattern) if item.is_file()))
        return found


STORES: tuple[Store, ...] = (
    Store(
        key="chat_history",
        title="Chat history",
        holds="The messages of the desktop chat, with a label on each reply saying how it was produced.",
        locations=(("data", "chat_history.json"), ("knowledge", "chat_history.json")),
        sensitivity="private",
        written_by="modules/memory.py (the second file is from the 2.0 app and is only read)",
    ),
    Store(
        key="user_profile",
        title="Saved facts and preferences",
        holds="What you asked the app to remember, with how each item is known, plus stated preferences and habits the app inferred.",
        locations=(("data", "user_profile.json"),),
        sensitivity="private",
        written_by="modules/profile_store.py only",
        companions=(("data", "user_profile.v*.backup.json"), ("data", "user_profile.json.damaged-*")),
    ),
    Store(
        key="adaptive_memory",
        title="Adaptive memory working files",
        holds="Habits seen fewer than three times (not yet treated as a pattern) and the thumbs-up/down feedback log.",
        locations=(("data", "memory_candidates.json"), ("data", "feedback_log.jsonl")),
        sensitivity="private",
        written_by="cognitive_nexus/adaptation.py",
    ),
    Store(
        key="chat_persona",
        title="Chat persona",
        holds="The assistant name, your name and the tone settings chosen in the sidebar.",
        locations=(("data", "chat_profile.json"),),
        sensitivity="private",
        written_by="modules/chat_profile.py",
    ),
    Store(
        key="response_learning",
        title="Response tuning",
        holds="Scores and counts the app keeps about its own answers. No message text.",
        locations=(("data", "response_preferences.json"), ("data", "reality_grounding_patterns.json")),
        sensitivity="learned",
        written_by="modules/response_planner.py, modules/response_self_critic.py, core/reality_grounding/answer_auditor.py",
    ),
    Store(
        key="knowledge_index",
        title="Knowledge index",
        holds="The pages, files and saved research you added, split into passages, with a keyword index and search vectors, in one SQLite database.",
        locations=(("knowledge", "web_research/"),),
        sensitivity="private",
        written_by="modules/knowledge_store.py only",
    ),
    Store(
        key="knowledge_notes",
        title="Knowledge notes",
        holds="Notes saved from the Files / Knowledge tab, as Markdown files.",
        locations=(("data", "knowledge_notes/"),),
        sensitivity="private",
        written_by="modules/research.py",
    ),
    Store(
        key="web_research",
        title="Web research sessions",
        holds="One JSON and one Markdown file per web research run: the query, sources, page text and summary.",
        locations=(("data", "web_research/"),),
        sensitivity="private",
        written_by="modules/web_research.py",
    ),
    Store(
        key="research_reports",
        title="Reality-First research reports",
        holds="Saved reports and the index of their summaries.",
        locations=(("data", "research_reports/"),),
        sensitivity="private",
        written_by="modules/reality_research_agent.py",
    ),
    Store(
        key="search_history",
        title="Bloodhound search history",
        holds="Saved Bloodhound searches: queries and ranked results.",
        locations=(("data", "search_history/"),),
        sensitivity="private",
        written_by="search/bloodhound_search.py",
    ),
    Store(
        key="search_cache",
        title="Search cache",
        holds="Cached search results, reused for up to a day. Safe to delete.",
        locations=(("data", "search_cache/"),),
        sensitivity="cache",
        written_by="search/bloodhound_search.py",
        in_backup=False,
    ),
    Store(
        key="images",
        title="Generated images",
        holds="Images you generated and, for each, a file with the prompt and settings used.",
        locations=(("data", "images/"), ("data", "comfyui/"), ("knowledge", "images/")),
        sensitivity="private",
        written_by="modules/image_gen.py, modules/comfyui_client.py (the third folder is from the 2.0 app)",
    ),
    Store(
        key="agent_state",
        title="Agent tasks and action history",
        holds="Tasks given to the agent, every action it took (inputs, approval, result), approval requests, and the background job queue.",
        locations=(("data", "agent/agent.db"),),
        sensitivity="private",
        written_by="agent/store.py, agent/jobs.py",
        companions=(("data", "agent/agent.db-wal"), ("data", "agent/agent.db-shm")),
    ),
    Store(
        key="agent_workspaces",
        title="Agent workspaces",
        holds="The private checkout of each coding task (a Git worktree of your repository on its own branch). The work itself is kept as commits on that branch in your repository.",
        locations=(("data", "agent/ws/"),),
        sensitivity="private",
        written_by="agent/workspace.py",
        in_backup=False,
    ),
    Store(
        key="snapshots",
        title="Local snapshots",
        holds="Copies of the data above, taken daily and before a restore, so a change can be undone. The newest seven are kept.",
        locations=(("data", "_snapshots/"),),
        sensitivity="private",
        written_by="modules/backup.py",
        in_backup=False,
    ),
    Store(
        key="settings",
        title="Settings",
        holds="Provider order, model names and feature switches. API keys are not stored here; they are in Linked accounts or in .env.",
        locations=(("config", "nexus_config.json"),),
        sensitivity="settings",
        written_by="modules/nexus_config.py",
    ),
    Store(
        key="linked_accounts",
        title="Linked accounts",
        holds="Credentials for outside services (GitHub, OpenAI, Anthropic, Brave Search, your own), with what each may be used for and when it runs out. On Windows each secret is encrypted for your Windows user; elsewhere the file is readable by your user only. Never part of a backup or an export.",
        locations=(("config", "accounts.json"),),
        sensitivity="private",
        written_by="modules/accounts.py only",
        in_backup=False,
        holds_credentials=True,
    ),
    Store(
        key="logs",
        title="Logs",
        holds="Problem events by kind and per-answer verification records. No prompts or answers.",
        locations=(("logs", ""),),
        sensitivity="log",
        written_by="modules/event_log.py, modules/response_verifier.py",
        in_backup=False,
    ),
)

_BY_KEY = {store.key: store for store in STORES}


def get_store(key: str) -> Store:
    try:
        return _BY_KEY[key]
    except KeyError:
        raise KeyError(f"Unknown data store '{key}'. Known stores: {', '.join(_BY_KEY)}") from None


def describe_location(root: str, relative: str) -> str:
    """A location as written in documentation, independent of where the roots are on this machine."""

    return f"<{root}>/{relative}" if relative else f"<{root}>/"


def summarize_stores() -> list[dict[str, Any]]:
    """One row per store with its size on this machine, for Diagnostics."""

    rows = []
    for store in STORES:
        files = store.files()
        newest = max((item.stat().st_mtime for item in files), default=0.0)
        rows.append(
            {
                "key": store.key,
                "title": store.title,
                "files": len(files),
                "bytes": sum(item.stat().st_size for item in files),
                "last_changed": datetime.fromtimestamp(newest).isoformat(timespec="seconds") if newest else "",
                "kind": store.sensitivity,
                "in_backup": store.in_backup,
            }
        )
    return rows


def render_markdown() -> str:
    """docs/DATA_STORES.md, generated so the documentation cannot drift from the code."""

    lines = [
        "# What Cognitive Nexus saves, and where",
        "",
        "Generated from `modules/data_stores.py` by `python tools/render_data_stores.py`. Do not edit by hand.",
        "",
        "Each kind of saved data is separate and has one module that writes it. `<data>`, `<knowledge>`, `<logs>` and",
        "`<config>` are folders inside the project by default (`data/`, `ai_system/knowledge_bank/`, `logs/`, `config/`).",
        "Set `COGNITIVE_NEXUS_HOME` to keep all four somewhere else, for example outside a Git checkout.",
        "",
        "| Data | What it holds | Where | Kind | In backups | Written by |",
        "|---|---|---|---|---|---|",
    ]
    for store in STORES:
        where = "<br>".join(f"`{describe_location(root, relative)}`" for root, relative in store.locations)
        lines.append(
            f"| **{store.title}** (`{store.key}`) | {store.holds} | {where} | {store.sensitivity} | "
            f"{'yes' if store.in_backup else 'no'} | {store.written_by} |"
        )
    lines += [
        "",
        "## Kinds",
        "",
        "- **private**: written by you or about you. Never commit these to a public repository.",
        "- **learned**: numbers the app derives from use; no message text.",
        "- **settings**: configuration without secrets.",
        "- **cache**: can be deleted at any time; it is rebuilt when needed.",
        "- **log**: diagnostics.",
        "",
        "## Not in this list",
        "",
        "- **API keys** live in `.env` in the project folder. They are never exported or backed up by the app.",
        "- **Android chat sessions** are kept by the phone backend in its own SQLite database (see the",
        "  `cognitive-nexus-android` repository). Facts, knowledge and research the phone uses go through the engine",
        "  modules above and are the same files.",
        "- **Example conversations** shipped with the app (`data/seed_knowledge/`) are part of the program, not your data.",
        "- **Downloaded models** are kept by Ollama and Hugging Face in their own folders.",
        "",
        "## Safe concurrent use",
        "",
        "Files that more than one program or tab can change are changed as one read-change-write under a lock file",
        "(`<name>.lock` next to the data file), so the desktop app and the phone backend do not overwrite each other.",
        "The knowledge index is a SQLite database, which gives the same protection through its own transactions.",
        "",
    ]
    return "\n".join(lines)
