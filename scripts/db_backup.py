#!/usr/bin/env python3
"""Back up the biardtz SQLite database using the online backup API.

Safe to run while biardtz is running (SQLite backup API handles WAL correctly).

Usage:
    python scripts/db_backup.py [--db-path /mnt/ssd/detections.db] \
                                 [--backup-dir ~/backups/biardtz] \
                                 [--keep 7]
"""
import argparse
import logging
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

DEFAULT_DB = Path("/mnt/ssd/detections.db")
DEFAULT_BACKUP_DIR = Path.home() / "backups" / "biardtz"
DEFAULT_KEEP = 7


def backup(db_path: Path, backup_dir: Path, keep: int) -> None:
    if not db_path.exists():
        log.error("Source database not found: %s", db_path)
        sys.exit(1)

    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    dest = backup_dir / f"detections-{stamp}.db"

    log.info("Backing up %s -> %s", db_path, dest)
    src_conn = sqlite3.connect(db_path)
    dst_conn = sqlite3.connect(dest)
    try:
        src_conn.backup(dst_conn)
        log.info("Backup complete: %s (%.1f MB)", dest, dest.stat().st_size / 1e6)
    finally:
        dst_conn.close()
        src_conn.close()

    # Prune old backups (keep newest N)
    backups = sorted(backup_dir.glob("detections-*.db"), reverse=True)
    for old in backups[keep:]:
        log.info("Removing old backup: %s", old.name)
        old.unlink()


def main():
    parser = argparse.ArgumentParser(description="Back up biardtz database")
    parser.add_argument("--db-path", type=Path, default=DEFAULT_DB)
    parser.add_argument("--backup-dir", type=Path, default=DEFAULT_BACKUP_DIR)
    parser.add_argument("--keep", type=int, default=DEFAULT_KEEP,
                        help="Number of backups to keep (default: 7)")
    args = parser.parse_args()
    backup(args.db_path, args.backup_dir, args.keep)


if __name__ == "__main__":
    main()
