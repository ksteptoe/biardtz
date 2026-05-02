from __future__ import annotations

import dataclasses
from pathlib import Path
from zoneinfo import ZoneInfo


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
    location_name: str = "London"
    tz_name: str = "Europe/London"
    array_bearing: float = 0.0  # compass bearing (degrees) that mic 0 faces; 0=North
    week: int = -1
    num_threads: int = 4
    db_path: Path = Path("/mnt/ssd/detections.db")
    birdnet_path: Path = dataclasses.field(default=None)
    enable_dashboard: bool = True
    enable_web: bool = True
    web_port: int = 8080
    bird_image_cache: Path = Path("/mnt/ssd/bird_images")
    audio_clip_dir: Path = Path("/mnt/ssd/audio_clips")

    # Verification — require watchlist species to be detected multiple times
    watchlist: tuple[str, ...] = ()
    watchlist_file: Path | None = None
    auto_watchlist_threshold: int = 0  # species with <= N detections auto-added (0=off)
    verify_min_detections: int = 2
    verify_window_seconds: float = 300.0

    def __post_init__(self):
        self.db_path = Path(self.db_path)
        self.bird_image_cache = Path(self.bird_image_cache)
        self.audio_clip_dir = Path(self.audio_clip_dir)
        if self.birdnet_path is None:
            # Sibling directory to the repository root
            self.birdnet_path = Path(__file__).resolve().parents[3] / "BirdNET-Analyzer"
        else:
            self.birdnet_path = Path(self.birdnet_path)
        if self.watchlist_file is not None:
            self.watchlist_file = Path(self.watchlist_file)
            if self.watchlist_file.exists():
                file_species = tuple(
                    line.strip() for line in self.watchlist_file.read_text().splitlines()
                    if line.strip() and not line.startswith("#")
                )
                self.watchlist = tuple(dict.fromkeys(self.watchlist + file_species))

    @property
    def chunk_samples(self) -> int:
        return int(self.sample_rate * self.chunk_duration)

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.tz_name)
