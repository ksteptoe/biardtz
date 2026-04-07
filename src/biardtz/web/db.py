"""Read-only database access for the web dashboard."""

from __future__ import annotations

import sqlite3
from datetime import datetime, time, timezone
from pathlib import Path
from zoneinfo import ZoneInfo


def get_connection(db_path: Path) -> sqlite3.Connection:
    """Open a read-only connection with WAL mode."""
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _has_column(conn: sqlite3.Connection, column: str) -> bool:
    """Check if a column exists in the detections table."""
    cursor = conn.execute("PRAGMA table_info(detections)")
    return any(row[1] == column for row in cursor.fetchall())


def _today_start_utc(local_tz: ZoneInfo) -> str:
    """Return the UTC ISO timestamp for the start of today in *local_tz*."""
    now_local = datetime.now(local_tz)
    start_of_day = datetime.combine(now_local.date(), time.min, tzinfo=local_tz)
    return start_of_day.astimezone(timezone.utc).isoformat()


def recent_detections(conn: sqlite3.Connection, limit: int = 20) -> list[dict]:
    """Most recent detections, newest first."""
    has_bearing = _has_column(conn, "bearing")
    if has_bearing:
        query = (
            "SELECT id, timestamp, common_name, sci_name, confidence, "
            "bearing, direction FROM detections ORDER BY timestamp DESC LIMIT ?"
        )
    else:
        query = (
            "SELECT id, timestamp, common_name, sci_name, confidence "
            "FROM detections ORDER BY timestamp DESC LIMIT ?"
        )
    rows = conn.execute(query, (limit,)).fetchall()
    results = [dict(r) for r in rows]
    if not has_bearing:
        for r in results:
            r["bearing"] = None
            r["direction"] = None
    return results


def species_stats(
    conn: sqlite3.Connection,
    local_tz: ZoneInfo | None = None,
) -> dict:
    """Today's and all-time stats + leaderboard.

    If *local_tz* is provided, "today" is calculated in that timezone.
    Otherwise falls back to UTC.
    """
    if local_tz is not None:
        today_start = _today_start_utc(local_tz)
    else:
        today_start = _today_start_utc(ZoneInfo("UTC"))

    # Today's counts (using local timezone boundary)
    row = conn.execute(
        "SELECT COUNT(*) as count, COUNT(DISTINCT common_name) as species "
        "FROM detections WHERE timestamp >= ?",
        (today_start,),
    ).fetchone()
    today_count = row["count"]
    today_species = row["species"]

    # All-time unique species
    row = conn.execute(
        "SELECT COUNT(DISTINCT common_name) as total FROM detections",
    ).fetchone()
    all_time_species = row["total"]

    # Leaderboard (all-time, top 15)
    rows = conn.execute(
        "SELECT common_name, sci_name, COUNT(*) as count "
        "FROM detections GROUP BY common_name "
        "ORDER BY count DESC LIMIT 15",
    ).fetchall()
    leaderboard = [dict(r) for r in rows]

    return {
        "today_count": today_count,
        "today_species": today_species,
        "all_time_species": all_time_species,
        "leaderboard": leaderboard,
    }
