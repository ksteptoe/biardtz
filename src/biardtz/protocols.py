"""Typing protocols for detection pipelines."""

from __future__ import annotations

from typing import Protocol

import numpy as np

from .detector import Detection


class DetectorProtocol(Protocol):
    """Common interface for bird and bat detectors."""

    async def predict(self, audio_chunk: np.ndarray) -> list[Detection]: ...
