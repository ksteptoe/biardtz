# Deployment Guide: Raspberry Pi

Step-by-step guide to getting biardtz running on a Raspberry Pi 4B for real-time bird identification.

## What you need

### Hardware
- Raspberry Pi 4B (2GB+ RAM)
- USB microphone
- MicroSD card (32GB+) with Debian 13 (Trixie) or Raspberry Pi OS
- SSD (recommended) for the detections database — avoids SD card wear
- Power supply, ethernet cable (for initial setup)

### Software (installed during this guide)
- Python 3.12+
- PortAudio (for microphone access)
- BirdNET-Analyzer (bird species inference)
- biardtz (this project)

## Step 1: Initial Pi setup

Flash your OS, boot the Pi, and connect via SSH over ethernet. See {doc}`pi_network_setup` to configure Wi-Fi and hostname-based SSH access.

## Step 2: Install system packages

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y python3-dev python3-venv libportaudio2 portaudio19-dev git
```

- `libportaudio2` / `portaudio19-dev` — required by the `sounddevice` library for audio capture
- `python3-dev` — needed to compile Python packages on ARM
- `python3-venv` — for creating isolated Python environments

## Step 3: Mount the SSD

biardtz writes detections to an SQLite database. An SSD avoids wearing out the SD card.

### Find the SSD device
```bash
lsblk
```

### Format (if new) and mount
```bash
sudo mkfs.ext4 /dev/sda1          # only if unformatted — this erases data!
sudo mkdir -p /mnt/ssd
sudo mount /dev/sda1 /mnt/ssd
sudo chown $USER:$USER /mnt/ssd
```

### Make it permanent (auto-mount on boot)
Add to `/etc/fstab`:
```bash
echo '/dev/sda1 /mnt/ssd ext4 defaults,noatime 0 2' | sudo tee -a /etc/fstab
```

The default database path is `/mnt/ssd/detections.db`. If you skip this step, override the path with `--db-path` when running biardtz.

## Step 4: Clone BirdNET-Analyzer

BirdNET-Analyzer is the machine learning engine that identifies bird species from audio. It must be cloned as a **sibling directory** to biardtz.

```bash
cd ~/
git clone https://github.com/kahst/BirdNET-Analyzer.git
```

Install its Python dependencies:
```bash
cd ~/BirdNET-Analyzer
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

```{note}
BirdNET uses TensorFlow Lite for inference on the Pi. Check the
[BirdNET-Analyzer README](https://github.com/kahst/BirdNET-Analyzer) for any
Pi-specific installation notes, especially around TFLite runtime.
```

## Step 5: Clone and install biardtz

```bash
cd ~/
git clone https://github.com/ksteptoe/biardtz.git
cd biardtz
python3 -m venv .venv
.venv/bin/pip install -e .
```

## Step 6: Check the USB microphone

Plug in your USB microphone and verify it's detected:

```bash
arecord -l
```

You should see your device listed. Note the card/device number if you need to specify it later.

To test recording:
```bash
arecord -d 5 -f cd test.wav && aplay test.wav
```

## Step 7: Run biardtz

### Basic usage
```bash
cd ~/biardtz
.venv/bin/biardtz
```

### With custom options
```bash
.venv/bin/biardtz \
    --lat 51.50 \
    --lon -0.12 \
    --threshold 0.25 \
    --db-path /mnt/ssd/detections.db \
    --dashboard \
    -v
```

### All CLI options

| Option | Default | Description |
|--------|---------|-------------|
| `--lat` | 51.50 | Latitude for species filtering |
| `--lon` | -0.12 | Longitude for species filtering |
| `--threshold` | 0.25 | Minimum confidence (0.0-1.0) |
| `--db-path` | `/mnt/ssd/detections.db` | SQLite database path |
| `--device` | system default | Audio device index |
| `--birdnet-path` | `../BirdNET-Analyzer` | Path to BirdNET-Analyzer directory |
| `--dashboard/--no-dashboard` | enabled | Rich live terminal dashboard |
| `-v` / `-vv` | warnings only | Verbosity: `-v` info, `-vv` debug |

## Step 8: Run as a service (optional)

To run biardtz automatically on boot, create a systemd service:

```bash
sudo tee /etc/systemd/system/biardtz.service > /dev/null <<'EOF'
[Unit]
Description=biardtz bird identification
After=network.target

[Service]
Type=simple
User=kevin
WorkingDirectory=/home/kevin/biardtz
ExecStart=/home/kevin/biardtz/.venv/bin/biardtz --lat 51.50 --lon -0.12
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF
```

Enable and start:
```bash
sudo systemctl enable biardtz
sudo systemctl start biardtz
```

Check status:
```bash
sudo systemctl status biardtz
journalctl -u biardtz -f    # follow live logs
```

## Directory layout on the Pi

```
~/
├── biardtz/              # this project
│   ├── .venv/            # Python virtual environment
│   └── src/biardtz/      # source code
├── BirdNET-Analyzer/     # cloned separately
│   └── .venv/            # its own virtual environment
/mnt/ssd/
└── detections.db         # created automatically on first run
```

## Troubleshooting

### "BirdNET-Analyzer not found"
Ensure it's cloned at `~/BirdNET-Analyzer/` (sibling to `~/biardtz/`), or pass `--birdnet-path /path/to/BirdNET-Analyzer`.

### No audio device found
- Check `arecord -l` — is the USB mic listed?
- Try specifying the device explicitly: `--device 1` (use the index from `arecord -l`)

### Database permission errors
- Check the mount: `mount | grep ssd`
- Check ownership: `ls -la /mnt/ssd/`
- Or use a local path: `--db-path ~/detections.db`

### High CPU / slow inference
- BirdNET inference is CPU-bound. On Pi 4B, expect ~1-3 seconds per 3-second chunk
- Reduce threads if overheating: edit `num_threads` in config (default: 4)
