from __future__ import annotations

import asyncio
import logging
import queue

import numpy as np
import sounddevice as sd

from .config import AudioConfig, Config

_logger = logging.getLogger(__name__)

# Reconnection parameters
_INITIAL_BACKOFF = 2.0    # seconds
_MAX_BACKOFF = 60.0       # seconds
_BACKOFF_FACTOR = 2.0


def validate_device_indices(config: Config) -> None:
    """Raise ValueError if enabled pipelines share the same device_index."""
    pipelines = []
    if config.bird.enabled:
        pipelines.append(("bird", config.bird.audio.device_index))
    if config.bat.enabled:
        pipelines.append(("bat", config.bat.audio.device_index))

    indices = [(name, idx) for name, idx in pipelines if idx is not None]
    seen: dict[int, str] = {}
    for name, idx in indices:
        if idx in seen:
            raise ValueError(
                f"Pipelines '{seen[idx]}' and '{name}' both use audio device {idx}. "
                "Each pipeline must use a different device."
            )
        seen[idx] = name


def log_available_devices() -> None:
    """Log all audio input devices to help identify microphones."""
    try:
        devices = sd.query_devices()
        input_devs = [
            (i, d) for i, d in enumerate(devices)
            if d["max_input_channels"] > 0
        ]
        if input_devs:
            _logger.info("Available audio input devices:")
            for i, d in input_devs:
                _logger.info(
                    "  [%d] %s (channels=%d, rate=%.0f Hz)",
                    i, d["name"], d["max_input_channels"],
                    d["default_samplerate"],
                )
        else:
            _logger.warning("No audio input devices found")
    except Exception:
        _logger.warning("Could not query audio devices", exc_info=True)


async def audio_producer(
    audio_config: AudioConfig | Config,
    out_queue: asyncio.Queue,
    *,
    pipeline_name: str = "bird",
    health=None,
) -> None:
    """Capture audio from the microphone and enqueue chunks.

    Each item placed on *out_queue* is a ``(mono, multichannel)`` tuple where
    *mono* is a 1-D float32 array (channel 0) and *multichannel* is either a
    ``(samples, 4)`` float32 array of raw mic channels or ``None`` when fewer
    than 5 hardware channels are available.

    Accepts either an ``AudioConfig`` directly or a legacy ``Config`` object
    (backward compatible — reads bird pipeline audio settings).

    Automatically reconnects on stream errors with exponential backoff.
    """
    # Support legacy Config objects for backward compatibility
    if isinstance(audio_config, Config):
        audio_config = audio_config.bird.audio

    backoff = _INITIAL_BACKOFF

    while True:  # outer reconnection loop
        try:
            await _run_audio_stream(audio_config, out_queue, pipeline_name=pipeline_name, health=health)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            msg = f"[{pipeline_name}] Audio stream failed: {exc}"
            _logger.error("%s — reconnecting in %.0fs", msg, backoff)
            if health:
                health.mark_audio_ok(False)
                health.record_error(msg)

            await asyncio.sleep(backoff)
            backoff = min(backoff * _BACKOFF_FACTOR, _MAX_BACKOFF)
        else:
            # Clean exit (sentinel None received)
            break


async def _run_audio_stream(
    audio_config: AudioConfig,
    out_queue: asyncio.Queue,
    *,
    pipeline_name: str = "bird",
    health=None,
) -> None:
    """Open one audio stream session and process until error or cancellation."""
    loop = asyncio.get_running_loop()
    has_multi = audio_config.channels >= 5
    chunk_samples = audio_config.chunk_samples
    buf_mono = np.empty(0, dtype=np.float32)
    buf_multi = np.empty((0, 4), dtype=np.float32) if has_multi else None
    thread_q: queue.Queue[tuple[np.ndarray, np.ndarray | None] | None] = queue.Queue(maxsize=16)

    def _callback(indata: np.ndarray, frames: int, time_info, status):
        if status:
            _logger.warning("[%s] Audio status: %s", pipeline_name, status)
        if indata.ndim > 1:
            mono = indata[:, 0].copy()
            multi = indata[:, 1:5].copy() if has_multi else None
        else:
            mono = indata.copy().ravel()
            multi = None
        thread_q.put((mono, multi))

    stream = sd.InputStream(
        samplerate=audio_config.sample_rate,
        channels=audio_config.channels,
        dtype="float32",
        device=audio_config.device_index,
        blocksize=4096,
        callback=_callback,
    )

    _logger.info(
        "[%s] Opening audio stream: device=%s, rate=%d Hz, channels=%d",
        pipeline_name,
        audio_config.device_index,
        audio_config.sample_rate,
        audio_config.channels,
    )

    stream.start()
    if health:
        health.mark_audio_ok(True)
    try:
        while True:
            item = await loop.run_in_executor(None, thread_q.get)
            if item is None:
                break
            mono_data, multi_data = item
            buf_mono = np.concatenate((buf_mono, mono_data))
            if buf_multi is not None and multi_data is not None:
                buf_multi = np.concatenate((buf_multi, multi_data))
            while len(buf_mono) >= chunk_samples:
                mono_chunk = buf_mono[:chunk_samples]
                buf_mono = buf_mono[chunk_samples:]
                if buf_multi is not None and len(buf_multi) >= chunk_samples:
                    multi_chunk = buf_multi[:chunk_samples]
                    buf_multi = buf_multi[chunk_samples:]
                else:
                    multi_chunk = None
                await out_queue.put((mono_chunk, multi_chunk))
    finally:
        stream.stop()
        stream.close()
        _logger.info("[%s] Audio stream closed", pipeline_name)
