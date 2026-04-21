"""Tests for biardtz.web.health_checks."""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

from biardtz.config import Config
from biardtz.web import health_checks

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_heartbeat(hb_dir: Path, data: dict) -> None:
    hb_dir.mkdir(parents=True, exist_ok=True)
    (hb_dir / "heartbeat.json").write_text(json.dumps(data))


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ago_iso(seconds: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(seconds=seconds)).isoformat()


def _make_db(path: Path) -> None:
    conn = sqlite3.connect(str(path))
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS detections (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            common_name TEXT NOT NULL,
            sci_name TEXT NOT NULL,
            confidence REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS audio_clips (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            common_name TEXT NOT NULL,
            filename TEXT NOT NULL
        );
    """)
    conn.executemany(
        "INSERT INTO detections (timestamp, common_name, sci_name, confidence) VALUES (?,?,?,?)",
        [
            ("2026-04-20T10:00:00+00:00", "Robin", "Erithacus rubecula", 0.9),
            ("2026-04-20T11:00:00+00:00", "Blackbird", "Turdus merula", 0.8),
            ("2026-04-20T12:00:00+00:00", "Robin", "Erithacus rubecula", 0.7),
        ],
    )
    conn.execute(
        "INSERT INTO audio_clips (common_name, filename) VALUES (?,?)",
        ("Robin", "robin_20260420.wav"),
    )
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# check_pipeline
# ---------------------------------------------------------------------------

class TestCheckPipeline:
    def test_no_heartbeat(self, tmp_path):
        with patch.object(health_checks, "read_heartbeat", return_value=None):
            result = health_checks.check_pipeline()
        assert result["status"] == "fail"
        assert result["pid"] is None
        assert "No heartbeat" in result["detail"]

    def test_pipeline_ok(self, tmp_path):
        hb = {
            "status": "ok",
            "pid": os.getpid(),
            "heartbeat": _now_iso(),
            "audio_stream": "ok",
            "detections": 42,
            "species": 5,
            "started": _ago_iso(3600),
            "uptime_seconds": 3600,
            "recent_errors": [],
        }
        with patch.object(health_checks, "read_heartbeat", return_value=hb):
            result = health_checks.check_pipeline()
        assert result["status"] == "ok"
        assert result["alive"] is True
        assert result["detections"] == 42

    def test_pipeline_dead_pid(self):
        hb = {
            "status": "ok",
            "pid": 99999999,
            "heartbeat": _now_iso(),
            "audio_stream": "ok",
            "detections": 0,
            "species": 0,
            "recent_errors": [],
        }
        with patch.object(health_checks, "read_heartbeat", return_value=hb):
            with patch("os.kill", side_effect=OSError):
                result = health_checks.check_pipeline()
        assert result["status"] == "fail"
        assert "not running" in result["detail"]

    def test_pipeline_stale_heartbeat(self):
        hb = {
            "status": "ok",
            "pid": os.getpid(),
            "heartbeat": _ago_iso(60),
            "audio_stream": "ok",
            "detections": 10,
            "species": 2,
            "recent_errors": [],
        }
        with patch.object(health_checks, "read_heartbeat", return_value=hb):
            result = health_checks.check_pipeline()
        assert result["status"] == "warn"
        assert "stale" in result["detail"]

    def test_pipeline_degraded(self):
        hb = {
            "status": "degraded",
            "pid": os.getpid(),
            "heartbeat": _now_iso(),
            "audio_stream": "disconnected",
            "detections": 0,
            "species": 0,
            "recent_errors": ["[12:00:00] Audio error"],
        }
        with patch.object(health_checks, "read_heartbeat", return_value=hb):
            result = health_checks.check_pipeline()
        assert result["status"] == "warn"
        assert result["audio"] == "disconnected"
        assert len(result["errors"]) == 1


# ---------------------------------------------------------------------------
# check_version
# ---------------------------------------------------------------------------

class TestCheckVersion:
    def test_returns_versions(self):
        result = health_checks.check_version()
        assert result["status"] == "ok"
        assert "biardtz_version" in result
        assert "python_version" in result


# ---------------------------------------------------------------------------
# check_database
# ---------------------------------------------------------------------------

class TestCheckDatabase:
    def test_file_not_found(self, tmp_path):
        result = health_checks.check_database(tmp_path / "nope.db")
        assert result["status"] == "fail"

    def test_file_exists(self, tmp_path):
        db_path = tmp_path / "test.db"
        _make_db(db_path)
        result = health_checks.check_database(db_path)
        assert result["status"] == "ok"
        assert result["size_mb"] >= 0
        assert "wal_mb" in result

    def test_with_wal_file(self, tmp_path):
        db_path = tmp_path / "test.db"
        _make_db(db_path)
        wal_path = tmp_path / "test.db-wal"
        wal_path.write_bytes(b"\x00" * 4096)
        result = health_checks.check_database(db_path)
        assert result["wal_mb"] >= 0


# ---------------------------------------------------------------------------
# check_config
# ---------------------------------------------------------------------------

class TestCheckConfig:
    def test_returns_config_values(self):
        config = Config()
        result = health_checks.check_config(config)
        assert result["status"] == "ok"
        assert result["location"] == "London"
        assert result["timezone"] == "Europe/London"


# ---------------------------------------------------------------------------
# Tier 1
# ---------------------------------------------------------------------------

class TestTier1:
    def test_tier1_returns_all_sections(self, tmp_path):
        config = Config(db_path=tmp_path / "test.db")
        _make_db(config.db_path)
        with patch.object(health_checks, "read_heartbeat", return_value=None):
            result = health_checks.tier1_checks(config)
        assert "pipeline" in result
        assert "software" in result
        assert "database" in result
        assert "config" in result


# ---------------------------------------------------------------------------
# Tier 2 checks
# ---------------------------------------------------------------------------

class TestCheckCpuTemp:
    def test_reads_thermal_zone(self, tmp_path):
        mock_path = MagicMock()
        mock_path.exists.return_value = True
        mock_path.read_text.return_value = "45000\n"
        with patch("biardtz.web.health_checks.Path") as MockPath:
            MockPath.return_value = mock_path
            result = health_checks.check_cpu_temp()
        assert result["status"] == "ok"
        assert result["temp_c"] == 45.0

    def test_high_temp_warns(self):
        mock_path = MagicMock()
        mock_path.exists.return_value = True
        mock_path.read_text.return_value = "75000\n"
        with patch("biardtz.web.health_checks.Path") as MockPath:
            MockPath.return_value = mock_path
            result = health_checks.check_cpu_temp()
        assert result["status"] == "warn"

    def test_unavailable(self):
        mock_path = MagicMock()
        mock_path.exists.return_value = False
        with patch("biardtz.web.health_checks.Path") as MockPath:
            MockPath.return_value = mock_path
            result = health_checks.check_cpu_temp()
        assert result["status"] == "warn"
        assert "Unavailable" in result["detail"]


class TestCheckMemory:
    def test_parses_meminfo(self):
        meminfo = "MemTotal:       8000000 kB\nMemFree:         500000 kB\nMemAvailable:   4000000 kB\n"
        mock_path = MagicMock()
        mock_path.read_text.return_value = meminfo
        with patch("biardtz.web.health_checks.Path") as MockPath:
            MockPath.return_value = mock_path
            result = health_checks.check_memory()
        assert result["status"] == "ok"
        assert result["percent"] == 50
        assert result["total_mb"] == round(8000000 / 1024)

    def test_high_usage_warns(self):
        meminfo = "MemTotal:       8000000 kB\nMemFree:         100000 kB\nMemAvailable:   1200000 kB\n"
        mock_path = MagicMock()
        mock_path.read_text.return_value = meminfo
        with patch("biardtz.web.health_checks.Path") as MockPath:
            MockPath.return_value = mock_path
            result = health_checks.check_memory()
        assert result["status"] == "warn"


class TestCheckDisk:
    def test_reads_statvfs(self):
        mock_stat = MagicMock()
        mock_stat.f_blocks = 1000000
        mock_stat.f_frsize = 4096
        mock_stat.f_bavail = 500000
        with patch("os.statvfs", return_value=mock_stat):
            result = health_checks.check_disk()
        assert result["status"] == "ok"
        assert result["percent"] == 50

    def test_unavailable(self):
        with patch("os.statvfs", side_effect=OSError):
            result = health_checks.check_disk()
        assert result["status"] == "warn"


class TestCheckMicrophone:
    def test_respeaker_detected(self):
        mock_r = MagicMock()
        mock_r.stdout = "card 1: ReSpeaker [ReSpeaker]\n"
        with patch.object(health_checks, "_run", return_value=mock_r):
            result = health_checks.check_microphone()
        assert result["status"] == "ok"
        assert "ReSpeaker" in result["detail"]

    def test_no_device(self):
        mock_r = MagicMock()
        mock_r.stdout = ""
        with patch.object(health_checks, "_run", return_value=mock_r):
            result = health_checks.check_microphone()
        assert result["status"] == "fail"

    def test_arecord_not_found(self):
        with patch.object(health_checks, "_run", return_value=None):
            result = health_checks.check_microphone()
        assert result["status"] == "warn"


class TestCheckNetwork:
    def test_full_network(self):
        def mock_run(cmd, **kw):
            r = MagicMock()
            r.returncode = 0
            if cmd[0] == "iwgetid":
                r.stdout = "MyWiFi\n"
            elif cmd[0] == "hostname":
                r.stdout = "192.168.1.50 100.100.1.1\n"
            elif cmd[0] == "tailscale":
                r.stdout = json.dumps({"Self": {"TailscaleIPs": ["100.100.1.1"]}})
            return r
        with patch.object(health_checks, "_run", side_effect=mock_run):
            result = health_checks.check_network()
        assert result["ssid"] == "MyWiFi"
        assert "192.168.1.50" in result["ips"]
        assert result["tailscale"] == "100.100.1.1"

    def test_no_network(self):
        with patch.object(health_checks, "_run", return_value=None):
            result = health_checks.check_network()
        assert result["ssid"] is None


class TestCheckSystemd:
    def test_active(self):
        def mock_run(cmd, **kw):
            r = MagicMock()
            if "is-active" in cmd:
                r.stdout = "active\n"
            elif "show" in cmd:
                r.stdout = "ActiveEnterTimestamp=Mon 2026-04-20 10:00:00 BST\n"
            return r
        with patch.object(health_checks, "_run", side_effect=mock_run):
            result = health_checks.check_systemd()
        assert result["status"] == "ok"
        assert result["active"] is True

    def test_not_found(self):
        with patch.object(health_checks, "_run", return_value=None):
            result = health_checks.check_systemd()
        assert result["status"] == "warn"


class TestCheckSystemUptime:
    def test_parses_uptime(self):
        mock_path = MagicMock()
        mock_path.read_text.return_value = "86500.50 172000.00\n"
        with patch("biardtz.web.health_checks.Path") as MockPath:
            MockPath.return_value = mock_path
            result = health_checks.check_system_uptime()
        assert result["status"] == "ok"
        assert result["seconds"] == 86500
        assert "1d" in result["detail"]


class TestCheckBirdnet:
    def test_path_not_found(self):
        config = Config(birdnet_path=Path("/nonexistent"))
        result = health_checks.check_birdnet(config)
        assert result["status"] == "fail"

    def test_model_found(self, tmp_path):
        bn_path = tmp_path / "BirdNET-Analyzer"
        model_dir = bn_path / "checkpoints" / "V2.4"
        model_dir.mkdir(parents=True)
        (model_dir / "BirdNET_GLOBAL_6K_V2.4_Model_FP16.tflite").write_bytes(b"model")
        labels = model_dir / "BirdNET_GLOBAL_6K_V2.4_Labels.txt"
        labels.write_text("Species_A\nSpecies_B\nSpecies_C\n")
        config = Config(birdnet_path=bn_path)
        result = health_checks.check_birdnet(config)
        assert result["status"] == "ok"
        assert result["label_count"] == 3
        assert result["model_found"] is True


class TestCheckDbIntegrity:
    def test_file_not_found(self, tmp_path):
        result = health_checks.check_db_integrity(tmp_path / "nope.db")
        assert result["status"] == "fail"

    def test_valid_db(self, tmp_path):
        db_path = tmp_path / "test.db"
        _make_db(db_path)
        result = health_checks.check_db_integrity(db_path)
        assert result["status"] == "ok"
        assert result["detail"] == "ok"
        assert result["total_detections"] == 3
        assert result["total_species"] == 2
        assert result["audio_clips"] == 1


# ---------------------------------------------------------------------------
# quick_status
# ---------------------------------------------------------------------------

class TestQuickStatus:
    def test_no_heartbeat(self):
        with patch.object(health_checks, "read_heartbeat", return_value=None):
            assert health_checks.quick_status() == "red"

    def test_ok(self):
        hb = {"pid": os.getpid(), "heartbeat": _now_iso(), "status": "ok"}
        with patch.object(health_checks, "read_heartbeat", return_value=hb):
            assert health_checks.quick_status() == "green"

    def test_degraded(self):
        hb = {"pid": os.getpid(), "heartbeat": _now_iso(), "status": "degraded"}
        with patch.object(health_checks, "read_heartbeat", return_value=hb):
            assert health_checks.quick_status() == "yellow"

    def test_dead_pid(self):
        hb = {"pid": 99999999, "heartbeat": _now_iso(), "status": "ok"}
        with patch.object(health_checks, "read_heartbeat", return_value=hb):
            with patch("os.kill", side_effect=OSError):
                assert health_checks.quick_status() == "red"

    def test_stale_heartbeat(self):
        hb = {"pid": os.getpid(), "heartbeat": _ago_iso(60), "status": "ok"}
        with patch.object(health_checks, "read_heartbeat", return_value=hb):
            assert health_checks.quick_status() == "yellow"


# ---------------------------------------------------------------------------
# Tier 2 combined
# ---------------------------------------------------------------------------

class TestTier2:
    def test_tier2_returns_all_sections(self, tmp_path):
        config = Config(db_path=tmp_path / "test.db", birdnet_path=tmp_path / "bn")
        _make_db(config.db_path)
        with patch.object(health_checks, "_run", return_value=None), \
             patch("os.statvfs", side_effect=OSError):
            result = health_checks.tier2_checks(config)
        assert "hardware" in result
        assert "network" in result
        assert "service" in result
        assert "uptime" in result
        assert "birdnet" in result
        assert "db_integrity" in result
