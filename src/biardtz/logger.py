from __future__ import annotations

import logging
from datetime import datetime, timezone

import aiosqlite

from .config import Config
from .detector import Detection

_logger = logging.getLogger(__name__)

_SCHEMA = """\
CREATE TABLE IF NOT EXISTS detections (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp     TEXT NOT NULL,
    common_name   TEXT NOT NULL,
    sci_name      TEXT NOT NULL,
    confidence    REAL NOT NULL,
    latitude      REAL,
    longitude     REAL,
    bearing       REAL,
    direction     TEXT,
    detection_type TEXT NOT NULL DEFAULT 'bird'
);
CREATE INDEX IF NOT EXISTS idx_timestamp ON detections(timestamp);
CREATE INDEX IF NOT EXISTS idx_species   ON detections(common_name);
CREATE INDEX IF NOT EXISTS idx_ts_species_conf ON detections(timestamp, common_name, confidence);
CREATE INDEX IF NOT EXISTS idx_detection_type ON detections(detection_type);
CREATE TABLE IF NOT EXISTS audio_clips (
    common_name TEXT PRIMARY KEY,
    confidence  REAL NOT NULL,
    filename    TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS bat_detection_details (
    detection_id  INTEGER PRIMARY KEY REFERENCES detections(id),
    call_type     TEXT,
    freq_min_khz  REAL,
    freq_max_khz  REAL,
    duration_ms   REAL
);
"""

# Columns added after initial schema — migrated via ALTER TABLE
_MIGRATION_COLUMNS = [
    ("bearing", "REAL"),
    ("direction", "TEXT"),
    ("detection_type", "TEXT DEFAULT 'bird'"),
]


class DetectionLogger:
    """Async SQLite logger for bird detections."""

    def __init__(self, config: Config):
        self._config = config
        self._db: aiosqlite.Connection | None = None
        self._session_start = datetime.now(timezone.utc)
        self._count = 0

    async def init_db(self) -> None:
        self._config.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._db = await aiosqlite.connect(self._config.db_path)
        await self._db.execute("PRAGMA journal_mode=WAL")
        await self._db.execute("PRAGMA busy_timeout=5000")
        await self._db.execute("PRAGMA synchronous=NORMAL")

        # Non-blocking integrity check — warn but don't abort
        try:
            cursor = await self._db.execute("PRAGMA integrity_check")
            result = await cursor.fetchone()
            if result and result[0] != "ok":
                _logger.warning("Database integrity check failed: %s", result[0])
            else:
                _logger.debug("Database integrity check passed")
        except Exception:
            _logger.warning("Could not run integrity check", exc_info=True)

        await self._db.executescript(_SCHEMA)

        # Migrate existing databases: add columns if missing
        for col_name, col_type in _MIGRATION_COLUMNS:
            try:
                await self._db.execute(f"ALTER TABLE detections ADD COLUMN {col_name} {col_type}")
                _logger.info("Migrated: added column %s to detections", col_name)
            except Exception:
                pass  # Column already exists

        await self._db.commit()
        _logger.info("Database ready at %s (WAL mode)", self._config.db_path)

    async def log(self, detection: Detection) -> None:
        assert self._db is not None
        ts = datetime.now(timezone.utc).isoformat()
        await self._db.execute(
            "INSERT INTO detections "
            "(timestamp, common_name, sci_name, confidence, latitude, longitude, "
            "bearing, direction, detection_type) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (ts, detection.common_name, detection.sci_name, detection.confidence,
             self._config.latitude, self._config.longitude,
             detection.bearing, detection.direction, detection.detection_type),
        )
        await self._db.commit()
        self._count += 1

    async def log_bat_details(
        self, detection_id: int, call_type: str | None = None,
        freq_min_khz: float | None = None, freq_max_khz: float | None = None,
        duration_ms: float | None = None,
    ) -> None:
        """Store bat-specific metadata for a detection."""
        assert self._db is not None
        await self._db.execute(
            "INSERT OR REPLACE INTO bat_detection_details "
            "(detection_id, call_type, freq_min_khz, freq_max_khz, duration_ms) "
            "VALUES (?, ?, ?, ?, ?)",
            (detection_id, call_type, freq_min_khz, freq_max_khz, duration_ms),
        )
        await self._db.commit()

    async def get_audio_confidence(self, common_name: str) -> float | None:
        """Return the stored best confidence for a species' audio clip, or None."""
        assert self._db is not None
        cursor = await self._db.execute(
            "SELECT confidence FROM audio_clips WHERE common_name = ?",
            (common_name,),
        )
        row = await cursor.fetchone()
        return row[0] if row else None

    async def save_audio_clip(
        self, common_name: str, confidence: float, filename: str,
    ) -> None:
        """Insert or update the best audio clip for a species (higher confidence wins)."""
        assert self._db is not None
        await self._db.execute(
            "INSERT INTO audio_clips (common_name, confidence, filename) "
            "VALUES (?, ?, ?) "
            "ON CONFLICT(common_name) DO UPDATE SET "
            "confidence = excluded.confidence, filename = excluded.filename "
            "WHERE excluded.confidence > audio_clips.confidence",
            (common_name, confidence, filename),
        )
        await self._db.commit()

    async def session_summary(self) -> str:
        assert self._db is not None
        elapsed = datetime.now(timezone.utc) - self._session_start
        hours, remainder = divmod(int(elapsed.total_seconds()), 3600)
        minutes, seconds = divmod(remainder, 60)

        cursor = await self._db.execute(
            "SELECT COUNT(DISTINCT common_name) FROM detections WHERE timestamp >= ?",
            (self._session_start.isoformat(),),
        )
        row = await cursor.fetchone()
        unique = row[0] if row else 0

        return (
            f"Session: {hours}h {minutes}m {seconds}s | "
            f"Detections: {self._count} | Unique species: {unique}"
        )

    async def close(self) -> None:
        if self._db:
            await self._db.close()
            self._db = None
