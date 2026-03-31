# Changelog

## Version 0.0.6

- Ruff lint fixes applied across the codebase
- `.claude/` directory partially tracked in git (settings.json committable)
- Release workflow documented: `make release KIND=patch` after every fix

## Version 0.0.5

- GitHub Actions CI workflow added (`.github/workflows/ci.yml`)
- Lint job: Ruff check on Python 3.12
- Test job: unit and integration tests on Python 3.12 and 3.13
- CI installs `libportaudio2` system dependency for sounddevice

## Version 0.0.4

- Unit and integration test suites added (`tests/unit/`, `tests/integration/`)
- Tests mock sounddevice and BirdNET-Analyzer (not required locally)
- pytest markers: `integration`, `live`

## Version 0.0.3

- Makefile with incremental test caching via stamps
- `make release KIND=patch|minor|major` workflow (tests, changelog, git tag, push)
- `make bootstrap`, `make lint`, `make format`, `make docs` targets

## Version 0.0.2

- Ruff linter and formatter configuration in pyproject.toml
- Development dependencies (`.[dev]`) including pytest, ruff, sphinx, coverage

## Version 0.0.1

- Initial implementation of the core detection pipeline
- `config.py` — centralised Config dataclass with all tunable parameters
- `audio_capture.py` — sounddevice stream feeding an asyncio.Queue
- `detector.py` — BirdNET TFLite wrapper for 3-second chunk inference
- `logger.py` — async SQLite logger with auto-created schema (aiosqlite)
- `dashboard.py` — Rich live terminal dashboard for recent detections
- `main.py` — async orchestrator wiring all pipeline stages
- `cli.py` — Click CLI with options for location, threshold, device, and dashboard
- `api.py` — public Python API exposing Config, Detection, Detector, DetectionLogger
