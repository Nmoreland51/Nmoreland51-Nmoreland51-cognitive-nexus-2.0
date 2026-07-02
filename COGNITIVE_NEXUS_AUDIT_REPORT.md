# Cognitive Nexus Repository Audit Report

Audit date: 2026-05-31  
Project path: `C:\Users\Nmore\Downloads\Nmoreland51-cognitive-nexus-main\Nmoreland51-cognitive-nexus-main`  
Live app checked: `http://localhost:8501`

## 1. Executive Summary

| Area | Status | Blunt result |
|---|---|---|
| App boot | Working | The live Streamlit app on port `8501` responds `200 ok`; Streamlit AppTest reports `exceptions 0`. |
| Chat UI | Working | `app.py` has a real chat tab, `st.chat_input`, message rendering, history persistence, and streaming through `NexusCore`. |
| Chat model response | Working | Core health live probe returned `Cognitive Nexus works.` through Ollama model `llama3.2:3b`. |
| Provider routing | Partially working | `ProviderRouter` supports Ollama, OpenAI, Anthropic, Hugging Face local, and fallback. Ollama works; cloud providers are offline because API keys are not set. |
| Ollama detection | Working | Implemented in `modules/providers.py` and `modules/provider_router.py`; detects `http://localhost:11434` and installed models. |
| Memory | Partially working | JSON profile memory, chat history, local facts, and knowledge chunk retrieval exist. Project-level memory is still loose and not unified. |
| Web research | Partially working | DDGS/DuckDuckGo search, scraping, summaries, report saving, and memory ingestion exist. Tests pass, but external search quality depends on network and package state. |
| Reality-First Research | Partially working | Real module exists with search, source trust scoring, claim extraction, contradiction heuristics, verdicts, and report saving. It is heuristic, not a true verifier. |
| Diagnostics | Working | Diagnostics tab and `modules/core_health.py` expose provider, import, storage, retrieval, image, memory, and last-turn health. |
| File/project awareness | Partial | Project inventory and file/URL ingestion exist. No full project-aware assistant dispatcher yet. |
| Image generation | Partial | Automatic1111 and local Diffusers paths are implemented; ComfyUI is detected but direct generation is workflow-only. |
| Repo stability | Partially working | Active app is stable. Repository state is very dirty: 77 unstaged tracked changes and 289 untracked files. Several active required modules are untracked. |

Bottom line: this is now a working local Streamlit prototype with a real Ollama path and serious diagnostics, but it is not yet a clean repository. The biggest risk is not the live app; it is the dirty/untracked architecture state.

## 2. Git / Repository State

Command:

```powershell
git branch --show-current
git log --oneline -n 15
```

Output summary:

```text
main
b5db870 Integrate Cognitive Nexus control center features
381a53f Update runtime log snapshot
5bab8e5 Add Cognitive Nexus full project snapshot
5e132b7 Initial commit
```

Command:

```powershell
git status --porcelain=v1 -uall
```

Output summary:

```text
unstaged tracked changes: 77
untracked files: 289
staged files: 0
total dirty entries: 366
```

Command:

```powershell
git diff --stat
```

Relevant output:

```text
65 tracked files changed, 50927 insertions(+), 8008 deletions(-)
```

Important tracked modified files:

- `.env.example`
- `README.md`
- `app.py`
- `cognitive_nexus_ai.py`
- `config/nexus_config.json`
- `data/chat_history.json`
- `data/user_profile.json`
- `logs/uncertainty.jsonl`
- `modules/chat_profile.py`
- `modules/context_manager.py`
- `modules/image_gen.py`
- `modules/nexus_config.py`
- `modules/nexus_core.py`
- `modules/project_status.py`
- `modules/provider_router.py`
- `modules/providers.py`
- `modules/research.py`
- `nexus_router.py`
- `run.py`
- `streamlit_app.err.log`
- `streamlit_app.out.log`
- `streamlit_app.pid`
- `test_web_research_simple.py`
- `tests/test_context_manager.py`
- `tests/test_image_generation_module.py`
- `tests/test_nexus_core.py`
- `tests/test_provider_router.py`
- `verify_setup.py`
- `web_research_module.py`

Important deleted tracked files:

- `ENHANCED_IMAGE_GENERATION_INTEGRATION - Copy.md`
- `OPENCHAT_INTEGRATION_GUIDE - Copy.md`
- `TEMP_THINKING_INTEGRATION_GUIDE - Copy.md`
- `UI_STRUCTURE_DOCUMENTATION - Copy.md`
- `cognitive_nexus_ai - Copy.py`
- `cognitive_nexus_ai_corrupted_backup.py`
- `cognitive_nexus_ai_updated - Copy.py`
- `cognitive_nexus_temp_thinking - Copy.py`
- `experimental_test.py`
- `requirements - Copy.txt`
- `requirements_openchat - Copy.txt`
- `simple_test.py`
- `streamlit_stderr.log`
- `streamlit_stdout.log`
- `test_web_research_module.py`

Important untracked files/directories:

- `core/`
- `modules/core_health.py`
- `modules/reality_research_agent.py`
- `tests/test_core_health.py`
- `tests/test_reality_research_agent.py`
- `tests/test_reality_first_reasoning.py`
- `tests/test_reality_grounding.py`
- `tests/test_prompt_firewall.py`
- `tests/test_research_notes.py`
- `tests/test_web_research_module.py`
- `AGENTS.md`
- `progress/`
- `audit/`
- `data/research_reports/`
- `data/search_cache/`
- `data/search_history/`
- `data/web_research/`
- `data/images/`
- `legacy/`
- `agents/`, `memory/`, `providers/`, `research/`, `routing/`, `simulation/`, `theories/`, `visualization/`, `worlds/`

Critical git fact: `core/`, `modules/core_health.py`, and `modules/reality_research_agent.py` are untracked, but the active app imports them. A clean checkout of the latest commit may not run like this working tree.

## 3. File Tree Overview

Important app entry points:

- `app.py`: main Streamlit dashboard.
- `streamlit_app.py`: compatibility entry point, imports `app.main`.
- `run.py`: launcher/helper script.
- `launch*.py`, `launch*.bat`, `start_app.ps1`: older launch helpers.

Important active modules:

- `modules/nexus_core.py`: central backend for chat, memory, research, grounding, provider requests.
- `modules/provider_router.py`: provider fallback and streaming router.
- `modules/providers.py`: Ollama detection, simple Ollama generation helper, provider inventory.
- `modules/nexus_config.py`: runtime config and `.env` loading.
- `modules/context_manager.py`: local memory/profile/context bundle.
- `modules/memory.py`: Streamlit chat history persistence.
- `modules/research.py`: URL/text/note ingestion and lightweight search helpers.
- `modules/web_research.py`: DDGS search, scraping, summaries, saved web research sessions.
- `modules/reality_research_agent.py`: Reality-First research workflow.
- `modules/image_gen.py`: Automatic1111/local Diffusers/image gallery helpers.
- `modules/comfyui_client.py`: ComfyUI workflow client.
- `modules/project_status.py`: project inventory and environment status.
- `modules/core_health.py`: self-check diagnostics.

Important reasoning/search modules:

- `core/__init__.py`
- `core/reasoning/`
- `core/reality_grounding/`
- `search/bloodhound_search.py`
- `search/onion_search.py`

Important data/config:

- `config/nexus_config.json`
- `.env.example`
- `data/user_profile.json`
- `data/chat_history.json`
- `data/research_reports/`
- `data/web_research/`
- `data/search_cache/`
- `data/search_history/`
- `ai_system/knowledge_bank/web_research/`

Tests:

- Active broad suite is under `tests/`.
- Root-level `python -m unittest discover` does not discover most tests; it only found 2 tests.
- Correct suite command is `python -m unittest discover -s tests -p "test_*.py"`.

## 4. Exact Changed Files

| File | Status | What changed | Why it matters | Risk |
|---|---|---|---|---|
| `.env.example` | Modified | Added local embedding/backend configuration examples. | Documents RAG/embedding behavior. | Low. |
| `README.md` | Modified | Added/updated project description and usage/status content. | Public-facing docs changed. | Low/medium if docs overclaim. |
| `app.py` | Modified | Major Streamlit dashboard expansion: wide layout, tabs, advanced sidebar, reality research tab, image/gallery UI, memory/files UI, diagnostics/self-check. | Main UI and app flow live here. | High because large file changed heavily. |
| `cognitive_nexus_ai.py` | Modified | Small legacy app changes. | Legacy entry remains in repo. | Medium; may confuse future agents. |
| `config/nexus_config.json` | Modified | Runtime provider/search/grounding config updated. | Controls live behavior. | Medium; local config drift. |
| `data/chat_history.json` | Modified | Chat/session data changed. | Runtime data. | Low for app, high for repo cleanliness. |
| `data/user_profile.json` | Modified | Local facts/profile memory changed. | Memory state. | Medium privacy/data concern. |
| `logs/uncertainty.jsonl` | Modified | Grounding/uncertainty logs appended. | Diagnostics history. | Low; generated log. |
| `modules/chat_profile.py` | Modified | Persona/profile handling adjusted. | Prompt/persona behavior. | Medium. |
| `modules/context_manager.py` | Modified | Added structured user profile memory, remember/forget commands, profile summary, context loading fixes. | Makes memory real enough for chat. | Medium. |
| `modules/image_gen.py` | Modified | Added style options, provider summaries, gallery metadata handling, image artifact summaries. | Image tab/gallery now has more real status. | Medium; local Diffusers can be heavy. |
| `modules/nexus_config.py` | Modified | Added config defaults/env loading for local providers/search/reality settings. | Central runtime behavior. | Medium. |
| `modules/nexus_core.py` | Modified | Added retrieval metadata, local knowledge fallback, memory command routing, prompt scaffolding suppression, provider metadata capture, research integration. | Central backend; most important changed file. | High. |
| `modules/project_status.py` | Modified | Added counts for reports, notes, memory, images, recent files. | Diagnostics/inventory. | Low/medium. |
| `modules/provider_router.py` | Modified | Added provider metadata, model resolution, HF local detection, fallback attempt logging, stale Ollama model fallback. | Provider reliability. | High. |
| `modules/providers.py` | Modified | Added Ollama model ranking/preferences and improved provider inventory. | Ollama-first stability. | Medium. |
| `modules/research.py` | Modified | Added Markdown note save/list and ingestion helper behavior. | Knowledge/memory storage. | Medium. |
| `nexus_router.py` | Modified | Routing/prompt classification changed, including safer route decisions and prompt templates. | Chat intent routing. | Medium/high. |
| `run.py` | Modified | Launcher/status behavior changed. | Startup helper. | Low/medium. |
| `streamlit_app.err.log` | Modified | Runtime log changed; currently empty. | Generated runtime file. | Low; should not be tracked long term. |
| `streamlit_app.out.log` | Modified | Runtime Streamlit output changed. | Generated runtime file. | Low. |
| `streamlit_app.pid` | Modified | PID updated to current Streamlit process. | Runtime state. | Low; should not be tracked. |
| `test_web_research_simple.py` | Modified | Legacy/simple web research test changed. | Test drift. | Low/medium. |
| `tests/test_context_manager.py` | Modified | Added/updated memory command/profile tests. | Covers memory changes. | Low. |
| `tests/test_image_generation_module.py` | Modified | Added image module/gallery/provider tests. | Covers image behavior. | Low. |
| `tests/test_nexus_core.py` | Modified | Added core chat, memory, local knowledge fallback, prompt-suppression tests. | Covers core stability. | Low. |
| `tests/test_provider_router.py` | Modified | Added provider order, HF local, Ollama model ranking/fallback tests. | Covers provider routing. | Low. |
| `verify_setup.py` | Modified | Setup verification changed. | Install/health helper. | Medium until re-reviewed. |
| `web_research_module.py` | Modified | Added optional sentence-transformers backend fallback, hash embeddings, improved semantic search/retrieval. | Knowledge/RAG layer. | Medium/high. |
| `modules/core_health.py` | Added / Untracked | New self-check module for imports, storage, providers, logs, live model probe. | Diagnostics now prove core health. | High if not committed. |
| `modules/reality_research_agent.py` | Added / Untracked | New Reality-First research pipeline. | Signature feature. | High if not committed. |
| `core/` | Added / Untracked | Reasoning and reality-grounding packages plus compatibility exports. | Active app imports these. | Critical if not committed. |
| `tests/test_core_health.py` | Added / Untracked | Tests for health check behavior. | Prevents fallback-only fake readiness. | Low if committed, high if left untracked. |
| `tests/test_reality_research_agent.py` | Added / Untracked | Tests for research agent. | Validates research pipeline. | Medium. |
| `tests/test_reality_first_reasoning.py` | Added / Untracked | Tests reasoning/grounding behavior. | Reality-first safety. | Medium. |
| `tests/test_reality_grounding.py` | Added / Untracked | Tests hallucination/speculation/grounding. | Reality layer coverage. | Medium. |
| `tests/test_prompt_firewall.py` | Added / Untracked | Tests prompt injection/trust auditing. | Security/grounding. | Medium. |
| `tests/test_research_notes.py` | Added / Untracked | Tests Markdown knowledge notes. | Memory/knowledge. | Low. |
| `tests/test_web_research_module.py` | Added / Untracked | Replacement for deleted top-level web research module test. | RAG/web module coverage. | Medium. |
| `progress/` | Added / Untracked | Progress snapshots. | Useful handoff docs. | Low. |
| `audit/` | Added / Untracked | Prior audit artifacts/screenshots/json/logs. | Useful evidence but bulky. | Medium repo bloat. |
| `data/research_reports/` | Added / Untracked | Saved Reality-First reports. | Feature evidence and memory corpus. | Medium privacy/bloat. |
| `data/web_research/` | Added / Untracked | Saved web research sessions. | Feature evidence. | Medium privacy/bloat. |
| `data/search_cache/`, `data/search_history/` | Added / Untracked | Search cache/history files. | Speeds repeat research. | Medium privacy/bloat. |
| `data/images/` | Added / Untracked | Generated PNGs and metadata. | Gallery evidence. | Medium bloat. |
| Deleted `*- Copy.*`, `experimental_test.py`, `simple_test.py`, old logs | Deleted | Legacy duplicate/corrupt/noisy files removed from tracked tree and appear moved into `legacy/` as untracked copies. | Good cleanup direction. | Medium until commit strategy is decided. |
| `__pycache__/` and `modules/__pycache__/` | Modified/Untracked | Python bytecode changed from imports/tests/compileall. | Generated artifacts. | Should be ignored, not reviewed. |

## 5. Architecture As It Exists Now

Startup flow:

1. `streamlit_app.py` imports `app.main`.
2. `app.py` sets Streamlit config with wide layout and expanded sidebar.
3. `app.main()` restores persisted chat via `modules/memory.py`.
4. `get_nexus_core()` creates cached `NexusCore(PROJECT_ROOT)`.
5. Sidebar loads Ollama status, project inventory, image provider status, chat profile, and core provider status.
6. UI renders tabs:
   - Reality-First Research
   - Chat
   - Image Generation
   - Web Research
   - Files / Knowledge
   - Memory
   - Gallery
   - Tools / Utilities
   - Diagnostics
   - Settings

Chat/message flow:

1. User enters message in `render_chat_tab()` through `st.chat_input`.
2. Message is saved with `modules/memory.add_message`.
3. `get_nexus_core().stream_chat_response(user_message, get_messages(), settings)` streams the reply.
4. `NexusCore` handles direct commands, local memory commands, router classification, optional Reality-First/Bloodhound routes, context retrieval, prompt building, provider request creation, provider streaming, cleanup/audit, and diagnostics metadata.
5. Assistant message is saved to chat history.

Provider routing flow:

1. `modules/provider_router.ProviderRouter` uses configured provider order.
2. It detects provider status via `_detect_ollama`, `_detect_openai`, `_detect_anthropic`, `_detect_huggingface_local`, `_detect_fallback`.
3. Ollama uses `GET /api/tags` and `POST /api/generate`.
4. OpenAI and Anthropic are called via raw `requests`, not SDKs.
5. Hugging Face local loads `transformers.pipeline` lazily only if `HF_LOCAL_MODEL` is configured.
6. Fallback always returns a clear non-model message.

Memory flow:

1. Chat history: `data/chat_history.json`.
2. User profile/facts: `data/user_profile.json`.
3. Memory commands handled in `modules/context_manager.py`.
4. Knowledge chunks stored under `ai_system/knowledge_bank/web_research/`.
5. Markdown notes target `data/knowledge_notes/`; current health check says this folder is missing until a note is saved.
6. Research reports can append to `data/research_reports/memory_index.jsonl` and ingest chunks into the research module.

Research flow:

1. Basic web research tab uses `modules/web_research.run_research_session`.
2. It searches via DDGS/DuckDuckGo, scrapes pages using `requests` and BeautifulSoup, optionally summarizes through AI callback, saves JSON/Markdown, and can ingest pages to memory.
3. Reality-First tab uses `modules/reality_research_agent.run_reality_research`.
4. Reality-First calls Bloodhound search, scores sources, extracts claims, detects contradiction patterns, builds verdicts, saves reports, and optionally writes memory.

Diagnostics/logging flow:

1. `render_diagnostics_tab()` displays provider health, last route, last plan, last provider result, retrieval, memory, image state, research state, logs, raw diagnostics.
2. `modules/core_health.py` performs import checks, provider checks, storage path checks, recent log signal collection, and live model probe.
3. Runtime logs include `streamlit_app.out.log`, `streamlit_app.err.log`, `logs/cognitive_nexus.log`, and `logs/uncertainty.jsonl`.

## 6. Import Chain Audit

Primary import chain from `app.py`:

- `app.py`
  - `modules.chat_profile`
  - `modules.context_manager`
  - `modules.core_health`
  - `modules.image_gen`
  - `modules.memory`
  - `modules.project_status`
  - `modules.providers`
  - `modules.research`
  - `modules.nexus_config`
  - `modules.nexus_core`
  - `modules.reality_research_agent`
  - `modules.response_planner`
  - `nexus_router`
- `modules.nexus_core`
  - `core.reasoning`
  - `core.reality_grounding`
  - `modules.provider_router`
  - `modules.web_research`
  - `search.bloodhound_search`
- `core/__init__.py`
  - imports `core.observation`, `core.model`, `core.cognition`, `core.grounding`, `core.compression`

Active import check command:

```powershell
python -c "import app; import modules.nexus_core; import modules.provider_router; import modules.reality_research_agent; import modules.web_research; import search.bloodhound_search; import core; import core.reasoning; import core.reality_grounding; print('imports ok')"
```

Result:

```text
imports ok
```

Streamlit warnings during bare imports:

```text
WARNING streamlit.runtime.scriptrunner_utils.script_run_context: Thread 'MainThread': missing ScriptRunContext! This warning can be ignored when running in bare mode.
WARNING streamlit.runtime.caching.cache_data_api: No runtime found, using MemoryCacheStorageManager
```

Broken imports:

- No broken imports found in the active app import chain.

Missing modules:

- None in the current working tree.
- Critical caveat: `core/`, `modules/core_health.py`, and `modules/reality_research_agent.py` are untracked. They exist locally but are not committed.

Circular imports:

- None observed from import/runtime checks.

Dead legacy imports:

- Legacy files still exist in `legacy/` and top-level old app files. They are not the active app path.
- `compileall .` enters `legacy/` and fails on a corrupted legacy file.

Names referenced but not defined:

- No active import-time undefined-name errors detected.
- Full static undefined-name analysis was not run.

## 7. Runtime / Test Results

### Compile Check

Command:

```powershell
python -m compileall .
```

Result: Failed because repo-wide compile includes legacy corrupted backup.

Relevant exact error:

```text
Compiling '.\legacy\cognitive_nexus_ai_corrupted_backup.py'...
***   File ".\legacy\cognitive_nexus_ai_corrupted_backup.py", line 410
    for topic in data.get('RelatedTopics', [])[:max_results-1]:
    ^^^
SyntaxError: expected 'except' or 'finally' block
```

Active app compile command:

```powershell
python -m compileall -q app.py streamlit_app.py modules core search nexus_router.py web_research_module.py
```

Result:

```text
exit code 0
```

### Unit Tests

Command requested:

```powershell
python -m unittest discover
```

Result:

```text
..
----------------------------------------------------------------------
Ran 2 tests in 0.000s

OK
```

Important: this does not discover the real test suite under `tests/`.

Actual active suite command:

```powershell
python -m unittest discover -s tests -p "test_*.py"
```

Result:

```text
Ran 122 tests in 5.555s

OK
```

Notable non-fatal test output:

```text
INFO:web_research_module:sentence-transformers embeddings unavailable; falling back to hash vectors: model unavailable
```

### Pytest

Command:

```powershell
python -m pytest --version
```

Result:

```text
C:\Users\Nmore\AppData\Local\Programs\Python\Python312\python.exe: No module named pytest
```

Pytest is listed in `requirements_web_research.txt`, but not installed in the current environment.

### Streamlit Startup

Existing live process checked instead of launching a duplicate:

```text
PID: 19320
Command: python -m streamlit run streamlit_app.py --server.port 8501 --server.address localhost --server.headless true --browser.gatherUsageStats false
URL: http://localhost:8501
```

Health check:

```powershell
Invoke-WebRequest -UseBasicParsing http://localhost:8501/_stcore/health
```

Result:

```text
StatusCode Content
---------- -------
       200 ok
```

Streamlit AppTest:

```text
exceptions 0
```

### Core Health Probe

Command:

```powershell
python -m modules.core_health --probe --model llama3.2:3b
```

Relevant result:

```text
"status": "ok"
"ready_model_providers": ["ollama"]
"provider": "ollama"
"model": "llama3.2:3b"
"text_preview": "Cognitive Nexus works."
```

Detected provider state:

```text
Ollama: ready, 2 models
OpenAI: offline, OPENAI_API_KEY is not set.
Anthropic: offline, ANTHROPIC_API_KEY is not set.
Hugging Face local: offline, HF_LOCAL_MODEL is not configured.
Fallback: ready
```

## 8. Feature Inventory

| Feature | Present? | Working? | Main files | Notes |
|---|---|---|---|---|
| Streamlit app shell | Yes | Yes | `app.py`, `streamlit_app.py` | Live on `8501`; AppTest clean. |
| Chat UI | Yes | Yes | `app.py` | Uses `st.chat_input`, `st.chat_message`. |
| Chat history | Yes | Yes | `modules/memory.py`, `data/chat_history.json` | Persists JSON history. |
| Clear chat button | Yes | Yes | `app.py` | Sidebar clear/reset controls. |
| Provider router | Yes | Partial/Yes | `modules/provider_router.py` | Local Ollama works; cloud untested/offline. |
| Ollama provider | Yes | Yes | `modules/providers.py`, `modules/provider_router.py` | Live probe passed. |
| OpenAI provider | Yes | Present but untested | `modules/provider_router.py` | Requires `OPENAI_API_KEY`; no SDK used. |
| Anthropic provider | Yes | Present but untested | `modules/provider_router.py` | Requires `ANTHROPIC_API_KEY`; no SDK used. |
| Fallback response | Yes | Yes | `modules/providers.py`, `modules/provider_router.py` | Clear fallback text exists. |
| Memory system | Yes | Partial | `modules/context_manager.py`, `modules/memory.py` | Facts/profile/history work; project memory not unified. |
| Knowledge/file ingestion | Yes | Partial | `modules/research.py`, `web_research_module.py`, `app.py` | Text/URL/notes/chunks exist. |
| Web search | Yes | Partial/Yes | `modules/web_research.py`, `modules/research.py` | DDGS test passed; external network-dependent. |
| Web scraping | Yes | Partial/Yes | `modules/web_research.py`, `web_research_module.py` | BeautifulSoup/requests. |
| Reality-First Research Agent | Yes | Partial/Yes | `modules/reality_research_agent.py` | Real pipeline, heuristic verification. |
| Bloodhound search | Yes | Partial/Yes | `search/bloodhound_search.py` | Query expansion/fetch/link-follow/cache/report. |
| Trust scoring | Yes | Partial | `modules/reality_research_agent.py`, `core/reality_grounding/prompt_firewall.py` | Heuristic source/domain trust. |
| Contradiction detection | Yes | Partial | `modules/reality_research_agent.py`, `core/reality_grounding/contradiction_checker.py` | Pattern/claim heuristic, not formal truth engine. |
| Research report saving | Yes | Yes | `modules/reality_research_agent.py`, `modules/web_research.py` | JSON/Markdown to `data/research_reports` and `data/web_research`. |
| Diagnostics panel | Yes | Yes | `app.py`, `modules/core_health.py`, `modules/project_status.py` | Strong current feature. |
| Logs/status panel | Yes | Yes | `app.py`, `modules/project_status.py` | Log tail and raw diagnostics exist. |
| Image generation | Yes | Partial | `modules/image_gen.py`, `modules/comfyui_client.py`, `app.py` | Automatic1111/local Diffusers implemented; ComfyUI workflow-only. |
| Settings/config | Yes | Yes | `app.py`, `modules/nexus_config.py`, `config/nexus_config.json` | Runtime config saved. |
| `.env` loading | Yes | Yes | `modules/nexus_config.py` | Simple `.env` parser. |
| Requirements/dependencies | Yes | Partial | `requirements*.txt` | Split/incomplete; pytest and optional vector deps absent. |
| Tests | Yes | Yes with correct command | `tests/` | 122 pass via explicit tests dir. |

## 9. Provider / Model Audit

Providers configured in:

- `modules/nexus_config.py`
- `config/nexus_config.json`
- Sidebar in `app.py`
- `modules/provider_router.py`

Current provider order:

```json
["ollama", "openai", "anthropic", "huggingface_local", "fallback"]
```

Ollama detection:

- `modules/providers.py::check_ollama_status`
- Calls `GET http://localhost:11434/api/tags`
- Ranks installed models using `rank_ollama_models`
- Current detected models:
  - `llama3.2:3b`
  - `BlackHillsInfoSec/llama-3.1-8b-abliterated:latest`

If Ollama is offline:

- `check_ollama_status` returns `available=False` and message `Ollama is not running. Start it with: ollama serve`.
- `ProviderRouter` records failed attempt and tries the next provider.
- If no real provider works, fallback returns a clear fallback response.

Fake fallback response risk:

- The fallback response is explicit and not pretending to be model output:
  - `Fallback: no working text provider returned an answer...`
- Core health treats fallback-only probe as failure.
- This is good.

Model names:

- Some defaults are hardcoded:
  - Ollama preferences in `modules/providers.py`
  - OpenAI default `gpt-4.1-mini`
  - Anthropic default `claude-sonnet-4-20250514`
  - Local Diffusers model `runwayml/stable-diffusion-v1-5`
- Ollama model can be overridden by `OLLAMA_MODEL` or `OLLAMA_PREFERRED_MODEL`.

API keys:

- `OPENAI_API_KEY` read from environment.
- `ANTHROPIC_API_KEY` read from environment.
- `.env` loading exists through `modules/nexus_config.py`.

Local-first behavior:

- Real, not just planned.
- The app boots and answers with Ollama without API keys.
- Cloud providers are optional and disabled without keys.

## 10. Memory / Knowledge Audit

Storage locations:

- Chat history: `data/chat_history.json`
- User profile/facts: `data/user_profile.json`
- Knowledge chunks: `ai_system/knowledge_bank/web_research/chunks.json`
- Knowledge metadata: `ai_system/knowledge_bank/web_research/metadata.json`
- Knowledge embeddings/hash vectors: `ai_system/knowledge_bank/web_research/embeddings.json`
- Markdown notes: `data/knowledge_notes/` currently missing until created
- Research memory index: `data/research_reports/memory_index.jsonl`

Formats:

- JSON for chat, profile, chunks, embeddings, metadata, reports.
- Markdown for reports and knowledge notes.
- JSONL for research memory index.
- No active SQLite found.
- FAISS is referenced in requirements, but not installed and not active in current runtime.
- Embeddings currently fall back to hash vectors because `sentence_transformers` is unavailable.

Loaded into chat:

- Yes, through `NexusCore._retrieve_context()` when knowledge use is enabled.
- User facts can be included through `build_context_bundle()`.

Searchable:

- Yes, via `web_research_module.WebResearchModule.semantic_search`.
- Search is lexical/hash-vector fallback unless sentence-transformers is installed.

Saved automatically:

- Chat history is saved.
- Memory commands save facts.
- Research can save reports and memory chunks.
- Not every conversation is summarized into long-term memory automatically.

Project-specific memory:

- Present in concept and some file/folder structures, but not unified.
- No clean project memory dispatcher yet.

Verdict:

- Real but partial.

## 11. Research Agent Audit

Web research exists:

- `modules/web_research.py`
- `modules/research.py`
- `web_research_module.py`
- `search/bloodhound_search.py`

DuckDuckGo/DDGS:

- `modules/web_research.py` imports `ddgs.DDGS`, falling back to `duckduckgo_search.DDGS`.
- `modules/research.py` also uses DuckDuckGo Instant Answer API and Wikipedia fallback.

Scraping:

- Uses `requests.Session`.
- Uses BeautifulSoup when available.
- Strips junk selectors and extracts title, headings, paragraphs, lists, code blocks, links, text.

Saving:

- Web sessions save JSON/Markdown under `data/web_research/`.
- Reality-First reports save JSON/Markdown under `data/research_reports/`.
- Bloodhound search can save search history under `data/search_history/`.

Claim extraction:

- Exists in `modules/reality_research_agent.py::extract_claim_records`.
- Heuristic extraction from source snippets/text.

Trust scoring:

- Exists in `score_source_trust`.
- Uses source category/domain/match strength/recency heuristics.

Contradiction detection:

- Exists in `detect_claim_contradictions`.
- Heuristic; not a guaranteed truth engine.

Grounded facts vs speculation:

- Partially exists through:
  - `core/reality_grounding/speculation_classifier.py`
  - `core/reality_grounding/source_grounder.py`
  - `core/reality_grounding/confidence_estimator.py`
  - Reality report verdict/uncertainty fields

Fake/stubbed vs real:

- Real: search, scraping, report saving, source scoring, claims, contradiction heuristics.
- Partial/stub-like: trust and contradiction are heuristic; no independent factual oracle.
- Optional: AI synthesis only happens if a provider callback is available.

## 12. UI Audit

Tabs present:

- Reality-First Research
- Chat
- Image Generation
- Web Research
- Files / Knowledge
- Memory
- Gallery
- Tools / Utilities
- Diagnostics
- Settings

Sidebar controls:

- Ollama status/model selector.
- Memory/knowledge/web toggles.
- Response mode and verbosity.
- Advanced mode.
- Demo mode.
- Provider fallback order.
- ComfyUI URL.
- HF local model field.
- Clear chat, reset session, refresh app.

Chat input:

- Present: `st.chat_input("Message Cognitive Nexus")`.

Status indicators:

- Provider status, image provider status, response status, diagnostics metrics.

Diagnostics:

- Strong and real.
- Shows provider health, local knowledge retrieval, image providers/artifacts, last turn trace, reality/trust, search/reports, memory/local data, raw diagnostics, logs, performance timings.

Missing/confusing:

- UI is large and dense.
- Sidebar advanced settings are powerful but can confuse normal demo users.
- `python -m unittest discover` does not run the main test suite, which can confuse verification.
- There is a second Streamlit process on port `8502`, which can confuse which app is active.

Slow sections:

- Reality-First Research and Bloodhound search can block on network calls.
- Image Diffusers generation can be heavy.
- Hugging Face provider would load model lazily and could be slow.
- Streamlit reruns can re-trigger status checks, though caching is used.

## 13. Dependency Audit

Dependency files:

- `requirements.txt`
- `requirements_web_research.txt`
- `requirements_openchat.txt`
- `requirements_packaging.txt`

Current `requirements.txt`:

```text
streamlit>=1.28.0
requests>=2.31.0
pillow>=10.0.0
beautifulsoup4>=4.12.0
duckduckgo-search>=6.1.0
ddgs>=9.0.0
trafilatura>=1.6.0
```

Installed/import availability checked:

```text
streamlit: True
requests: True
bs4: True
ddgs: True
duckduckgo_search: True
trafilatura: True
PIL: True
sentence_transformers: False
faiss: False
numpy: True
openai: False
anthropic: False
transformers: True
torch: True
diffusers: True
pytest: False
```

Missing dependencies:

- `pytest` is not installed despite being listed in `requirements_web_research.txt`.
- `sentence_transformers` is not installed, so semantic embeddings fall back to hash vectors.
- `faiss` is not installed; FAISS vector search is not active.
- `openai` and `anthropic` SDKs are not installed, but the current cloud provider code uses raw `requests`, so SDKs are not required for current code.

Unused/heavy optional dependencies:

- `torch`, `transformers`, and `diffusers` are installed and heavy.
- They are optional but can create local model/device risk if activated.

Dependency conflicts:

- No formal conflict check was run.
- No `pyproject.toml` found in this audit.

## 14. Performance Risks

Likely slowness sources:

- Ollama local model generation can take seconds/minutes depending on model and prompt.
- Hugging Face local provider lazily loads `transformers.pipeline`; first call can be very slow.
- Local Diffusers image generation loads heavy model weights.
- Web research uses blocking network calls and scraping.
- Bloodhound can expand queries, fetch pages, follow links, and run AI summary.
- Root `compileall .` traverses `dist/`, `build/`, `legacy/`, and many skills, making repo-wide tooling noisy/slow.
- Large tracked/generated JSON files under `ai_system/knowledge_bank/web_research/` can slow diffs and repo operations.
- Streamlit reruns can re-check providers and summaries, though caching mitigates this.

Current mitigations:

- Streamlit `@st.cache_data` and `@st.cache_resource` used.
- DDGS search and scraping have `lru_cache`.
- Provider status TTL exists.
- Core health quick check is cached; live probe is button-triggered.

## 15. Security / Privacy Risks

API keys:

- No hardcoded API keys found in inspected provider/config code.
- Keys are read from environment/`.env`.

Local data privacy:

- `data/user_profile.json`, `data/chat_history.json`, `data/research_reports/`, `data/search_history/`, and `data/web_research/` may contain private user information and should not be committed blindly.

Unsafe eval/exec:

- No active `eval()` or `exec()` found in inspected active code search.

Network calls:

- Web research performs external network requests through DDGS, DuckDuckGo, Wikipedia, and scraped pages.
- Image/provider detection probes local endpoints Automatic1111 and ComfyUI.
- Onion search module exists but is disabled by config unless enabled.

Untrusted scraping:

- Scraped HTML is parsed as text through BeautifulSoup.
- Prompt firewall exists for injected content, but web content is still untrusted and should be sandboxed carefully in prompts.

File writing:

- App writes local JSON/Markdown/images/logs under `data/`, `logs/`, and knowledge folders.
- File names are generally slugified for reports/notes.

Local path leakage:

- Diagnostics expose full local paths in raw reports and logs.
- Fine for local-first app, risky for public demo screenshots/log sharing.

## 16. Current Top Blockers

1. Blocker:
   - File: `core/`, `modules/core_health.py`, `modules/reality_research_agent.py`
   - Symptom: Active app depends on untracked files.
   - Exact error: No current runtime error; git state shows these as `??`.
   - Why it matters: A clean clone or commit without these files will break the app.
   - Recommended fix: Decide what is real, add the required active files to git, and ignore generated artifacts.

2. Blocker:
   - File: `legacy/cognitive_nexus_ai_corrupted_backup.py`
   - Symptom: Repo-wide compile fails.
   - Exact error: `SyntaxError: expected 'except' or 'finally' block` at line 410.
   - Why it matters: `python -m compileall .` fails, making the repo look broken.
   - Recommended fix: Move legacy broken files outside package/tooling scope or exclude them; do not let active checks traverse corrupted backups.

3. Blocker:
   - File: repository root / `.gitignore`
   - Symptom: Runtime/cache/data files are tracked or untracked in huge volume.
   - Exact error: `77` unstaged tracked changes and `289` untracked files.
   - Why it matters: Impossible to review safely; risks committing private data.
   - Recommended fix: Add/confirm ignore rules for `__pycache__/`, logs, PID files, generated reports/images/cache unless intentionally curated.

4. Blocker:
   - File: test configuration
   - Symptom: `python -m unittest discover` only runs 2 tests.
   - Exact error: none; misleading success: `Ran 2 tests`.
   - Why it matters: People may think tests pass while skipping 120 tests.
   - Recommended fix: Add a documented `python -m unittest discover -s tests -p "test_*.py"` command or test runner script.

5. Blocker:
   - File: `requirements.txt`
   - Symptom: Runtime has packages not listed and optional test/vector packages missing.
   - Exact error: `No module named pytest`; `sentence_transformers: False`; `faiss: False`.
   - Why it matters: Setup is not reproducible.
   - Recommended fix: Split `requirements-core.txt`, `requirements-dev.txt`, `requirements-research.txt`, `requirements-image.txt`.

6. Blocker:
   - File: `app.py`
   - Symptom: Main UI file is very large and owns too many tabs/workflows.
   - Exact error: none.
   - Why it matters: Future changes are risky; architecture drift returns easily.
   - Recommended fix: Do not add features here; extract tab renderers later after behavior stabilizes.

7. Blocker:
   - File: `modules/reality_research_agent.py`
   - Symptom: Reality-first verification is heuristic.
   - Exact error: none.
   - Why it matters: It can overstate confidence if presented as a true lie detector.
   - Recommended fix: Label it as heuristic source-grounded research; strengthen citations/contradiction handling before marketing.

8. Blocker:
   - File: `web_research_module.py`
   - Symptom: Embedding backend falls back to hash vectors.
   - Exact output: `sentence-transformers embeddings unavailable; falling back to hash vectors: model unavailable`.
   - Why it matters: RAG quality is limited.
   - Recommended fix: Keep hash fallback, but document optional install for `sentence-transformers` and add robust model-load diagnostics.

9. Blocker:
   - File: `data/`, `logs/`
   - Symptom: Private/generated runtime state mixed into repo state.
   - Exact error: many modified/untracked `data/*`, `logs/*`.
   - Why it matters: Privacy and repo hygiene risk.
   - Recommended fix: Keep a tiny curated sample dataset; ignore the rest.

10. Blocker:
   - File: live runtime
   - Symptom: Two Streamlit processes are running (`8501` and `8502`).
   - Exact output: PID `19320` on `8501`, PID `31524` on `8502`.
   - Why it matters: Easy to test the wrong instance.
   - Recommended fix: Standardize one launch command and clean stale alternate server processes before demos.

## 17. Recommended Next Steps

### Phase 1: Make It Boot

- Commit or otherwise preserve active required files: `core/`, `modules/core_health.py`, `modules/reality_research_agent.py`, new tests.
- Exclude or quarantine broken legacy files so repo-wide compile does not fail.
- Add a `.gitignore` pass for bytecode, logs, PID files, generated images, generated reports, search cache/history.

### Phase 2: Make Chat Reliable

- Keep Ollama as the default primary provider.
- Add a small chat smoke-test command that asks Ollama for one short sentence and fails if fallback answers.
- Keep prompt-scaffolding suppression and add more tests if more model echo patterns appear.

### Phase 3: Make Provider Routing Real

- Document provider order and failure behavior in README.
- Add cloud provider smoke tests with mocked HTTP responses, not real API calls.
- Add UI messaging that clearly says which provider answered and why fallback was used.

### Phase 4: Make Memory Real

- Separate chat history, user facts, project memory, research memory, and file knowledge into clear folders/schemas.
- Add import/export/clear controls for each memory type.
- Decide whether `data/knowledge_notes/` should be created at startup or lazily.

### Phase 5: Make Reality-First Research Real

- Treat source trust, claims, contradictions, and verdicts as heuristic unless backed by direct citations.
- Improve citation mapping from each claim to exact source URLs.
- Add tests with mocked conflicting sources and weak-source cases.

### Phase 6: Clean UI / Diagnostics

- Keep Diagnostics prominent.
- Split `app.py` tab renderers into modules only after behavior is stable.
- Create a demo-safe mode that hides local paths and private memory.

## 18. Files ChatGPT Should Look At First

1. `app.py`
   - Main Streamlit UI, tabs, sidebar, chat input, diagnostics, and tab workflows.
2. `modules/nexus_core.py`
   - Central backend for chat, memory, research routing, grounding, provider calls.
3. `modules/provider_router.py`
   - Provider detection/fallback/streaming behavior.
4. `modules/providers.py`
   - Ollama detection, model ranking, fallback response, provider inventory.
5. `modules/core_health.py`
   - New self-check proving imports, storage, providers, and live model probe.
6. `modules/reality_research_agent.py`
   - Reality-First Research Agent implementation.
7. `modules/web_research.py`
   - DDGS search, scraping, web research sessions.
8. `search/bloodhound_search.py`
   - Deep search/query expansion/link-following/reporting.
9. `web_research_module.py`
   - Local knowledge chunks, embeddings/hash fallback, semantic search.
10. `modules/context_manager.py`
   - User memory, profile facts, remember/forget commands, context bundle.
11. `core/__init__.py`
   - Top-level core compatibility exports.
12. `core/reality_grounding/`
   - Hallucination/speculation/source grounding/trust audit modules.
13. `core/reasoning/`
   - Reality modeling, feasibility, epistemic routing, constraints.
14. `requirements.txt`
   - Current minimal runtime dependencies.
15. `config/nexus_config.json`
   - Current provider/search/reality runtime settings.

## 19. Brutally Honest Verdict

- Is this repo currently a working app or a broken prototype?
  - It is a working local prototype in the current dirty working tree. It is not yet a clean, reproducible repo.

- What is real?
  - Streamlit app shell, Ollama local chat path, provider routing, chat history, local facts memory, knowledge chunks, web research, Reality-First heuristic research, Bloodhound search, diagnostics, image provider detection/gallery.

- What is fake/stubbed?
  - The "truth-checking" is heuristic, not a literal lie detector.
  - Project-aware operating-system behavior is not fully built.
  - Cloud provider support is present but untested without API keys.
  - ComfyUI direct image generation is workflow-based, not a simple implemented image provider path.
  - FAISS/vector RAG is not active; hash-vector fallback is active.

- What is the first thing to fix?
  - Repository hygiene: commit/track the active files needed to run, ignore generated/private artifacts, and quarantine broken legacy files.

- What should NOT be touched yet?
  - Do not add more features/tabs.
  - Do not redesign the UI.
  - Do not rewrite the research agent.
  - Do not package a public demo until the dirty git state is cleaned.

- What is the fastest path to a working demo?
  - Preserve current working app, clean the repo, keep Ollama `llama3.2:3b`, show Chat + Reality-First Research + Diagnostics only, and use a small curated knowledge/report sample.

- What is the fastest path to a portfolio-worthy version?
  - Make a clean branch with only the active app, core modules, tests, README, screenshots, setup instructions, and a demo-safe dataset. Then record a short demo showing Ollama chat, memory command, web research report, and Diagnostics self-check.
