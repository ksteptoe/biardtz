# Deployment Guide: Raspberry Pi

A step-by-step guide to getting biardtz running on a Raspberry Pi 4B for real-time bird identification. Written so you can walk through it together with someone new to the Pi.

## What you need

### Hardware
- Raspberry Pi 4B (2GB+ RAM)
- ReSpeaker USB 4 Mic Array (UAC 1.0)
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
pip install .
```

This pulls in TensorFlow, librosa, and other dependencies. It will take several minutes on the Pi — TensorFlow is a large package.

### Fix flatbuffers version

pip may install an ancient date-based version of flatbuffers (`20181003210633`) that is incompatible with Python 3.12+. Force-install a modern version:

```bash
pip install 'flatbuffers==25.12.19'
```

### Download model checkpoints

BirdNET ships without model weights. Download them after install:

```bash
python -c "from birdnet_analyzer.utils import ensure_model_exists; ensure_model_exists()"
```

Then symlink the checkpoints into the cloned repo so the sibling-directory import path can find them:

```bash
ln -s $(python -c "import birdnet_analyzer, os; print(os.path.join(os.path.dirname(birdnet_analyzer.__file__), 'checkpoints'))") \
      ~/BirdNET-Analyzer/birdnet_analyzer/checkpoints
```

```{note}
If TensorFlow fails to install (e.g. on older Pi models with limited RAM), you can use the lighter `tflite-runtime` instead:

    pip install tflite-runtime
    pip install /path/to/BirdNET-Analyzer --no-deps
    pip install librosa resampy tqdm pandas matplotlib kagglehub
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

## Step 7: Mount the SSD

biardtz writes detections to an SQLite database. The database **must** live on an ext4-formatted SSD, not the SD card — constant SQLite WAL writes will wear out a microSD card quickly, and exFAT (the factory format on Samsung T7 drives) does not support Unix permissions or reliable SQLite WAL mode.

### 1. Identify the SSD

```bash
lsblk -f
```

Look for the Samsung T7 — typically `/dev/sda1`. If it shows as exFAT mounted at `/media/$USER/T7`, it was auto-mounted and needs to be reformatted.

### 2. Unmount if auto-mounted

```bash
sudo umount /dev/sda1
```

### 3. Format as ext4 (first time only — erases all data)

```bash
sudo mkfs.ext4 -L biardtz_ssd /dev/sda1
```

### 4. Create mount point and mount

```bash
sudo mkdir -p /mnt/ssd
sudo mount /dev/sda1 /mnt/ssd
sudo chown $USER:$USER /mnt/ssd
```

### 5. Add to fstab for auto-mount on boot

Use the UUID (more reliable than `/dev/sda1` which can change):

```bash
# Get the UUID
sudo blkid /dev/sda1

# Add fstab entry (replace <your-uuid> with the actual UUID)
echo 'UUID=<your-uuid> /mnt/ssd ext4 defaults,nofail,noatime 0 2' | sudo tee -a /etc/fstab
```

### 6. Verify

```bash
make verify-storage
```

This checks: mount point exists, filesystem is ext4, writable by current user, available space, and fstab entry.

**Mount options explained:**
- `nofail` — the Pi will still boot even if the SSD is disconnected
- `noatime` — skips updating access timestamps, reducing unnecessary writes

If you skip the SSD, override the database path when running:
```bash
biardtz --db-path ~/detections.db
```

## Step 8: Set up the ReSpeaker USB 4-Mic Array

Plug in the ReSpeaker USB 4 Mic Array and verify it's detected:

```bash
lsusb | grep -i seed
arecord -l
```

You should see `ReSpeaker 4 Mic Array (UAC1.0)` listed as a capture device.

### Hardware constraints

The ReSpeaker has fixed hardware parameters that cannot be changed:

| Parameter | Value | Notes |
|-----------|-------|-------|
| Channels | 6 | Fixed — cannot do mono at hardware level |
| Sample rate | 16000 Hz | Fixed — does not support 48000 Hz |
| Format | S16_LE | Only supported format |

You can verify these with:

```bash
arecord -D hw:3,0 --dump-hw-params
```

> **Note:** The card number (3 in `hw:3,0`) may vary depending on other USB devices. Check `arecord -l` for the actual number.

The `audio_capture.py` module handles this automatically — it opens all 6 channels and extracts channel 0 (mono). The Config defaults are set to `sample_rate=16000` and `channels=6`.

### Test recording (5 seconds)

```bash
arecord -D hw:3,0 -c 6 -r 16000 -f S16_LE -d 5 /tmp/test.wav
```

Then check the sounddevice device index:

```bash
python -c "import sounddevice; print(sounddevice.query_devices())"
```

Note the index for the ReSpeaker (typically 1) — you'll use this with `--device`.

## Step 9: Verify the installation

Before running biardtz for real, walk through these checks to confirm that the hardware, audio stack, and software are all working correctly.

### 1. Verify mic detection

```bash
arecord -l
```

You should see the ReSpeaker listed as a capture device, for example:

```
card 2: ArrayUAC10 [ReSpeaker 4 Mic Array (UAC1.0)], device 0: USB Audio [USB Audio]
  Subdevices: 1/1
  Subdevice #0: subdevice #0
```

The card number may differ depending on other USB devices. If the ReSpeaker does not appear, try a different USB port or check `lsusb | grep -i seed`.

### 2. Audio capture test

Record 3 seconds of audio via sounddevice and check that the microphone is picking up sound:

```bash
python -c "
import sounddevice as sd
import numpy as np
audio = sd.rec(int(3 * 48000), samplerate=48000, channels=1, dtype='float32', device=0)
sd.wait()
peak = np.max(np.abs(audio))
rms = np.sqrt(np.mean(audio**2))
print(f'Samples: {len(audio)}, Peak: {peak:.4f}, RMS: {rms:.6f}')
print('Audio capture working!' if peak > 0 else 'WARNING: silence — check mic')
"
```

Expected output (values will vary depending on ambient noise):

```
Samples: 144000, Peak: 0.0372, RMS: 0.003841
Audio capture working!
```

If you see `WARNING: silence`, the mic may not be the default device. Check `python -c "import sounddevice; print(sounddevice.query_devices())"` and adjust the `device=` parameter. The ReSpeaker typically shows as device 0 (6 in, 2 out) in sounddevice.

### 3. CLI check

```bash
biardtz --help
```

You should see the full list of command-line options (lat, lon, threshold, device, etc.). This confirms the package is installed and the entry point is registered.

### 4. Run the detector

Start biardtz to confirm the full pipeline initialises:

```bash
biardtz --db-path ~/test_detections.db -v
```

You should see log output indicating that audio capture and BirdNET inference have started. Press `Ctrl+C` to stop. If detections are logged, you can inspect them:

```bash
sqlite3 ~/test_detections.db "SELECT * FROM detections LIMIT 5;"
```

Clean up the test database when done:

```bash
rm -f ~/test_detections.db
```

If all four checks pass, the installation is verified and ready for production use.

## Step 10: Access the web dashboard

biardtz includes a browser-based dashboard for viewing detections from any device on the local network (phone, tablet, laptop). It starts automatically when you run `biardtz`.

### Default (integrated mode)

The web dashboard starts alongside the detection pipeline:

```bash
biardtz --location "Biarritz, France" --device 2
```

Open `http://<pi-ip>:8080/` in any browser on the same network. The dashboard is mobile-friendly.

### Standalone mode

To run the dashboard without the detection pipeline (read-only access to the database):

```bash
biardtz-web
```

This is useful for browsing historical detections without starting audio capture.

### CLI options

| Option | Default | Description |
|--------|---------|-------------|
| `--web/--no-web` | `--web` | Enable or disable the web dashboard |
| `--web-port` | 8080 | Port for the web dashboard |

### What you'll see

- **Summary cards** — today's detections, today's species, all-time species count
- **Recent detections** — bird name, confidence bar, compass direction, and photo
- **Species leaderboard** — ranked by detection count
- **Auto-refresh** — detections update every 5 seconds, stats every 30 seconds

Bird photos are fetched from Wikipedia/Wikidata and cached on the SSD. A fallback silhouette is shown when no photo is available.

## Step 11: Remote access with Tailscale

Tailscale lets you access the web dashboard from anywhere — not just your home network. It creates a secure VPN tunnel with no port forwarding or firewall changes needed.

### Install on the Pi

```bash
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up
```

The second command prints an authentication URL. Open it in a browser on any device to log in (Google, Microsoft, GitHub, etc.).

### Check your Tailscale IP

```bash
tailscale status
```

Note the IP (e.g. `100.x.x.x`) — this is your Pi's Tailscale address.

### Install on other devices

Install Tailscale on any device you want to use remotely:

- **Windows / Mac:** Download from [tailscale.com/download](https://tailscale.com/download)
- **iPhone / Android:** Install from the App Store or Google Play

Sign in with the same account on each device.

### Access the dashboard remotely

Once both devices are on Tailscale, open:

```
http://<tailscale-ip>:8080
```

This works from anywhere — home, work, or mobile data.

### Summary of access methods

| Location | URL |
|----------|-----|
| Home network | `http://kspi-002.local:8080` or `http://192.168.1.124:8080` |
| Anywhere (Tailscale) | `http://<tailscale-ip>:8080` |

Tailscale starts automatically at boot (`tailscaled.service` is enabled by default).

## Step 12: Run biardtz

### Basic usage

```bash
conda activate biardtz
biardtz
```

### With custom options

```bash
biardtz \
    --location "Biarritz, France" \
    --threshold 0.25 \
    --db-path /mnt/ssd/detections.db \
    --dashboard \
    -v
```

### All CLI options

| Option | Default | Description |
|--------|---------|-------------|
| `--location, -l` | `London` | Town/city name for species filtering (geocoded automatically) |
| `--threshold` | 0.25 | Minimum confidence (0.0-1.0) |
| `--db-path` | `/mnt/ssd/detections.db` | SQLite database path |
| `--device` | system default | Audio device index |
| `--birdnet-path` | `../BirdNET-Analyzer` | Path to BirdNET-Analyzer directory |
| `--array-bearing` | `0.0` | Compass bearing (degrees) the mic array faces |
| `--dashboard/--no-dashboard` | enabled | Rich live terminal dashboard |
| `--web/--no-web` | enabled | Web dashboard on local network |
| `--web-port` | 8080 | Port for the web dashboard |
| `-v` / `-vv` | warnings only | Verbosity: `-v` info, `-vv` debug |
| `--version` | | Print version and exit |

## Step 13: Run as a service (optional)

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
- Check `arecord -l` — is the ReSpeaker listed?
- Try specifying the device explicitly: `--device 1` (use the index from `sounddevice.query_devices()`)
- If the ReSpeaker doesn't appear in `lsusb`, try a different USB port

### "Channels count non available" or "invalid argument"
- The ReSpeaker requires 6 channels at 16000 Hz — these are fixed in hardware
- Ensure `Config` has `channels=6` and `sample_rate=16000`
- Check with `arecord -D hw:X,0 --dump-hw-params` (replace X with your card number)

### Database permission errors
- Check the mount: `mount | grep ssd`
- Check ownership: `ls -la /mnt/ssd/`
- Or use a local path: `--db-path ~/detections.db`

### High CPU / slow inference
- BirdNET inference is CPU-bound. On Pi 4B, expect ~1-3 seconds per 3-second chunk
- Reduce threads if overheating: edit `num_threads` in config (default: 4)
