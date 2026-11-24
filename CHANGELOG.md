# Changelog

Notable changes to the engine and desktop app. Versions follow `cognitive_nexus/version.py`.

## 2.1.0 (unreleased)

### Owner control

What the assistant may say is now the owner's decision, visible in one place. The full account is `docs/OWNER_CONTROL.md`; every mechanism is listed in `docs/OWNER_CONTROL_RESTRICTIONS.md`.

- **The app has one content rule (no sexual content involving minors) and no topic filters.** Removed: a keyword classifier that labelled "how do I kill a stuck process" as harmful and answered such messages with a canned text without asking the model; a block on the letters "child", "cp" and "illegal"; prompt lines telling the model to stay "defensive" and "high level"; a "locked" prompt the persona could not override; a safety slider and checkboxes that changed nothing; and flags named "allow" and "bypass" that added restrictions.
- A model's own refusal is shown as written and marked as the model's. The app used to replace it with a text of its own.
- **Your own messages are never scanned, scored or fenced.** The prompt firewall used to wrap every message you sent as "untrusted" and rate phrases such as "act as" and "from now on" as hostile. It now applies only to text you did not write (web pages, documents, tool output).
- **Settings, Behaviour**: your own text for how the assistant should answer, saved and applied on every turn; the whole system prompt shown word for word; the last prompt exactly as it was sent; what the selected model or its provider may do; and the permissions and protections, each with whether you can change it.
- Three settings with measured consequences: how text from web pages and files is handled (planted instructions obeyed 0, 6 or 7 times out of 12), what the reality check does (label, withhold, or off; it used to withhold detail even in fiction), and how far the coding agent goes unasked.
- The one content rule is checked before anything is written or drawn, and the check was measured with the real model: on requests it was never adjusted on, 36 of 36 forbidden requests were stopped and 43 of 44 ordinary ones answered. The first version of the check stopped 2 of 13; `docs/benchmarks/README.md` has the history.
- **Pictures are held to a stricter line than you asked for**: no picture that would show anyone under 18 nude or undressed, whatever the scene. This is the assistant's own limit, not the owner's rule, and is described as such wherever it appears.
- The greeting no longer claims limits the app does not have.

### Fixed
- The chat-model list no longer offers embedding models. With `all-minilm` installed for knowledge search, the app picked it as the default chat model, and it cannot chat.
- Chat no longer falls back after 12 seconds on CPU-only machines; Ollama gets at least 120 seconds for the first token and stays loaded between requests.
- Chat web search now runs when asked, answers in under a minute on CPU with sources, and says so when search finds nothing instead of inventing an answer.
- Research verdicts are based on passages that address the claim. "TRUE at 0.8 confidence" from unrelated trusted sites is gone.
- "forget it" no longer deletes unrelated memories; fact ids are stable across launches.
- Deep-mode answers get their intended 780-token budget (a misplaced branch capped them at 420).
- The fallback reply names the provider that failed and why.
- A failed model is no longer saved or shown as an answer: research summaries, knowledge answers and reports show a plain failure notice and store nothing as a "summary". An answer cut off part-way is marked as cut off.
- If the local model fails, the prompt is no longer sent to OpenAI or Anthropic just because a key is configured. Cloud providers are used only when placed first in the provider order or when "Allow cloud fallback" is turned on.
- The Anthropic provider would have failed on every request: its default model (`claude-sonnet-4-20250514`) was retired in June 2026. The default is now `claude-sonnet-5-5`, retired model names in saved settings are replaced automatically, and the request follows the current API. Not yet run against the live API (no key was available).
- A local model whose name starts with "o" (for example `orca-mini`) is no longer sent to OpenAI as a model name.
- Long prompts are no longer cut by the model server. A normal 2,147-token chat prompt was being sent with a 2,048-token window, and Ollama silently kept 1,026 tokens, dropping the instructions. The prompt is now sized in tokens against the model's real window and trimmed in a fixed order, least important first.
- The adaptive memory no longer erases facts saved by "remember ...": it kept its own copy of the profile and wrote it back whole. Its "forget" no longer matches parts of words ("forget it" could erase every memory containing "it").
- Saved memory no longer drops old facts silently at 25 or 60 items; the limit is 500 and reaching it is reported.
- Two programs or tabs saving at the same time no longer overwrite each other's changes (measured before the fix: 22 of 80 concurrent updates survived).
- A web page can no longer give the model instructions. Page text was pasted straight into the prompt, and the local model obeyed 6 of 12 planted instructions ("end every answer with ...", "do not tell the user ..."). Sentences aimed at an AI model are now removed, the rest is fenced as untrusted, and a page cannot forge the end of the fence: 0 of 12 obeyed, with the real facts still answered.
- The claim check no longer counts a passage as support because it shares the claim's words. It compares the same statement: a different figure, a different year for a one-time event, or the opposite word ("fell" for "rose") contradicts; another year of a recurring event, a question, a hedge, an open question or a reported opinion settles nothing; a passage about someone else is not about the claim.
- "Latest version" answers could stay whatever they were when the app started: search results and fetched pages were cached with no expiry. They now expire after 10 and 30 minutes, and failed fetches are not remembered.
- Contradictions between sources were flagged whenever two sentences shared words and one contained "not". They are now found with the claim check's rules, between statements made outright, about the same thing.

### Added
- Search sources with automatic switching (SearXNG, Brave Search API, search pages, Wikipedia).
- Refusal to fetch local and private-network addresses during research.
- Crash-safe (atomic) saves for memory, settings and the knowledge index.
- Local image generation downloads 2.0 GB instead of 5.1 GB.
- Continuous integration: tests on Windows and Ubuntu, lint, type check, secret scan, dependency audit.
- `docs/STATUS.md`, the audit ledger (`docs/AUDIT_146_PROGRESS.md`) and pinned dependencies (`requirements/constraints.txt`).
- Every reply is labelled with who wrote it (provider and model, or no model), whether the prompt stayed on this machine, the time taken, the cost when a cloud provider reports usage, and the tools that ran.
- The chat model is checked with a real test prompt at start; Diagnostics can send a test prompt to any provider and shows a provider as working only after it has produced text.
- Diagnostics counts model failures, fallback notices, search-source failures and tool failures separately (also written to `logs/events.jsonl`).
- Cloud calls retry rate limits and dropped connections and report the provider's own error message.
- Saved facts record how each is known (instruction, preference, stated fact, or inferred by the app), when it was first said and last confirmed. A new value replaces the old one and keeps it as history ("remember also:" keeps both); "remember for 3 days that ..." expires; "forget ..." also removes earlier values, related preferences and the copies in local snapshots.
- "Your data" in the Memory tab, and `python tools/data_tool.py`: export, passphrase-encrypted backup, verified restore with undo, daily local snapshots, repair of a damaged file from a snapshot, and permanent selective wipe. `docs/DATA_STORES.md` lists everything the app saves.
- `COGNITIVE_NEXUS_HOME` keeps all saved data outside the project folder.
- The summary of older chat turns covers the whole conversation and keeps decisions, numbers and file names rather than the last 18 messages.
- Diagnostics shows how the last prompt was fitted to the model's context window.
- Claim checks show their working: why each passage was counted, when the page was retrieved and published, which sources did not address the claim, and which were repeats of a site or passage already counted. When supporting and contradicting pages have different dates, the report says which is newer.
- The model re-reads each passage the rules count as supporting a claim, and the passage counts only if both agree (a setting; a few seconds per passage). Measured on unseen passages: false support 5 of 30 without it, 3 of 30 with it.
- Research answers flag links that were not among the retrieved pages, in addition to version numbers and years that are not in the sources.
- Fetching pages: one retry for a dropped connection or a busy server, a pause between requests to the same site, the same page under two addresses fetched once, and copies of one article on several sites marked as one source.
- Measured results in `docs/benchmarks`, each with the tool that produced it: hidden instructions in pages, the claim check on four labelled sets (two of them never used to adjust it), and research answers on frozen pages. Saved results carry a fingerprint of the prompt they were measured with, and a test fails when the app's prompt changes without a new measurement.
- **Agent tab.** Give the coding agent a repository and a failing test, start it or hand it to the background worker, see what waits for you (requests for approval, changes to accept or send back, with the diff), every action it took with inputs and checked results, background jobs, and every tool with what it can affect.
- The coding agent sets up what a repository needs: a virtual environment per task inside the sandbox, with the packages named in the repository's own requirement files, from a download cache. By default only ready-made packages are installed (no build scripts run), a requirement file the task itself changed is not trusted, and `pip install` typed as a command is still refused. Settings, Behaviour has the choice (declared files only, anything, nothing).
- The coding agent was measured on a second set of seeded bugs that nothing had been tuned on: 4 of 9 fixed with the local 8B model, against 7 of 9 on the first set. The lower figure is the one the app now quotes. No failure was reported as a success in either run.
- Foundations for an agent that acts (`agent/`): a registry in which every tool has a schema and a declared effect; approvals by effect, with anything that reaches outside the machine always needing one; a history of every action with its inputs, approval and checked result; tasks with owner, status, dependencies and acceptance tests; a sandbox for running programs with a clean environment, memory, process and time limits and, on Windows, writes refused outside the task folder; a private Git worktree and branch per task; and tools to read, search, edit with undo, run tests and commit.

### Known limitations
See `docs/STATUS.md`.

## 2.0.0

The state of the `main` branch on 2026-07-02, before the changes above.
