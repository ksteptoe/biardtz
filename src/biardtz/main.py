from __future__ import annotations

import asyncio
import logging
import re
import signal
import wave
from pathlib import Path

import numpy as np

from .audio_capture import audio_producer, log_available_devices, validate_device_indices
from .config import Config
from .dashboard import Dashboard
from .detector import Detector
from .doa import estimate_doa
from .health import HealthMonitor
from .logger import DetectionLogger
from .protocols import DetectorProtocol

_logger = logging.getLogger(__name__)


def _species_slug(common_name: str) -> str:
    """Convert a species name to a filesystem-safe slug."""
    return re.sub(r"[^a-z0-9]+", "_", common_name.lower()).strip("_")


def _save_audio_clip(
    chunk: np.ndarray, audio_dir: Path, filename: str, sample_rate: int = 16_000,
) -> str:
    """Save a mono float32 chunk as 16-bit PCM WAV. Returns filename."""
    audio_dir.mkdir(parents=True, exist_ok=True)
    filepath = audio_dir / filename
    pcm = (chunk * 32767).clip(-32768, 32767).astype(np.int16)
    with wave.open(str(filepath), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm.tobytes())
    return filename


async def _detection_worker(
    detector: DetectorProtocol,
    audio_queue: asyncio.Queue,
    det_logger: DetectionLogger,
    dashboard_queue: asyncio.Queue | None,
    config: Config | None = None,
    health: HealthMonitor | None = None,
    pipeline_name: str = "bird",
    sample_rate: int = 16_000,
) -> None:
    while True:
        item = await audio_queue.get()
        if isinstance(item, tuple):
            chunk, multichannel = item
        else:
            chunk, multichannel = item, None

        try:
            detections = await detector.predict(chunk)
        except Exception:
            _logger.exception("[%s] Inference error", pipeline_name)
            if health:
                health.record_error(f"[{pipeline_name}] Inference error")
            continue

        # Run DOA only for bird detections with multichannel data
        bearing = None
        direction = None
        if (
            pipeline_name == "bird"
            and detections
            and multichannel is not None
            and config is not None
        ):
            try:
                loop = asyncio.get_running_loop()
                bearing, direction = await loop.run_in_executor(
                    None, estimate_doa, multichannel,
                    config.sample_rate, config.array_bearing,
                )
            except Exception:
                _logger.exception("DOA estimation error")

        for det in detections:
            if bearing is not None:
                det = det._replace(bearing=bearing, direction=direction)
            _logger.info(
                "[%s] Detected: %s (%.1f%%)%s",
                pipeline_name,
                det.common_name, det.confidence * 100,
                f" from {det.direction} ({det.bearing:.0f}\u00b0)" if det.direction else "",
            )
            await det_logger.log(det)

            # Save audio clip if this is the best sample for the species
            if config is not None:
                best = await det_logger.get_audio_confidence(det.common_name)
                if best is None or det.confidence > best:
                    filename = f"{_species_slug(det.common_name)}.wav"
                    loop = asyncio.get_running_loop()
                    await loop.run_in_executor(
                        None, _save_audio_clip, chunk,
                        config.audio_clip_dir, filename, sample_rate,
                    )
                    await det_logger.save_audio_clip(
                        det.common_name, det.confidence, filename,
                    )

            if health:
                health.mark_detection()
            if dashboard_queue is not None:
                await dashboard_queue.put(det)


async def run(config: Config) -> None:
    """Main async entry point — runs the full detection pipeline."""
    det_logger = DetectionLogger(config)
    await det_logger.init_db()

    health = HealthMonitor()
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
            pass

    loc = config.location_name or f"{config.latitude:.2f}, {config.longitude:.2f}"

    # Validate that enabled pipelines use different audio devices
    if config.bat.enabled:
        validate_device_indices(config)
        log_available_devices()

    tasks: list[asyncio.Task] = []

    # --- Bird pipeline ---
    if config.bird.enabled:
        _logger.info(
            "Starting bird pipeline (threshold=%.0f%%, location=%s)",
            config.bird.confidence_threshold * 100, loc,
        )
        detector = Detector(config)
        bird_queue: asyncio.Queue = asyncio.Queue(maxsize=8)
        tasks.append(
            asyncio.create_task(
                audio_producer(config.bird.audio, bird_queue, pipeline_name="bird", health=health),
                name="bird-audio",
            )
        )
        tasks.append(
            asyncio.create_task(
                _detection_worker(
                    detector, bird_queue, det_logger, dashboard_queue,
                    config, health=health, pipeline_name="bird",
                    sample_rate=config.bird.audio.sample_rate,
                ),
                name="bird-worker",
            )
        )

    # --- Bat pipeline ---
    if config.bat.enabled:
        _logger.info(
            "Starting bat pipeline (threshold=%.0f%%, rate=%d Hz)",
            config.bat.confidence_threshold * 100,
            config.bat.audio.sample_rate,
        )
        from .bat_detector import BatDetector

        bat_detector = BatDetector(config.bat)
        bat_queue: asyncio.Queue = asyncio.Queue(maxsize=8)
        tasks.append(
            asyncio.create_task(
                audio_producer(config.bat.audio, bat_queue, pipeline_name="bat", health=health),
                name="bat-audio",
            )
        )
        tasks.append(
            asyncio.create_task(
                _detection_worker(
                    bat_detector, bat_queue, det_logger, dashboard_queue,
                    config, health=health, pipeline_name="bat",
                    sample_rate=config.bat.audio.sample_rate,
                ),
                name="bat-worker",
            )
        )

    # --- Shared services ---
    tasks.append(asyncio.create_task(health.run(), name="health"))

    if config.enable_dashboard and dashboard_queue is not None:
        dashboard = Dashboard(local_tz=config.tz)
        tasks.append(asyncio.create_task(dashboard.run(dashboard_queue), name="dashboard"))

    if config.enable_web:
        import uvicorn

        from .web import create_app

        web_app = create_app(config)
        uvi_config = uvicorn.Config(
            web_app, host="0.0.0.0", port=config.web_port, log_level="warning",
        )
        server = uvicorn.Server(uvi_config)
        tasks.append(asyncio.create_task(server.serve(), name="web"))
        _logger.info("Web dashboard at http://0.0.0.0:%d/", config.web_port)

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
        health.cleanup()
        _logger.info("Shutdown complete")
