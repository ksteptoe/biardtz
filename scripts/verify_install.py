#!/usr/bin/env python
"""Progressive installation verification for biardtz.

Usage:
    python scripts/verify_install.py [group]

Groups: env, hardware, audio, model, e2e, all (default)
"""
import argparse
import os
import signal
import subprocess
import sys
import time


def step(name):
    print(f"\n{'=' * 60}")
    print(f"  {name}")
    print(f"{'=' * 60}")


# ---------------------------------------------------------------------------
# Group: env
# ---------------------------------------------------------------------------

def check_env():
    step("Python environment")
    ok = True

    print(f"  Python:     {sys.executable}")
    print(f"  Version:    {sys.version.split()[0]}")

    if sys.version_info < (3, 12):
        print("  FAIL: Python 3.12+ required")
        ok = False
    else:
        print("  PASS: Python >= 3.12")

    in_venv = sys.prefix != sys.base_prefix
    print(f"  Virtualenv: {'Yes' if in_venv else 'No'}")
    if not in_venv:
        print("  WARN: not in a virtualenv — run 'source .venv/bin/activate'")

    packages = ["click", "sounddevice", "numpy", "aiosqlite", "rich"]
    for pkg in packages:
        try:
            __import__(pkg)
            print(f"  import {pkg}: PASS")
        except ImportError:
            print(f"  import {pkg}: FAIL")
            ok = False

    print("  Importing keras (may take a moment)...")
    try:
        __import__("keras")
        print("  import keras: PASS")
    except ImportError:
        print("  import keras: FAIL — install tensorflow/keras in the venv")
        ok = False

    try:
        import biardtz
        print(f"  import biardtz: PASS (v{biardtz.__version__})")
    except ImportError:
        print("  import biardtz: FAIL — run 'pip install -e .[dev]'")
        ok = False

    return ok


# ---------------------------------------------------------------------------
# Group: hardware
# ---------------------------------------------------------------------------

def check_alsa():
    step("ALSA capture devices (arecord -l)")
    result = subprocess.run(["arecord", "-l"], capture_output=True, text=True)
    output = result.stdout + result.stderr
    print(output)
    if "ReSpeaker" in output or "card" in output.lower():
        print("PASS: capture device found")
        return True
    print("WARN: no capture devices listed — is the mic plugged in?")
    return False


def check_sounddevice():
    step("sounddevice query")
    import sounddevice as sd

    devices = sd.query_devices()
    print(devices)
    for i, d in enumerate(sd.query_devices()):
        if d["max_input_channels"] > 0:
            print(f"\nPASS: input device found — index {i}: {d['name']}")
            return True
    print("FAIL: no input device found")
    return False


# ---------------------------------------------------------------------------
# Group: audio
# ---------------------------------------------------------------------------

def check_audio_capture():
    step("Audio capture test (3 seconds)")
    import numpy as np
    import sounddevice as sd

    dev_info = sd.query_devices(0)
    samplerate = int(dev_info["default_samplerate"])
    duration = 3
    print(f"Recording {duration}s at {samplerate} Hz ...")
    audio = sd.rec(
        int(duration * samplerate),
        samplerate=samplerate,
        channels=1,
        dtype="float32",
        device=0,
    )
    sd.wait()
    peak = float(np.max(np.abs(audio)))
    rms = float(np.sqrt(np.mean(audio**2)))
    print(f"Samples: {len(audio)}  Peak: {peak:.4f}  RMS: {rms:.6f}")
    if peak > 0:
        print("PASS: audio capture working")
        return True
    print("FAIL: silence detected — check mic connection")
    return False


# ---------------------------------------------------------------------------
# Group: model
# ---------------------------------------------------------------------------

def check_model():
    step("BirdNET model")
    from biardtz.config import Config

    cfg = Config()
    birdnet = cfg.birdnet_path
    print(f"  BirdNET path: {birdnet}")

    if not birdnet.exists():
        print("  FAIL: directory not found")
        print("  Clone it: git clone https://github.com/kahst/BirdNET-Analyzer.git")
        return False
    print("  PASS: directory exists")

    if str(birdnet) not in sys.path:
        sys.path.insert(0, str(birdnet))

    try:
        from birdnet_analyzer import config as birdnet_cfg
        from birdnet_analyzer import model as birdnet_model
        from birdnet_analyzer.utils import read_lines
        print("  PASS: birdnet_analyzer imports OK")
    except ImportError as exc:
        print(f"  FAIL: import error — {exc}")
        return False

    try:
        birdnet_cfg.MODEL_PATH = birdnet_cfg.BIRDNET_MODEL_PATH
        birdnet_cfg.LABELS_FILE = birdnet_cfg.BIRDNET_LABELS_FILE
        birdnet_cfg.SAMPLE_RATE = birdnet_cfg.BIRDNET_SAMPLE_RATE
        birdnet_cfg.SIG_LENGTH = birdnet_cfg.BIRDNET_SIG_LENGTH
        birdnet_cfg.LABELS = read_lines(birdnet_cfg.LABELS_FILE)
        birdnet_cfg.TFLITE_THREADS = cfg.num_threads
        print(f"  Labels loaded: {len(birdnet_cfg.LABELS)}")
    except Exception as exc:
        print(f"  FAIL: config setup — {exc}")
        return False

    print("  Loading model (may take 10-15s on Pi)...")
    try:
        birdnet_model.load_model()
        print("  PASS: model loaded")
    except Exception as exc:
        print(f"  FAIL: model load — {exc}")
        return False

    return True


# ---------------------------------------------------------------------------
# Group: cli
# ---------------------------------------------------------------------------

def check_cli():
    step("CLI entry point (biardtz --help)")
    result = subprocess.run(["biardtz", "--help"], capture_output=True, text=True)
    if result.returncode == 0:
        for line in result.stdout.splitlines()[:5]:
            print(line)
        print("...")
        print("PASS: CLI entry point works")
        return True
    print(f"FAIL: biardtz --help exited with code {result.returncode}")
    print(result.stderr)
    return False


# ---------------------------------------------------------------------------
# Group: e2e
# ---------------------------------------------------------------------------

def check_e2e():
    step("End-to-end pipeline (10s)")
    db_path = "/tmp/biardtz_verify.db"

    # Clean up any previous run
    if os.path.exists(db_path):
        os.remove(db_path)

    cmd = [sys.executable, "-m", "biardtz", "--db-path", db_path, "--no-dashboard", "-v"]
    print(f"  Starting: {' '.join(cmd)}")
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    print(f"  PID: {proc.pid}")
    print("  Running for 10 seconds...")
    time.sleep(10)

    print("  Sending SIGTERM...")
    proc.send_signal(signal.SIGTERM)
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        print("  WARN: process did not exit, sending SIGKILL")
        proc.kill()
        proc.wait()

    exit_code = proc.returncode
    # SIGTERM gives -15 on Linux, which is a clean shutdown
    clean_exit = exit_code in (0, -15)
    print(f"  Exit code: {exit_code} ({'clean' if clean_exit else 'ERROR'})")

    if proc.stdout:
        output = proc.stdout.read()
        if output.strip():
            print("  --- output (last 10 lines) ---")
            for line in output.strip().splitlines()[-10:]:
                print(f"  {line}")
            print("  ---")

    db_exists = os.path.exists(db_path)
    if db_exists:
        size = os.path.getsize(db_path)
        print(f"  Database: {db_path} ({size} bytes)")
        os.remove(db_path)
        print("  Cleaned up temp database")
    else:
        print(f"  WARN: database not created at {db_path}")

    if clean_exit and db_exists:
        print("PASS: end-to-end pipeline works")
        return True
    if clean_exit and not db_exists:
        print("WARN: pipeline ran but no database — check db_path permissions")
        return False
    print("FAIL: pipeline did not exit cleanly")
    return False


# ---------------------------------------------------------------------------
# Group dispatch
# ---------------------------------------------------------------------------

GROUPS = {
    "env": [("env", check_env)],
    "hardware": [("alsa", check_alsa), ("sounddevice", check_sounddevice)],
    "audio": [("audio_capture", check_audio_capture)],
    "model": [("model", check_model)],
    "cli": [("cli", check_cli)],
    "e2e": [("e2e", check_e2e)],
    "all": None,  # special: runs everything
}

ALL_ORDER = ["env", "hardware", "audio", "model", "cli", "e2e"]


def run_checks(group):
    if group == "all":
        checks = []
        for g in ALL_ORDER:
            checks.extend(GROUPS[g])
    else:
        checks = GROUPS[group]

    results = {}
    for name, fn in checks:
        results[name] = fn()

    print(f"\n{'=' * 60}")
    print("  SUMMARY")
    print(f"{'=' * 60}")
    for name, passed in results.items():
        status = "PASS" if passed else "FAIL"
        print(f"  {status}  {name}")

    if all(results.values()):
        print("\nAll checks passed.")
        return 0
    else:
        print("\nSome checks failed. See output above.")
        return 1


def main():
    parser = argparse.ArgumentParser(description="biardtz installation verification")
    parser.add_argument(
        "group",
        nargs="?",
        default="all",
        choices=list(GROUPS.keys()),
        help="Check group to run (default: all)",
    )
    args = parser.parse_args()
    print(f"biardtz verification — group: {args.group}")
    return run_checks(args.group)


if __name__ == "__main__":
    sys.exit(main())
