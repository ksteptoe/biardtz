from __future__ import annotations

import asyncio
import logging
import signal

from .audio_capture import audio_producer
from .config import Config
from .dashboard import Dashboard
from .detector import Detector
from .logger import DetectionLogger

_logger = logging.getLogger(__name__)


async def _detection_worker(
    detector: Detector,
    audio_queue: asyncio.Queue,
    det_logger: DetectionLogger,
    dashboard_queue: asyncio.Queue | None,
) -> None:
    while True:
        chunk = await audio_queue.get()
        try:
            detections = await detector.predict(chunk)
        except Exception:
            _logger.exception("Inference error")
            continue
        for det in detections:
            _logger.info("Detected: %s (%.1f%%)", det.common_name, det.confidence * 100)
            await det_logger.log(det)
            if dashboard_queue is not None:
                await dashboard_queue.put(det)


async def run(config: Config) -> None:
    """Main async entry point — runs the full detection pipeline."""
    detector = Detector(config)
    det_logger = DetectionLogger(config)
    await det_logger.init_db()

    audio_queue: asyncio.Queue = asyncio.Queue(maxsize=8)
    dashboard_queue: asyncio.Queue | None = asyncio.Queue(maxsize=32) if config.enable_dashboard else None

    loop = asyncio.get_running_loop()
    stop_event = asyncio.Event()

    def _signal_handler():
        _logger.info("Shutdown signal received")
        stop_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _signal_handler)
        except NotImplementedError:
            # Windows doesn't support add_signal_handler
            pass

    _logger.info("Starting biardtz pipeline (threshold=%.0f%%, lat=%.2f, lon=%.2f)",
                 config.confidence_threshold * 100, config.latitude, config.longitude)

    tasks = [
        asyncio.create_task(audio_producer(config, audio_queue), name="audio"),
        asyncio.create_task(_detection_worker(detector, audio_queue, det_logger, dashboard_queue), name="worker"),
    ]
    if config.enable_dashboard and dashboard_queue is not None:
        dashboard = Dashboard()
        tasks.append(asyncio.create_task(dashboard.run(dashboard_queue), name="dashboard"))

    try:
        await stop_event.wait()
    except (KeyboardInterrupt, asyncio.CancelledError):
        pass
    finally:
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        summary = await det_logger.session_summary()
        _logger.info(summary)
        await det_logger.close()
        _logger.info("Shutdown complete")
