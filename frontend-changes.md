# Frontend / Tooling Change Log

This file collects change notes from feature branches that were merged into
`main`. Each section below was authored on a separate branch; they are kept
verbatim here for reference.

---

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

---

# Frontend Changes — Theme Toggle Button

Adds a light/dark theme toggle button fixed in the top-right corner of the app.

## Requirements coverage

| Requirement | Status | Where |
|-------------|--------|-------|
| Toggle button top-right, icon-based (sun/moon), fits existing aesthetic | ✅ | `index.html` `#themeToggle`; `style.css` `.theme-toggle` |
| Smooth transition animation on toggle | ✅ | `.theme-toggle-icon` opacity+rotate+scale; body/surfaces `transition` |
| Accessible + keyboard-navigable | ✅ | native `<button>`, `role="switch"`, `aria-checked` synced, `aria-label` describes destination state, `:focus-visible` ring, 44×44 target |
| Light-theme CSS variables (bg, text, primary/secondary, border, surface) | ✅ | `:root[data-theme="light"]` block |
| Good contrast / accessibility in light theme | ✅ | `#0f172a` text on `#ffffff` bg = ~17:1; `#475569` secondary on white = ~7.5:1 |
| Toggle between themes on click, smooth transitions | ✅ | `toggleTheme()` + CSS transitions |
| Uses CSS custom properties | ✅ | all colors routed through existing `--*` vars |
| `data-theme` attribute on body or html | ✅ | set on `<html>` (`document.documentElement`), matched by `:root[data-theme="light"]` |
| All existing elements work in both themes | ✅ | every themed element already references the palette vars, including code blocks (new `--code-bg`), source chips, welcome card, sidebar, suggested questions, input, scrollbars |
| Maintains visual hierarchy / design language | ✅ | same primary blue accent, same radii, same typography |

## Behavior

- **Default theme:** dark (matches existing design). On first load, the saved
  preference in `localStorage` wins; otherwise `prefers-color-scheme` is used;
  otherwise dark.
- **Click / Enter / Space** on the button toggles between light and dark.
- Preference is persisted to `localStorage` under the key `theme`.
- Swaps a sun ↔ moon icon with a smooth rotate + fade cross-fade (~0.3–0.4s).
- All themeable surfaces (background, surface, input, messages, sidebar,
  suggested-question cards, code blocks, source chips) transition their
  `background-color` / `color` / `border-color` over 0.3s.
- Respects `prefers-reduced-motion`: transitions disabled for users who opt out.

## Accessibility

- `<button>` element, so Tab-reachable and Enter/Space activates it natively.
- `role="switch"` with `aria-checked` kept in sync with the current theme.
- `aria-label` updates to describe the *destination* state ("Switch to light
  theme" / "Switch to dark theme"), so screen readers announce what will happen.
- Focus ring uses the existing `--focus-ring` variable for visual consistency.
- SVG icons marked `aria-hidden="true"` to avoid double-announcement.
- 44×44 px hit target (meets WCAG minimum target size).

## Files Changed

### `frontend/index.html`

- Added the `#themeToggle` `<button>` at the top of `<body>`, before
  `.container`. Contains two inline SVGs (sun + moon) that cross-fade via CSS.
- Bumped the `?v=` query param on `style.css` and `script.js` from `9` → `10`
  to bust browser cache.

### `frontend/style.css`

- Split CSS custom properties: `:root` keeps the existing dark palette as the
  default; new `:root[data-theme="light"]` block defines a light palette
  (white background, slate text, lighter surfaces, same primary blue accent).
- Added a shared `--code-bg` variable (used by `.message-content code/pre`)
  so inline code legibility is preserved in both themes. The old
  hard-coded `rgba(0,0,0,0.2)` was replaced with `var(--code-bg)`.
- Added `transition: background-color / color / border-color 0.3s ease` to
  `body` and themeable surfaces.
- Added `.theme-toggle` styles:
  - Fixed position top-right (`top: 1rem; right: 1rem`), `z-index: 100`.
  - 44×44 px circular button, uses `--surface` / `--border-color` so it
    adapts to each theme.
  - Hover / active / `:focus-visible` states consistent with other buttons
    in the app (`--primary-color` accent, `--focus-ring` shadow).
- Added `.theme-toggle-sun` / `.theme-toggle-moon` rules for the cross-fade
  animation (opacity + rotate + scale).
- Added a `prefers-reduced-motion` block that disables all theme and toggle
  transitions.

### `frontend/script.js`

- Added `themeToggle` to the DOM-element cache and grabbed it on
  `DOMContentLoaded`.
- Added `initTheme()`, `applyTheme(theme)`, and `toggleTheme()`:
  - `applyTheme` sets/removes `data-theme="light"` on `<html>` and keeps
    `aria-checked`, `aria-label`, and `title` in sync.
  - `initTheme` reads `localStorage`, falls back to
    `prefers-color-scheme: light`, then finally to dark.
  - `toggleTheme` flips the attribute and writes the new value to
    `localStorage`. Both reads/writes are wrapped in try/catch so privacy
    modes that block storage don't break the toggle.
- Wired `themeToggle.addEventListener('click', toggleTheme)` in
  `setupEventListeners`. No separate keydown handler is needed — native
  `<button>` semantics already fire `click` on Enter and Space.

## Verification

- Loaded the worktree's `frontend/` via a local static server and verified
  with Playwright:
  - Button renders top-right (top=16, right=16, 44×44 px), `role=switch`,
    `tabIndex=0`.
  - Click flips `data-theme`, `body` background, icon visibility, and
    `aria-checked`.
  - Tab focuses the button; Enter and Space both toggle the theme.
  - Reload preserves the selected theme via `localStorage`.
  - Screenshots confirm both light and dark states render cleanly.

## Notes for reviewers

- The project's existing dev server serves `frontend/` from the main
  worktree, not this `ui_feature` worktree, so end-to-end verification in
  the main dev server will only show the changes once merged. The logic was
  verified against the same files via a temporary static server.
- No backend changes; no new dependencies; no build step.

---

# Frontend changes: Prettier-based quality tooling

## What this PR does

Adds Prettier to the repo to enforce consistent formatting on the frontend (`frontend/*.html`, `*.css`, `*.js`). Adds two dev scripts — `scripts/format.sh` (writes fixes) and `scripts/quality.sh` (check-only, non-zero exit on drift). Runs one initial reformat pass across the three frontend files so the tree is already conformant.

The original task mentioned `black`; `black` is a Python formatter and this task was scoped to frontend only, so Prettier (the JS/CSS/HTML equivalent) was used instead.

## Scope

**Frontend only.** Backend Python is untouched:

- `pyproject.toml`, `uv.lock`, `backend/**`, `main.py`, `run.sh` — unmodified
- `.prettierignore` blocks Prettier from ever formatting `backend/`, `*.py`, `docs/`, `*.md`, `uv.lock`, `.venv/`, `.trees/`, `.claude/`, `node_modules/`

## Files added

| File | Purpose |
|------|---------|
| `package.json` | `private: true`, one devDep (`prettier ^3.3.3`), `format` / `format:check` npm scripts |
| `package-lock.json` | Pins Prettier exactly (3.8.3) — committed for reproducibility, same reason `uv.lock` is committed for Python |
| `.prettierrc.json` | Prettier config tuned to match existing style: 4-space indent, single quotes in JS, semicolons, no trailing commas, print width 100, LF line endings |
| `.prettierignore` | Excludes everything non-frontend |
| `scripts/format.sh` | Writes Prettier fixes in place. Executable. |
| `scripts/quality.sh` | Check-only; exits non-zero on drift. Suitable for wiring into CI later. Executable. |

## Files modified

| File | Change |
|------|--------|
| `.gitignore` | Adds `node_modules/` |
| `frontend/index.html` | Reformatted (see below) |
| `frontend/script.js` | Reformatted (see below) |
| `frontend/style.css` | Reformatted (see below) |

## What the initial reformat actually changed

This was a bigger diff than planned — 173 insertions / 123 deletions across the three files — because Prettier's defaults for HTML/CSS/JS make more changes than just whitespace-trimming. None of the changes are semantic; the rendered page and the runtime behavior are identical. Summary:

### `frontend/index.html`
- `<!DOCTYPE html>` → `<!doctype html>` (lowercased — Prettier default)
- Children of `<html>` now indented one level (so `<head>` and `<body>` sit inside the `<html>` block)
- Void elements get self-closing slashes: `<meta />`, `<link />`, `<br />`
- Trailing newline added

### `frontend/script.js`
- Single-arg arrow callbacks get parens: `x => ...` → `(x) => ...`
- Long lines split across multiple lines (welcome-message call, `.map(...).join('')` chain, `fetch(..., { method: 'DELETE' })`)
- Redundant blank lines inside blocks collapsed
- Trailing whitespace stripped
- Final newline added
- Trailing comma after last object key removed (matches `trailingComma: "none"` config)

### `frontend/style.css`
- Multiple-selector rules split one-per-line: `*, *::before, *::after` → three lines
- Long `font-family` / `transition` values wrapped with hanging indent
- Single-line rules like `.message-content h1 { font-size: 1.5rem; }` expanded to multi-line form

## How to use

From the repo root:

```bash
# One-time setup
npm install

# Format everything (rewrites files in place)
./scripts/format.sh

# Check everything is formatted — exits non-zero on drift
./scripts/quality.sh
```

Also works via npm:

```bash
npm run format        # equivalent to format.sh
npm run format:check  # equivalent to quality.sh
```

## Verification performed

- `./scripts/format.sh` reformatted three files on first run.
- `./scripts/format.sh` on second run: all three files report `unchanged` — idempotent.
- `./scripts/quality.sh` exits 0.
- `git diff` touches **zero** files under `backend/` — scope is honored.
- Dev server on port 8000 still responds 200 on `/` and `/script.js` after the reformat (the reformat is whitespace/cosmetic and doesn't change anything browsers or the FastAPI `StaticFiles` mount care about).

## Not included (potential follow-ups)

- No ESLint / Stylelint / HTMLHint — this change is formatting, not linting.
- No pre-commit hook — can be added via `husky` + `lint-staged` later.
- No GitHub Actions workflow running `quality.sh` in CI — the script is ready for it when wanted.
- No `black` / Python-side tooling — intentionally out of scope per the frontend-only restriction.
