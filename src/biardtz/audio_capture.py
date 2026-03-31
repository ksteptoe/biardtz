from __future__ import annotations

import asyncio
import logging
import queue

import numpy as np
import sounddevice as sd

from .config import Config

_logger = logging.getLogger(__name__)


async def audio_producer(config: Config, out_queue: asyncio.Queue) -> None:
    """Capture audio from the microphone and enqueue 3-second chunks."""
    loop = asyncio.get_running_loop()
    buf = np.empty(0, dtype=np.float32)
    thread_q: queue.Queue[np.ndarray | None] = queue.Queue(maxsize=16)

    def _callback(indata: np.ndarray, frames: int, time_info, status):
        if status:
            _logger.warning("Audio status: %s", status)
        thread_q.put(indata[:, 0].copy() if indata.ndim > 1 else indata.copy().ravel())

    stream = sd.InputStream(
        samplerate=config.sample_rate,
        channels=config.channels,
        dtype="float32",
        device=config.device_index,
        blocksize=4096,
        callback=_callback,
    )

    _logger.info(
        "Opening audio stream: device=%s, rate=%d Hz, channels=%d",
        config.device_index,
        config.sample_rate,
        config.channels,
    )

    stream.start()
    try:
        while True:
            data = await loop.run_in_executor(None, thread_q.get)
            if data is None:
                break
            buf = np.concatenate((buf, data))
            while len(buf) >= config.chunk_samples:
                chunk = buf[: config.chunk_samples]
                buf = buf[config.chunk_samples :]
                await out_queue.put(chunk)
    finally:
        stream.stop()
        stream.close()
        _logger.info("Audio stream closed")
