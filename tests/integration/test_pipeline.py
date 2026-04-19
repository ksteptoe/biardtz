"""Integration test: mock audio -> detector -> real SQLite logger."""

import asyncio
from unittest.mock import patch

import numpy as np
import pytest

from biardtz.config import Config
from biardtz.detector import Detection, Detector
from biardtz.logger import DetectionLogger
from biardtz.main import _detection_worker


@pytest.mark.integration
class TestPipeline:
    def test_audio_to_db_pipeline(self, tmp_path):
        """Wire mock audio chunks through a real detector (mocked predict) and real logger to SQLite."""
        asyncio.run(self._run(tmp_path))

    @staticmethod
    async def _run(tmp_path):
        db_path = tmp_path / "pipeline.db"
        birdnet_dir = tmp_path / "BirdNET-Analyzer"
        birdnet_dir.mkdir()

        config = Config(
            db_path=db_path,
            birdnet_path=birdnet_dir,
            confidence_threshold=0.25,
            enable_dashboard=False,
            audio_clip_dir=tmp_path / "audio_clips",
        )

        # Set up detector with mocked _load_model and _predict_sync
        detections_to_return = [
            Detection("European Robin", "Erithacus rubecula", 0.92),
            Detection("Great Tit", "Parus major", 0.67),
        ]

        with patch.object(Detector, "_load_model"):
            detector = Detector(config)

        with patch.object(detector, "_predict_sync", return_value=detections_to_return):
            # Set up real logger
            det_logger = DetectionLogger(config)
            await det_logger.init_db()

            try:
                audio_queue = asyncio.Queue()
                # Put one audio chunk and then let the worker process it
                chunk = np.zeros(config.chunk_samples, dtype=np.float32)
                await audio_queue.put((chunk, None))

                # Run worker for just one iteration
                worker_task = asyncio.create_task(
                    _detection_worker(detector, audio_queue, det_logger, None, config)
                )
                # Give the worker time to process
                await asyncio.sleep(0.1)
                worker_task.cancel()
                try:
                    await worker_task
                except asyncio.CancelledError:
                    pass

                # Verify rows in DB
                cursor = await det_logger._db.execute("SELECT COUNT(*) FROM detections")
                row = await cursor.fetchone()
                assert row[0] == 2

                cursor = await det_logger._db.execute(
                    "SELECT common_name, sci_name, confidence FROM detections ORDER BY common_name"
                )
                rows = await cursor.fetchall()
                assert len(rows) == 2
                names = {r[0] for r in rows}
                assert "European Robin" in names
                assert "Great Tit" in names

                # Verify summary works
                summary = await det_logger.session_summary()
                assert "Detections: 2" in summary
                assert "Unique species: 2" in summary
            finally:
                await det_logger.close()
