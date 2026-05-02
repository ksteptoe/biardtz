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
        lg.log = AsyncMock(return_value=1)
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
        item = dashboard_q.get_nowait()
        assert item == (det, True)

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

    def test_doa_estimation_with_multichannel(self, detector, det_logger, tmp_path):
        """When multichannel data is provided, estimate_doa is called and bearing/direction set."""
        from biardtz.main import _detection_worker

        det = Detection("Robin", "Erithacus rubecula", 0.9)
        detector.predict = AsyncMock(return_value=[det])
        det_logger.get_audio_confidence = AsyncMock(return_value=None)

        config = Config(
            audio_clip_dir=tmp_path / "clips",
            sample_rate=48_000,
            array_bearing=0.0,
        )

        mono = np.zeros(100, dtype=np.float32)
        multichannel = np.zeros((100, 4), dtype=np.float32)

        audio_q = asyncio.Queue()
        audio_q.put_nowait((mono, multichannel))

        async def run():
            with patch("biardtz.main.estimate_doa", return_value=(45.0, "NE")) as mock_doa:
                task = asyncio.create_task(
                    _detection_worker(detector, audio_q, det_logger, None, config=config)
                )
                await asyncio.sleep(0.05)
                task.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await task
                return mock_doa

        mock_doa = asyncio.run(run())
        mock_doa.assert_called_once()
        # Verify the logged detection has bearing and direction set
        logged_det = det_logger.log.call_args[0][0]
        assert logged_det.bearing == 45.0
        assert logged_det.direction == "NE"

    def test_health_mark_detection_called(self, detector, det_logger):
        """health.mark_detection() is called after logging a detection."""
        from biardtz.main import _detection_worker

        det = Detection("Robin", "Erithacus rubecula", 0.9)
        detector.predict = AsyncMock(return_value=[det])

        health = MagicMock()
        audio_q = asyncio.Queue()
        audio_q.put_nowait(np.zeros(100, dtype=np.float32))

        async def run():
            task = asyncio.create_task(
                _detection_worker(detector, audio_q, det_logger, None, health=health)
            )
            await asyncio.sleep(0.05)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task

        asyncio.run(run())
        health.mark_detection.assert_called_once()
        det_logger.log.assert_called_once()

    def test_health_record_error_on_inference_failure(self, detector, det_logger):
        """health.record_error() is called when inference raises."""
        from biardtz.main import _detection_worker

        detector.predict = AsyncMock(side_effect=RuntimeError("model crash"))
        health = MagicMock()
        audio_q = asyncio.Queue()
        audio_q.put_nowait(np.zeros(100, dtype=np.float32))

        async def run():
            task = asyncio.create_task(
                _detection_worker(detector, audio_q, det_logger, None, health=health)
            )
            await asyncio.sleep(0.05)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task

        asyncio.run(run())
        health.record_error.assert_called_once_with("Inference error")


class TestDetectionWorkerWithVerifier:
    """Tests for _detection_worker with verifier integration."""

    @pytest.fixture
    def detector(self):
        d = MagicMock()
        d.predict = AsyncMock(return_value=[])
        return d

    @pytest.fixture
    def det_logger(self):
        lg = MagicMock()
        lg.log = AsyncMock(return_value=42)
        lg.get_audio_confidence = AsyncMock(return_value=None)
        lg.save_audio_clip = AsyncMock()
        return lg

    def test_worker_sends_true_when_no_verifier(self, detector, det_logger):
        """Without verifier, dashboard receives (det, True)."""
        from biardtz.main import _detection_worker

        det = Detection("Robin", "Erithacus rubecula", 0.9)
        detector.predict = AsyncMock(return_value=[det])
        audio_q = asyncio.Queue()
        dashboard_q = asyncio.Queue()
        audio_q.put_nowait(np.zeros(100, dtype=np.float32))

        async def run():
            task = asyncio.create_task(
                _detection_worker(detector, audio_q, det_logger, dashboard_q, verifier=None)
            )
            await asyncio.sleep(0.05)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task

        asyncio.run(run())
        item = dashboard_q.get_nowait()
        assert item == (det, True)

    def test_worker_sends_false_for_watchlist_first_detection(self, detector, det_logger):
        """Watchlist species on first detection: dashboard gets (det, False)."""
        from biardtz.main import _detection_worker

        det = Detection("Nightingale", "Luscinia megarhynchos", 0.8)
        detector.predict = AsyncMock(return_value=[det])
        audio_q = asyncio.Queue()
        dashboard_q = asyncio.Queue()
        audio_q.put_nowait(np.zeros(100, dtype=np.float32))

        verifier = MagicMock()
        verifier.needs_verification = MagicMock(return_value=True)
        verifier.submit = AsyncMock(return_value=False)

        async def run():
            task = asyncio.create_task(
                _detection_worker(detector, audio_q, det_logger, dashboard_q, verifier=verifier)
            )
            await asyncio.sleep(0.05)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task

        asyncio.run(run())
        item = dashboard_q.get_nowait()
        assert item == (det, False)

    def test_worker_logs_verified_false_for_watchlist(self, detector, det_logger):
        """Worker logs with verified=False when species needs verification."""
        from biardtz.main import _detection_worker

        det = Detection("Nightingale", "Luscinia megarhynchos", 0.8)
        detector.predict = AsyncMock(return_value=[det])
        audio_q = asyncio.Queue()
        audio_q.put_nowait(np.zeros(100, dtype=np.float32))

        verifier = MagicMock()
        verifier.needs_verification = MagicMock(return_value=True)
        verifier.submit = AsyncMock(return_value=False)

        async def run():
            task = asyncio.create_task(
                _detection_worker(detector, audio_q, det_logger, None, verifier=verifier)
            )
            await asyncio.sleep(0.05)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task

        asyncio.run(run())
        det_logger.log.assert_called_once()
        _, kwargs = det_logger.log.call_args
        assert kwargs["verified"] is False

    def test_worker_logs_verified_true_for_non_watchlist(self, detector, det_logger):
        """Worker logs with verified=True for non-watchlist species even with verifier."""
        from biardtz.main import _detection_worker

        det = Detection("Robin", "Erithacus rubecula", 0.9)
        detector.predict = AsyncMock(return_value=[det])
        audio_q = asyncio.Queue()
        audio_q.put_nowait(np.zeros(100, dtype=np.float32))

        verifier = MagicMock()
        verifier.needs_verification = MagicMock(return_value=False)

        async def run():
            task = asyncio.create_task(
                _detection_worker(detector, audio_q, det_logger, None, verifier=verifier)
            )
            await asyncio.sleep(0.05)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task

        asyncio.run(run())
        det_logger.log.assert_called_once()
        _, kwargs = det_logger.log.call_args
        assert kwargs["verified"] is True

    def test_worker_calls_verifier_submit_for_watchlist(self, detector, det_logger):
        """Worker calls verifier.submit with the detection and row_id."""
        from biardtz.main import _detection_worker

        det = Detection("Nightingale", "Luscinia megarhynchos", 0.8)
        detector.predict = AsyncMock(return_value=[det])
        det_logger.log = AsyncMock(return_value=99)
        audio_q = asyncio.Queue()
        audio_q.put_nowait(np.zeros(100, dtype=np.float32))

        verifier = MagicMock()
        verifier.needs_verification = MagicMock(return_value=True)
        verifier.submit = AsyncMock(return_value=True)

        async def run():
            task = asyncio.create_task(
                _detection_worker(detector, audio_q, det_logger, None, verifier=verifier)
            )
            await asyncio.sleep(0.05)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task

        asyncio.run(run())
        verifier.submit.assert_called_once_with(det, 99)

    def test_worker_sends_true_when_verifier_confirms(self, detector, det_logger):
        """When verifier.submit returns True, dashboard gets (det, True)."""
        from biardtz.main import _detection_worker

        det = Detection("Nightingale", "Luscinia megarhynchos", 0.8)
        detector.predict = AsyncMock(return_value=[det])
        audio_q = asyncio.Queue()
        dashboard_q = asyncio.Queue()
        audio_q.put_nowait(np.zeros(100, dtype=np.float32))

        verifier = MagicMock()
        verifier.needs_verification = MagicMock(return_value=True)
        verifier.submit = AsyncMock(return_value=True)

        async def run():
            task = asyncio.create_task(
                _detection_worker(detector, audio_q, det_logger, dashboard_q, verifier=verifier)
            )
            await asyncio.sleep(0.05)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task

        asyncio.run(run())
        item = dashboard_q.get_nowait()
        assert item == (det, True)


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
                patch("biardtz.main.Verifier") as mock_verifier_cls,
            ):
                mock_det = MagicMock()
                mock_det.predict = AsyncMock(return_value=[])
                mock_det_cls.return_value = mock_det

                mock_logger = MagicMock()
                mock_logger.init_db = AsyncMock()
                mock_logger.session_summary = AsyncMock(return_value="Summary")
                mock_logger.close = AsyncMock()
                mock_logger.log = AsyncMock(return_value=1)
                mock_logger.rare_species = AsyncMock(return_value=set())
                mock_log_cls.return_value = mock_logger

                mock_verifier = MagicMock()
                mock_verifier.refresh_auto_watchlist = AsyncMock()
                mock_verifier.expire_pending = AsyncMock(return_value=[])
                mock_verifier_cls.return_value = mock_verifier

                # Make audio_producer set stop_event after brief delay
                async def fake_audio(cfg, q, **kwargs):
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
                patch("biardtz.main.Verifier") as mock_verifier_cls,
            ):
                mock_det = MagicMock()
                mock_det.predict = AsyncMock(return_value=[])
                mock_det_cls.return_value = mock_det

                mock_logger = MagicMock()
                mock_logger.init_db = AsyncMock()
                mock_logger.session_summary = AsyncMock(return_value="Summary")
                mock_logger.close = AsyncMock()
                mock_logger.log = AsyncMock(return_value=1)
                mock_logger.rare_species = AsyncMock(return_value=set())
                mock_log_cls.return_value = mock_logger

                mock_verifier = MagicMock()
                mock_verifier.refresh_auto_watchlist = AsyncMock()
                mock_verifier.expire_pending = AsyncMock(return_value=[])
                mock_verifier_cls.return_value = mock_verifier

                mock_dash = MagicMock()
                mock_dash.run = AsyncMock(side_effect=lambda q: asyncio.sleep(60))
                mock_dash_cls.return_value = mock_dash

                async def fake_audio(cfg, q, **kwargs):
                    await asyncio.sleep(60)

                mock_audio.side_effect = fake_audio

                task = asyncio.create_task(run(config))
                await asyncio.sleep(0.1)
                task.cancel()
                await task  # run() catches CancelledError internally

                mock_dash_cls.assert_called_once()

        asyncio.run(run_test())
