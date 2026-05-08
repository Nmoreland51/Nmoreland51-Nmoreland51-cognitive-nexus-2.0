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

- Chat with local Ollama support and fallback mode.
- Provider detection and model selection.
- Adaptive memory from `cognitive_nexus/adaptation.py`.
- Web search and URL extraction.
- DuckDuckGo web research with optional page scraping, AI summaries, source display, and local JSON/Markdown exports.
- File upload ingestion for text, markdown, JSON, and CSV.
- Stored knowledge querying using the existing web research store.
- Image generation with provider detection for Automatic1111 and optional local Diffusers.
- Generated image gallery with saved PNG outputs and JSON metadata.
- Memory inspection for current session and legacy Cognitive Nexus history.
- Project diagnostics, detected providers, logs, commands, and skill inventory.

## Install

From the project folder:

```powershell
pip install -r requirements.txt
```

The web research feature uses:

- `ddgs` / `duckduckgo-search` for DuckDuckGo-compatible search.
- `requests`, `beautifulsoup4`, and optional `trafilatura` for page scraping and readable text extraction.

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
- Optional local Diffusers generation when these heavier packages are installed:

```powershell
pip install torch diffusers pillow transformers accelerate safetensors
```

For Automatic1111, start the WebUI with API support, for example:

```powershell
webui-user.bat --api
```

The tab lets you set prompt, negative prompt, provider, model/checkpoint, width, height, steps, CFG scale, seed, and number of images. If no provider is running, the app shows a clear unavailable message instead of crashing.

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
