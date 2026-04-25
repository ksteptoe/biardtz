from __future__ import annotations

import dataclasses
from pathlib import Path
from zoneinfo import ZoneInfo


@dataclasses.dataclass
class AudioConfig:
    """Audio capture parameters for a single microphone."""

    sample_rate: int = 16_000
    channels: int = 6
    device_index: int | None = None
    chunk_duration: float = 3.0

    @property
    def chunk_samples(self) -> int:
        return int(self.sample_rate * self.chunk_duration)


@dataclasses.dataclass
class PipelineConfig:
    """Configuration for one detection pipeline (bird or bat)."""

    enabled: bool = True
    audio: AudioConfig = dataclasses.field(default_factory=AudioConfig)
    confidence_threshold: float = 0.25
    model_path: Path | None = None

    def __post_init__(self):
        if self.model_path is not None:
            self.model_path = Path(self.model_path)


def _default_bird_pipeline() -> PipelineConfig:
    return PipelineConfig(
        enabled=True,
        audio=AudioConfig(sample_rate=16_000, channels=6, chunk_duration=3.0),
        confidence_threshold=0.25,
    )


def _default_bat_pipeline() -> PipelineConfig:
    return PipelineConfig(
        enabled=False,
        audio=AudioConfig(sample_rate=256_000, channels=1, chunk_duration=0.5),
        confidence_threshold=0.25,
    )


@dataclasses.dataclass
class Config:
    """All tunable parameters for the biardtz pipeline."""

    # Pipeline configs
    bird: PipelineConfig = dataclasses.field(default_factory=_default_bird_pipeline)
    bat: PipelineConfig = dataclasses.field(default_factory=_default_bat_pipeline)

    # Location & environment
    latitude: float = 51.50
    longitude: float = -0.12
    location_name: str = "London"
    tz_name: str = "Europe/London"
    array_bearing: float = 0.0  # compass bearing (degrees) that mic 0 faces; 0=North
    week: int = -1
    num_threads: int = 4

    # Paths
    db_path: Path = Path("/mnt/ssd/detections.db")
    birdnet_path: Path = dataclasses.field(default=None)
    bird_image_cache: Path = Path("/mnt/ssd/bird_images")
    audio_clip_dir: Path = Path("/mnt/ssd/audio_clips")

    # UI
    enable_dashboard: bool = True
    enable_web: bool = True
    web_port: int = 8080

    def __post_init__(self):
        self.db_path = Path(self.db_path)
        self.bird_image_cache = Path(self.bird_image_cache)
        self.audio_clip_dir = Path(self.audio_clip_dir)
        if self.birdnet_path is None:
            # Sibling directory to the repository root
            self.birdnet_path = Path(__file__).resolve().parents[3] / "BirdNET-Analyzer"
        else:
            self.birdnet_path = Path(self.birdnet_path)

    # --- Backward-compatible properties delegating to bird pipeline ---
    @property
    def sample_rate(self) -> int:
        return self.bird.audio.sample_rate

    @property
    def chunk_duration(self) -> float:
        return self.bird.audio.chunk_duration

    @property
    def channels(self) -> int:
        return self.bird.audio.channels

    @property
    def device_index(self) -> int | None:
        return self.bird.audio.device_index

    @property
    def confidence_threshold(self) -> float:
        return self.bird.confidence_threshold

    @property
    def chunk_samples(self) -> int:
        return self.bird.audio.chunk_samples

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.tz_name)
