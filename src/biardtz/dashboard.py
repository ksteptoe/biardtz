from __future__ import annotations

import asyncio
import logging
from collections import deque
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from rich.live import Live
from rich.table import Table
from rich.text import Text

from .detector import Detection

_logger = logging.getLogger(__name__)


class Dashboard:
    """Rich live terminal dashboard showing recent detections."""

    def __init__(self, max_rows: int = 20, local_tz: ZoneInfo | None = None):
        self._recent: deque[tuple[str, Detection, bool]] = deque(maxlen=max_rows)
        self._total = 0
        self._species: set[str] = set()
        self._start = datetime.now(timezone.utc)
        self._local_tz = local_tz or ZoneInfo("UTC")

    def _build_table(self) -> Table:
        elapsed = datetime.now(timezone.utc) - self._start
        hours, remainder = divmod(int(elapsed.total_seconds()), 3600)
        minutes, _ = divmod(remainder, 60)

        table = Table(
            title=f"biardtz  |  {hours}h {minutes}m  |  {self._total} detections  |  {len(self._species)} species",
            expand=True,
        )
        table.add_column("", width=2)
        table.add_column("Time", width=10)
        table.add_column("Species", ratio=2)
        table.add_column("Scientific Name", ratio=2)
        table.add_column("Confidence", justify="right", width=12)
        table.add_column("Direction", justify="center", width=6)

        for ts, det, verified in reversed(self._recent):
            conf = det.confidence
            if conf >= 0.75:
                style = "bold green"
            elif conf >= 0.5:
                style = "yellow"
            else:
                style = "dim"
            status = "" if verified else Text("?", style="bold yellow")
            table.add_row(
                status,
                ts, det.common_name, det.sci_name,
                Text(f"{conf:.1%}", style=style),
                det.direction or "",
            )

        return table

    async def run(self, detection_queue: asyncio.Queue) -> None:
        with Live(self._build_table(), refresh_per_second=4) as live:
            while True:
                item = await detection_queue.get()
                if isinstance(item, tuple) and len(item) == 2:
                    detection, verified = item
                else:
                    detection, verified = item, True
                ts = datetime.now(self._local_tz).strftime("%H:%M:%S")
                self._recent.append((ts, detection, verified))
                self._total += 1
                self._species.add(detection.common_name)
                live.update(self._build_table())
