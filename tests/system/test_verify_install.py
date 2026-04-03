"""Progressive installation verification as pytest tests.

Mirrors the check groups in scripts/verify_install.py so that each
verification stage can be exercised via ``make test-live`` or
``make test-full`` on real Pi hardware.
"""
from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

pytestmark = pytest.mark.live

BIRDNET_PATH = Path(__file__).resolve().parents[3] / "BirdNET-Analyzer"


def _has_capture_device() -> bool:
    try:
        import sounddevice as sd

        return any(d["max_input_channels"] > 0 for d in sd.query_devices())
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Group 1: Environment
# ---------------------------------------------------------------------------


class TestVerifyEnv:
    """Python environment checks."""

    def test_python_version_312_or_higher(self):
        assert sys.version_info >= (3, 12), (
            f"Python 3.12+ required, got {sys.version_info.major}.{sys.version_info.minor}"
        )

    def test_running_in_virtualenv(self):
        assert sys.prefix != sys.base_prefix, (
            "Not running inside a virtualenv -- activate .venv first"
        )

    def test_import_click(self):
        import click  # noqa: F401

    def test_import_sounddevice(self):
        import sounddevice  # noqa: F401

    def test_import_numpy(self):
        import numpy  # noqa: F401

    def test_import_aiosqlite(self):
        import aiosqlite  # noqa: F401

    def test_import_rich(self):
        import rich  # noqa: F401

    def test_import_keras(self):
        import keras  # noqa: F401

    def test_import_biardtz(self):
        import biardtz

        assert hasattr(biardtz, "__version__")


# ---------------------------------------------------------------------------
# Group 2: Hardware (requires microphone)
# ---------------------------------------------------------------------------


class TestVerifyHardware:
    """Microphone detection -- requires audio hardware."""

    def test_alsa_capture_device_found(self):
        result = subprocess.run(
            ["arecord", "-l"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        output = result.stdout + result.stderr
        assert "card" in output.lower(), (
            "No ALSA capture device found -- is the mic plugged in?"
        )

    def test_sounddevice_input_device_found(self):
        if not _has_capture_device():
            pytest.skip("No audio capture device found")

        import sounddevice as sd

        input_devices = [
            d for d in sd.query_devices() if d["max_input_channels"] > 0
        ]
        assert len(input_devices) > 0, "No input device reported by sounddevice"


# ---------------------------------------------------------------------------
# Group 3: Audio capture (requires hardware)
# ---------------------------------------------------------------------------


class TestVerifyAudio:
    """Live audio capture -- requires a working microphone."""

    def test_audio_capture_3s_not_silent(self):
        if not _has_capture_device():
            pytest.skip("No audio capture device found")

        import numpy as np
        import sounddevice as sd

        dev_info = sd.query_devices(0)
        samplerate = int(dev_info["default_samplerate"])
        duration = 3

        audio = sd.rec(
            int(duration * samplerate),
            samplerate=samplerate,
            channels=1,
            dtype="float32",
            device=0,
        )
        sd.wait()

        peak = float(np.max(np.abs(audio)))
        assert peak > 0, (
            f"Silence detected (peak={peak}) -- check mic connection"
        )


# ---------------------------------------------------------------------------
# Group 4: BirdNET model
# ---------------------------------------------------------------------------


class TestVerifyModel:
    """BirdNET-Analyzer model loading."""

    def test_birdnet_directory_exists(self):
        if not BIRDNET_PATH.exists():
            pytest.skip(
                f"BirdNET-Analyzer not found at {BIRDNET_PATH} -- "
                "clone it: git clone https://github.com/kahst/BirdNET-Analyzer.git"
            )
        assert BIRDNET_PATH.is_dir()

    def test_birdnet_imports(self):
        if not BIRDNET_PATH.exists():
            pytest.skip("BirdNET-Analyzer directory not found")

        if str(BIRDNET_PATH) not in sys.path:
            sys.path.insert(0, str(BIRDNET_PATH))

        from birdnet_analyzer import config as birdnet_cfg  # noqa: F401
        from birdnet_analyzer import model as birdnet_model  # noqa: F401
        from birdnet_analyzer.utils import read_lines  # noqa: F401

    def test_birdnet_model_loads_with_labels(self):
        if not BIRDNET_PATH.exists():
            pytest.skip("BirdNET-Analyzer directory not found")

        if str(BIRDNET_PATH) not in sys.path:
            sys.path.insert(0, str(BIRDNET_PATH))

        from birdnet_analyzer import config as birdnet_cfg
        from birdnet_analyzer import model as birdnet_model
        from birdnet_analyzer.utils import read_lines

        birdnet_cfg.MODEL_PATH = birdnet_cfg.BIRDNET_MODEL_PATH
        birdnet_cfg.LABELS_FILE = birdnet_cfg.BIRDNET_LABELS_FILE
        birdnet_cfg.SAMPLE_RATE = birdnet_cfg.BIRDNET_SAMPLE_RATE
        birdnet_cfg.SIG_LENGTH = birdnet_cfg.BIRDNET_SIG_LENGTH
        birdnet_cfg.LABELS = read_lines(birdnet_cfg.LABELS_FILE)
        birdnet_cfg.TFLITE_THREADS = 4

        assert len(birdnet_cfg.LABELS) > 0, "No labels loaded"

        birdnet_model.load_model()


# ---------------------------------------------------------------------------
# Group 5: End-to-end
# ---------------------------------------------------------------------------


class TestVerifyE2E:
    """Full pipeline end-to-end -- requires hardware and model."""

    def test_biardtz_runs_and_creates_db(self, tmp_path):
        if not _has_capture_device():
            pytest.skip("No audio capture device found")
        if not BIRDNET_PATH.exists():
            pytest.skip("BirdNET-Analyzer directory not found")

        db_path = tmp_path / "biardtz_pytest_verify.db"

        cmd = [
            sys.executable, "-m", "biardtz",
            "--db-path", str(db_path),
            "--no-dashboard",
            "-v",
        ]
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )

        time.sleep(10)

        proc.send_signal(signal.SIGTERM)
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()

        exit_code = proc.returncode
        # SIGTERM yields -15 on Linux, which counts as a clean shutdown
        assert exit_code in (0, -15), (
            f"Pipeline exited with unexpected code {exit_code}"
        )
        assert db_path.exists(), (
            f"Database was not created at {db_path}"
        )

        # Clean up is handled by tmp_path
        size = os.path.getsize(db_path)
        assert size > 0, "Database file is empty"
