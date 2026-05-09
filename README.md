# Cognitive Nexus Local AI

This project runs as a local Streamlit AI dashboard at:

```text
http://localhost:8501
```

The main entry point is:

```text
app.py
```

## Features Exposed in the Browser

- Centralized server-side backend in `modules/nexus_core.py`.
- Chat with streaming output, route-aware prompts, adaptive response planning, long-context packing, and fallback mode.
- Provider detection, model selection, and configurable fallback order.
- Adaptive memory from `cognitive_nexus/adaptation.py`.
- Web search and URL extraction.
- DuckDuckGo web research with optional page scraping, AI summaries, source display, and local JSON/Markdown exports.
- Bloodhound Search Mode from chat commands like `search for ...`, `find every mention of ...`, `bloodhound search ...`, and `deep search ...`.
- File upload ingestion for text, markdown, JSON, and CSV.
- Stored knowledge querying using the existing web research store.
- Image generation with provider detection for Automatic1111, ComfyUI workflows, and optional local Diffusers.
- Generated image gallery with saved PNG outputs and JSON metadata.
- Memory inspection for current session and legacy Cognitive Nexus history.
- Project diagnostics, central provider router status, ComfyUI status, logs, commands, and skill inventory.
- Response verification metadata logged to `logs/uncertainty.jsonl`.
- Response planner diagnostics in the Chat and Logs / Status tabs, including mode, intent, token budget, and context window.

## Central Backend

The Streamlit UI is intentionally thin. Major tabs route through the shared backend:

```text
modules/nexus_core.py
```

Supporting backend pieces:

- `modules/provider_router.py` - Ollama, OpenAI, Anthropic, local Transformers, and fallback routing.
- `modules/context_manager.py` - recent turns, older summaries, persistent facts, memory, and knowledge trimming.
- `modules/response_planner.py` - intent detection, response mode selection, token budgeting, streaming acknowledgement, and learned response-style preferences.
- `search/bloodhound_search.py` - query expansion, multi-source public search, safe page fetching, ranking, dedupe, and search-history saves.
- `modules/internal_prompts.py` - protected internal operating prompts kept separate from chat state.
- `modules/comfyui_client.py` - ComfyUI workflow upload, queueing, polling, downloads, and metadata.
- `modules/response_verifier.py` - lightweight uncertainty and unsupported-claim logging.
- `modules/nexus_config.py` - `.env`, `config/nexus_config.json`, runtime folders, and settings.

## Install

From the project folder:

```powershell
pip install -r requirements.txt
```

The web research feature uses:

- `ddgs` / `duckduckgo-search` for DuckDuckGo-compatible search.
- `requests`, `beautifulsoup4`, and optional `trafilatura` for page scraping and readable text extraction.

Dependency sets:

```powershell
pip install -r requirements/core.txt
pip install -r requirements/full.txt
```

`requirements.txt` remains the recommended one-command install for the full Streamlit app.

## Run

```powershell
streamlit run app.py --server.port 8501
```

Then open:

```text
http://localhost:8501
```

## Ollama

The app checks Ollama at:

```text
http://localhost:11434/api/tags
```

Start Ollama with:

```powershell
ollama serve
```

Install a chat model if needed:

```powershell
ollama pull llama3.2
```

The app sends chat prompts to:

```text
http://localhost:11434/api/generate
```

## Optional Image Generation

The Image Generation tab is local-first and supports:

- Automatic1111 Stable Diffusion WebUI API at `http://127.0.0.1:7860`.
- ComfyUI at `http://127.0.0.1:8188` with uploaded or saved API workflow JSON.
- Optional local Diffusers generation when these heavier packages are installed:

```powershell
pip install torch diffusers pillow transformers accelerate safetensors
```

For Automatic1111, start the WebUI with API support, for example:

```powershell
webui-user.bat --api
```

The tab lets you set prompt, negative prompt, provider, model/checkpoint, width, height, steps, CFG scale, seed, and number of images. If no provider is running, the app shows a clear unavailable message instead of crashing.

For ComfyUI:

1. Start ComfyUI.
2. Export an API-format workflow JSON.
3. Upload it in the Image Generation tab under `ComfyUI Workflows`.
4. Enter prompt text and run the workflow.

Saved ComfyUI workflows and outputs live under:

```text
data/comfyui/workflows
data/comfyui/outputs
data/comfyui/metadata
```

New image outputs are saved under:

```text
data/images/generated
```

Matching metadata is saved under:

```text
data/images/metadata
```

The Gallery tab also reads older project image folders:

```text
ai_system/knowledge_bank/images
generated_images
```

## Knowledge Storage

Web URLs and uploaded text files are stored in:

```text
ai_system/knowledge_bank/web_research
```

The existing `web_research_module.py` handles extraction, chunking, simple embeddings, and retrieval.

Full web research sessions are saved to:

```text
data/web_research
```

Each saved session includes:

- JSON with query, settings, search results, scraped pages, summary, and errors.
- Markdown with summary, sources, and scraped excerpts.

## Bloodhound Search Mode

Bloodhound Search Mode runs from the normal Chat tab. Example commands:

```text
search for streamlit websocket error
find every mention of Cognitive Nexus
bloodhound search exact phrase here
deep search obscure filename.py
```

The sidebar includes Bloodhound controls for depth, max results, link following, and cache usage. Results are ranked into best matches and weak/possible matches, with coverage details and saved files.

If `ENABLE_ONION_SEARCH=true` and a Tor SOCKS proxy is available, Bloodhound also searches onion indexes as a secondary lane. Onion results are included and labeled, but they are not prioritized above stronger public-web matches.

Saved Bloodhound sessions live under:

```text
data/search_history
```

Relevant config/environment options:

```text
ENABLE_BLOODHOUND_SEARCH=true
ENABLE_ONION_SEARCH=false
TOR_SOCKS_PROXY=127.0.0.1:9050
MAX_SEARCH_RESULTS=50
SEARCH_TIMEOUT_SECONDS=20
ENABLE_SEARCH_CACHE=true
SEARCH_CACHE_TTL_HOURS=24
ENABLE_LINK_FOLLOWING=true
```

## Memory Storage

Persistent memory is stored in:

```text
data/user_profile.json
data/memory_candidates.json
data/feedback_log.jsonl
```

Legacy chat history is read from:

```text
ai_system/knowledge_bank/chat_history.json
```

The current dashboard session can be saved to:

```text
data/chat_history.json
```

## Notes

Older demos, packaging scripts, and legacy app files are preserved. The supported Streamlit command for the integrated dashboard is:

```powershell
streamlit run app.py --server.port 8501
```
