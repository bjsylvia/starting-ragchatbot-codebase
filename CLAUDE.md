# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Course Materials RAG System — a FastAPI backend + static HTML/JS frontend that answers questions about course transcripts using ChromaDB vector search and Anthropic Claude with tool-calling. Python 3.13+, managed with `uv`.

## Commands

**All dependency management MUST go through `uv`.** Never use `pip`, `pip-tools`, `poetry`, or edit `pyproject.toml` / `uv.lock` by hand. Also never invoke `python` or `uvicorn` directly — always prefix with `uv run`. The single source of truth for the environment is `uv.lock`; any `pip install` drifts it and silently breaks reproducibility.

| Task | Use | Don't use |
|------|-----|-----------|
| Install/sync deps | `uv sync` | `pip install -r ...` |
| Add a new dep | `uv add <pkg>` | `pip install <pkg>` |
| Run the server | `./run.sh` or `uv run uvicorn app:app --reload --port 8000` | bare `uvicorn ...` |
| Run a script | `uv run python script.py` | bare `python script.py` |
| Run tests (if added) | `uv run pytest` | bare `pytest` |

Install dependencies:
```bash
uv sync
```

**The dev server is managed by the user, not Claude.** Do not start, stop, or restart it yourself — assume one is already running on port 8000 for verification, and ask before killing it if a restart seems necessary.

Run the server (serves API + static frontend on port 8000):
```bash
./run.sh
# or equivalently:
cd backend && uv run uvicorn app:app --reload --port 8000
```

Requires `ANTHROPIC_API_KEY` in `.env` at the repo root (see `.env.example`). On startup, `app.py` auto-loads any `.pdf`/`.docx`/`.txt` files in `docs/` into ChromaDB at `backend/chroma_db/`. Courses already present (matched by `Course.title`) are skipped — to re-ingest after editing a document, delete `backend/chroma_db/` or call `add_course_folder(..., clear_existing=True)`.

There is no test suite, linter, or build step configured. `main.py` at the repo root is a leftover stub and unrelated to the running app.

## Architecture

### Tool-based RAG (not classic retrieve-then-generate)

The key architectural decision: the LLM decides *whether* to search, not the backend. `RAGSystem.query()` sends the user question to Claude with a `search_course_content` tool exposed; Claude only invokes the tool for course-specific questions and answers from general knowledge otherwise. This is enforced by the system prompt in `ai_generator.py` ("One search per query maximum", "General knowledge questions: Answer using existing knowledge without searching").

Flow (`backend/rag_system.py` → `backend/ai_generator.py`):
1. `AIGenerator.generate_response()` makes the first Claude call with `tool_choice: auto` and the tool definitions from `ToolManager`.
2. If `stop_reason == "tool_use"`, `_handle_tool_execution()` runs each requested tool via `ToolManager.execute_tool()`, appends the `tool_result` blocks, and makes a second Claude call **without tools** to get the final text.
3. Sources collected during tool execution are pulled from `tool_manager.get_last_sources()` after the response and returned alongside the answer. `ToolManager` inspects each registered tool for a `last_sources` attribute — any new source-producing tool must expose that attribute plus a reset path.

### Two-collection ChromaDB layout (`backend/vector_store.py`)

- `course_catalog` — one document per course (the title), with `instructor`, `course_link`, and lessons serialized as `lessons_json`. Used for fuzzy course-name resolution.
- `course_content` — the chunked lesson text, filterable by `course_title` and `lesson_number`.

`VectorStore.search()` is a two-step lookup: when a `course_name` is provided, it first semantic-searches `course_catalog` to resolve it to an exact `course_title`, then queries `course_content` with that exact filter. This lets the LLM pass loose names like "MCP" and still get hits against the canonically-stored title.

### Document format expected by the ingester (`backend/document_processor.py`)

Course files have a fixed three-line header followed by lesson blocks:
```
Course Title: <title>
Course Link: <url>
Course Instructor: <name>

Lesson N: <title>
Lesson Link: <url>
<body...>
Lesson N+1: ...
```
The title line doubles as the course's unique ID in ChromaDB. Chunking is sentence-aware (regex handles abbreviations), sized per `Config.CHUNK_SIZE` with `CHUNK_OVERLAP`. The first chunk of each lesson is prefixed with `Lesson N content:` so retrieved chunks carry lesson context; later chunks in the same lesson get `Course <title> Lesson N content:`.

### Session/history

`SessionManager` is **in-memory only** — sessions disappear on restart. It stores the last `MAX_HISTORY * 2` messages per session and formats them into a plain-text block prepended to the system prompt. The frontend creates a session on load via `/api/query` (empty `session_id` → server allocates one).

### Config

All tunables live in `backend/config.py` as a dataclass instance (`config`). Notable defaults: `ANTHROPIC_MODEL="claude-sonnet-4-20250514"`, `EMBEDDING_MODEL="all-MiniLM-L6-v2"`, `CHUNK_SIZE=800`, `MAX_RESULTS=5`, `MAX_HISTORY=2`, `CHROMA_PATH="./chroma_db"` (resolved relative to the working dir — i.e. `backend/chroma_db/` when launched via `run.sh`).

### Frontend

`frontend/` is plain HTML/CSS/JS mounted at `/` by FastAPI via `StaticFiles`. `DevStaticFiles` wraps it to inject `Cache-Control: no-cache` headers so edits show up without a hard refresh. The two backend endpoints are `POST /api/query` and `GET /api/courses`.
