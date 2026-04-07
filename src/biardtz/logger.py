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
    longitude     REAL
);
CREATE INDEX IF NOT EXISTS idx_timestamp ON detections(timestamp);
CREATE INDEX IF NOT EXISTS idx_species   ON detections(common_name);
"""


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
        await self._db.commit()
        _logger.info("Database ready at %s (WAL mode)", self._config.db_path)

    async def log(self, detection: Detection) -> None:
        assert self._db is not None
        ts = datetime.now(timezone.utc).isoformat()
        await self._db.execute(
            "INSERT INTO detections (timestamp, common_name, sci_name, confidence, latitude, longitude) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (ts, detection.common_name, detection.sci_name, detection.confidence,
             self._config.latitude, self._config.longitude),
        )
        await self._db.commit()
        self._count += 1

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
