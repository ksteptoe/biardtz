# biardtz

[![CI](https://github.com/ksteptoe/biardtz/actions/workflows/ci.yml/badge.svg)](https://github.com/ksteptoe/biardtz/actions/workflows/ci.yml)
[![PyPI-Server](https://img.shields.io/pypi/v/biardtz.svg)](https://pypi.org/project/biardtz/)
[![Project generated with PyScaffold](https://img.shields.io/badge/-PyScaffold-005CA0?logo=pyscaffold)](https://pyscaffold.org/)

> Real-time bird identification on Raspberry Pi using BirdNET.

A passive, always-on bird identification station that listens via a ReSpeaker USB 4-Mic Array, identifies species in real time using Cornell Lab's BirdNET acoustic AI model, and logs every detection to a SQLite database. Designed for Raspberry Pi 5 deployment.

**Key features:**

- Real-time bird ID using BirdNET with configurable confidence thresholds
- Audio clip playback --- saves the best sample per species and plays it from the dashboard
- Web dashboard with detection filtering, search, species leaderboard, and date range selection
- Chart.js visualisations: detection timeline, daily trend, species frequency, and activity heatmap --- all filterable by bird search with case-insensitive glob pattern support (Enter-to-search for wildcards, 300ms debounce for plain text)
- Chart drill-down: click any chart element (timeline point, species bar, trend bar, heatmap cell) to see matching detections in a detail panel
- Enhanced chart tooltips showing per-species breakdown on hover with "Click for details" hints
- Species leaderboard and summary stats filter dynamically when a bird search is active
- Two-level drill-down: click a stat banner for a bar chart, click a bar to see individual detection cards
- Health panel drawer: click the header dot for live system health (CPU, memory, disk, network, service status)
- Mobile-first responsive layout with tab navigation (Live/Charts/Species) and two-column desktop view
- Server-side chart caching and loading skeletons for fast page loads
- Rich terminal dashboard for headless monitoring
- Systemd service with health monitoring and auto-restart
- Direction-of-arrival estimation via ReSpeaker 4-mic array

See the full [Build Log](docs/build_log.md) for hardware details, architecture, and setup instructions.

## Quick Start

```bash
# Create a virtual environment and install with dev dependencies
python -m venv .venv
.venv/Scripts/pip install -e ".[dev]"   # Windows
# .venv/bin/pip install -e ".[dev]"     # Linux/Mac

biardtz --help
```

Key CLI options:

```
--location, -l TEXT  Town/city for species filtering (default: London)
--threshold FLOAT    Minimum confidence 0.0-1.0 (default: 0.25)
--device INT         Audio device index (None = system default)
--array-bearing FLOAT  Compass bearing the mic array faces (default: 0.0)
--dashboard/--no-dashboard  Enable Rich live dashboard (default: on)
--web/--no-web       Enable web dashboard (default: on)
-v / -vv             Verbosity (info / debug)
```

Subcommands:

```
biardtz status     # Pipeline health from heartbeat file
biardtz diagnose   # Full diagnostic: process, systemd, audio, errors
```

## Development

```bash
git clone https://github.com/ksteptoe/biardtz.git
cd biardtz
make bootstrap  # Create .venv and install .[dev]
make test       # Run unit + integration tests (cached via stamps)
make test-all   # Run all tests without caching
make lint       # Run Ruff linter and format check
make format     # Auto-fix lint issues and format code
make docs       # Build Sphinx/MyST docs to docs/_build/html
```

### Installation Verification (Pi hardware)

On the Raspberry Pi with the ReSpeaker mic attached, verify each layer of the stack progressively:

```bash
make verify-env    # Python, venv, package imports
make verify-hw     # ALSA and sounddevice mic detection
make verify-audio  # 3-second audio capture test
make verify-model  # BirdNET model load
make verify-e2e    # Full 10-second pipeline run
make verify        # All of the above in sequence
```

See the [Deployment Guide](docs/deployment_guide.md#step-9-verify-the-installation) for details on each stage.

### Releasing

Versions are derived from git tags via setuptools-scm. After every fix:

```bash
make release KIND=patch   # runs tests, shows changelog, tags and pushes
```

### Continuous Integration

GitHub Actions runs on every push and PR to `main`:

- **Lint job:** Ruff check on Python 3.12
- **Test job:** Unit and integration tests on Python 3.12 and 3.13
- CI installs `libportaudio2` for the `sounddevice` dependency

## Repository Layout

```
src/biardtz/
    __init__.py         Package version and metadata
    __main__.py         python -m biardtz entry point
    cli.py              Click CLI — parses options, builds Config, launches run()
    config.py           Dataclass with all tunable parameters (location, threshold, paths)
    audio_capture.py    sounddevice stream -> asyncio.Queue producer
    detector.py         BirdNET TFLite wrapper — inference on 3-second audio chunks
    logger.py           aiosqlite detection logger with schema auto-creation
    dashboard.py        Rich live terminal dashboard showing recent detections
    main.py             Async orchestrator — wires audio, detector, logger, dashboard
    api.py              Public Python API (Config, Detection, Detector, DetectionLogger)
    health.py           Pipeline health monitor and heartbeat writer
    geocode.py          Location name to lat/lon/timezone resolution
    doa.py              Direction-of-arrival estimation for mic array
    web/                FastAPI web dashboard (routes, DB queries, image cache, health checks)
    templates/          Jinja2 HTML templates for the web UI (including health panel drawer)
    static/             CSS, JS, and static assets
docs/
    build_log.md        Comprehensive build log — hardware, architecture, setup guide
    conf.py             Sphinx configuration
    index.md            Documentation landing page
tests/
    unit/               Fast unit tests (mocked dependencies)
    integration/        Filesystem and cross-module tests
.github/
    workflows/ci.yml    GitHub Actions CI (lint + test matrix)
```

## For Claude -- Agent Orientation

**What this project is:** A PyScaffold-based Python package (`biardtz`) that runs a real-time bird detection pipeline on Raspberry Pi 5 hardware using BirdNET-Analyzer.

**Current state:** Core modules are implemented — config, audio capture, BirdNET detector, async SQLite logger, Rich dashboard, Click CLI, and async orchestrator. The package installs and exposes the `biardtz` CLI entry point.

**What needs doing next:**
- ~~Testing on Raspberry Pi 5 hardware with the ReSpeaker mic array~~ Done (tested on Pi 4B — ReSpeaker fixed at 6ch/16kHz/S16_LE)
- systemd service file for auto-start on boot
- Tuning confidence thresholds against local species
- Phase 2: bat detection with BatDetect2

**Key conventions:**
- Async throughout (`asyncio`), audio captured in a callback thread
- All config via a single `Config` dataclass, overridable from CLI
- Database on external SSD at `/mnt/ssd/detections.db`
- Sphinx docs with MyST (Markdown)

## Note

This project has been set up using [PyScaffold](https://pyscaffold.org/) 4.6
with the [ClickStart](https://github.com/ksteptoe/pyscaffoldext-ClickStart) extension.
