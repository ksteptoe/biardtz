"""Tests for biardtz.health."""

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

from biardtz.health import HealthMonitor, read_heartbeat


class TestHealthMonitor:
    def test_initial_status_is_degraded(self, tmp_path):
        hm = HealthMonitor(health_dir=tmp_path)
        status = hm._build_status()
        assert status["status"] == "degraded"
        assert status["audio_stream"] == "disconnected"
        assert status["detections"] == 0
        assert status["species"] == 0
        assert status["last_detection"] is None
        assert status["recent_errors"] == []

    def test_mark_audio_ok(self, tmp_path):
        hm = HealthMonitor(health_dir=tmp_path)
        hm.mark_audio_ok(True)
        status = hm._build_status()
        assert status["status"] == "ok"
        assert status["audio_stream"] == "ok"

    def test_mark_audio_not_ok(self, tmp_path):
        hm = HealthMonitor(health_dir=tmp_path)
        hm.mark_audio_ok(True)
        hm.mark_audio_ok(False)
        status = hm._build_status()
        assert status["status"] == "degraded"

    def test_mark_detection_increments(self, tmp_path):
        hm = HealthMonitor(health_dir=tmp_path)
        hm.mark_detection()
        hm.mark_detection()
        hm.mark_detection()
        status = hm._build_status()
        assert status["detections"] == 3
        assert status["last_detection"] is not None

    def test_set_species_count(self, tmp_path):
        hm = HealthMonitor(health_dir=tmp_path)
        hm.set_species_count(7)
        status = hm._build_status()
        assert status["species"] == 7

    def test_record_error(self, tmp_path):
        hm = HealthMonitor(health_dir=tmp_path)
        hm.record_error("test error")
        status = hm._build_status()
        assert len(status["recent_errors"]) == 1
        assert "test error" in status["recent_errors"][0]

    def test_record_error_rolling_window(self, tmp_path):
        hm = HealthMonitor(health_dir=tmp_path)
        for i in range(15):
            hm.record_error(f"error {i}")
        status = hm._build_status()
        assert len(status["recent_errors"]) == 10
        assert "error 14" in status["recent_errors"][-1]
        assert "error 5" in status["recent_errors"][0]

    def test_status_has_pid(self, tmp_path):
        hm = HealthMonitor(health_dir=tmp_path)
        status = hm._build_status()
        assert status["pid"] == os.getpid()

    def test_status_has_uptime(self, tmp_path):
        hm = HealthMonitor(health_dir=tmp_path)
        status = hm._build_status()
        assert isinstance(status["uptime_seconds"], int)
        assert status["uptime_seconds"] >= 0

    def test_status_has_heartbeat_timestamp(self, tmp_path):
        hm = HealthMonitor(health_dir=tmp_path)
        status = hm._build_status()
        # Should be a valid ISO timestamp
        datetime.fromisoformat(status["heartbeat"])

    def test_status_has_started_timestamp(self, tmp_path):
        hm = HealthMonitor(health_dir=tmp_path)
        status = hm._build_status()
        datetime.fromisoformat(status["started"])


class TestWriteHeartbeat:
    def test_writes_json_file(self, tmp_path):
        hm = HealthMonitor(health_dir=tmp_path)
        hm._write_heartbeat()
        hb_path = tmp_path / "heartbeat.json"
        assert hb_path.exists()
        data = json.loads(hb_path.read_text())
        assert data["pid"] == os.getpid()

    def test_creates_directory(self, tmp_path):
        health_dir = tmp_path / "sub" / "dir"
        hm = HealthMonitor(health_dir=health_dir)
        hm._write_heartbeat()
        assert (health_dir / "heartbeat.json").exists()

    def test_atomic_write(self, tmp_path):
        """No partial .tmp files left behind after successful write."""
        hm = HealthMonitor(health_dir=tmp_path)
        hm._write_heartbeat()
        tmp_files = list(tmp_path.glob(".heartbeat-*.tmp"))
        assert tmp_files == []


class TestCleanup:
    def test_writes_stopped_status(self, tmp_path):
        hm = HealthMonitor(health_dir=tmp_path)
        hm.mark_audio_ok(True)
        hm.cleanup()
        data = json.loads((tmp_path / "heartbeat.json").read_text())
        assert data["status"] == "stopped"
        assert data["audio_stream"] == "disconnected"


class TestReadHeartbeat:
    def test_returns_none_when_missing(self, tmp_path):
        result = read_heartbeat(health_dir=tmp_path)
        assert result is None

    def test_reads_valid_heartbeat(self, tmp_path):
        hb_data = {"status": "ok", "pid": 1234}
        (tmp_path / "heartbeat.json").write_text(json.dumps(hb_data))
        result = read_heartbeat(health_dir=tmp_path)
        assert result == hb_data

    def test_returns_none_on_invalid_json(self, tmp_path):
        (tmp_path / "heartbeat.json").write_text("not json{{{")
        result = read_heartbeat(health_dir=tmp_path)
        assert result is None


class TestSdNotify:
    def test_no_op_without_env_var(self, tmp_path):
        """sd_notify does nothing when NOTIFY_SOCKET is not set."""
        from biardtz.health import _sd_notify
        # Should not raise
        with patch.dict(os.environ, {}, clear=True):
            _sd_notify(b"WATCHDOG=1")


class TestHealthMonitorRun:
    def test_run_writes_heartbeat(self, tmp_path):
        """run() should write heartbeat and can be cancelled."""
        import asyncio

        async def _run():
            hm = HealthMonitor(health_dir=tmp_path)
            task = asyncio.create_task(hm.run())
            await asyncio.sleep(0.2)
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        asyncio.run(_run())
        assert (tmp_path / "heartbeat.json").exists()
