# biardtz

[![PyPI-Server](https://img.shields.io/pypi/v/biardtz.svg)](https://pypi.org/project/biardtz/)
[![Project generated with PyScaffold](https://img.shields.io/badge/-PyScaffold-005CA0?logo=pyscaffold)](https://pyscaffold.org/)

> Real-time bird identification on Raspberry Pi using BirdNET.

A passive, always-on bird identification station that listens via an array microphone, identifies species in real time using Cornell Lab's BirdNET acoustic AI model, and logs every detection to a SQLite database. Designed for Raspberry Pi 5 deployment.

See the full [Build Log](docs/build_log.md) for hardware details, architecture, and setup instructions.

## Quick Start

```bash
pip install -e .
biardtz --help
```

Key CLI options:

```
--lat FLOAT       Latitude for species filtering (default: 51.50)
--lon FLOAT       Longitude for species filtering (default: -0.12)
--threshold FLOAT Minimum confidence 0.0-1.0 (default: 0.25)
--device INT      Audio device index (None = system default)
--dashboard/--no-dashboard  Enable Rich live dashboard (default: on)
-v / -vv          Verbosity (info / debug)
```

## Development

```bash
git clone <repository-url>
cd biardtz
make dev      # Install in development mode with all dependencies
make test     # Run tests
make lint     # Run linter
make format   # Format code
make docs     # Build documentation
```

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
docs/
    build_log.md        Comprehensive build log — hardware, architecture, setup guide
    conf.py             Sphinx configuration
    index.md            Documentation landing page
tests/                  (to be added)
```

## For Claude -- Agent Orientation

**What this project is:** A PyScaffold-based Python package (`biardtz`) that runs a real-time bird detection pipeline on Raspberry Pi 5 hardware using BirdNET-Analyzer.

**Current state:** Core modules are implemented — config, audio capture, BirdNET detector, async SQLite logger, Rich dashboard, Click CLI, and async orchestrator. The package installs and exposes the `biardtz` CLI entry point.

**What needs doing next:**
- Testing on Raspberry Pi 5 hardware with the ReSpeaker mic array
- Unit and integration tests
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
