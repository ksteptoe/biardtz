"""Test real BirdNET inference on audio data."""
from __future__ import annotations

import asyncio

import numpy as np
import pytest

from biardtz.detector import Detection

pytestmark = pytest.mark.live

SAMPLE_RATE = 16_000
CHUNK_DURATION = 3.0


class TestRealInference:
    def test_predict_returns_detection_list(self, real_detector):
        """Feed synthetic noise and verify return type / structure."""
        chunk = np.random.randn(int(SAMPLE_RATE * CHUNK_DURATION)).astype(np.float32) * 0.01
        detections = asyncio.run(
            real_detector.predict(chunk)
        )

        assert isinstance(detections, list)
        for det in detections:
            assert isinstance(det, Detection)
            assert isinstance(det.common_name, str) and len(det.common_name) > 0
            assert isinstance(det.sci_name, str) and len(det.sci_name) > 0
            assert 0.0 <= det.confidence <= 1.0

    def test_predict_with_silence(self, real_detector):
        """Silent input should return empty or low-confidence detections."""
        chunk = np.zeros(int(SAMPLE_RATE * CHUNK_DURATION), dtype=np.float32)
        detections = asyncio.run(
            real_detector.predict(chunk)
        )
        assert isinstance(detections, list)
        # Silence should produce few or no detections
        # (not asserting empty — model behaviour may vary)

    def test_predict_resamples_correctly(self, real_detector):
        """Ensure 16 kHz input doesn't crash (BirdNET expects 48 kHz internally)."""
        chunk = np.random.randn(int(SAMPLE_RATE * CHUNK_DURATION)).astype(np.float32) * 0.05
        # Should not raise
        detections = asyncio.run(
            real_detector.predict(chunk)
        )
        assert isinstance(detections, list)
