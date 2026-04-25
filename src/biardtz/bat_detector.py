"""Bat echolocation call detector using BatDetect2 ONNX model.

Requires the optional ``bat`` dependency group::

    pip install -e ".[bat]"
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .config import PipelineConfig
from .detector import Detection

_logger = logging.getLogger(__name__)


@dataclass
class BatCall:
    """Metadata for a single bat echolocation call."""

    call_type: str | None = None
    freq_min_khz: float | None = None
    freq_max_khz: float | None = None
    duration_ms: float | None = None


class BatDetector:
    """Wraps BatDetect2 ONNX model for inference on ultrasonic audio chunks.

    Parameters
    ----------
    pipeline_config : PipelineConfig
        Bat pipeline configuration with model_path and confidence_threshold.
    """

    def __init__(self, pipeline_config: PipelineConfig):
        self._config = pipeline_config
        self._model = None
        self._labels: list[str] = []
        self._load_model()

    def _load_model(self) -> None:
        model_path = self._config.model_path
        if model_path is None:
            raise FileNotFoundError(
                "No bat model path configured. Set bat pipeline model_path "
                "to a BatDetect2 ONNX model file."
            )
        model_path = Path(model_path)
        if not model_path.exists():
            raise FileNotFoundError(
                f"Bat model not found at {model_path}. "
                "Download a BatDetect2 ONNX model or specify the correct path."
            )

        try:
            import onnxruntime as ort  # type: ignore[import-untyped]
        except ImportError as exc:
            raise ImportError(
                "onnxruntime is required for bat detection. "
                "Install with: pip install -e '.[bat]'"
            ) from exc

        self._model = ort.InferenceSession(
            str(model_path),
            providers=["CPUExecutionProvider"],
        )

        # Try to extract labels from model metadata
        meta = self._model.get_modelmeta()
        if meta.custom_metadata_map and "labels" in meta.custom_metadata_map:
            self._labels = meta.custom_metadata_map["labels"].split(",")
        else:
            self._labels = []

        _logger.info(
            "BatDetect2 model loaded from %s (%d labels)",
            model_path, len(self._labels),
        )

    def _predict_sync(self, audio_chunk: np.ndarray) -> list[Detection]:
        """Run inference on a single audio chunk.

        Parameters
        ----------
        audio_chunk : np.ndarray
            1-D float32 array of ultrasonic audio samples.

        Returns
        -------
        list[Detection]
            Detected bat species above the confidence threshold.
        """
        if self._model is None:
            return []

        # Prepare input: BatDetect2 expects (batch, 1, samples) float32
        if audio_chunk.ndim == 1:
            audio_chunk = audio_chunk.reshape(1, 1, -1)
        elif audio_chunk.ndim == 2:
            audio_chunk = audio_chunk.reshape(1, *audio_chunk.shape)

        input_name = self._model.get_inputs()[0].name
        outputs = self._model.run(None, {input_name: audio_chunk.astype(np.float32)})

        # Expect outputs[0] = class probabilities (batch, num_classes)
        if not outputs:
            return []

        predictions = outputs[0]
        if predictions.ndim == 1:
            predictions = predictions.reshape(1, -1)

        detections = []
        for pred in predictions:
            for idx, score in enumerate(pred):
                if score >= self._config.confidence_threshold:
                    if idx < len(self._labels):
                        label = self._labels[idx]
                        # Labels expected as "Scientific Name_Common Name"
                        parts = label.split("_", 1)
                        sci = parts[0] if len(parts) > 0 else label
                        common = parts[1] if len(parts) > 1 else label
                    else:
                        sci = f"Unknown bat sp. {idx}"
                        common = f"Unknown bat {idx}"
                    detections.append(
                        Detection(
                            common_name=common,
                            sci_name=sci,
                            confidence=min(float(score), 1.0),
                            detection_type="bat",
                        )
                    )

        return detections

    async def predict(self, audio_chunk: np.ndarray) -> list[Detection]:
        """Async wrapper — runs inference in executor."""
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._predict_sync, audio_chunk)
