"""Read-only database access for the web dashboard."""

from __future__ import annotations

import re
import sqlite3
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

_GLOB_CHARS = re.compile(r"[*?\[\]]")


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


def recent_detections(
    conn: sqlite3.Connection,
    limit: int = 20,
    offset: int = 0,
    species: str | None = None,
    min_confidence: float | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    search: str | None = None,
) -> list[dict]:
    """Most recent detections, newest first, with optional filters."""
    has_bearing = _has_column(conn, "bearing")
    cols = "id, timestamp, common_name, sci_name, confidence"
    if has_bearing:
        cols += ", bearing, direction"

    conditions: list[str] = []
    params: list = []

    if species:
        conditions.append("common_name = ?")
        params.append(species)
    if min_confidence is not None:
        conditions.append("confidence >= ?")
        params.append(min_confidence)
    if date_from:
        conditions.append("timestamp >= ?")
        params.append(date_from)
    if date_to:
        conditions.append("timestamp < ?")
        params.append(date_to)
    if search:
        if _GLOB_CHARS.search(search):
            conditions.append("common_name GLOB ?")
            params.append(search)
        else:
            conditions.append("common_name LIKE ?")
            params.append(f"%{search}%")

    where = ""
    if conditions:
        where = "WHERE " + " AND ".join(conditions)

    query = f"SELECT {cols} FROM detections {where} ORDER BY timestamp DESC LIMIT ? OFFSET ?"
    params.extend([limit, offset])

    rows = conn.execute(query, params).fetchall()
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


def _days_ago_utc(days: int, local_tz: ZoneInfo | None = None) -> str:
    """Return UTC ISO timestamp for *days* ago at start of that local day."""
    tz = local_tz or ZoneInfo("UTC")
    now_local = datetime.now(tz)
    target = now_local - timedelta(days=days)
    start_of_day = datetime.combine(target.date(), time.min, tzinfo=tz)
    return start_of_day.astimezone(timezone.utc).isoformat()


def _utc_offset_modifier(local_tz: ZoneInfo | None) -> str:
    """Return an SQLite datetime modifier like '+1 hours' for the current UTC offset."""
    tz = local_tz or ZoneInfo("UTC")
    offset_sec = int(datetime.now(tz).utcoffset().total_seconds())
    hours = offset_sec // 3600
    sign = "+" if hours >= 0 else ""
    return f"{sign}{hours} hours"


def detection_timeline(
    conn: sqlite3.Connection,
    days: int = 7,
    local_tz: ZoneInfo | None = None,
) -> list[dict]:
    """Hourly detection counts for the last *days* days, in local time."""
    since = _days_ago_utc(days, local_tz)
    modifier = _utc_offset_modifier(local_tz)
    rows = conn.execute(
        f"SELECT strftime('%Y-%m-%dT%H:00:00', timestamp, '{modifier}') AS hour, "
        "COUNT(*) AS count "
        "FROM detections WHERE timestamp >= ? "
        "GROUP BY hour ORDER BY hour",
        (since,),
    ).fetchall()
    return [dict(r) for r in rows]


def species_frequency(
    conn: sqlite3.Connection,
    days: int = 30,
    limit: int = 15,
    local_tz: ZoneInfo | None = None,
) -> list[dict]:
    """Top species by detection count over the last *days* days."""
    since = _days_ago_utc(days, local_tz)
    rows = conn.execute(
        "SELECT common_name, sci_name, COUNT(*) AS count "
        "FROM detections WHERE timestamp >= ? "
        "GROUP BY common_name ORDER BY count DESC LIMIT ?",
        (since, limit),
    ).fetchall()
    return [dict(r) for r in rows]


def activity_heatmap(
    conn: sqlite3.Connection,
    days: int = 30,
    local_tz: ZoneInfo | None = None,
) -> list[dict]:
    """Detection counts by day-of-week and hour-of-day."""
    since = _days_ago_utc(days, local_tz)
    rows = conn.execute(
        "SELECT CAST(strftime('%w', timestamp) AS INTEGER) AS dow, "
        "CAST(strftime('%H', timestamp) AS INTEGER) AS hour, "
        "COUNT(*) AS count "
        "FROM detections WHERE timestamp >= ? "
        "GROUP BY dow, hour",
        (since,),
    ).fetchall()
    return [dict(r) for r in rows]


def daily_trend(
    conn: sqlite3.Connection,
    days: int = 30,
    local_tz: ZoneInfo | None = None,
) -> list[dict]:
    """Daily detection count and unique species over the last *days* days."""
    since = _days_ago_utc(days, local_tz)
    rows = conn.execute(
        "SELECT date(timestamp) AS day, COUNT(*) AS count, "
        "COUNT(DISTINCT common_name) AS species "
        "FROM detections WHERE timestamp >= ? "
        "GROUP BY day ORDER BY day",
        (since,),
    ).fetchall()
    return [dict(r) for r in rows]


def species_audio_map(conn: sqlite3.Connection) -> dict[str, str]:
    """Return {common_name: filename} for all species with audio clips."""
    try:
        rows = conn.execute("SELECT common_name, filename FROM audio_clips").fetchall()
        return {row["common_name"]: row["filename"] for row in rows}
    except Exception:
        return {}  # table doesn't exist yet


def species_list(conn: sqlite3.Connection, q: str | None = None) -> list[dict]:
    """Distinct species, optionally filtered by prefix/substring."""
    if q:
        if _GLOB_CHARS.search(q):
            rows = conn.execute(
                "SELECT DISTINCT common_name, sci_name FROM detections "
                "WHERE common_name GLOB ? ORDER BY common_name",
                (q,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT DISTINCT common_name, sci_name FROM detections "
                "WHERE common_name LIKE ? ORDER BY common_name",
                (f"%{q}%",),
            ).fetchall()
    else:
        rows = conn.execute(
            "SELECT DISTINCT common_name, sci_name FROM detections "
            "ORDER BY common_name",
        ).fetchall()
    return [dict(r) for r in rows]
