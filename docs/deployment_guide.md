# Deployment Guide: Raspberry Pi

A step-by-step guide to getting biardtz running on a Raspberry Pi 4B for real-time bird identification. Written so you can walk through it together with someone new to the Pi.

## What you need

### Hardware
- Raspberry Pi 4B (2GB+ RAM)
- USB microphone
- MicroSD card (32GB+) with Debian 13 (Trixie) or Raspberry Pi OS
- SSD (recommended) for the detections database — avoids SD card wear
- Power supply, ethernet cable (for initial setup)

### Software (installed during this guide)
- Miniforge (conda for ARM64) — manages Python versions
- Python 3.12 (via conda) — required because TensorFlow doesn't support Python 3.13 yet
- BirdNET-Analyzer v2.4.0 — bird species inference engine
- biardtz — this project

## Quick setup (automated)

The project includes a `Makefile.pi` that automates every step below. Copy it to your Pi and run:

```bash
cd ~/biardtz
make -f Makefile.pi setup    # installs everything
make -f Makefile.pi test     # runs all tests
make -f Makefile.pi run      # starts biardtz
```

Run `make -f Makefile.pi help` to see all available targets. The rest of this guide explains each step manually if you want to understand what's happening.

## Step 1: Initial Pi setup

Flash Debian 13 (Trixie) or Raspberry Pi OS onto your MicroSD card, insert it, and power on the Pi. Connect via ethernet and SSH:

```bash
ssh kevin@<pi-ip-address>
```

See {doc}`pi_network_setup` to configure Wi-Fi and hostname-based SSH access so you can use `ssh pi` instead.

## Step 2: Install system packages

These are Linux packages needed for audio capture and building Python extensions:

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y build-essential python3-dev libportaudio2 portaudio19-dev libsndfile1 git wget curl
```

What each package does:
- `build-essential` — C compiler, needed to build some Python packages on ARM
- `libportaudio2` / `portaudio19-dev` — audio library used by `sounddevice` for microphone input
- `libsndfile1` — audio file reading library
- `git` — to clone the source code repositories
- `wget` / `curl` — to download Miniforge

## Step 3: Install Miniforge (conda)

Debian 13 ships with Python 3.13, but BirdNET-Analyzer needs Python 3.12 (TensorFlow doesn't support 3.13 yet). We use **Miniforge** — a lightweight conda distribution for ARM64 — to manage Python versions.

### Download and install

```bash
wget https://github.com/conda-forge/miniforge/releases/latest/download/Miniforge3-Linux-aarch64.sh
bash Miniforge3-Linux-aarch64.sh
```

The installer will ask you:
1. **License** — press Enter to scroll, then type `yes`
2. **Install location** — press Enter to accept the default (`~/miniforge3`)
3. **Initialise conda** — type `yes` (this adds conda to your shell)

Then reload your shell:

```bash
source ~/.bashrc
```

### Verify it works

```bash
conda --version
```

You should see something like `conda 24.x.x`.

## Step 4: Create a Python 3.12 environment

Create a dedicated environment for biardtz with the correct Python version:

```bash
conda create -n biardtz python=3.12 -y
conda activate biardtz
```

Verify:

```bash
python --version
# Should show: Python 3.12.x
```

```{tip}
Every time you open a new SSH session, you need to activate the environment:
`conda activate biardtz`
```

## Step 5: Clone and install BirdNET-Analyzer

BirdNET-Analyzer is the machine learning engine that identifies bird species from audio. It must be installed as a **sibling directory** to biardtz.

### Clone the repository

```bash
cd ~/
git clone https://github.com/kahst/BirdNET-Analyzer.git
```

### Install into the conda environment

```bash
conda activate biardtz
cd ~/BirdNET-Analyzer
pip install -e .
pip install pyarrow
```

```{note}
`pyarrow` is not listed in BirdNET's dependencies but is required at runtime.
The install may take several minutes on the Pi — it's a large package.
```

### Test BirdNET

BirdNET includes an example audio file. Let's make sure everything works:

```bash
birdnet-analyze birdnet_analyzer/example/soundscape.wav --lat 51.50 --lon -0.12 --rtype table
```

You should see a table of detected bird species with confidence scores. If this works, BirdNET is ready.

## Step 6: Clone and install biardtz

```bash
cd ~/
git clone https://github.com/ksteptoe/biardtz.git
cd biardtz
conda activate biardtz
pip install -e ".[dev]"
```

### Run the test suite

All tests mock the hardware, so they work without a microphone or SSD:

```bash
pytest tests/ -v
```

All tests should pass. This confirms the code is correctly installed.

### Check the CLI

```bash
biardtz --help
```

You should see the full list of command-line options.

## Step 7: Mount the SSD (optional but recommended)

biardtz writes detections to an SQLite database. An SSD avoids wearing out the SD card with constant writes.

### Find the SSD device

```bash
lsblk
```

Look for your SSD (usually `/dev/sda1`).

### Format (only if new — this erases all data!)

```bash
sudo mkfs.ext4 /dev/sda1
```

### Mount it

```bash
sudo mkdir -p /mnt/ssd
sudo mount /dev/sda1 /mnt/ssd
sudo chown $USER:$USER /mnt/ssd
```

### Make it permanent (auto-mount on boot)

```bash
echo '/dev/sda1 /mnt/ssd ext4 defaults,noatime 0 2' | sudo tee -a /etc/fstab
```

If you skip the SSD, override the database path when running:
```bash
biardtz --db-path ~/detections.db
```

## Step 8: Check the USB microphone

Plug in your USB microphone and check it's detected:

```bash
arecord -l
```

You should see your microphone listed with a card and device number.

### Test recording (5 seconds)

```bash
arecord -d 5 -f cd test.wav && aplay test.wav
```

If you hear your recording played back, the microphone is working.

## Step 9: Run biardtz

### Basic usage

```bash
conda activate biardtz
biardtz
```

### With custom options

```bash
biardtz \
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

## Step 10: Run as a service (optional)

To run biardtz automatically on boot, create a systemd service:

```bash
# Find the full path to biardtz in your conda env
which biardtz
# e.g. /home/kevin/miniforge3/envs/biardtz/bin/biardtz
```

Create the service file:

```bash
sudo tee /etc/systemd/system/biardtz.service > /dev/null <<'EOF'
[Unit]
Description=biardtz bird identification
After=network.target

[Service]
Type=simple
User=kevin
WorkingDirectory=/home/kevin/biardtz
ExecStart=/home/kevin/miniforge3/envs/biardtz/bin/biardtz --lat 51.50 --lon -0.12 --db-path /mnt/ssd/detections.db
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF
```

Enable and start:

```bash
sudo systemctl enable biardtz     # start on boot
sudo systemctl start biardtz      # start now
```

Check it's running:

```bash
sudo systemctl status biardtz     # current status
journalctl -u biardtz -f          # follow live logs (Ctrl+C to stop)
```

## Directory layout on the Pi

When everything is installed, your Pi will look like this:

```
~/
├── miniforge3/               # conda installation
│   └── envs/biardtz/         # Python 3.12 environment
├── biardtz/                  # this project
│   ├── Makefile.pi           # automated setup script
│   └── src/biardtz/          # source code
├── BirdNET-Analyzer/         # cloned separately
│   └── birdnet_analyzer/     # BirdNET v2.4.0 package
/mnt/ssd/
└── detections.db             # created automatically on first run
```

## Testing without hardware

You can install and test everything without a microphone or SSD:

- **biardtz tests** — all tests mock the hardware: `pytest tests/ -v`
- **BirdNET test** — uses the included example file: `birdnet-analyze birdnet_analyzer/example/soundscape.wav --rtype table`
- **CLI check** — `biardtz --help` confirms the CLI is working
- **biardtz dry run** — `biardtz --db-path ~/test.db --no-dashboard -v` will start but fail at audio capture (no mic), confirming everything up to that point works

## Troubleshooting

### Python version issues
Debian 13 ships with Python 3.13, but TensorFlow needs 3.12. Always use the conda environment:
```bash
conda activate biardtz
python --version   # should show 3.12.x
```

### "BirdNET-Analyzer not found"
Ensure it's cloned at `~/BirdNET-Analyzer/` (sibling to `~/biardtz/`), or pass `--birdnet-path /path/to/BirdNET-Analyzer`.

### "No module named 'pyarrow'"
Install it in the conda env: `conda activate biardtz && pip install pyarrow`

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
