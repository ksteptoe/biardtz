"""Root conftest — shared fixtures and skip logic for live/system tests."""
from __future__ import annotations

from pathlib import Path

import pytest

_BIRDNET_PATH = Path(__file__).resolve().parents[2] / "BirdNET-Analyzer"


def _find_capture_device() -> int | None:
    """Return the device index of the first capture device, or None."""
    try:
        import sounddevice as sd

        for i, dev in enumerate(sd.query_devices()):
            if dev["max_input_channels"] > 0:
                return i
    except Exception:
        pass
    return None


_HAS_AUDIO_HW = _find_capture_device() is not None
_HAS_BIRDNET = _BIRDNET_PATH.exists()


@pytest.fixture
def live_config(tmp_path):
    """Config pointing at real hardware and BirdNET, with a tmp_path DB."""
    from biardtz.config import Config

    device_index = _find_capture_device()
    return Config(
        device_index=device_index,
        db_path=tmp_path / "test_live.db",
    )


def pytest_collection_modifyitems(config, items):
    """Auto-skip @live tests when hardware is missing."""
    skip_audio = pytest.mark.skip(reason="No audio capture device found")
    skip_birdnet = pytest.mark.skip(reason="BirdNET-Analyzer not found")

    for item in items:
        if "live" not in item.keywords:
            continue

        # Check test path to decide which hardware is needed
        path = str(item.fspath)
        needs_audio = "test_audio" in path or "test_pipeline" in path
        needs_birdnet = "test_detector" in path or "test_pipeline" in path

        if needs_audio and not _HAS_AUDIO_HW:
            item.add_marker(skip_audio)
        if needs_birdnet and not _HAS_BIRDNET:
            item.add_marker(skip_birdnet)
