# BirdWatch Pi — Build Log & Project Documentation

> A real-time bird identification system using a Raspberry Pi 5, array microphone, and Cornell Lab's BirdNET acoustic AI model.

---

## Project Overview

**Goal:** Build a passive, always-on bird identification station that listens to garden/window audio, identifies bird species in real time using machine learning, and logs every detection to a persistent database.

**Author:** Kevin Steptoe
**Start date:** March 2026
**Status:** Hardware deployed — v0.1.0 released — SSD and BirdNET running on Pi

---

## What I Learned Along the Way

This section captures the key decisions, mistakes avoided, and things I didn't know before starting. It is written as a log of the discovery process, not just a list of conclusions.

### On the Raspberry Pi

- The Pi 5 ships as a **bare board only** — no storage, no OS, nothing. It will not boot out of the box.
- You must flash an OS onto a microSD card from another computer first, using **Raspberry Pi Imager** (free, from raspberrypi.com).
- If your computer has no SD card slot (very common on modern laptops), you need a **USB SD card reader** — ~£8–10, any brand works.
- The Pi Imager lets you pre-configure hostname, SSH, WiFi, and username before flashing, so you can skip the first-boot wizard entirely and go straight to SSH.

**Memory decision:** I initially ordered the 16GB model but realised this was significant overkill. BirdNET at runtime uses roughly 400 MB of RAM total. The 8GB model was chosen as a sensible middle ground — enough for the current project, and sufficient headroom when bat detection (BatDetect2) is added in a future phase.

### On Storage

There are two separate storage concerns in this build, which I initially conflated:

**1. The microSD card (boot drive)**

The Pi boots from microSD. The OS and BirdNET model files (~4 GB total) live here. The key insight is that **not all SD cards are equal** for always-on applications. A standard consumer card written to continuously by SQLite will fail within weeks due to NAND wear. The **Samsung PRO Endurance** series uses MLC NAND with firmware tuned for surveillance/dashcam workloads — exactly the same write pattern as continuous detection logging.

I chose 128GB (rather than the sufficient 64GB) for better wear levelling across more NAND cells, and because the price difference was acceptable.

**2. The USB SSD (database drive)**

The SQLite detection database should **not** live on the SD card. Even with an Endurance card, it is better practice to offload continuous writes to a proper SSD. The Samsung T7 1TB is connected via USB and mounted at `/mnt/ssd/`. The `db_path` in `config.py` points here. This makes the SD card essentially read-only after boot, giving it an indefinite lifespan.

> **Note on 2026 pricing:** Both the SD card and SSD are significantly more expensive than historical prices due to the global NAND memory shortage. The T7 1TB was £154.99 at time of purchase — this is the current market rate, not a markup.

### On the Microphone

BirdNET expects 48 kHz mono audio internally, but handles resampling itself. The key requirement is an **array microphone with onboard beamforming** — this dramatically improves detection accuracy compared to a single omnidirectional mic by focusing on the signal direction and suppressing background noise in hardware before the audio even reaches Python.

I originally specified the ReSpeaker 6+1 Mic Array but found it unavailable. The **ReSpeaker USB Mic Array v2.0 (4-mic)** is actually the successor and the better product — it uses the XMOS XVF-3000 chip with improved DSP algorithms. Fewer physical microphones, better audio quality.

Key properties:
- USB Audio Class 1.0 — plug and play on Linux, no drivers needed
- Onboard AEC, beamforming, noise suppression, and Direction of Arrival (DoA)
- Appears as a standard ALSA device — works transparently with `sounddevice`

**Hardware constraints discovered during bring-up (2026-04-01):** The ReSpeaker has fixed parameters — 6 channels, 16000 Hz sample rate, S16_LE format only. These cannot be changed. The `audio_capture.py` module opens all 6 channels and extracts channel 0 for mono input. Config defaults are set accordingly (`sample_rate=16000`, `channels=6`).

### On BirdNET

Cornell Lab's [BirdNET-Analyzer](https://github.com/kahst/BirdNET-Analyzer) is the open-source Python tool we use. Key things to understand:

- It uses a **TensorFlow Lite** model (~1 GB on disk, ~100–150 MB in RAM)
- Install via `pip install /path/to/BirdNET-Analyzer` — this pulls in TensorFlow, librosa, etc.
- The new BirdNET-Analyzer (v2.4+) uses `birdnet_analyzer` as a Python package — the old `analyze.py` top-level script no longer exists. Our `detector.py` imports `birdnet_analyzer.model` and `birdnet_analyzer.config` directly.
- It expects **3-second audio chunks** at **48 kHz mono** — our `detector.py` resamples from the ReSpeaker's 16 kHz to 48 kHz before inference
- Setting your **latitude, longitude, and week number** dramatically improves accuracy — the model uses location and season to weight species priors
- The confidence threshold is tunable — 0.25 is a reasonable starting point; lower catches more species with more false positives, higher is more conservative
- Two firmware options on the ReSpeaker: processed (beamformed) audio on channel 0, or raw per-mic channels 1–4. We use channel 0.

### On Future-Proofing for Bat Detection

Bats echolocate at **20–120 kHz** — completely inaudible to all standard microphones which cut off at ~20 kHz. Adding bat detection in a future phase will require:

- A dedicated **ultrasonic USB microphone** (e.g. Dodotronic Ultramic 384K, ~£200–250)
- Sample rate of **192–384 kHz** (vs 48 kHz for birds)
- **BatDetect2** — a separate open-source Python model, architecturally similar to BirdNET

The good news: the Pi 5 8GB is sufficient for both workloads, and the software architecture is designed so BirdNET and BatDetect2 can run as separate pipelines, scheduled by time of day (birds by day, bats at dusk/night).

---

## Bill of Materials

All prices include UK VAT. Purchased March 2026.

| # | Item | Specification | Supplier | Price |
|---|------|--------------|----------|-------|
| 1 | Raspberry Pi 5 | 8GB RAM | Raspberry Pi / approved reseller | £120.00 |
| 2 | Keyboard & Mouse | Combo, Black/Grey, UK layout | Raspberry Pi | £24.00 |
| 3 | USB-C Power Supply | 27W, UK plug, White | Raspberry Pi | £11.50 |
| 4 | Pi 5 Case | FLIRC passive cooling case | FLIRC | £15.40 |
| 5 | Micro HDMI Cable | 1m | The Pi Hut | £3.80 |
| 6 | Array Microphone | ReSpeaker USB Mic Array v2.0, XMOS XVF-3000 | Seeed Studio | £47.98 |
| 7 | microSD Card | Samsung PRO Endurance 128GB, 100MB/s read, 30MB/s write | Amazon UK | £53.70 |
| 8 | USB SSD | Samsung T7 1TB, USB 3.2 Gen 2, 1050MB/s read | Amazon UK | £154.99 |
| 9 | USB SD Card Reader | Acer, USB-C & USB-A dual interface | Amazon UK | ~£10.00 |
| | **Total** | | | **~£441** |

### Items Considered But Not Purchased

| Item | Reason not purchased |
|------|---------------------|
| RTC module (DS3231) | Not needed — indoor deployment with ethernet and NTP |
| UPS HAT (Waveshare) | SQLite WAL mode provides sufficient crash protection |
| Raspberry Pi 5 16GB | Overkill — 8GB more than sufficient for this workload |

---

## System Architecture

```
                        ┌─────────────────────────────────┐
                        │         Raspberry Pi 5           │
                        │                                  │
  ┌──────────────┐      │  ┌──────────┐   ┌────────────┐  │
  │  ReSpeaker   │ USB  │  │  audio_  │   │  detector  │  │
  │  4-Mic Array │─────▶│  │  capture │──▶│  (BirdNET  │  │
  │  (XVF-3000)  │      │  │  .py     │   │  TFLite)   │  │
  └──────────────┘      │  └──────────┘   └─────┬──────┘  │
                        │                        │         │
                        │  ┌─────────────────────▼──────┐  │
                        │  │      logger.py             │  │
                        │  │   (aiosqlite async)        │  │
                        │  └─────────────┬──────────────┘  │
                        │                │                  │
                        └────────────────┼──────────────────┘
                                         │
                              ┌──────────▼──────────┐
                              │  Samsung T7 1TB SSD  │
                              │  /mnt/ssd/           │
                              │  detections.db       │
                              └─────────────────────┘
```

**Audio pipeline:** 3-second chunks → BirdNET TFLite inference → confidence filter → async SQLite write

**Key design decisions:**
- Async architecture (`asyncio`) keeps audio capture and inference decoupled
- Audio captured in a `sounddevice` callback thread, fed to an `asyncio.Queue`
- Inference runs in a single worker coroutine — no threading complexity
- All detections written to SQLite with timestamp, species, confidence, and GPS coordinates

---

## Software Stack

| Component | Package | Purpose |
|-----------|---------|---------|
| Bird ID model | BirdNET-Analyzer (Cornell Lab) | TFLite acoustic inference |
| Audio capture | `sounddevice` | Low-latency ALSA interface |
| Array processing | `numpy` | Audio buffering and slicing |
| Database | `aiosqlite` + SQLite | Async detection logging |
| Terminal UI | `rich` | Live detection display |
| Web dashboard | `fastapi` + `uvicorn` | Browser-based detection viewer |
| Templating | `jinja2` + HTMX | Server-rendered pages with live updates |
| Image fetch | `httpx` + `Pillow` | Bird photo retrieval and caching |
| CLI | `click` | Command-line interface |
| OS | Raspberry Pi OS 64-bit | Debian-based Linux |

---

## Project File Structure

```
biardtz/                         # Repository root (PyScaffold layout)
├── pyproject.toml              # Project metadata, dependencies, entry points
├── src/biardtz/                 # Source package
│   ├── __init__.py             # Package version and metadata
│   ├── __main__.py             # python -m biardtz entry point
│   ├── cli.py                  # Click CLI — parses options, builds Config, launches run()
│   ├── config.py               # Dataclass with all tunable parameters
│   ├── audio_capture.py        # sounddevice stream → asyncio.Queue
│   ├── detector.py             # BirdNET TFLite wrapper
│   ├── logger.py               # aiosqlite detection logger + schema
│   ├── dashboard.py            # Rich live terminal dashboard
│   ├── doa.py                  # Direction of Arrival (GCC-PHAT on mic array)
│   ├── main.py                 # Async orchestrator — wires all pipeline stages
│   ├── api.py                  # Public Python API
│   └── web/                    # Web dashboard (FastAPI + HTMX)
│       ├── __init__.py         # FastAPI app factory
│       ├── routes.py           # Page, API, and HTMX partial endpoints
│       ├── image_cache.py      # Wikidata bird image fetcher + SSD cache
│       ├── health_checks.py    # 14 health probe functions (two-tier)
│       └── db.py               # Read-only database queries
│   ├── templates/              # Jinja2 HTML templates
│   └── static/                 # Static assets (fallback-bird.svg)
├── docs/                       # Sphinx documentation (MyST Markdown)
│   ├── build_log.md            # This file
│   ├── conf.py                 # Sphinx config
│   └── index.md                # Documentation landing page
├── tests/
│   ├── unit/                   # Fast unit tests (mocked dependencies)
│   └── integration/            # Filesystem and cross-module tests
├── .github/
│   └── workflows/ci.yml        # GitHub Actions CI (lint + test matrix)
├── Makefile                    # Build, test, lint, release automation
└── BirdNET-Analyzer/           # Cornell submodule (git clone, outside package)
```

---

## Phase Roadmap

### Phase 1 — Bird Detection (current)
- [x] Hardware procurement
- [x] Core software implementation (config, audio, detector, logger, dashboard, CLI)
- [x] Unit and integration test suites
- [x] GitHub Actions CI (Ruff lint + pytest on Python 3.12/3.13)
- [x] Makefile with incremental test caching and release automation
- [x] Raspberry Pi OS flash and initial setup
- [x] BirdNET-Analyzer installation on Pi
- [x] SSD formatted, mounted, and verified
- [x] Database resilience (backup, export, vacuum)
- [x] Location geocoding
- [x] Direction of Arrival estimation
- [ ] First live detection test
- [ ] Systemd service for auto-start on boot
- [ ] Validate detection accuracy against known local species

### Phase 2 — Bat Detection (future)
- [ ] Procure ultrasonic USB microphone (Dodotronic Ultramic 384K or equivalent)
- [ ] Install BatDetect2
- [ ] Build parallel pipeline with time-of-day scheduling
- [ ] Extend database schema for bat detections
- [ ] Validate against local bat species at dusk

### Phase 3 — Visualisation & Reporting (in progress)
- [x] Web dashboard (FastAPI + HTMX) for browsing detections
- [ ] Daily/weekly species summary emails
- [ ] Integration with citizen science platforms (eBird, iNaturalist)
- [ ] Optional: camera trap integration for visual confirmation

---

## Setup Guide

### 1. Flash the SD Card

Download [Raspberry Pi Imager](https://www.raspberrypi.com/software/) on your computer. Insert the microSD via USB reader. Select:
- Device: Raspberry Pi 5
- OS: Raspberry Pi OS (64-bit)
- Storage: your SD card

In advanced settings, pre-configure: hostname, SSH enabled, username/password, and WiFi if not using ethernet. Write and eject.

### 2. First Boot

Insert SD into Pi, connect ethernet, power on. SSH in from your computer:

```bash
ssh pi@birdwatch.local
```

Update the system:

```bash
sudo apt update && sudo apt full-upgrade -y
sudo reboot
```

### 3. Mount the SSD

The Samsung T7 ships formatted as exFAT, which is not suitable for SQLite WAL mode.
It must be reformatted as ext4.

```bash
# Identify the SSD
lsblk -f
# Look for the Samsung T7 — typically /dev/sda1

# If auto-mounted (e.g. at /media/kevin/T7 as exFAT), unmount first
sudo umount /dev/sda1

# Format as ext4 (first time only — destroys all data)
sudo mkfs.ext4 -L biardtz_ssd /dev/sda1

# Create mount point and mount
sudo mkdir -p /mnt/ssd
sudo mount /dev/sda1 /mnt/ssd
sudo chown $USER:$USER /mnt/ssd

# Add to fstab for auto-mount on boot (use UUID, not device path)
# Get the UUID:
sudo blkid /dev/sda1
# Then add to fstab (replace <your-uuid> with the actual UUID):
echo 'UUID=<your-uuid> /mnt/ssd ext4 defaults,nofail,noatime 0 2' | sudo tee -a /etc/fstab

# Verify the setup
make verify-storage
```

**Notes:**
- Using UUID in fstab is more reliable than `/dev/sda1`, which can change across reboots.
- `nofail` means the Pi will still boot even if the SSD is disconnected.
- `noatime` reduces unnecessary writes, extending SSD lifespan.
- The default database path `/mnt/ssd/detections.db` is set in `config.py` and overridable via `--db-path`.

### 4. Install Dependencies

```bash
sudo apt install -y python3-dev libportaudio2 ffmpeg git

# Clone BirdNET-Analyzer
git clone https://github.com/kahst/BirdNET-Analyzer.git

# Clone and install biardtz
git clone <repository-url> biardtz
cd biardtz
pip install -e . --break-system-packages
```

### 5. Configure

Configuration is handled via CLI options. At minimum, set your location when running:

```bash
biardtz --location "Biarritz, France"
```

This geocodes the place name to coordinates using OpenStreetMap (requires network on first run). You can also pass raw coordinates with `--lat` / `--lon` if preferred.

Find your microphone device index:

```python
import sounddevice as sd
print(sd.query_devices())
# Pass the ReSpeaker index via --device
```

### 6. Run

```bash
biardtz --location "Biarritz, France" --device 2
```

Run `biardtz --help` for all available options.

### 7. Auto-start on Boot (systemd)

```bash
sudo nano /etc/systemd/system/biardtz.service
```

```ini
[Unit]
Description=biardtz real-time bird detection
After=network.target

[Service]
User=pi
WorkingDirectory=/home/pi/biardtz
ExecStart=/usr/local/bin/biardtz --location "Biarritz, France"
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable biardtz
sudo systemctl start biardtz
```

---

## Key Configuration Parameters

| Parameter | Default | Notes |
|-----------|---------|-------|
| `sample_rate` | 16000 | ReSpeaker hardware fixed at 16 kHz; BirdNET resamples internally |
| `channels` | 6 | ReSpeaker hardware fixed at 6 channels; channel 0 extracted for mono |
| `chunk_duration` | 3.0 | BirdNET window size in seconds |
| `confidence_threshold` | 0.25 | Lower = more detections, more false positives |
| `location_name` | (none) | Place name for geocoding via `--location` / `-l` |
| `latitude` / `longitude` | 51.50 / -0.12 | Auto-set from `--location`, or manual via `--lat` / `--lon` |
| `week` | -1 | -1 disables seasonal filter; set to ISO week for better accuracy |
| `num_threads` | 4 | Pi 5 has 4 cores — leave at 4 |
| `db_path` | `/mnt/ssd/detections.db` | Override via `--db-path` |
| `array_bearing` | 0.0 | Physical bearing of mic array (degrees from north) via `--array-bearing` |

---

## Database Schema

```sql
CREATE TABLE detections (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp     TEXT NOT NULL,      -- ISO 8601 UTC
    common_name   TEXT NOT NULL,
    sci_name      TEXT NOT NULL,
    confidence    REAL NOT NULL,      -- 0.0 to 1.0
    latitude      REAL,
    longitude     REAL,
    bearing       REAL,              -- degrees from north (0-360), nullable
    direction     TEXT               -- compass direction (N, NE, E, etc.), nullable
);
```

Useful queries:

```sql
-- Species seen today
SELECT common_name, COUNT(*), MAX(confidence)
FROM detections
WHERE date(timestamp) = date('now')
GROUP BY common_name ORDER BY COUNT(*) DESC;

-- All-time species list
SELECT DISTINCT common_name, MIN(timestamp) as first_seen
FROM detections ORDER BY first_seen;
```

---

## Session Log — 2026-04-07

### BirdNET-Analyzer Model Fix

The BirdNET `checkpoints/` directory was a broken symlink pointing into `site-packages`, left over from a pip install. Replaced it with a real directory and downloaded the V2.4 TFLite model files using BirdNET's built-in `ensure_model_exists()` function, which handles checksums and caching correctly.

Also fixed the `verify` script to invoke `sys.executable -m biardtz` instead of the bare `biardtz` command — the latter resolved to a conda environment that lacked BirdNET dependencies.

### Clean SIGTERM Shutdown

`asyncio.run()` was propagating `CancelledError` on SIGTERM, causing exit code 1 even though shutdown was intentional. Added exception handling in `cli.py` to catch `CancelledError` and `KeyboardInterrupt`, returning exit code 0 for clean stops.

Added unit and integration tests: the integration test spawns a subprocess, sends SIGTERM, and asserts exit code 0.

### SSD Setup (Samsung T7 1TB)

The Samsung T7 arrived factory-formatted as exFAT, which is unsuitable for SQLite WAL mode (no POSIX advisory locking). Reformatted as ext4:

```bash
sudo mkfs.ext4 -L biardtz_ssd /dev/sda1
```

Mounted at `/mnt/ssd` with a UUID-based fstab entry using `nofail,noatime` flags. Added `make verify-storage` target that checks mount status, filesystem type, permissions, available space, and fstab presence. Copied the initial empty-schema database to `/mnt/ssd/detections.db`.

### Database Resilience

Hardened the SQLite connection in `logger.py`:
- `PRAGMA busy_timeout=5000` — wait up to 5 seconds on lock contention instead of failing immediately
- `PRAGMA synchronous=NORMAL` — reduces fsync frequency (WAL mode already provides crash safety)
- Non-blocking integrity check on startup (logs a warning on corruption, does not block the pipeline)

New scripts:
- **`scripts/db_backup.py`** — uses SQLite's online backup API (safe while biardtz is running), 7-day rotation of old backups
- **`scripts/db_export_csv.py`** — read-only streaming export with `--since` date filter

New Makefile targets: `db-backup`, `db-export`, `db-vacuum`. Added `cron-install` target to `Makefile.pi` for daily 03:00 UTC automated backups.

### Location Geocoding

Replaced the `--lat`/`--lon` CLI options with `--location`/`-l`, which accepts human-readable place names:

```bash
biardtz --location "Biarritz, France"
```

Uses `geopy` with the Nominatim geocoder (OpenStreetMap — free, no API key required). The resolved coordinates are passed to BirdNET for species filtering. Added `location_name` field to `Config`. Defaults remain London (51.50, -0.12) when no location is specified.

### Direction of Arrival (DOA)

Added compass direction estimation for detected birds using GCC-PHAT (Generalized Cross-Correlation with Phase Transform) on the ReSpeaker 4-Mic Array's raw channels.

New module `doa.py` implements a steering-vector scan across all 6 microphone pairs. Audio capture now passes `(mono, multichannel)` tuples through the pipeline — BirdNET still receives mono only, while DOA runs in an executor and is only invoked when detections are found above the confidence threshold.

Added `--array-bearing` CLI option to set the array's physical orientation (degrees from north), so compass directions are absolute rather than relative.

Database schema extended with two new columns:
```sql
ALTER TABLE detections ADD COLUMN bearing REAL;
ALTER TABLE detections ADD COLUMN direction TEXT;
```
Migration is backward-compatible — existing rows get NULL values. The Rich dashboard now includes a direction column.

**Released as v0.1.0.**

### Web Dashboard (v0.2.0)

Added a browser-based dashboard for viewing detections from any device on the local network. Stack: FastAPI + Jinja2 + HTMX + Tailwind CSS (via CDN).

Features:
- Summary cards showing today's detections, today's species, and all-time species count
- Recent detections list with bird photos sourced from Wikipedia/Wikidata (cached on SSD)
- Colour-coded confidence bars (green >75%, amber >50%, grey below)
- SVG compass indicator showing direction of arrival
- Species leaderboard
- Auto-refresh via HTMX (detections every 5s, stats every 30s)
- Mobile-friendly responsive layout with an emerald green nature theme

Two ways to run:
- **Integrated:** `biardtz` starts the web dashboard automatically on port 8080
- **Standalone:** `biardtz-web` runs just the dashboard in read-only mode against the database

CLI flags: `--web/--no-web`, `--web-port 8080`. Access at `http://<pi-ip>:8080/` from any device on the network.

New modules:
- `src/biardtz/web/__init__.py` — FastAPI app factory
- `src/biardtz/web/routes.py` — page, API, and HTMX partial endpoints
- `src/biardtz/web/image_cache.py` — Wikidata image fetcher with SSD cache
- `src/biardtz/web/db.py` — read-only database queries
- `src/biardtz/templates/` — Jinja2 HTML templates
- `src/biardtz/static/fallback-bird.svg` — fallback bird silhouette

New dependencies: `fastapi`, `uvicorn`, `httpx`, `Pillow`.

### Phase 1 Progress Update

Updated checklist:
- [x] Raspberry Pi OS flash and initial setup
- [x] BirdNET-Analyzer installation on Pi
- [x] SSD formatted, mounted, and verified
- [x] Database resilience (backup, export, vacuum)
- [x] Location geocoding via `--location` flag
- [x] Direction of Arrival estimation
- [ ] First live detection test
- [ ] Systemd service for auto-start on boot
- [ ] Validate detection accuracy against known local species

---

## Session Log --- 2026-04-21

### Health Panel Drawer (v1.1.4)

Added a slide-out health panel to the web dashboard, accessible by clicking the coloured dot in the header bar. The panel uses two-tier loading to stay responsive:

**Tier 1 (instant, no subprocess calls):**
- Pipeline status from the heartbeat file (PID, uptime, audio stream, detection/species counts, recent errors)
- Database file size and WAL size
- Software versions (biardtz and Python)
- Config summary (location, coordinates, confidence, sample rate, channels, timezone)

**Tier 2 (async, loaded with skeleton placeholders via HTMX):**
- CPU temperature from `/sys/class/thermal/thermal_zone0/temp`
- Memory usage from `/proc/meminfo`
- Disk usage for `/mnt/ssd`
- Microphone detection via `arecord -l`
- Network info: WiFi SSID (`iwgetid`), IP addresses (`hostname -I`), Tailscale status
- Systemd service status and uptime
- BirdNET model validation (model file existence, species label count)
- Database integrity (`PRAGMA quick_check`, row counts, audio clip count)

The health dot in the header polls `/api/health/quick` every 30 seconds and changes colour: green when healthy, yellow when degraded (stale heartbeat or degraded pipeline status), red when the pipeline is down or the heartbeat is missing.

New files:
- `src/biardtz/web/health_checks.py` --- 14 probe functions organised into `tier1_checks()` and `tier2_checks()`, plus `quick_status()` for the dot colour
- `src/biardtz/templates/_health_panel.html` --- Jinja2 template for the drawer with HTMX lazy-loading of Tier 2 sections

New API endpoints:
- `GET /api/health` --- full Tier 1 + Tier 2 combined as JSON
- `GET /api/health/quick` --- returns `{"color": "green"}` (or yellow/red)
- `GET /api/health/tier2/hardware` --- HTML partial for CPU/memory/disk/mic
- `GET /api/health/tier2/db` --- HTML partial for DB integrity
- `GET /api/health/tier2/birdnet` --- HTML partial for BirdNET model status
- `GET /api/health/tier2/network` --- HTML partial for network/WiFi/Tailscale/systemd
- `GET /api/health/tier2/uptime` --- HTML partial for system uptime

### Today Chart Improvements (v1.1.6--v1.1.11)

Reworked the Today banner drill-down chart to be more useful and visually polished:

- **Midnight-to-now range** --- the chart now shows hours from 00:00 to the current hour, not a rolling 24-hour window. This makes the chart match what users expect from a "today" view.
- **Hour padding** --- all hours from midnight to now are present on the X axis, even hours with zero detections. No gaps.
- **Cumulative line** --- a line overlaid on the bar chart shows cumulative detections through the day, plotted on a secondary Y axis. This gives an at-a-glance sense of the day's progression.
- **Nearest-element tooltip** --- hover shows a tooltip for the nearest element (bar or line), making it easy to read values without precise cursor placement.
- **Visual refinements** --- bars are visually dominant (wider, higher z-order) and the cursor changes to a pointer when hovering over clickable bars.

---

## References

- [BirdNET-Analyzer GitHub](https://github.com/kahst/BirdNET-Analyzer) — Cornell Lab of Ornithology
- [BatDetect2 GitHub](https://github.com/macaodha/batdetect2) — for future bat detection phase
- [ReSpeaker USB Mic Array Wiki](https://wiki.seeedstudio.com/ReSpeaker_Mic_Array_v2.0/) — Seeed Studio
- [Raspberry Pi Documentation](https://www.raspberrypi.com/documentation/)
- [sounddevice documentation](https://python-sounddevice.readthedocs.io/)
- [aiosqlite documentation](https://aiosqlite.omnilib.dev/)
