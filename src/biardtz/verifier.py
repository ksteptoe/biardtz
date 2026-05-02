"""Multi-chunk verification for rare / watchlist species.

Detections for species on the watchlist are logged immediately with
``verified=False`` and held in an in-memory pending buffer.  Once the
same species is detected *verify_min_detections* times within
*verify_window_seconds*, all pending rows are promoted to ``verified=True``.
"""

from __future__ import annotations

import logging
import time
from collections import defaultdict
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .config import Config
    from .detector import Detection
    from .logger import DetectionLogger

_logger = logging.getLogger(__name__)


@dataclass
class _PendingEntry:
    row_id: int
    mono_time: float  # time.monotonic()


class Verifier:
    """Decide whether a detection needs multi-chunk confirmation."""

    def __init__(self, config: Config, det_logger: DetectionLogger) -> None:
        self._config = config
        self._logger = det_logger
        self._watchlist: set[str] = set(config.watchlist)
        self._auto_watchlist: set[str] = set()
        self._pending: dict[str, list[_PendingEntry]] = defaultdict(list)

    # ── public API ──────────────────────────────────────────────────────

    def needs_verification(self, species: str) -> bool:
        """Return True if *species* is on the explicit or auto watchlist."""
        return species in self._watchlist or species in self._auto_watchlist

    async def submit(self, det: Detection, row_id: int) -> bool:
        """Register a detection.  Returns True once verification threshold is met."""
        species = det.common_name
        if not self.needs_verification(species):
            return True

        now = time.monotonic()
        cutoff = now - self._config.verify_window_seconds

        pending = self._pending[species]
        pending.append(_PendingEntry(row_id=row_id, mono_time=now))

        # Prune expired entries
        self._pending[species] = pending = [p for p in pending if p.mono_time >= cutoff]

        if len(pending) >= self._config.verify_min_detections:
            row_ids = [p.row_id for p in pending]
            await self._logger.verify_detections(row_ids)
            del self._pending[species]
            _logger.info("Verified %s (%d detections in window)", species, len(row_ids))
            return True

        _logger.debug(
            "Pending verification for %s (%d/%d)",
            species, len(pending), self._config.verify_min_detections,
        )
        return False

    async def expire_pending(self) -> list[str]:
        """Remove stale entries whose window has passed. Returns expired species names."""
        now = time.monotonic()
        cutoff = now - self._config.verify_window_seconds
        expired: list[str] = []
        for species in list(self._pending):
            self._pending[species] = [p for p in self._pending[species] if p.mono_time >= cutoff]
            if not self._pending[species]:
                del self._pending[species]
                expired.append(species)
        if expired:
            _logger.debug("Expired unverified: %s", ", ".join(expired))
        return expired

    async def refresh_auto_watchlist(self) -> None:
        """Query the DB for species with few detections and update the auto-watchlist."""
        threshold = self._config.auto_watchlist_threshold
        if threshold <= 0:
            self._auto_watchlist = set()
            return
        self._auto_watchlist = await self._logger.rare_species(threshold)
        if self._auto_watchlist:
            _logger.debug("Auto-watchlist (%d species): %s",
                          len(self._auto_watchlist), ", ".join(sorted(self._auto_watchlist)))
