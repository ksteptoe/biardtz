# CLAUDE.md — Project Instructions for Claude Code

## Project Overview

**biardtz** — a real-time bird (and future bat) identification system for Raspberry Pi 5, built with PyScaffold. Package lives at `src/biardtz/`.

## Key Facts

- **Build system:** PyScaffold with setuptools-scm (version from git tags)
- **Python:** 3.12+, src layout, editable install via `pip install -e ".[dev]"`
- **CLI entry point:** `biardtz` (defined in pyproject.toml as `biardtz.cli:cli`)
- **Test runner:** pytest, tests in `tests/unit/` and `tests/integration/`
- **Linter:** Ruff (config in pyproject.toml)
- **Docs:** Sphinx with MyST Markdown in `docs/`

## Common Commands

```bash
# Setup
python -m venv .venv
.venv/Scripts/pip.exe install -e ".[dev]"   # Windows
# .venv/bin/pip install -e ".[dev]"         # Linux/Mac

# Test
.venv/Scripts/pytest.exe tests/ -v

# Lint
.venv/Scripts/ruff.exe check .

# Run
biardtz --help
```

## Agent Patterns

When working on this project, use these agent patterns for parallel work:

### Test Agent
For writing or updating tests, spawn a worktree-isolated agent:
```
Agent(
  description="Build/update tests",
  isolation="worktree",
  run_in_background=True,
  prompt="""
    Write tests for [specific modules] in tests/unit/ and tests/integration/.
    - Use pytest, unittest.mock (patch, MagicMock, AsyncMock)
    - Mock sounddevice and BirdNET-Analyzer (not available locally)
    - Use tmp_path fixture for database/file paths
    - Mark integration tests with @pytest.mark.integration
    - Read source files first to understand exact APIs
    [specific instructions...]
  """
)
```

### Documentation Agent
For docs updates, spawn a worktree-isolated agent:
```
Agent(
  description="Update documentation",
  isolation="worktree",
  run_in_background=True,
  prompt="""
    Update documentation files: README.md, docs/build_log.md, CHANGELOG.md, etc.
    - Read every file before editing
    - Keep the PyScaffold src layout accurate in any layout diagrams
    - Author: Kevin Steptoe
    [specific instructions...]
  """
)
```

### CI Fix Agent
When CI fails, spawn a worktree-isolated agent to investigate and fix:
```
Agent(
  description="Fix CI failures",
  isolation="worktree",
  run_in_background=True,
  prompt="""
    CI is failing. Investigate and fix the failures.
    1. Run `gh run list --limit 1` then `gh run view <id> --log-failed` to get failure details
    2. Read the failing files and understand the root cause
    3. Apply minimal fixes — do not refactor unrelated code
    4. Run the same checks locally to verify (e.g. ruff check ., pytest tests/ -v)
    5. If lint failures are auto-fixable, prefer `ruff check --fix .` over manual edits
    [specific CI context...]
  """
)
```

### After Agents Complete
Agents in worktrees can't always run bash (sandbox). After they finish:
1. Copy changed files from `.claude/worktrees/agent-XXXX/` into the main tree
2. Reinstall if pyproject.toml changed: `pip install -e ".[dev]"`
3. Run tests to verify: `pytest tests/ -v`
4. Clean up worktrees if needed

### Running Agents in Parallel
Multiple agents can run simultaneously in separate worktrees. They won't conflict with each other or the main tree. Use `run_in_background=True` and you'll be notified on completion.

## Architecture

```
src/biardtz/
    config.py           Config dataclass — single source of truth for all params
    audio_capture.py    sounddevice InputStream -> asyncio.Queue (3s chunks)
    detector.py         BirdNET TFLite wrapper (direct import + subprocess fallback)
    logger.py           aiosqlite writer, WAL mode, auto-creates schema
    dashboard.py        Rich live terminal display
    main.py             Async orchestrator — wires audio -> detector -> logger -> dashboard
    cli.py              Click CLI entry point
    api.py              Public API re-exports
```

## Workflow Rules

- **After every fix, always release:** Run `make release KIND=patch` after committing and pushing any bug fix or CI fix. Do not skip this step.

## Conventions

- All config via the `Config` dataclass, overridable from CLI flags
- Async throughout (asyncio); CPU-bound inference runs in executor
- Database path defaults to `/mnt/ssd/detections.db` (Pi SSD mount)
- BirdNET-Analyzer expected as sibling directory `../BirdNET-Analyzer/`
- No hardcoded paths/thresholds outside config.py
