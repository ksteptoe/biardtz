"""Tests for biardtz.main — the async orchestrator."""

import asyncio
import wave
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pytest

from biardtz.config import Config
from biardtz.detector import Detection


class TestSpeciesSlug:
    """Tests for _species_slug."""

    def test_multi_word(self):
        from biardtz.main import _species_slug

        assert _species_slug("Eurasian Blue Tit") == "eurasian_blue_tit"

    def test_single_word(self):
        from biardtz.main import _species_slug

        assert _species_slug("Robin") == "robin"

    def test_extra_whitespace(self):
        from biardtz.main import _species_slug

        assert _species_slug("  Great  Spotted  Woodpecker  ") == "great_spotted_woodpecker"


class TestSaveAudioClip:
    """Tests for _save_audio_clip — saves float32 array as 16-bit PCM WAV."""

    def test_creates_wav_file(self, tmp_path):
        from biardtz.main import _save_audio_clip

        chunk = np.zeros(16000, dtype=np.float32)
        filename = "test_bird.wav"
        result = _save_audio_clip(chunk, tmp_path, filename)
        assert (tmp_path / filename).exists()
        assert result == filename

    def test_wav_properties(self, tmp_path):
        from biardtz.main import _save_audio_clip

        # 1 second of silence at 16kHz
        chunk = np.zeros(16000, dtype=np.float32)
        filename = "test_bird.wav"
        _save_audio_clip(chunk, tmp_path, filename)

        with wave.open(str(tmp_path / filename), "rb") as wf:
            assert wf.getnchannels() == 1
            assert wf.getframerate() == 16000
            assert wf.getsampwidth() == 2  # 16-bit
            assert wf.getnframes() == 16000

    def test_signal_values_converted(self, tmp_path):
        from biardtz.main import _save_audio_clip

        # A simple sine-like signal
        chunk = np.array([0.0, 0.5, 1.0, -1.0], dtype=np.float32)
        filename = "signal.wav"
        _save_audio_clip(chunk, tmp_path, filename)

        with wave.open(str(tmp_path / filename), "rb") as wf:
            assert wf.getnframes() == 4


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
        lg.get_audio_confidence = AsyncMock(return_value=None)
        lg.save_audio_clip = AsyncMock()
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
        det_logger.get_audio_confidence = AsyncMock(return_value=None)
        audio_q = asyncio.Queue()
        audio_q.put_nowait(np.zeros(100, dtype=np.float32))

        config = Config(audio_clip_dir=Path("/tmp/test_clips"))

        async def run():
            task = asyncio.create_task(
                _detection_worker(detector, audio_q, det_logger, None, config=config)
            )
            await asyncio.sleep(0.05)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task

        asyncio.run(run())
        det_logger.log.assert_called_once()
        # Audio confidence should be checked for best-clip logic
        det_logger.get_audio_confidence.assert_called()

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
