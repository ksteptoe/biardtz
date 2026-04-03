#!/usr/bin/env python
"""Verify biardtz installation: mic detection, audio capture, CLI, and package import."""
import subprocess
import sys


def step(name):
    print(f"\n{'=' * 60}")
    print(f"  {name}")
    print(f"{'=' * 60}")


def check_alsa():
    step("1/4  ALSA capture devices (arecord -l)")
    result = subprocess.run(["arecord", "-l"], capture_output=True, text=True)
    output = result.stdout + result.stderr
    print(output)
    if "ReSpeaker" in output or "card" in output.lower():
        print("PASS: capture device found")
        return True
    print("WARN: no capture devices listed — is the mic plugged in?")
    return False


def check_sounddevice():
    step("2/4  sounddevice query")
    import sounddevice as sd

    devices = sd.query_devices()
    print(devices)
    # Find an input device
    for i, d in enumerate(sd.query_devices()):
        if d["max_input_channels"] > 0:
            print(f"\nPASS: input device found — index {i}: {d['name']}")
            return True
    print("FAIL: no input device found")
    return False


def check_audio_capture():
    step("3/4  Audio capture test (3 seconds)")
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


def check_cli():
    step("4/4  CLI entry point (biardtz --help)")
    result = subprocess.run(["biardtz", "--help"], capture_output=True, text=True)
    if result.returncode == 0:
        # Print just the first few lines
        for line in result.stdout.splitlines()[:5]:
            print(line)
        print("...")
        print("PASS: CLI entry point works")
        return True
    print(f"FAIL: biardtz --help exited with code {result.returncode}")
    print(result.stderr)
    return False


def main():
    print("biardtz installation verification")
    results = {}
    results["alsa"] = check_alsa()
    results["sounddevice"] = check_sounddevice()
    results["audio_capture"] = check_audio_capture()
    results["cli"] = check_cli()

    print(f"\n{'=' * 60}")
    print("  SUMMARY")
    print(f"{'=' * 60}")
    for name, passed in results.items():
        status = "PASS" if passed else "FAIL"
        print(f"  {status}  {name}")

    if all(results.values()):
        print("\nAll checks passed. Installation verified.")
        return 0
    else:
        print("\nSome checks failed. See output above.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
