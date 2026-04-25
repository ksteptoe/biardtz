"""Tests for biardtz.audio_capture."""

import asyncio
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pytest

from biardtz.config import AudioConfig, Config, PipelineConfig


class TestAudioProducer:
    def test_puts_correct_size_chunks_on_queue(self):
        config = Config(bird=PipelineConfig(audio=AudioConfig(sample_rate=48_000, chunk_duration=3.0)))
        chunk_samples = config.chunk_samples  # 144000

        mock_stream = MagicMock()
        mock_stream.start = MagicMock()
        mock_stream.stop = MagicMock()
        mock_stream.close = MagicMock()

        # Simulate audio data arriving as (mono, multi) tuples
        audio_data = np.random.randn(chunk_samples).astype(np.float32)
        half = chunk_samples // 2

        def fake_input_stream(**kwargs):
            # Capture the callback so we can feed it data
            fake_input_stream.callback = kwargs.get("callback")
            return mock_stream

        with patch.dict(sys.modules, {"sounddevice": MagicMock()}):
            import biardtz.audio_capture as ac_module

            # Re-patch sd.InputStream
            with patch.object(ac_module.sd, "InputStream", side_effect=fake_input_stream):

                async def run_test():
                    out_queue = asyncio.Queue()

                    # We need to feed data through the thread_q inside audio_producer.
                    # The simplest approach: run audio_producer in a task and feed its internal queue.
                    import queue as stdlib_queue

                    test_queue = stdlib_queue.Queue(maxsize=16)
                    # Put audio data as (mono, multi) tuples, then None sentinel
                    test_queue.put((audio_data[:half], None))
                    test_queue.put((audio_data[half:], None))
                    test_queue.put(None)

                    with patch.object(ac_module.queue, "Queue", return_value=test_queue):
                        task = asyncio.create_task(ac_module.audio_producer(config, out_queue))
                        # Wait for the task to finish (it'll exit on None sentinel)
                        await asyncio.wait_for(task, timeout=5.0)

                    # Should have exactly one chunk (as a tuple)
                    assert not out_queue.empty()
                    mono, multi = await out_queue.get()
                    assert len(mono) == chunk_samples
                    assert out_queue.empty()

                asyncio.run(run_test())

    def test_stream_started_and_stopped(self):
        config = Config()
        mock_stream = MagicMock()

        with patch.dict(sys.modules, {"sounddevice": MagicMock()}):
            import biardtz.audio_capture as ac_module

            def fake_input_stream(**kwargs):
                return mock_stream

            with patch.object(ac_module.sd, "InputStream", side_effect=fake_input_stream):
                import queue as stdlib_queue

                test_queue = stdlib_queue.Queue(maxsize=16)
                test_queue.put(None)  # immediate stop

                with patch.object(ac_module.queue, "Queue", return_value=test_queue):

                    async def run_test():
                        out_queue = asyncio.Queue()
                        await ac_module.audio_producer(config, out_queue)

                    asyncio.run(run_test())

            mock_stream.start.assert_called_once()
            mock_stream.stop.assert_called_once()
            mock_stream.close.assert_called_once()

    def test_callback_warns_on_status(self):
        """Cover lines 22-24: callback logs warning when status is set."""
        config = Config(bird=PipelineConfig(audio=AudioConfig(sample_rate=48_000, chunk_duration=3.0)))
        mock_stream = MagicMock()
        captured_callback = None

        def fake_input_stream(**kwargs):
            nonlocal captured_callback
            captured_callback = kwargs.get("callback")
            return mock_stream

        with patch.dict(sys.modules, {"sounddevice": MagicMock()}):
            import biardtz.audio_capture as ac_module

            with patch.object(ac_module.sd, "InputStream", side_effect=fake_input_stream):
                import queue as stdlib_queue

                test_queue = stdlib_queue.Queue(maxsize=16)
                test_queue.put(None)

                with patch.object(ac_module.queue, "Queue", return_value=test_queue):

                    async def run_test():
                        out_queue = asyncio.Queue()
                        await ac_module.audio_producer(config, out_queue)

                    asyncio.run(run_test())

            # Now invoke the captured callback with a status flag
            assert captured_callback is not None
            indata = np.random.randn(4096, 1).astype(np.float32)
            with patch.object(ac_module._logger, "warning") as mock_warn:
                captured_callback(indata, 4096, None, "input overflow")
                mock_warn.assert_called_once()

    def test_callback_handles_multidim_input(self):
        """Cover line 24: callback extracts column 0 from multi-dim input."""
        config = Config(bird=PipelineConfig(audio=AudioConfig(sample_rate=48_000, chunk_duration=3.0)))
        mock_stream = MagicMock()
        captured_callback = None

        def fake_input_stream(**kwargs):
            nonlocal captured_callback
            captured_callback = kwargs.get("callback")
            return mock_stream

        with patch.dict(sys.modules, {"sounddevice": MagicMock()}):
            import biardtz.audio_capture as ac_module

            with patch.object(ac_module.sd, "InputStream", side_effect=fake_input_stream):
                import queue as stdlib_queue

                real_queue = stdlib_queue.Queue(maxsize=16)
                real_queue.put(None)

                with patch.object(ac_module.queue, "Queue", return_value=real_queue):

                    async def run_test():
                        out_queue = asyncio.Queue()
                        await ac_module.audio_producer(config, out_queue)

                    asyncio.run(run_test())

            # Test with 2D input (multi-channel)
            assert captured_callback is not None
            indata_2d = np.random.randn(4096, 2).astype(np.float32)
            # The callback puts data on thread_q; we just verify no error
            # We need a fresh queue for the callback to put into
            fresh_q = stdlib_queue.Queue(maxsize=16)
            with patch.object(ac_module.queue, "Queue", return_value=fresh_q):
                # Callback uses thread_q from closure, not ac_module.queue
                # So we just call it and check it doesn't crash
                captured_callback(indata_2d, 4096, None, None)


class TestReconnectionAndHealth:
    """Tests for reconnection with backoff and health monitor integration."""

    def test_reconnects_on_stream_error_with_backoff(self):
        """Outer while loop retries after _run_audio_stream raises, with backoff."""
        config = Config(bird=PipelineConfig(audio=AudioConfig(sample_rate=48_000, chunk_duration=3.0)))

        with patch.dict(sys.modules, {"sounddevice": MagicMock()}):
            import biardtz.audio_capture as ac_module

            call_count = 0

            async def fake_run_audio_stream(cfg, q, *, pipeline_name="bird", health=None):
                nonlocal call_count
                call_count += 1
                if call_count < 3:
                    raise OSError("Device disconnected")
                # Third call: clean exit (return normally)

            with patch.object(ac_module, "_run_audio_stream", side_effect=fake_run_audio_stream):
                with patch.object(ac_module.asyncio, "sleep", new_callable=AsyncMock) as mock_sleep:

                    async def run_test():
                        out_queue = asyncio.Queue()
                        await ac_module.audio_producer(config, out_queue)

                    asyncio.run(run_test())

            assert call_count == 3
            # First backoff = 2.0, second = 4.0
            assert mock_sleep.call_count == 2
            mock_sleep.assert_any_call(2.0)
            mock_sleep.assert_any_call(4.0)

    def test_health_mark_audio_ok_on_stream_start(self):
        """health.mark_audio_ok(True) is called when stream starts successfully."""
        config = Config(bird=PipelineConfig(audio=AudioConfig(sample_rate=48_000, chunk_duration=3.0)))
        mock_stream = MagicMock()

        with patch.dict(sys.modules, {"sounddevice": MagicMock()}):
            import biardtz.audio_capture as ac_module

            def fake_input_stream(**kwargs):
                return mock_stream

            with patch.object(ac_module.sd, "InputStream", side_effect=fake_input_stream):
                import queue as stdlib_queue

                test_queue = stdlib_queue.Queue(maxsize=16)
                test_queue.put(None)  # immediate stop

                health = MagicMock()

                with patch.object(ac_module.queue, "Queue", return_value=test_queue):

                    async def run_test():
                        out_queue = asyncio.Queue()
                        await ac_module.audio_producer(config, out_queue, health=health)

                    asyncio.run(run_test())

            health.mark_audio_ok.assert_called_once_with(True)

    def test_health_record_error_on_stream_failure(self):
        """health.mark_audio_ok(False) and health.record_error() called on error."""
        config = Config(bird=PipelineConfig(audio=AudioConfig(sample_rate=48_000, chunk_duration=3.0)))

        with patch.dict(sys.modules, {"sounddevice": MagicMock()}):
            import biardtz.audio_capture as ac_module

            call_count = 0

            async def fake_run_audio_stream(cfg, q, *, pipeline_name="bird", health=None):
                nonlocal call_count
                call_count += 1
                if call_count == 1:
                    raise RuntimeError("Audio device lost")
                # Second call: clean exit

            health = MagicMock()

            with patch.object(ac_module, "_run_audio_stream", side_effect=fake_run_audio_stream):
                with patch.object(ac_module.asyncio, "sleep", new_callable=AsyncMock):

                    async def run_test():
                        out_queue = asyncio.Queue()
                        await ac_module.audio_producer(config, out_queue, health=health)

                    asyncio.run(run_test())

            health.mark_audio_ok.assert_called_with(False)
            health.record_error.assert_called_once()
            assert "Audio stream failed" in health.record_error.call_args[0][0]

    def test_cancelled_error_propagates_without_reconnect(self):
        """CancelledError should propagate, not trigger reconnection."""
        config = Config(bird=PipelineConfig(audio=AudioConfig(sample_rate=48_000, chunk_duration=3.0)))

        with patch.dict(sys.modules, {"sounddevice": MagicMock()}):
            import biardtz.audio_capture as ac_module

            async def fake_run_audio_stream(cfg, q, *, pipeline_name="bird", health=None):
                raise asyncio.CancelledError()

            with patch.object(ac_module, "_run_audio_stream", side_effect=fake_run_audio_stream):

                async def run_test():
                    out_queue = asyncio.Queue()
                    with pytest.raises(asyncio.CancelledError):
                        await ac_module.audio_producer(config, out_queue)

                asyncio.run(run_test())
