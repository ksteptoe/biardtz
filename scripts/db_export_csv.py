#!/usr/bin/env python3
"""Export biardtz detections to CSV.

Safe to run while biardtz is running (opens database in read-only mode).

Usage:
    python scripts/db_export_csv.py [--db-path /mnt/ssd/detections.db] \
                                     [--output detections.csv] \
                                     [--since 2026-01-01]
"""
import argparse
import csv
import sqlite3
import sys
from pathlib import Path

DEFAULT_DB = Path("/mnt/ssd/detections.db")


def export(db_path: Path, output: Path, since: str | None) -> None:
    if not db_path.exists():
        print(f"Error: database not found: {db_path}", file=sys.stderr)
        sys.exit(1)

    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        query = (
            "SELECT id, timestamp, common_name, sci_name, confidence,"
            " latitude, longitude, bearing, direction FROM detections"
        )
        params: tuple = ()
        if since:
            query += " WHERE timestamp >= ?"
            params = (since,)
        query += " ORDER BY timestamp"

        cursor = conn.execute(query, params)
        columns = [desc[0] for desc in cursor.description]

        with open(output, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(columns)
            count = 0
            for row in cursor:
                writer.writerow(row)
                count += 1

        print(f"Exported {count} detections to {output}")
    finally:
        conn.close()


def main():
    parser = argparse.ArgumentParser(description="Export biardtz detections to CSV")
    parser.add_argument("--db-path", type=Path, default=DEFAULT_DB)
    parser.add_argument("--output", "-o", type=Path, default=Path("detections.csv"),
                        help="Output CSV file (default: detections.csv)")
    parser.add_argument("--since", type=str, default=None,
                        help="ISO date filter, e.g. 2026-01-01")
    args = parser.parse_args()
    export(args.db_path, args.output, args.since)


if __name__ == "__main__":
    main()
