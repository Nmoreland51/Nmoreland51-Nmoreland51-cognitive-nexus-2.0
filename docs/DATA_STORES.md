# What Cognitive Nexus saves, and where

Generated from `modules/data_stores.py` by `python tools/render_data_stores.py`. Do not edit by hand.

Each kind of saved data is separate and has one module that writes it. `<data>`, `<knowledge>`, `<logs>` and
`<config>` are folders inside the project by default (`data/`, `ai_system/knowledge_bank/`, `logs/`, `config/`).
Set `COGNITIVE_NEXUS_HOME` to keep all four somewhere else, for example outside a Git checkout.

| Data | What it holds | Where | Kind | In backups | Written by |
|---|---|---|---|---|---|
| **Chat history** (`chat_history`) | The messages of the desktop chat, with a label on each reply saying how it was produced. | `<data>/chat_history.json`<br>`<knowledge>/chat_history.json` | private | yes | modules/memory.py (the second file is from the 2.0 app and is only read) |
| **Saved facts and preferences** (`user_profile`) | What you asked the app to remember, with how each item is known, plus stated preferences and habits the app inferred. | `<data>/user_profile.json` | private | yes | modules/profile_store.py only |
| **Adaptive memory working files** (`adaptive_memory`) | Habits seen fewer than three times (not yet treated as a pattern) and the thumbs-up/down feedback log. | `<data>/memory_candidates.json`<br>`<data>/feedback_log.jsonl` | private | yes | cognitive_nexus/adaptation.py |
| **Chat persona** (`chat_persona`) | The assistant name, your name and the tone settings chosen in the sidebar. | `<data>/chat_profile.json` | private | yes | modules/chat_profile.py |
| **Response tuning** (`response_learning`) | Scores and counts the app keeps about its own answers. No message text. | `<data>/response_preferences.json`<br>`<data>/reality_grounding_patterns.json` | learned | yes | modules/response_planner.py, modules/response_self_critic.py, core/reality_grounding/answer_auditor.py |
| **Knowledge index** (`knowledge_index`) | The pages, files and saved research you added, split into passages, with a keyword index and search vectors, in one SQLite database. | `<knowledge>/web_research/` | private | yes | modules/knowledge_store.py only |
| **Knowledge notes** (`knowledge_notes`) | Notes saved from the Files / Knowledge tab, as Markdown files. | `<data>/knowledge_notes/` | private | yes | modules/research.py |
| **Web research sessions** (`web_research`) | One JSON and one Markdown file per web research run: the query, sources, page text and summary. | `<data>/web_research/` | private | yes | modules/web_research.py |
| **Reality-First research reports** (`research_reports`) | Saved reports and the index of their summaries. | `<data>/research_reports/` | private | yes | modules/reality_research_agent.py |
| **Bloodhound search history** (`search_history`) | Saved Bloodhound searches: queries and ranked results. | `<data>/search_history/` | private | yes | search/bloodhound_search.py |
| **Search cache** (`search_cache`) | Cached search results, reused for up to a day. Safe to delete. | `<data>/search_cache/` | cache | no | search/bloodhound_search.py |
| **Generated images** (`images`) | Images you generated and, for each, a file with the prompt and settings used. | `<data>/images/`<br>`<data>/comfyui/`<br>`<knowledge>/images/` | private | yes | modules/image_gen.py, modules/comfyui_client.py (the third folder is from the 2.0 app) |
| **Agent tasks and action history** (`agent_state`) | Tasks given to the agent, every action it took (inputs, approval, result), approval requests, and the background job queue. | `<data>/agent/agent.db` | private | yes | agent/store.py, agent/jobs.py |
| **Agent workspaces** (`agent_workspaces`) | The private checkout of each coding task (a Git worktree of your repository on its own branch). The work itself is kept as commits on that branch in your repository. | `<data>/agent/ws/` | private | no | agent/workspace.py |
| **Local snapshots** (`snapshots`) | Copies of the data above, taken daily and before a restore, so a change can be undone. The newest seven are kept. | `<data>/_snapshots/` | private | no | modules/backup.py |
| **Settings** (`settings`) | Provider order, model names and feature switches. API keys are not stored here; they are in Linked accounts or in .env. | `<config>/nexus_config.json` | settings | yes | modules/nexus_config.py |
| **Linked accounts** (`linked_accounts`) | Credentials for outside services (GitHub, OpenAI, Anthropic, Brave Search, your own), with what each may be used for and when it runs out. On Windows each secret is encrypted for your Windows user; elsewhere the file is readable by your user only. Never part of a backup or an export. | `<config>/accounts.json` | private | no | modules/accounts.py only |
| **Logs** (`logs`) | Problem events by kind and per-answer verification records. No prompts or answers. | `<logs>/` | log | no | modules/event_log.py, modules/response_verifier.py |

## Kinds

- **private**: written by you or about you. Never commit these to a public repository.
- **learned**: numbers the app derives from use; no message text.
- **settings**: configuration without secrets.
- **cache**: can be deleted at any time; it is rebuilt when needed.
- **log**: diagnostics.

## Not in this list

- **API keys** live in `.env` in the project folder. They are never exported or backed up by the app.
- **Android chat sessions** are kept by the phone backend in its own SQLite database (see the
  `cognitive-nexus-android` repository). Facts, knowledge and research the phone uses go through the engine
  modules above and are the same files.
- **Example conversations** shipped with the app (`data/seed_knowledge/`) are part of the program, not your data.
- **Downloaded models** are kept by Ollama and Hugging Face in their own folders.

## Safe concurrent use

Files that more than one program or tab can change are changed as one read-change-write under a lock file
(`<name>.lock` next to the data file), so the desktop app and the phone backend do not overwrite each other.
The knowledge index is a SQLite database, which gives the same protection through its own transactions.
