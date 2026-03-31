from __future__ import annotations

import asyncio
import logging
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import NamedTuple

import numpy as np

from .config import Config

_logger = logging.getLogger(__name__)


class Detection(NamedTuple):
    common_name: str
    sci_name: str
    confidence: float


class Detector:
    """Wraps BirdNET-Analyzer for inference on audio chunks."""

    def __init__(self, config: Config):
        self._config = config
        self._predict_fn = None
        self._use_subprocess = False
        self._load_model()

    def _load_model(self):
        birdnet = self._config.birdnet_path
        if not birdnet.exists():
            raise FileNotFoundError(
                f"BirdNET-Analyzer not found at {birdnet}. "
                "Clone it as a sibling directory: git clone https://github.com/kahst/BirdNET-Analyzer.git"
            )

        # Try direct import first
        try:
            if str(birdnet) not in sys.path:
                sys.path.insert(0, str(birdnet))
            from analyze import predict  # type: ignore[import-untyped]

            self._predict_fn = predict
            _logger.info("BirdNET loaded via direct import from %s", birdnet)
        except (ImportError, ModuleNotFoundError) as exc:
            _logger.warning("Direct BirdNET import failed (%s), falling back to subprocess", exc)
            self._use_subprocess = True

    def _predict_sync(self, audio_chunk: np.ndarray) -> list[Detection]:
        if self._use_subprocess:
            return self._predict_subprocess(audio_chunk)
        return self._predict_direct(audio_chunk)

    def _predict_direct(self, audio_chunk: np.ndarray) -> list[Detection]:
        cfg = self._config
        results = self._predict_fn(
            audio_chunk,
            cfg.sample_rate,
            lat=cfg.latitude,
            lon=cfg.longitude,
            week=cfg.week,
            sensitivity=1.0,
            num_threads=cfg.num_threads,
        )
        detections = []
        for species, confidence in results.items():
            if confidence >= cfg.confidence_threshold:
                parts = species.split("_", 1)
                sci = parts[0] if len(parts) > 0 else species
                common = parts[1] if len(parts) > 1 else species
                detections.append(Detection(common_name=common, sci_name=sci, confidence=confidence))
        return detections

    def _predict_subprocess(self, audio_chunk: np.ndarray) -> list[Detection]:
        import wave

        cfg = self._config
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            tmp_path = Path(tmp.name)
            with wave.open(tmp.name, "w") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(cfg.sample_rate)
                wf.writeframes((audio_chunk * 32767).astype(np.int16).tobytes())

        try:
            analyze_py = cfg.birdnet_path / "analyze.py"
            result = subprocess.run(
                [
                    sys.executable,
                    str(analyze_py),
                    "--i",
                    str(tmp_path),
                    "--lat",
                    str(cfg.latitude),
                    "--lon",
                    str(cfg.longitude),
                    "--week",
                    str(cfg.week),
                    "--min_conf",
                    str(cfg.confidence_threshold),
                    "--rtype",
                    "csv",
                ],
                capture_output=True,
                text=True,
                timeout=30,
            )
            return self._parse_csv_output(result.stdout)
        finally:
            tmp_path.unlink(missing_ok=True)

    @staticmethod
    def _parse_csv_output(csv_text: str) -> list[Detection]:
        detections = []
        for line in csv_text.strip().splitlines()[1:]:  # skip header
            parts = line.split("\t")
            if len(parts) >= 5:
                sci_name = parts[2]
                common_name = parts[3]
                confidence = float(parts[4])
                detections.append(Detection(common_name=common_name, sci_name=sci_name, confidence=confidence))
        return detections

    async def predict(self, audio_chunk: np.ndarray) -> list[Detection]:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._predict_sync, audio_chunk)
