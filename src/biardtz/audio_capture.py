from __future__ import annotations

import asyncio
import logging
import queue

import numpy as np
import sounddevice as sd

from .config import Config

_logger = logging.getLogger(__name__)


async def audio_producer(config: Config, out_queue: asyncio.Queue) -> None:
    """Capture audio from the microphone and enqueue 3-second chunks.

    Each item placed on *out_queue* is a ``(mono, multichannel)`` tuple where
    *mono* is a 1-D float32 array (channel 0) and *multichannel* is either a
    ``(samples, 4)`` float32 array of raw mic channels or ``None`` when fewer
    than 5 hardware channels are available.
    """
    loop = asyncio.get_running_loop()
    has_multi = config.channels >= 5
    buf_mono = np.empty(0, dtype=np.float32)
    buf_multi = np.empty((0, 4), dtype=np.float32) if has_multi else None
    thread_q: queue.Queue[tuple[np.ndarray, np.ndarray | None] | None] = queue.Queue(maxsize=16)

    def _callback(indata: np.ndarray, frames: int, time_info, status):
        if status:
            _logger.warning("Audio status: %s", status)
        if indata.ndim > 1:
            mono = indata[:, 0].copy()
            multi = indata[:, 1:5].copy() if has_multi else None
        else:
            mono = indata.copy().ravel()
            multi = None
        thread_q.put((mono, multi))

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
            item = await loop.run_in_executor(None, thread_q.get)
            if item is None:
                break
            mono_data, multi_data = item
            buf_mono = np.concatenate((buf_mono, mono_data))
            if buf_multi is not None and multi_data is not None:
                buf_multi = np.concatenate((buf_multi, multi_data))
            while len(buf_mono) >= config.chunk_samples:
                mono_chunk = buf_mono[: config.chunk_samples]
                buf_mono = buf_mono[config.chunk_samples :]
                if buf_multi is not None and len(buf_multi) >= config.chunk_samples:
                    multi_chunk = buf_multi[: config.chunk_samples]
                    buf_multi = buf_multi[config.chunk_samples :]
                else:
                    multi_chunk = None
                await out_queue.put((mono_chunk, multi_chunk))
    finally:
        stream.stop()
        stream.close()
        _logger.info("Audio stream closed")
