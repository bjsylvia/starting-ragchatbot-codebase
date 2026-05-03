# Testing Framework Enhancements

This change set adds API-layer testing infrastructure to the RAG system's backend test suite. No frontend source was modified; the filename follows the slash-command convention.

## Summary

- Added `[tool.pytest.ini_options]` in `pyproject.toml` so `uv run pytest` works from the repo root with sane defaults.
- Added `httpx` to the dev dependency group (required by FastAPI's `TestClient`).
- Extended `backend/tests/conftest.py` with API-layer fixtures: a `StubRAGSystem`, an inline `_build_test_app` that mirrors the real endpoints without the `../frontend` static mount, and an `api_client` TestClient fixture.
- Added `backend/tests/test_api_endpoints.py` covering `POST /api/query`, `GET /api/courses`, `DELETE /api/session/{id}`, and `GET /`.

Total: 59 tests passing (44 prior + 15 new API tests), run time ~0.9 s.

## Files changed

### `pyproject.toml`

Added pytest config and `httpx` dev dependency:

- `testpaths = ["backend/tests"]` — run tests from anywhere without cd'ing.
- `pythonpath = ["backend"]` — lets tests `import rag_system`, `import vector_store`, etc., without path hacks.
- `python_files = ["test_*.py"]`, `python_classes = ["Test*"]`, `python_functions = ["test_*"]` — explicit collection rules.
- `addopts = ["-ra", "--tb=short", "--strict-markers"]` — short tracebacks, summary of non-pass results, and strict marker enforcement so typos in `@pytest.mark.*` fail loudly.
- `filterwarnings` — suppresses a few third-party deprecations and the `resource_tracker` noise `backend/app.py` already silences at runtime.
- `markers = ["api: tests that exercise the FastAPI HTTP layer"]` — registered so `--strict-markers` accepts it.

### `backend/tests/conftest.py`

Appended (existing fixtures unchanged):

- **`StubRAGSystem`** — records `query` / `get_course_analytics` calls, lets tests queue an answer, sources, or exception. Exposes a `session_manager` with a mutable `sessions` dict and a deterministic `create_session()` that returns `test-session-1`, `test-session-2`, etc.
- **`_build_test_app(rag)`** — constructs a FastAPI app inline with the same `POST /api/query`, `DELETE /api/session/{id}`, and `GET /api/courses` endpoints as `backend/app.py`, wired to the stub. Two deliberate differences from production:
  - `GET /` returns `{"status": "ok"}` instead of mounting `../frontend`. The static mount doesn't exist in the test environment (and instantiating it would fail on a missing directory), so an inline route is the cleanest way to still exercise the root path.
  - No startup event — the real one calls `rag_system.add_course_folder("../docs")`, which is not wanted in tests.
- **`stub_rag`** fixture — a fresh `StubRAGSystem` per test.
- **`api_client`** fixture — a `TestClient` wrapping the freshly built app, used as a context manager so startup/shutdown hooks fire.

### `backend/tests/test_api_endpoints.py` (new)

Marked with `pytestmark = pytest.mark.api`. Grouped into classes:

- **`TestQueryEndpoint`** — happy path with explicit `session_id`; auto-allocated `session_id` when omitted; empty query string is still forwarded; empty-sources case; `422` for missing body and wrong types; `RAGSystem.query` exceptions map to `500`; `link: null` serializes correctly.
- **`TestCoursesEndpoint`** — returns analytics payload; empty catalog; exception in `get_course_analytics` maps to `500`.
- **`TestSessionEndpoint`** — existing session deletion returns `204`; deleting an unknown session is idempotent (also `204`).
- **`TestRoot`** — `GET /` is reachable.
- **`TestCORS`** — `access-control-allow-origin: *` appears on an `/api/query` response when an `Origin` header is present.

## Rationale for the inline app

`backend/app.py` does two things at import time that make it unsuitable for direct use in tests:

1. Constructs `RAGSystem(config)` — this eagerly initializes `VectorStore`, which loads the `all-MiniLM-L6-v2` sentence-transformer model and opens a ChromaDB at `./chroma_db`. Both are slow and environment-dependent.
2. Mounts `../frontend` via `StaticFiles`. That directory exists in dev but the mount fails if the cwd is unexpected, and in general we don't want tests coupled to frontend assets.

Rather than monkey-patching around these, the test app is defined inline in `conftest.py` with the same routes, request/response models, and error mapping. This keeps the tests hermetic (no network, no filesystem fixtures, no model downloads) and fast (~0.9 s for the full suite).

## Running

```bash
uv sync                 # picks up httpx
uv run pytest           # 59 tests, ~1 s
uv run pytest -m api    # only the new API layer
```
