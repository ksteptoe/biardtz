# Test Plan

This document describes the testing strategy for biardtz, covering the existing mocked test suite and the planned live/system tests that exercise real hardware on the Raspberry Pi.

## Current State

The project has **68 unit and integration tests** achieving **94% code coverage**. All tests are fully mocked — they run without audio hardware or BirdNET models, making them suitable for CI.

| Directory | Scope | Hardware needed |
|---|---|---|
| `tests/unit/` | Individual module behaviour (Config, Detector, Logger, Dashboard, CLI, etc.) | No |
| `tests/integration/` | Cross-module pipeline with real SQLite, mocked audio/inference | No |

### Running existing tests

```bash
make test          # Cached unit + integration (skips if unchanged)
make test-all      # All non-live tests, with coverage
```

## Planned System Tests

System tests exercise real hardware and the real BirdNET model on the Pi. They are marked `@pytest.mark.live` and skipped automatically when hardware is absent.

### Prerequisites

- Raspberry Pi 5 with a **ReSpeaker 4-Mic Array** (USB, ALSA card 2)
- **BirdNET-Analyzer** installed at `../BirdNET-Analyzer/`
- `libportaudio2` system package

### Test files

#### `tests/conftest.py` — shared fixtures

Root-level conftest providing:

- A real `Config` fixture pointing at the ReSpeaker device and BirdNET path
- Hardware detection via `sounddevice.query_devices()` with automatic skip when no capture device is found
- `pytest.importorskip("sounddevice")` guard for headless CI environments
- `tmp_path`-based `db_path` for test isolation

#### `tests/system/conftest.py` — session-scoped fixtures

- **`detector`** — real `Detector` instance, session-scoped (TFLite model load takes ~2 s, should not repeat per test)
- **`logger`** — real `DetectionLogger` with per-test `tmp_path` database

#### `tests/system/test_audio_smoke.py`

Records 3 seconds of audio from the ReSpeaker and asserts:

- Result is a numpy array with the expected shape (channels × samples)
- Audio is non-silent (RMS above a noise-floor threshold)

#### `tests/system/test_detector_real.py`

Feeds a 3-second audio buffer (from the mic or a synthetic chirp) to the real BirdNET model and asserts:

- Returns `list[Detection]`
- Each element has `common_name` (str), `sci_name` (str), and `confidence` in [0, 1]
- **No species-specific assertions** — ambient sound is unpredictable

#### `tests/system/test_pipeline_live.py`

End-to-end test: real audio → real inference → real SQLite. Runs for ~6 seconds (2 chunks) and asserts:

- Database file is created with the correct schema
- `session_summary()` returns a valid statistics string
- Row count ≥ 0 (birds may or may not be present)

#### `tests/system/test_cli_smoke.py`

- `biardtz --help` exits with code 0
- A short live run (~5 s) terminated via SIGINT exits cleanly

### Key design patterns

- **`@pytest.mark.live`** separates hardware tests from the mocked suite
- **Session-scoped model loading** avoids repeated 2 s TFLite loads
- **Generous timeouts** (`--timeout=180`) accommodate Pi I/O and inference latency
- **Structural assertions only** — validate types, shapes, and schemas, never specific species
- **Graceful skip** when hardware is absent, so CI stays green

### Running live tests

```bash
make test-live     # Runs only @live tests with 180 s timeout

# Or directly:
.venv/bin/pytest tests/system/ -v -m live --timeout=180
```

## Configuration change

The `live` marker must be registered in `pyproject.toml`:

```toml
markers = [
  "integration: filesystem/external-tool tests",
  "live: system tests requiring Pi hardware"
]
```
