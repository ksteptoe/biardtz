# biardtz User Guide

**Real-time bird identification on Raspberry Pi**

*Kevin Steptoe --- April 2026*

---

## What is biardtz?

biardtz is a bird identification system that runs on a Raspberry Pi. It listens through a ReSpeaker USB microphone array, identifies bird species using BirdNET machine learning, logs detections to a database, and displays results on a web dashboard accessible from any device.

### Key features

- **Real-time identification** --- 3-second audio chunks analysed continuously
- **Species filtering** --- uses your location and time of year to improve accuracy
- **Direction of arrival** --- estimates which compass direction the bird is calling from
- **Audio clip playback** --- saves the best audio sample per species and plays it from the web dashboard
- **Web dashboard** --- mobile-friendly, auto-refreshing, with bird photos
- **Remote access** --- view detections from anywhere via Tailscale VPN
- **Auto-start** --- runs as a systemd service, survives reboots and SSH disconnects

---

## Hardware

| Component | Model | Purpose |
|-----------|-------|---------|
| Computer | Raspberry Pi 5 | Runs the pipeline |
| Microphone | ReSpeaker USB 4 Mic Array | 6-channel audio capture at 16 kHz |
| Storage | Samsung T7 SSD (ext4) | SQLite database for detections |
| Power | Official Pi 5 PSU | Reliable power supply |

The ReSpeaker has fixed hardware parameters: 6 channels, 16000 Hz sample rate, S16_LE format. biardtz handles channel extraction automatically.

---

## Software architecture

biardtz is an async Python application with five concurrent tasks:

```
Microphone
    |
    v
Audio Capture (sounddevice -> asyncio.Queue, 3s chunks)
    |
    v
Detection Worker (BirdNET inference + DOA estimation)
    |
    v
Detection Logger (aiosqlite, WAL mode)
    |
    +---> Terminal Dashboard (Rich live display)
    +---> Web Dashboard (Starlette + uvicorn, port 8080)
    +---> Health Monitor (heartbeat file, error tracking)
```

All configuration flows through a single `Config` dataclass. The async design means audio capture never blocks on inference, and the web server runs alongside detection.

### Module reference

| Module | Responsibility |
|--------|---------------|
| `cli.py` | Click CLI entry point, argument parsing |
| `config.py` | Config dataclass --- single source of truth for all parameters |
| `audio_capture.py` | sounddevice InputStream to asyncio.Queue (3-second chunks) |
| `detector.py` | BirdNET TFLite wrapper (direct import with subprocess fallback) |
| `doa.py` | Direction of arrival estimation from multichannel audio |
| `logger.py` | aiosqlite writer, WAL mode, auto-creates schema |
| `dashboard.py` | Rich live terminal display |
| `web.py` | Starlette web application with REST API |
| `main.py` | Async orchestrator wiring all components together |
| `health.py` | Health monitor with heartbeat file and error tracking |
| `geocode.py` | Location name to lat/lon/timezone resolution |

---

## Installation

### Prerequisites

- Raspberry Pi with Debian 13 or Raspberry Pi OS
- Miniforge (conda) with Python 3.12 environment
- BirdNET-Analyzer v2.4.0 installed as a sibling directory

### Install biardtz

```bash
conda activate biardtz
cd ~/biardtz
pip install -e ".[dev]"
```

### Automated setup

The project includes `Makefile.pi` for fully automated installation:

```bash
make -f Makefile.pi setup    # installs everything
make -f Makefile.pi test     # runs tests
make -f Makefile.pi run      # starts biardtz
```

### Verify installation

```bash
make verify     # runs all checks: env, hardware, audio, model, storage, e2e
biardtz --help  # confirm CLI is registered
```

---

## Running biardtz

### Basic usage

```bash
biardtz
```

This starts the full pipeline with default settings: London location, 0.25 confidence threshold, terminal dashboard, and web dashboard on port 8080.

### Custom location

```bash
biardtz --location "Biarritz, France" -v
```

The location is geocoded automatically to get latitude, longitude, and timezone. This filters BirdNET's species list to birds expected in that region at the current time of year.

### All command-line options

| Option | Default | Description |
|--------|---------|-------------|
| `--location, -l` | `London` | Town or city name for species filtering |
| `--threshold` | `0.25` | Minimum confidence score (0.0 to 1.0) |
| `--db-path` | `/mnt/ssd/detections.db` | Path to SQLite database |
| `--device` | system default | Audio input device index |
| `--birdnet-path` | `../BirdNET-Analyzer` | Path to BirdNET-Analyzer directory |
| `--array-bearing` | `0.0` | Compass bearing (degrees) the mic array faces |
| `--dashboard/--no-dashboard` | enabled | Rich terminal dashboard |
| `--web/--no-web` | enabled | Web dashboard |
| `--web-port` | `8080` | Port for the web dashboard |
| `-v` / `-vv` | warnings only | Verbosity: info / debug |
| `--version` | | Print version and exit |

### Stop the pipeline

Press **Ctrl+C**. biardtz performs a clean shutdown: cancels all tasks, writes a session summary to the log, and closes the database.

---

## Web dashboard

The web dashboard starts automatically alongside the detection pipeline.

### Access locally

Open any browser on the same network:

```
http://kspi-002.local:8080
http://192.168.1.124:8080
```

### Access remotely

With Tailscale installed on both the Pi and your device:

```
http://100.74.44.10:8080
```

Works from anywhere --- home, work, or mobile data.

### What you see

- **Summary cards** --- today's detections, today's species, all-time species count
- **Recent detections** --- bird name, confidence bar, compass direction, photo, and play button
- **Audio clip playback** --- click the play button on any detection row to hear the best recorded sample for that species; clicking play on another row stops the current clip
- **Species leaderboard** --- ranked by detection count
- **Auto-refresh** --- detections update every 5 seconds, stats every 30 seconds

Bird photos are fetched from Wikipedia/Wikidata and cached on the SSD.

### Audio clips

biardtz saves the best audio sample per species as a WAV file (16-bit PCM, mono, 16 kHz, ~288 KB per 3-second clip). When a detection has higher confidence than the existing clip for that species, the clip is automatically replaced. Clips are stored in `/mnt/ssd/audio_clips/` (configurable via `audio_clip_dir` in the Config dataclass) and tracked in an `audio_clips` SQLite table. Storage is bounded --- even with hundreds of species, total usage stays under ~100 MB.

### Standalone mode

To browse historical detections without starting audio capture:

```bash
biardtz-web
```

---

## Systemd service

biardtz can run as a background service that starts on boot and survives SSH disconnects.

### Install

```bash
sudo bash systemd/install.sh
```

### Manage

```bash
sudo systemctl start biardtz      # Start
sudo systemctl stop biardtz       # Stop
sudo systemctl restart biardtz    # Restart
sudo systemctl status biardtz     # Check status
sudo systemctl enable biardtz     # Enable auto-start on boot
sudo systemctl disable biardtz    # Disable auto-start
```

### View logs

```bash
journalctl -u biardtz -f          # Follow live logs
journalctl -u biardtz --since today  # Today's logs
```

---

## Monitoring and debugging

biardtz has built-in health monitoring, structured logging, and diagnostic tools. This section covers everything you need to check on the system, investigate problems, and understand what's happening.

### Quick status

```bash
make status
# or: biardtz status
```

Shows: pipeline status (ok/degraded/stopped), PID, uptime, audio stream state, detection count, species count, last detection time, and recent errors.

### Full diagnostics

```bash
make diagnose
# or: biardtz diagnose
```

Runs six checks:

1. **Pipeline** --- is the process alive? Is the heartbeat fresh (< 30s), stale (< 120s), or dead?
2. **Systemd** --- is the service enabled and active?
3. **Tailscale** --- is the VPN daemon running with auto-start?
4. **Audio** --- is the ReSpeaker detected by ALSA?
5. **Recent errors** --- last 5 ERROR lines from the log file
6. **Recommendations** --- restart suggestions, SSH session warnings

### Logs

biardtz writes logs to two places: the systemd journal and a rotating log file.

```bash
make logs              # Follow live journal logs (Ctrl+C to stop)
make tail-logs         # Tail the rotating log file
make logs-errors       # Show the 20 most recent ERROR lines
```

| Log destination | Location | Details |
|----------------|----------|---------|
| Rotating file | `/mnt/ssd/biardtz/logs/biardtz.log` | Always INFO+, 5 MB per file, 5 backups |
| Systemd journal | `journalctl -u biardtz` | Only when running as a service |
| Console | stdout | WARNING by default; `-v` for INFO, `-vv` for DEBUG |

### Heartbeat

The health monitor writes a JSON heartbeat file every 10 seconds:

```bash
make heartbeat         # Pretty-print the heartbeat file
```

**Location:** `/mnt/ssd/biardtz/heartbeat.json`

**Contents:**

```json
{
    "status": "ok",
    "pid": 1234,
    "started": "2026-04-13T08:00:00+00:00",
    "uptime_seconds": 3600,
    "heartbeat": "2026-04-13T09:00:00+00:00",
    "audio_stream": "ok",
    "detections": 42,
    "species": 12,
    "last_detection": "2026-04-13T08:55:00+00:00",
    "recent_errors": []
}
```

The systemd watchdog uses this heartbeat --- if no update arrives within 60 seconds, the service is automatically restarted.

### Web API

When the web dashboard is running, you can also query detections programmatically:

```bash
# Recent detections as JSON
curl http://localhost:8080/api/detections?limit=10

# Bird image by scientific name
curl http://localhost:8080/api/image/Turdus%20merula -o blackbird.jpg

# Audio clip for a species
curl http://localhost:8080/api/audio/Turdus_merula.wav -o blackbird.wav
```

### Common debugging workflows

**Pipeline won't start:**
```bash
make diagnose                    # Check all systems
biardtz --db-path ~/test.db -vv  # Run manually with debug logging
```

**Pipeline keeps crashing:**
```bash
make logs-errors                 # Check recent errors
journalctl -u biardtz --since "1 hour ago"  # Journal history
make heartbeat                   # Check last known state
```

**No detections showing:**
```bash
make status                      # Is the pipeline running?
make heartbeat                   # Check detection count
sqlite3 /mnt/ssd/detections.db "SELECT COUNT(*) FROM detections WHERE timestamp > datetime('now', '-1 hour');"
```

**Audio problems:**
```bash
arecord -l                       # Is the ReSpeaker detected?
arecord -D hw:3,0 -c 6 -r 16000 -f S16_LE -d 3 /tmp/test.wav  # Test capture
python -c "import sounddevice; print(sounddevice.query_devices())"  # Check device index
```

---

## Database

Detections are stored in an SQLite database at `/mnt/ssd/detections.db` (configurable with `--db-path`).

### Query detections

```bash
sqlite3 /mnt/ssd/detections.db "SELECT * FROM detections ORDER BY timestamp DESC LIMIT 10;"
```

### Maintenance

```bash
make db-backup     # Back up to ~/backups/biardtz/ (keeps last 7)
make db-export     # Export all detections to CSV
make db-vacuum     # Reclaim space (stop biardtz first)
```

---

## Development

### Setup

```bash
python -m venv .venv
pip install -e ".[dev]"
```

### Test

```bash
make test          # Cached unit + integration tests
make test-all      # All tests, no cache
make test-live     # Live hardware tests only
make test-full     # Everything including live tests
```

### Lint

```bash
make lint          # Check with Ruff
make format        # Auto-fix with Ruff
```

### Build docs

```bash
make docs          # Build HTML docs to docs/_build/html
make docs-pdf      # Generate PDF guide via pandoc
make cheatsheet    # Print the CLI cheatsheet to terminal
```

### Release

```bash
make release KIND=patch    # Bump patch version, tag, and push
make release KIND=minor    # Bump minor version
make release KIND=major    # Bump major version
```

---

## Generating a PDF from this guide

Install pandoc and a LaTeX distribution, then run:

```bash
pandoc docs/biardtz_guide.md -o biardtz_guide.pdf \
    --pdf-engine=xelatex \
    -V geometry:margin=2.5cm \
    -V fontsize=11pt \
    -V colorlinks=true \
    --toc \
    --toc-depth=2 \
    -V title="biardtz User Guide" \
    -V author="Kevin Steptoe" \
    -V date="April 2026"
```

On the Pi, install the required packages:

```bash
sudo apt install -y pandoc texlive-xetex texlive-fonts-recommended
```

Or use Sphinx's built-in LaTeX builder:

```bash
make docs   # then check docs/_build/html
# Or for LaTeX/PDF directly:
cd docs && make latexpdf
```

---

## Troubleshooting

| Problem | Solution |
|---------|----------|
| Pipeline dead | `sudo systemctl restart biardtz` or run `biardtz -v` manually |
| No heartbeat found | Pipeline never started or crashed --- check `journalctl -u biardtz` |
| No audio device | Run `arecord -l`, then use `--device N` with the correct index |
| BirdNET not found | Ensure `~/BirdNET-Analyzer/` exists or pass `--birdnet-path` |
| Database permission error | Check `mount \| grep ssd` and `ls -la /mnt/ssd/` |
| Web dashboard won't load | Wait 30s for boot; check Pi has power and network |
| Wrong Python version | Run `conda activate biardtz` then `python --version` (need 3.12) |
| High CPU / slow inference | Normal on Pi --- expect 1-3s per chunk. Reduce `num_threads` if overheating |
