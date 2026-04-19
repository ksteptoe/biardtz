# biardtz Cheatsheet

Quick reference for all biardtz commands and options.

## Start the pipeline

```bash
# Default (London, threshold 0.25, web dashboard on port 8080)
biardtz

# Custom location and verbose logging
biardtz --location "Biarritz, France" -v

# Full options
biardtz \
    --location "Biarritz, France" \
    --threshold 0.30 \
    --db-path /mnt/ssd/detections.db \
    --device 2 \
    --array-bearing 180 \
    --web-port 8080 \
    -vv
```

Stop with **Ctrl+C**.

## CLI options

| Option | Default | What it does |
|--------|---------|--------------|
| `--location, -l` | `London` | Town/city for species filtering (geocoded automatically) |
| `--threshold` | `0.25` | Minimum confidence 0.0-1.0 |
| `--db-path` | `/mnt/ssd/detections.db` | SQLite database path |
| `--device` | system default | Audio device index |
| `--birdnet-path` | `../BirdNET-Analyzer` | Path to BirdNET-Analyzer directory |
| `--array-bearing` | `0.0` | Compass bearing (degrees) the mic array faces |
| `--dashboard/--no-dashboard` | on | Rich terminal dashboard |
| `--web/--no-web` | on | Web dashboard |
| `--web-port` | `8080` | Web dashboard port |
| `-v` / `-vv` | warnings | `-v` = info, `-vv` = debug |
| `--version` | | Show version and exit |

## Subcommands

```bash
biardtz status       # Show pipeline health (from heartbeat file)
biardtz diagnose     # Full diagnostic: process, systemd, tailscale, audio, errors
```

## Systemd service

```bash
sudo bash systemd/install.sh          # Install and enable service
make start                             # Start service, confirm running
make stop                              # Stop service, confirm stopped
make restart                           # Restart service, confirm running
sudo systemctl status biardtz          # Check status
journalctl -u biardtz -f              # Follow live logs
```

## Web dashboard

| From where | URL |
|------------|-----|
| Home network | `http://kspi-002.local:8080` |
| Home network (IP) | `http://192.168.1.124:8080` |
| Anywhere (Tailscale) | `http://100.74.44.10:8080` |

Detection rows include a play button for species that have a saved audio clip. Clicking play stops any other clip that is currently playing.

## Monitoring & debugging

```bash
make status            # Pipeline health (biardtz status)
make diagnose          # Full diagnostics: process, systemd, tailscale, audio, errors
make logs              # Follow live systemd journal logs
make logs-errors       # Show recent ERROR lines from log file
make tail-logs         # Tail the rotating log file
make heartbeat         # Show raw heartbeat JSON
```

### Log & heartbeat locations

| File | Path |
|------|------|
| Rotating log | `/mnt/ssd/biardtz/logs/biardtz.log` (5 MB, 5 backups) |
| Heartbeat | `/mnt/ssd/biardtz/heartbeat.json` (updated every 10s) |
| Audio clips | `/mnt/ssd/audio_clips/` (best WAV per species, ~288 KB each) |
| Journal | `journalctl -u biardtz` |

### What `diagnose` checks

1. **Pipeline** --- process alive, heartbeat age, status
2. **Systemd** --- service enabled/active
3. **Tailscale** --- daemon running, auto-start enabled
4. **Audio** --- ReSpeaker detected via `arecord -l`
5. **Recent errors** --- last 5 ERROR lines from log
6. **Recommendations** --- restart tips, SSH session warnings

## Make targets

```bash
make help              # Show all targets
make bootstrap         # Create venv and install deps
make test              # Run unit + integration tests (cached)
make test-all          # Run all tests (no cache)
make lint              # Ruff check
make format            # Ruff auto-fix
make docs              # Build Sphinx docs to docs/_build/html
make docs-pdf          # Generate PDF guide via pandoc
make cheatsheet        # Print this cheatsheet to terminal
make release KIND=patch  # Tag and push a release (patch/minor/major)
make verify            # Run all installation verification checks
make start             # Start biardtz systemd service
make stop              # Stop biardtz systemd service
make restart           # Restart biardtz systemd service
```

## Web API

All endpoints are available when the web dashboard is running (default port 8080).

| Endpoint | Parameters | Description |
|----------|------------|-------------|
| `GET /api/detections` | `limit`, `offset`, `species`, `min_confidence`, `date_from`, `date_to`, `search` | Recent detections as JSON |
| `GET /api/species` | `q` | Species list with optional search |
| `GET /api/charts/timeline` | `days` (default 7) | Hourly detection counts |
| `GET /api/charts/species` | `days` (default 30), `limit` (default 15) | Top species by count |
| `GET /api/charts/heatmap` | `days` (default 30) | Activity heatmap (day-of-week x hour) |
| `GET /api/charts/trend` | `days` (default 30) | Daily detection and species counts |
| `GET /api/image/{sci_name}` | | Bird photo (cached from Wikipedia) |
| `GET /api/audio/{filename}` | | Audio clip WAV file |

Chart endpoints are cached server-side (60s TTL) with `Cache-Control: max-age=60`.

```bash
curl http://localhost:8080/api/detections?limit=5
curl http://localhost:8080/api/species?q=robin
curl http://localhost:8080/api/charts/timeline?days=7
```

## Database maintenance

```bash
make db-backup                       # Back up to ~/backups/biardtz/
make db-export                       # Export detections to CSV
make db-vacuum                       # Reclaim unused space (stop biardtz first)

# Manual query
sqlite3 /mnt/ssd/detections.db "SELECT * FROM detections ORDER BY timestamp DESC LIMIT 10;"
```

## Pi setup (Makefile.pi)

```bash
make -f Makefile.pi setup    # Install everything from scratch
make -f Makefile.pi test     # Run tests
make -f Makefile.pi run      # Start biardtz
make -f Makefile.pi help     # Show all targets
```

## Conda environment

```bash
conda activate biardtz       # Activate (needed each SSH session)
conda deactivate             # Deactivate
python --version             # Should show 3.12.x
```

## Troubleshooting quick fixes

| Problem | Fix |
|---------|-----|
| Pipeline dead | `sudo systemctl restart biardtz` or `biardtz -v` |
| No heartbeat | Pipeline never started or crashed — check `journalctl -u biardtz` |
| No audio device | `arecord -l` to check, then `--device N` |
| BirdNET not found | Ensure `~/BirdNET-Analyzer/` exists or use `--birdnet-path` |
| DB permission error | Check `mount \| grep ssd` and `ls -la /mnt/ssd/` |
| Web dashboard won't load | Wait 30s for boot, check Pi has power/network |
| Wrong Python version | `conda activate biardtz` then `python --version` (need 3.12) |
