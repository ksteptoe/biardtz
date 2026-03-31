"""Tests for biardtz.audio_capture."""

import asyncio
import sys
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from biardtz.config import Config


class TestAudioProducer:
    def test_puts_correct_size_chunks_on_queue(self):
        config = Config(sample_rate=48_000, chunk_duration=3.0)
        chunk_samples = config.chunk_samples  # 144000

        mock_stream = MagicMock()
        mock_stream.start = MagicMock()
        mock_stream.stop = MagicMock()
        mock_stream.close = MagicMock()

        # Simulate audio data arriving: send exactly one chunk worth, then None to stop
        audio_data = np.random.randn(chunk_samples).astype(np.float32)
        half = chunk_samples // 2

        call_count = 0

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

                    original_queue_class = stdlib_queue.Queue

                    test_queue = stdlib_queue.Queue(maxsize=16)
                    # Put audio data, then None sentinel
                    test_queue.put(audio_data[:half])
                    test_queue.put(audio_data[half:])
                    test_queue.put(None)

                    with patch.object(ac_module.queue, "Queue", return_value=test_queue):
                        task = asyncio.create_task(ac_module.audio_producer(config, out_queue))
                        # Wait for the task to finish (it'll exit on None sentinel)
                        await asyncio.wait_for(task, timeout=5.0)

                    # Should have exactly one chunk
                    assert not out_queue.empty()
                    chunk = await out_queue.get()
                    assert len(chunk) == chunk_samples
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
