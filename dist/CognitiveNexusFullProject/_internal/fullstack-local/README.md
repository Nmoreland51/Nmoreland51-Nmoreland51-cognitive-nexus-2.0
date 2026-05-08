# Local Fullstack Build (HTML + API)

This is a fully local fullstack app inside:
`C:/Users/Nmore/Downloads/Nmoreland51-cognitive-nexus-main/Nmoreland51-cognitive-nexus-main/fullstack-local`

## Run locally

1. `cd C:/Users/Nmore/Downloads/Nmoreland51-cognitive-nexus-main/Nmoreland51-cognitive-nexus-main/fullstack-local`
2. `python -m venv .venv`
3. `.venv\\Scripts\\activate`
4. `pip install -r requirements.txt`
5. `uvicorn backend.app:app --host 127.0.0.1 --port 8000 --reload`
6. Open `http://127.0.0.1:8000`

## What is fixed

- Chat context is persisted in local SQLite (`backend/local_memory.db`).
- Image generation now includes recent chat context in a stable `effective_prompt`.
- Generated assets are stored locally in `generated_images/`.
- Frontend is plain HTML/CSS/JS for easy GitHub deployment.

## GitHub deployment readiness

- Commit the `fullstack-local/` folder.
- Add a repo-level `.gitignore` for `.venv/` and `__pycache__/`.
- Optionally add GitHub Actions for lint/tests.

## Notes

- Chat uses local Ollama endpoint by default (`http://localhost:11434`).
- If Ollama is not running, chat endpoint returns a clear backend error.
- Image endpoint currently uses a local placeholder renderer for guaranteed offline behavior.
