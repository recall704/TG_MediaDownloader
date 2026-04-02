---
title: "feat: Add --reload for Development Auto-Restart"
type: feat
status: completed
date: 2026-04-02
---

# feat: Add --reload for Development Auto-Restart

## Overview

Add a `--reload` CLI flag to `tg_downloader.py` that watches Python source files and automatically restarts the bot when changes are detected. This eliminates the manual stop/restart cycle during development.

## Problem Frame

Currently, developers must manually stop and restart the bot after every code change. The `run_dev.sh` script simply runs `docker compose up` with no file-watching capability. This slows down the development feedback loop.

## Requirements Trace

- R1. A `--reload` CLI flag enables auto-restart mode
- R2. When enabled, the bot restarts automatically when any Python source file changes
- R3. Only watches project source files (`modules/`, `tg_downloader.py`), not dependencies or session files
- R4. Does not affect production behavior — reload is off by default
- R5. Works with the existing `uv run python tg_downloader.py` execution model

## Scope Boundaries

- Non-goal: Docker hot-reload support (file volumes already mounted; reload runs the Python process)
- Non-goal: Watching non-Python files (config.json, session files, logs)
- Non-goal: Graceful reload of in-progress downloads (development tool only)

## Context & Research

### Relevant Code and Patterns

- **Entry point:** `tg_downloader.py:804` — `app.run(main())` is the final line that starts the event loop
- **Module structure:** All business logic lives in `modules/` directory
- **Dev runner:** `run_dev.sh` — currently just runs `docker compose up`
- **Dockerfile:** `Dockerfile:83` — CMD is `["uv", "run", "python", "/app/tg_downloader.py"]`
- **Dependencies:** Managed via `pyproject.toml` (uv), Python >=3.12

### External References

- **watchfiles** (https://pypi.org/project/watchfiles/) — Modern Rust-backed file watcher for Python. Uses `watchfiles.run_process()` to run a callable and restart on file changes. Well-maintained, 2.4k stars, production/stable status.

## Key Technical Decisions

- **Use `watchfiles` library**: Chosen over alternatives (aioreloader, watchdog) because it has a clean `run_process()` API that handles the restart loop, is Rust-backed for performance, and is the modern standard in the Python ecosystem (used by uvicorn, pytest-watch, etc.)
- **Watch only `.py` files in project root and `modules/`**: Excludes `.session`, `.log`, `__pycache__/`, `.venv/`, and `config.json` to avoid spurious restarts
- **Guard reload behind `--reload` flag**: Zero impact on production. The flag is parsed via `argparse` before any bot initialization
- **Use `if __name__ == "__main__"` guard with string target**: The `run_process()` call uses `target="tg_downloader:run_bot"` (string import path) so the subprocess calls the function directly without re-executing the `__main__` block. This avoids duplicate handler registration and module-level side effects on restart
- **Add `watchfiles` as optional dev dependency**: Uses `[project.optional-dependencies]` to keep it out of production Docker images
- **Change log handler to append mode**: Prevents log truncation on every reload

## Open Questions

### Resolved During Planning

- **Which library to use?**: `watchfiles` — modern, well-maintained, clean API
- **How to parse CLI args?**: Use Python's built-in `argparse` — already in stdlib, no new dependency
- **What files to watch?**: `tg_downloader.py` and `modules/**/*.py` — all project source code

### Deferred to Implementation

- **Exact watch path resolution**: Whether to use absolute paths or relative to script location (implementation detail)
- **Signal handling during reload**: How cleanly the Pyrogram session survives a restart (will be validated during implementation)

## Implementation Units

- [x] **Unit 1: Add watchfiles as dev-only dependency**

**Goal:** Add `watchfiles` as an optional development dependency to the project

**Requirements:** R4

**Dependencies:** None

**Files:**
- Modify: `pyproject.toml`

**Approach:**
- Add `[project.optional-dependencies]` section with `dev = ["watchfiles>=1.0.0"]` to `pyproject.toml`
- Run `uv sync --group dev` to update the lock file
- Keep watchfiles out of production dependencies to avoid bloating Docker images

**Patterns to follow:**
- Existing dependency format in `pyproject.toml` (e.g., `"pytest>=8.0.0"`)

**Test scenarios:**
- Happy path: `uv sync --group dev` completes without errors and `watchfiles` is importable
- Edge case: `uv sync` (without --group dev) succeeds without installing watchfiles

**Verification:**
- `uv run python -c "import watchfiles; print(watchfiles.__version__)"` succeeds after `uv sync --group dev`

- [ ] **Unit 2: Add --reload CLI argument parsing**

**Goal:** Add `argparse`-based CLI argument parsing to `tg_downloader.py` with a `--reload` flag

**Requirements:** R1, R4

**Dependencies:** None

**Files:**
- Modify: `tg_downloader.py`

**Approach:**
- Add `import argparse` to stdlib imports
- Parse `sys.argv` before `init()` is called (line 291: `app = init()`)
- Define `--reload` as a boolean flag with `default=False`
- Store the parsed flag for use at the entry point

**Patterns to follow:**
- Standard library `argparse` usage
- Place argparse setup before module-level `init()` call

**Test scenarios:**
- Happy path: Running `python tg_downloader.py --reload` parses the flag as `True`
- Happy path: Running `python tg_downloader.py` (no flag) parses the flag as `False`
- Edge case: Running `python tg_downloader.py --help` shows the `--reload` option in help text

**Verification:**
- `python tg_downloader.py --help` displays the `--reload` flag
- The flag value is accessible before `init()` executes

- [ ] **Unit 3: Implement reload wrapper logic with __main__ guard**

**Goal:** Restructure `tg_downloader.py` entry point to support `--reload` via `watchfiles.run_process()` without duplicate handler registration or side effects on restart

**Requirements:** R1, R2, R3, R5

**Dependencies:** Unit 1, Unit 2

**Files:**
- Modify: `tg_downloader.py`

**Approach:**
- **Add `if __name__ == "__main__":` guard** at the bottom of the file to replace the current bare `app.run(main())` call (line 804). This prevents module-level execution when imported as a subprocess by `watchfiles.run_process()`
- **Move `app = init()` inside a `run_bot()` function** so the Pyrogram client is freshly created on each reload. The function should:
  1. Call `init()` to get a fresh client (config reload, plugin re-registration, worker generation all happen here)
  2. Call `app.run(main())` to start the event loop
- **Import `watchfiles` conditionally** inside the `__main__` block when `--reload` is True
- **Use `watchfiles.run_process()`** with:
  - `target="tg_downloader:run_bot"` — import path to the function, not the module itself, so the subprocess calls the function directly without re-executing module-level code
  - `paths` set to project root
  - `watch_filter=watchfiles.filters.PythonFilter()` to only watch `.py` files
  - `recursive=True` to watch `modules/` subdirectories
- **Change logging FileHandler mode** from `"w+"` to `"a"` (append) so logs persist across reloads (line 62). This is a minor but important fix — truncating logs on every reload destroys debugging context
- When `--reload` is False: call `run_bot()` directly inside the `__main__` guard (preserves current behavior)

**Technical design:**
```
# Directional guidance, not implementation specification

# At module level: keep all imports, globals, decorators as-is
# Move the execution entry into a function:

def run_bot():
    global app
    app = init()
    app.run(main())

# At the bottom, inside __main__ guard:

if __name__ == "__main__":
    args = parse_args()  # argparse setup
    if args.reload:
        import watchfiles
        watchfiles.run_process(
            target="tg_downloader:run_bot",
            paths=[project_root],
            watch_filter=watchfiles.filters.PythonFilter(),
            recursive=True,
        )
    else:
        run_bot()
```

**Key detail:** Using `target="tg_downloader:run_bot"` (string import path) with `run_process` means the subprocess imports the module and calls `run_bot()` directly — it does NOT re-execute the `__main__` block. This avoids the decorator re-registration problem because decorators run once at import time in the subprocess, and `run_bot()` creates a fresh client each time.

**Patterns to follow:**
- `watchfiles.run_process()` pattern with string target from official docs
- Standard Python `if __name__ == "__main__"` guard pattern

**Test scenarios:**
- Happy path: With `--reload`, changing a file in `modules/` triggers a restart
- Happy path: With `--reload`, changing `tg_downloader.py` triggers a restart
- Happy path: Bot starts and runs normally without `--reload` (no behavioral change)
- Edge case: With `--reload`, changing `tg_downloader.log` does NOT trigger a restart
- Edge case: With `--reload`, changing `config.json` does NOT trigger a restart
- Edge case: Without `--reload`, file changes have no effect (normal behavior preserved)
- Error path: If `watchfiles` is not installed and `--reload` is passed, show a clear error message
- Integration: After a reload-triggered restart, bot reconnects to Telegram and responds to commands

**Verification:**
- Bot starts normally without `--reload`
- Bot starts and restarts on `.py` file changes with `--reload`
- Non-Python file changes do not trigger restarts
- Logs are not truncated on reload (append mode)

- [ ] **Unit 4: Update development runner script**

**Goal:** Update `run_dev.sh` to run the bot directly with `uv run` and `--reload` for reliable file watching

**Requirements:** R5

**Dependencies:** Unit 1, Unit 2, Unit 3

**Files:**
- Modify: `run_dev.sh`

**Approach:**
- Replace the current `docker compose up` command with `uv run --group dev python tg_downloader.py --reload`
- The script should set required environment variables (or rely on existing `.env` file)
- Keep `docker compose up` available as a separate command or comment for production-like testing
- File watching is unreliable inside Docker containers (volume mount event propagation issues), so direct `uv run` is the correct dev workflow

**Patterns to follow:**
- Existing `uv run` execution pattern from Dockerfile CMD

**Test scenarios:**
- Happy path: `./run_dev.sh` starts the bot with `--reload` enabled
- Happy path: Editing a Python file triggers an automatic restart

**Verification:**
- Running `./run_dev.sh` shows the bot starting with reload enabled
- File changes trigger restarts

## System-Wide Impact

- **Interaction graph:** Only affects the entry point (`tg_downloader.py`). No changes to handlers, plugins, or business logic. The `run_bot()` function re-runs `init()` on each reload, which re-registers plugins and regenerates workers — safe because the subprocess is fully isolated
- **Error propagation:** N/A — reload is a development-only feature
- **State lifecycle risks:** On restart, the Pyrogram session file persists; the bot will reconnect normally. In-progress downloads during a reload-triggered restart will be lost (acceptable for development). Module-level globals (queue, tasks, workers, plugin_registry, plugin_router) are re-initialized on each reload — this is correct behavior since the subprocess is a fresh process
- **API surface parity:** No API changes
- **Unchanged invariants:** All existing bot commands, handlers, and plugin behavior remain identical when `--reload` is not passed

## Risks & Dependencies

| Risk | Mitigation |
|------|------------|
| `watchfiles` may not detect changes reliably in Docker volume mounts | Addressed: `run_dev.sh` now uses direct `uv run` instead of Docker for development |
| Restarting mid-download loses progress | Acceptable for development; document as known behavior |
| Multiple rapid file changes cause restart storms | `watchfiles` has built-in debouncing; no additional handling needed |
| Pyrogram session file corruption on abrupt subprocess termination | Low risk — session files are written atomically. Validate during implementation |
| `watchfiles.PythonFilter` may watch test files | The filter watches all `.py` files by default; test file changes triggering reloads is acceptable for development |

## Documentation / Operational Notes

- Update `run_dev.sh` to use `uv run --group dev python tg_downloader.py --reload` for the dev workflow
- No production deployment changes — `--reload` is off by default
- Dockerfile CMD unchanged (production path)
- Change `logging.FileHandler` mode from `"w+"` to `"a"` to preserve logs across reloads

## Sources & References

- Related code: `tg_downloader.py:804` (entry point), `pyproject.toml` (dependencies), `run_dev.sh` (dev runner)
- External docs: https://watchfiles.helpmanual.io/
