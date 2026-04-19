# biardtz v1.0.0 Release Notes

**19 April 2026** | Kevin Steptoe

biardtz reaches v1.0.0 -- a fully featured, production-ready bird identification station for Raspberry Pi 5.

## What is biardtz?

A passive, always-on bird identification system that listens via a ReSpeaker USB 4-Mic Array, identifies species in real time using Cornell Lab's BirdNET acoustic AI model, and logs every detection to a SQLite database. It runs 24/7 as a systemd service on a Raspberry Pi 5 with SSD storage.

## Highlights

### Audio clip playback (new in v1.0)
The system now saves a representative audio sample for each detected species. When a higher-confidence detection arrives, the clip is automatically replaced -- so the best example of each bird's call is always available. Play buttons appear on every detection row in the web dashboard, letting you hear what the microphone captured.

### Web dashboard
A full-featured web interface accessible from any device on your network:
- Live detection feed with species images from Wikipedia
- Filtering by species, confidence threshold, date range, and free-text search
- Pagination with infinite scroll
- Charts: detection timeline, daily trend, species frequency bar chart, and activity heatmap
- Species leaderboard sidebar
- Audio playback on every detection card
- Mobile-first responsive design with tab navigation
- Connection status indicator

### Direction of arrival
Using GCC-PHAT cross-correlation across the ReSpeaker's four microphones, biardtz estimates which compass direction each bird call came from, displayed as a compass indicator on each detection card.

### Reliability
- Systemd service with automatic restart on failure
- Health monitoring with 10-second heartbeat file
- Audio stream reconnection with exponential backoff
- `biardtz status` and `biardtz diagnose` CLI commands
- Rotating file logs alongside journald

### Developer experience
- `make start`, `make stop`, `make restart` for service control
- `make status`, `make diagnose`, `make logs` for monitoring
- Progressive verification: `make verify` checks environment, hardware, audio, model, storage, and end-to-end pipeline
- Database maintenance: `make db-backup`, `make db-export`, `make db-vacuum`

## Quality

- **270 tests** across unit, integration, and system test suites
- **90% code coverage**
- Every source module has corresponding tests
- Comprehensive documentation: user guide, deployment guide, cheatsheet, and API reference
- CI via GitHub Actions with lint (Ruff) and test gates

## Architecture

```
Microphone -> audio_capture -> detector (BirdNET) -> logger (SQLite)
                                    |                     |
                              doa (GCC-PHAT)        web dashboard
                                                    (FastAPI/HTMX)
```

All async (asyncio). CPU-bound inference runs in a thread executor. Audio streams reconnect automatically. The web dashboard runs alongside the pipeline on port 8080.

## Full changelog since v0.1.0

### Features
- Audio clip playback -- best sample per species with auto-replacement
- Web dashboard with FastAPI, HTMX, and Tailwind CSS
- Chart.js visualisations (timeline, trend, species frequency, heatmap)
- Detection filtering, search, pagination, and date range selection
- Mobile-first responsive layout with tab navigation
- Server-side chart caching and loading skeletons
- Direction-of-arrival estimation via GCC-PHAT
- Location-based species filtering via geocoding (`--location`)
- Health monitor with heartbeat file and systemd watchdog
- `biardtz status` and `biardtz diagnose` CLI commands
- Systemd service with auto-restart and exponential backoff
- Audio stream reconnection on device errors
- Progressive installation verification (`make verify`)
- Database resilience: integrity checks, backup, export, vacuum
- SSD storage verification
- Wikipedia bird images with async fetch and disk cache
- Rich terminal dashboard for headless monitoring
- Tailscale remote access documentation
- `make start/stop/restart` service control targets
- Version display in `make status` output

### Infrastructure
- GitHub Actions CI with lint and test gates
- 270 tests with 90% coverage
- Comprehensive documentation suite
- PyScaffold build system with setuptools-scm versioning
