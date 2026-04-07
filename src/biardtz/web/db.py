"""Read-only database access for the web dashboard."""

from __future__ import annotations

import sqlite3
from pathlib import Path


def get_connection(db_path: Path) -> sqlite3.Connection:
    """Open a read-only connection with WAL mode."""
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def recent_detections(conn: sqlite3.Connection, limit: int = 20) -> list[dict]:
    """Most recent detections, newest first."""
    rows = conn.execute(
        "SELECT id, timestamp, common_name, sci_name, confidence, "
        "bearing, direction FROM detections ORDER BY timestamp DESC LIMIT ?",
        (limit,),
    ).fetchall()
    return [dict(r) for r in rows]


def species_stats(conn: sqlite3.Connection) -> dict:
    """Today's and all-time stats + leaderboard."""
    # Today's counts
    row = conn.execute(
        "SELECT COUNT(*) as count, COUNT(DISTINCT common_name) as species "
        "FROM detections WHERE date(timestamp) = date('now')",
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
