"""Health monitoring for the biardtz pipeline.

Writes a JSON heartbeat file periodically so external tools (systemd, scripts,
``biardtz status``) can determine whether the pipeline is alive and processing.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import socket
import tempfile
from datetime import datetime, timezone
from pathlib import Path

_logger = logging.getLogger(__name__)

DEFAULT_HEALTH_DIR = Path("/mnt/ssd/biardtz")


def _sd_notify(msg: bytes) -> None:
    """Send a notification to systemd if NOTIFY_SOCKET is set.

    This is a minimal sd_notify implementation — avoids adding an external
    dependency just for one socket write.
    """
    addr = os.environ.get("NOTIFY_SOCKET")
    if not addr:
        return
    if addr[0] == "@":
        addr = "\0" + addr[1:]  # abstract socket
    try:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        sock.connect(addr)
        sock.sendall(msg)
        sock.close()
    except OSError:
        _logger.debug("sd_notify failed", exc_info=True)
HEARTBEAT_FILE = "heartbeat.json"
HEARTBEAT_INTERVAL = 10  # seconds


class HealthMonitor:
    """Writes periodic heartbeat files with pipeline status."""

    def __init__(self, health_dir: Path = DEFAULT_HEALTH_DIR):
        self._health_dir = health_dir
        self._heartbeat_path = health_dir / HEARTBEAT_FILE
        self._audio_ok = False
        self._last_detection_time: str | None = None
        self._detection_count = 0
        self._species_count = 0
        self._start_time = datetime.now(timezone.utc)
        self._errors: list[str] = []  # rolling window of recent errors

    def mark_audio_ok(self, ok: bool = True) -> None:
        self._audio_ok = ok

    def mark_detection(self) -> None:
        self._detection_count += 1
        self._last_detection_time = datetime.now(timezone.utc).isoformat()

    def set_species_count(self, count: int) -> None:
        self._species_count = count

    def record_error(self, msg: str) -> None:
        ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
        self._errors.append(f"[{ts}] {msg}")
        # Keep only last 10
        self._errors = self._errors[-10:]

    def _build_status(self) -> dict:
        now = datetime.now(timezone.utc)
        uptime_s = (now - self._start_time).total_seconds()
        return {
            "status": "ok" if self._audio_ok else "degraded",
            "pid": os.getpid(),
            "started": self._start_time.isoformat(),
            "uptime_seconds": int(uptime_s),
            "heartbeat": now.isoformat(),
            "audio_stream": "ok" if self._audio_ok else "disconnected",
            "detections": self._detection_count,
            "species": self._species_count,
            "last_detection": self._last_detection_time,
            "recent_errors": self._errors,
        }

    def _write_heartbeat(self) -> None:
        """Atomically write heartbeat file."""
        self._health_dir.mkdir(parents=True, exist_ok=True)
        status = self._build_status()
        # Write to temp file then rename for atomicity
        fd, tmp_path = tempfile.mkstemp(
            dir=self._health_dir, prefix=".heartbeat-", suffix=".tmp"
        )
        try:
            with os.fdopen(fd, "w") as f:
                json.dump(status, f, indent=2)
                f.write("\n")
            os.replace(tmp_path, self._heartbeat_path)
        except Exception:
            # Clean up temp file on failure
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

    async def run(self) -> None:
        """Run heartbeat loop — meant to be an asyncio task."""
        _logger.info("Health monitor writing to %s", self._heartbeat_path)
        while True:
            try:
                self._write_heartbeat()
                _sd_notify(b"WATCHDOG=1")
            except Exception:
                _logger.warning("Failed to write heartbeat", exc_info=True)
            await asyncio.sleep(HEARTBEAT_INTERVAL)

    def cleanup(self) -> None:
        """Write a final 'stopped' heartbeat."""
        try:
            self._audio_ok = False
            status = self._build_status()
            status["status"] = "stopped"
            self._health_dir.mkdir(parents=True, exist_ok=True)
            with open(self._heartbeat_path, "w") as f:
                json.dump(status, f, indent=2)
                f.write("\n")
        except Exception:
            pass


def read_heartbeat(health_dir: Path = DEFAULT_HEALTH_DIR) -> dict | None:
    """Read the current heartbeat file. Returns None if not found."""
    path = health_dir / HEARTBEAT_FILE
    try:
        with open(path) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return None
