# Changelog

## Version 0.1.0 (unreleased)

- Initial implementation of the core detection pipeline
- `config.py` — centralised Config dataclass with all tunable parameters
- `audio_capture.py` — sounddevice stream feeding an asyncio.Queue
- `detector.py` — BirdNET TFLite wrapper for 3-second chunk inference
- `logger.py` — async SQLite logger with auto-created schema (aiosqlite)
- `dashboard.py` — Rich live terminal dashboard for recent detections
- `main.py` — async orchestrator wiring all pipeline stages
- `cli.py` — Click CLI with options for location, threshold, device, and dashboard
- `api.py` — public Python API exposing Config, Detection, Detector, DetectionLogger
