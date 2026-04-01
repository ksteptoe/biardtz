"""End-to-end live pipeline: real audio -> real inference -> real SQLite."""
from __future__ import annotations

import asyncio

import numpy as np
import pytest
import sounddevice as sd

from biardtz.detector import Detector
from biardtz.logger import DetectionLogger

pytestmark = pytest.mark.live

SAMPLE_RATE = 16_000
CHUNK_SECONDS = 3
NUM_CHUNKS = 2


class TestLivePipeline:
    def test_audio_to_detection_to_db(self, live_config):
        """Record real audio, run inference, log to SQLite, verify DB."""

        async def _run():
            try:
                detector = Detector(live_config)
            except (ImportError, OSError) as exc:
                pytest.skip(f"Cannot load BirdNET model: {exc}")
            logger = DetectionLogger(live_config)
            await logger.init_db()

            try:
                for _ in range(NUM_CHUNKS):
                    audio = sd.rec(
                        frames=CHUNK_SECONDS * SAMPLE_RATE,
                        samplerate=SAMPLE_RATE,
                        channels=1,
                        dtype="float32",
                        device=live_config.device_index,
                    )
                    sd.wait()
                    chunk = audio[:, 0]

                    detections = await detector.predict(chunk)
                    for det in detections:
                        await logger.log(det)

                summary = await logger.session_summary()
            finally:
                await logger.close()

            return summary

        summary = asyncio.run(_run())

        # DB file should exist
        assert live_config.db_path.exists()
        # Summary should be a meaningful string
        assert "Session:" in summary
        assert "Detections:" in summary
        assert "Unique species:" in summary
