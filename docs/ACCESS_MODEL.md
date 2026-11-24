# Who can use Cognitive Nexus, and how

Cognitive Nexus has one user: its owner. The desktop app has no accounts, roles or sign-in, so
whoever can reach it has the owner's full control. This page lists every way in, who can reach it,
what it can do and what protects it, so that the access model is settled and checked before anything
with more than one user is considered (audit item 114). `tests/test_access_model.py` checks the
defaults below and fails when a file starts a server that is not listed here.

## The model

- **One owner, on one computer.** The owner's own messages are instructions, never scanned or fenced
  as untrusted (`docs/OWNER_CONTROL.md`).
- **Everything else is outside**: web pages, files and tool output (fenced as material, never obeyed);
  the phone (signed in with a token); other people on the network (no way in by default); other
  programs on this computer (they run as the same Windows user, see *Not protected*).
- **Permissions inside the app are for actions, not for people**: what the coding agent may do on its
  own (`agent_autonomy`, approvals per action), what each linked account may be used for. They are in
  `docs/OWNER_CONTROL_RESTRICTIONS.md`.

## Ways in

| Way in | Reachable from | What it can do | Protected by |
|---|---|---|---|
| The app (`app.py`), started with `python run.py`, the launcher (`cognitive_nexus/launcher.py`) or `streamlit run app.py` | This computer only: `--server.address=localhost` in `run.py` and the launcher (`COGNITIVE_NEXUS_HOST`), and `.streamlit/config.toml` for `streamlit run` | Everything: chat, research, files, saved data including wiping it, pictures, the coding agent, linked accounts | Being on this computer; Streamlit's protection against cross-site requests and other origins (on by default) |
| The phone backend (repository `cognitive-nexus-android`, `backend/server.py`) | The network it is started on | Chat, research, files and pictures through this engine | A bearer token of at least 32 characters, compared in constant time; one token for every device |
| `python -m agent` | Whoever runs it as this computer's user | The coding agent, its tasks and approvals | Being this computer's user; actions that reach outside the machine still need an approval |
| `python tools/data_tool.py` | The same | Export, backup, restore, wipe | The same; wiping needs the confirmation word |
| `fullstack-local/` (an experimental separate app, not the one above) | This computer (its README starts it with `--host 127.0.0.1`); browser pages only from its own address | Chat and pictures through Ollama | No sign-in; other websites cannot call it from the browser (`FULLSTACK_ALLOWED_ORIGINS`) |
| Ollama (not part of this app) | Ollama's own setting, `127.0.0.1:11434` by default | The models | Ollama |

Usage statistics: Streamlit sends them to Streamlit by default; `.streamlit/config.toml` turns that
off. Otherwise the app reaches the network only for what the owner asks for: web search and the pages
it reads, a picture model's first download, a cloud model when one is chosen, packages for a coding task
under its package policy, and GitHub when the agent publishes with an approval.

## Not protected

- **Other programs and people using the same Windows account** can read every saved file: live data
  is not encrypted (item 112; backups can be). Use full-disk encryption on a shared or portable computer.
- **Anything running on this computer** can open `http://localhost:8501` and use the app as the owner.
- **Opening the app to the network** (`address = "0.0.0.0"`) gives everyone who can reach it the owner's
  full control. For the phone use the phone backend with its token, over a private network (item 085).
- **The phone backend's token** is shared by every device and cannot be rotated or withdrawn from the
  app (item 111).

## Before considering more than one user

It would need, at least: a sign-in for the app; a data folder per user (`COGNITIVE_NEXUS_HOME`); a
behaviour text and content decisions per user (whose rule applies to whom); linked accounts per user;
separate agent workspaces; and a record of who did what (the agent's history already records who
approved each action). None of it exists, and nothing is planned: it is the owner's decision what the
product is (item 136).
