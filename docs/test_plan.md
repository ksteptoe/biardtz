# Test Plan

This document describes the testing strategy for biardtz, covering the mocked test suite and the live/system tests that exercise real hardware on the Raspberry Pi.

## Test Suite Overview

| Directory | Tests | Scope | Hardware needed |
|---|---|---|---|
| `tests/unit/` | 60 | Individual module behaviour (Config, Detector, Logger, Dashboard, CLI, etc.) | No |
| `tests/integration/` | 8 | Cross-module pipeline with real SQLite, mocked audio/inference | No |
| `tests/system/` | 8 | Real hardware: mic, BirdNET model, full pipeline | Yes |

### Running tests

```bash
make test          # Cached unit + integration (skips if unchanged)
make test-all      # All non-live tests, with coverage
make test-live     # Live/system tests only (requires Pi hardware)

# Or directly:
.venv/bin/pytest tests/system/ -v -m live --timeout=180
```

## System Tests

System tests exercise real hardware and the real BirdNET model on the Pi. They are marked `@pytest.mark.live` and skipped automatically when hardware is absent.

### Prerequisites

- Raspberry Pi 5 with a **ReSpeaker 4-Mic Array** (USB, ALSA card 2)
- **BirdNET-Analyzer** pip-installed (`pip install birdnet_analyzer`) with model checkpoints downloaded
- `libportaudio2` system package
- **flatbuffers >= 25.9.23** (see [Known Issues](#known-issues) below)

### BirdNET model setup

BirdNET-Analyzer ships without model weights. After pip install, download them:

```python
from birdnet_analyzer.utils import ensure_model_exists
ensure_model_exists()
```

If using a sibling clone of BirdNET-Analyzer (at `../BirdNET-Analyzer/`), the checkpoints directory must also be present there. Symlink from the pip-installed location if needed:

```bash
ln -s .venv/lib/python3.12/site-packages/birdnet_analyzer/checkpoints \
      ../BirdNET-Analyzer/birdnet_analyzer/checkpoints
```

### Test files

#### `tests/conftest.py` — shared fixtures

Root-level conftest providing:

- **`live_config`** fixture — real `Config` pointing at the ReSpeaker device and BirdNET path, with `tmp_path` DB
- **Hardware auto-detection** via `sounddevice.query_devices()` — skips live tests when no capture device found
- **`pytest_collection_modifyitems` hook** — auto-skips tests based on which hardware they need (audio, BirdNET, or both)

#### `tests/system/conftest.py` — session-scoped fixtures

- **`real_detector`** — real `Detector` instance, session-scoped (TFLite model load takes ~2 s). Skips gracefully on `ImportError` or `OSError`.
- **`real_logger`** — real `DetectionLogger` with per-test `tmp_path` database

#### `tests/system/test_audio_smoke.py` (2 tests)

- Records 3 s from the ReSpeaker via `sd.rec()` — asserts numpy shape and non-silence (RMS > threshold)
- Opens an `InputStream` with callback — asserts callback fires and delivers multi-channel data

#### `tests/system/test_detector_real.py` (3 tests)

- Feeds synthetic noise to real BirdNET model — asserts `list[Detection]` with valid structure
- Feeds silence — asserts valid return (no crash)
- Verifies 16 kHz→48 kHz resampling path doesn't error

**No species-specific assertions** — ambient sound is unpredictable.

#### `tests/system/test_pipeline_live.py` (1 test)

End-to-end: real audio → real inference → real SQLite. Records 2 chunks (~6 s) and asserts:

- Database file created
- `session_summary()` returns a valid statistics string with Session/Detections/Unique species

#### `tests/system/test_cli_smoke.py` (2 tests)

- `biardtz --help` exits with code 0
- `biardtz --version` exits with code 0

### Key design patterns

- **`@pytest.mark.live`** separates hardware tests from the mocked suite
- **Session-scoped model loading** avoids repeated ~2 s TFLite loads
- **Generous timeouts** (`--timeout=180`) accommodate Pi I/O and inference latency
- **Structural assertions only** — validate types, shapes, and schemas, never specific species
- **Graceful skip** when hardware or model is absent, so CI stays green

## Known Issues

### flatbuffers version conflict

BirdNET-Analyzer depends on TensorFlow, which requires `flatbuffers >= 25.9.23`. However, pip may resolve to the ancient date-based version `20181003210633` (from 2018) because its version number is numerically larger than `25.x.y`.

This version uses the `imp` module, which was removed in Python 3.12, causing:

```
ModuleNotFoundError: No module named 'imp'
```

**Fix:** Force-install a modern version:

```bash
pip install 'flatbuffers==25.12.19'
```

### pyproject.toml marker registration

The `live` marker is registered in `pyproject.toml`:

```toml
markers = [
  "integration: filesystem/external-tool tests",
  "live: system tests requiring Pi hardware"
]
```
