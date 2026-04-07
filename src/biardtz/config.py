from __future__ import annotations

import dataclasses
from pathlib import Path


@dataclasses.dataclass
class Config:
    """All tunable parameters for the biardtz pipeline."""

    sample_rate: int = 16_000
    chunk_duration: float = 3.0
    channels: int = 6
    device_index: int | None = None
    confidence_threshold: float = 0.25
    latitude: float = 51.50
    longitude: float = -0.12
    location_name: str | None = None
    week: int = -1
    num_threads: int = 4
    db_path: Path = Path("/mnt/ssd/detections.db")
    birdnet_path: Path = dataclasses.field(default=None)
    enable_dashboard: bool = True

    def __post_init__(self):
        self.db_path = Path(self.db_path)
        if self.birdnet_path is None:
            # Sibling directory to the repository root
            self.birdnet_path = Path(__file__).resolve().parents[3] / "BirdNET-Analyzer"
        else:
            self.birdnet_path = Path(self.birdnet_path)

    @property
    def chunk_samples(self) -> int:
        return int(self.sample_rate * self.chunk_duration)
