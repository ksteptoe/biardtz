"""Tests for biardtz.main — the async orchestrator."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pytest

from biardtz.config import Config
from biardtz.detector import Detection


class TestDetectionWorker:
    """Tests for _detection_worker."""

    @pytest.fixture
    def detector(self):
        d = MagicMock()
        d.predict = AsyncMock(return_value=[])
        return d

    @pytest.fixture
    def det_logger(self):
        lg = MagicMock()
        lg.log = AsyncMock()
        return lg

    def test_processes_chunk_no_detections(self, detector, det_logger):
        from biardtz.main import _detection_worker

        audio_q = asyncio.Queue()
        audio_q.put_nowait(np.zeros(100, dtype=np.float32))

        async def run():
            task = asyncio.create_task(_detection_worker(detector, audio_q, det_logger, None))
            await asyncio.sleep(0.05)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task

        asyncio.run(run())
        detector.predict.assert_called_once()
        det_logger.log.assert_not_called()

    def test_processes_chunk_with_detections(self, detector, det_logger):
        from biardtz.main import _detection_worker

        det = Detection("Robin", "Erithacus rubecula", 0.9)
        detector.predict = AsyncMock(return_value=[det])
        audio_q = asyncio.Queue()
        audio_q.put_nowait(np.zeros(100, dtype=np.float32))

        async def run():
            task = asyncio.create_task(_detection_worker(detector, audio_q, det_logger, None))
            await asyncio.sleep(0.05)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task

        asyncio.run(run())
        det_logger.log.assert_called_once_with(det)

    def test_puts_detection_on_dashboard_queue(self, detector, det_logger):
        from biardtz.main import _detection_worker

        det = Detection("Robin", "Erithacus rubecula", 0.9)
        detector.predict = AsyncMock(return_value=[det])
        audio_q = asyncio.Queue()
        dashboard_q = asyncio.Queue()
        audio_q.put_nowait(np.zeros(100, dtype=np.float32))

        async def run():
            task = asyncio.create_task(_detection_worker(detector, audio_q, det_logger, dashboard_q))
            await asyncio.sleep(0.05)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task

        asyncio.run(run())
        assert not dashboard_q.empty()
        assert dashboard_q.get_nowait() == det

    def test_inference_error_continues(self, detector, det_logger):
        from biardtz.main import _detection_worker

        detector.predict = AsyncMock(side_effect=[RuntimeError("boom"), []])
        audio_q = asyncio.Queue()
        audio_q.put_nowait(np.zeros(100, dtype=np.float32))
        audio_q.put_nowait(np.zeros(100, dtype=np.float32))

        async def run():
            task = asyncio.create_task(_detection_worker(detector, audio_q, det_logger, None))
            await asyncio.sleep(0.05)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task

        asyncio.run(run())
        assert detector.predict.call_count == 2
        det_logger.log.assert_not_called()


class TestRun:
    """Tests for the run() orchestrator."""

    def test_run_starts_and_shuts_down(self, tmp_path):
        from biardtz.main import run

        config = Config(
            db_path=tmp_path / "test.db",
            birdnet_path=tmp_path / "BirdNET",
            enable_dashboard=False,
            enable_web=False,
        )

        async def run_test():
            with (
                patch("biardtz.main.Detector") as mock_det_cls,
                patch("biardtz.main.DetectionLogger") as mock_log_cls,
                patch("biardtz.main.audio_producer", new_callable=AsyncMock) as mock_audio,
            ):
                mock_det = MagicMock()
                mock_det.predict = AsyncMock(return_value=[])
                mock_det_cls.return_value = mock_det

                mock_logger = MagicMock()
                mock_logger.init_db = AsyncMock()
                mock_logger.session_summary = AsyncMock(return_value="Summary")
                mock_logger.close = AsyncMock()
                mock_logger.log = AsyncMock()
                mock_log_cls.return_value = mock_logger

                # Make audio_producer set stop_event after brief delay
                async def fake_audio(cfg, q):
                    await asyncio.sleep(60)

                mock_audio.side_effect = fake_audio

                task = asyncio.create_task(run(config))
                await asyncio.sleep(0.1)
                task.cancel()
                await task  # run() catches CancelledError internally

                mock_log_cls.assert_called_once_with(config)
                mock_logger.init_db.assert_called_once()

        asyncio.run(run_test())

    def test_run_with_dashboard(self, tmp_path):
        from biardtz.main import run

        config = Config(
            db_path=tmp_path / "test.db",
            birdnet_path=tmp_path / "BirdNET",
            enable_dashboard=True,
            enable_web=False,
        )

        async def run_test():
            with (
                patch("biardtz.main.Detector") as mock_det_cls,
                patch("biardtz.main.DetectionLogger") as mock_log_cls,
                patch("biardtz.main.audio_producer", new_callable=AsyncMock) as mock_audio,
                patch("biardtz.main.Dashboard") as mock_dash_cls,
            ):
                mock_det = MagicMock()
                mock_det.predict = AsyncMock(return_value=[])
                mock_det_cls.return_value = mock_det

                mock_logger = MagicMock()
                mock_logger.init_db = AsyncMock()
                mock_logger.session_summary = AsyncMock(return_value="Summary")
                mock_logger.close = AsyncMock()
                mock_logger.log = AsyncMock()
                mock_log_cls.return_value = mock_logger

                mock_dash = MagicMock()
                mock_dash.run = AsyncMock(side_effect=lambda q: asyncio.sleep(60))
                mock_dash_cls.return_value = mock_dash

                async def fake_audio(cfg, q):
                    await asyncio.sleep(60)

                mock_audio.side_effect = fake_audio

                task = asyncio.create_task(run(config))
                await asyncio.sleep(0.1)
                task.cancel()
                await task  # run() catches CancelledError internally

                mock_dash_cls.assert_called_once()

        asyncio.run(run_test())
