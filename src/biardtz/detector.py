from __future__ import annotations

import asyncio
import logging
import sys
from typing import NamedTuple

import numpy as np

from .config import Config

_logger = logging.getLogger(__name__)


class Detection(NamedTuple):
    common_name: str
    sci_name: str
    confidence: float
    bearing: float | None = None     # compass degrees 0-360
    direction: str | None = None     # octant: N, NE, E, SE, S, SW, W, NW
    detection_type: str = "bird"     # "bird" or "bat"


class Detector:
    """Wraps BirdNET-Analyzer for inference on audio chunks."""

    def __init__(self, config: Config):
        self._config = config
        self._birdnet_cfg = None
        self._birdnet_model = None
        self._labels: list[str] = []
        self._load_model()

    def _load_model(self):
        birdnet = self._config.birdnet_path
        if not birdnet.exists():
            raise FileNotFoundError(
                f"BirdNET-Analyzer not found at {birdnet}. "
                "Clone it as a sibling directory: git clone https://github.com/kahst/BirdNET-Analyzer.git"
            )

        if str(birdnet) not in sys.path:
            sys.path.insert(0, str(birdnet))

        try:
            from birdnet_analyzer import config as birdnet_cfg  # type: ignore[import-untyped]
            from birdnet_analyzer import model as birdnet_model  # type: ignore[import-untyped]
            from birdnet_analyzer.species.utils import get_species_list  # type: ignore[import-untyped]
            from birdnet_analyzer.utils import read_lines  # type: ignore[import-untyped]
        except ImportError as exc:
            raise ImportError(
                f"Failed to import birdnet_analyzer from {birdnet}. "
                "Ensure BirdNET-Analyzer dependencies are installed."
            ) from exc

        # Configure BirdNET globals
        birdnet_cfg.MODEL_PATH = birdnet_cfg.BIRDNET_MODEL_PATH
        birdnet_cfg.LABELS_FILE = birdnet_cfg.BIRDNET_LABELS_FILE
        birdnet_cfg.SAMPLE_RATE = birdnet_cfg.BIRDNET_SAMPLE_RATE
        birdnet_cfg.SIG_LENGTH = birdnet_cfg.BIRDNET_SIG_LENGTH
        birdnet_cfg.LABELS = read_lines(birdnet_cfg.LABELS_FILE)
        birdnet_cfg.LATITUDE = self._config.latitude
        birdnet_cfg.LONGITUDE = self._config.longitude
        birdnet_cfg.WEEK = self._config.week
        birdnet_cfg.MIN_CONFIDENCE = self._config.confidence_threshold
        birdnet_cfg.TFLITE_THREADS = self._config.num_threads

        # Build species list from location
        if self._config.latitude != -1 and self._config.longitude != -1:
            birdnet_cfg.SPECIES_LIST = get_species_list(
                self._config.latitude, self._config.longitude,
                self._config.week, birdnet_cfg.LOCATION_FILTER_THRESHOLD,
            )
        else:
            birdnet_cfg.SPECIES_LIST = []

        # Load the TFLite model
        birdnet_model.load_model()

        self._birdnet_cfg = birdnet_cfg
        self._birdnet_model = birdnet_model
        self._labels = birdnet_cfg.LABELS
        _logger.info(
            "BirdNET loaded from %s (%d labels, %d local species)",
            birdnet, len(self._labels), len(birdnet_cfg.SPECIES_LIST),
        )

    def _predict_sync(self, audio_chunk: np.ndarray) -> list[Detection]:
        cfg = self._config
        bcfg = self._birdnet_cfg

        # BirdNET expects 48kHz; resample if our capture rate differs
        if cfg.sample_rate != bcfg.BIRDNET_SAMPLE_RATE:
            ratio = bcfg.BIRDNET_SAMPLE_RATE / cfg.sample_rate
            target_len = int(len(audio_chunk) * ratio)
            indices = np.linspace(0, len(audio_chunk) - 1, target_len).astype(int)
            audio_chunk = audio_chunk[indices]

        # BirdNET predict expects a batch: list of samples
        prediction = self._birdnet_model.predict([audio_chunk])

        detections = []
        for pred in prediction:
            for label, score in zip(self._labels, pred, strict=True):
                if score >= cfg.confidence_threshold:
                    if bcfg.SPECIES_LIST and label not in bcfg.SPECIES_LIST:
                        continue
                    # Labels are "SciName_CommonName"
                    parts = label.split("_", 1)
                    sci = parts[0] if len(parts) > 0 else label
                    common = parts[1] if len(parts) > 1 else label
                    detections.append(Detection(common_name=common, sci_name=sci, confidence=min(float(score), 1.0)))

        return detections

    async def predict(self, audio_chunk: np.ndarray) -> list[Detection]:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._predict_sync, audio_chunk)
