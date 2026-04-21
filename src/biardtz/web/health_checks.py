"""Health check probe functions for the web dashboard.

Each probe returns a dict with at least a ``status`` field (ok/warn/fail)
and descriptive ``label`` and ``detail`` fields. Subprocess calls use
timeout=5 to avoid blocking.
"""

from __future__ import annotations

import os
import platform
import sqlite3
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from ..health import read_heartbeat


def _run(cmd: list[str], timeout: int = 5) -> subprocess.CompletedProcess | None:
    """Run a subprocess with timeout, returning None on failure."""
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return None


# ---------------------------------------------------------------------------
# Tier 1 — instant checks (no subprocess, no heavy I/O)
# ---------------------------------------------------------------------------


def check_pipeline() -> dict:
    """Pipeline status from heartbeat file."""
    hb = read_heartbeat()
    if hb is None:
        return {
            "status": "fail",
            "label": "Pipeline",
            "detail": "No heartbeat file",
            "pid": None,
            "detections": 0,
            "species": 0,
            "heartbeat_age": None,
            "audio": "unknown",
            "errors": [],
        }

    pid = hb.get("pid")
    alive = False
    if pid:
        try:
            os.kill(pid, 0)
            alive = True
        except (OSError, TypeError):
            pass

    hb_age = None
    hb_time = hb.get("heartbeat", "")
    if hb_time:
        try:
            hb_dt = datetime.fromisoformat(hb_time)
            hb_age = int((datetime.now(timezone.utc) - hb_dt).total_seconds())
        except ValueError:
            pass

    pipeline_status = hb.get("status", "unknown")
    if not alive:
        status = "fail"
        detail = f"PID {pid} not running"
    elif hb_age is not None and hb_age > 120:
        status = "fail"
        detail = f"Heartbeat {hb_age}s ago (dead)"
    elif hb_age is not None and hb_age > 30:
        status = "warn"
        detail = f"Heartbeat {hb_age}s ago (stale)"
    elif pipeline_status == "degraded":
        status = "warn"
        detail = "Degraded"
    else:
        status = "ok"
        detail = f"PID {pid} running"

    return {
        "status": status,
        "label": "Pipeline",
        "detail": detail,
        "pid": pid,
        "alive": alive,
        "detections": hb.get("detections", 0),
        "species": hb.get("species", 0),
        "heartbeat_age": hb_age,
        "audio": hb.get("audio_stream", "unknown"),
        "started": hb.get("started"),
        "uptime_seconds": hb.get("uptime_seconds", 0),
        "errors": hb.get("recent_errors", []),
    }


def check_version() -> dict:
    """Software version info."""
    try:
        from biardtz import __version__
    except Exception:
        __version__ = "unknown"

    return {
        "status": "ok",
        "label": "Software",
        "biardtz_version": __version__,
        "python_version": platform.python_version(),
    }


def check_database(db_path: Path) -> dict:
    """Database file size and basic info (no heavy queries)."""
    if not db_path.exists():
        return {"status": "fail", "label": "Database", "detail": "File not found"}

    size_mb = db_path.stat().st_size / (1024 * 1024)

    # Check WAL file size
    wal_path = db_path.parent / (db_path.name + "-wal")
    wal_mb = wal_path.stat().st_size / (1024 * 1024) if wal_path.exists() else 0

    return {
        "status": "ok",
        "label": "Database",
        "detail": f"{size_mb:.1f} MB",
        "size_mb": round(size_mb, 1),
        "wal_mb": round(wal_mb, 1),
        "path": str(db_path),
    }


def check_config(config) -> dict:
    """Key config values."""
    return {
        "status": "ok",
        "label": "Config",
        "location": config.location_name,
        "latitude": config.latitude,
        "longitude": config.longitude,
        "confidence_threshold": config.confidence_threshold,
        "sample_rate": config.sample_rate,
        "channels": config.channels,
        "timezone": config.tz_name,
    }


def tier1_checks(config) -> dict:
    """Run all Tier 1 (instant) checks. Returns combined dict."""
    return {
        "pipeline": check_pipeline(),
        "software": check_version(),
        "database": check_database(config.db_path),
        "config": check_config(config),
    }


# ---------------------------------------------------------------------------
# Tier 2 — async-safe but heavier (subprocess, DB queries)
# ---------------------------------------------------------------------------


def check_cpu_temp() -> dict:
    """CPU temperature from thermal zone."""
    try:
        temp_path = Path("/sys/class/thermal/thermal_zone0/temp")
        if temp_path.exists():
            millideg = int(temp_path.read_text().strip())
            temp_c = millideg / 1000
            status = "ok" if temp_c < 70 else ("warn" if temp_c < 80 else "fail")
            return {
                "status": status,
                "label": "CPU Temp",
                "detail": f"{temp_c:.1f}°C",
                "temp_c": round(temp_c, 1),
            }
    except (OSError, ValueError):
        pass
    return {"status": "warn", "label": "CPU Temp", "detail": "Unavailable"}


def check_memory() -> dict:
    """Memory usage from /proc/meminfo."""
    try:
        meminfo = Path("/proc/meminfo").read_text()
        values = {}
        for line in meminfo.splitlines():
            parts = line.split()
            if len(parts) >= 2:
                values[parts[0].rstrip(":")] = int(parts[1])  # kB

        total = values.get("MemTotal", 0)
        available = values.get("MemAvailable", 0)
        if total > 0:
            used = total - available
            pct = int(used / total * 100)
            status = "ok" if pct < 80 else ("warn" if pct < 90 else "fail")
            return {
                "status": status,
                "label": "Memory",
                "detail": f"{pct}% used",
                "total_mb": round(total / 1024),
                "used_mb": round(used / 1024),
                "percent": pct,
            }
    except (OSError, ValueError):
        pass
    return {"status": "warn", "label": "Memory", "detail": "Unavailable"}


def check_disk() -> dict:
    """Disk usage for /mnt/ssd."""
    try:
        st = os.statvfs("/mnt/ssd")
        total = st.f_blocks * st.f_frsize
        free = st.f_bavail * st.f_frsize
        used = total - free
        pct = int(used / total * 100) if total > 0 else 0
        status = "ok" if pct < 80 else ("warn" if pct < 90 else "fail")
        return {
            "status": status,
            "label": "Disk",
            "detail": f"{pct}% used ({free // (1024**3)} GB free)",
            "total_gb": round(total / (1024**3), 1),
            "free_gb": round(free / (1024**3), 1),
            "percent": pct,
        }
    except OSError:
        return {"status": "warn", "label": "Disk", "detail": "Unavailable"}


def check_microphone() -> dict:
    """Check for audio capture device via arecord."""
    r = _run(["arecord", "-l"])
    if r is None:
        return {"status": "warn", "label": "Microphone", "detail": "arecord not found"}
    if "ReSpeaker" in r.stdout:
        return {"status": "ok", "label": "Microphone", "detail": "ReSpeaker detected"}
    if "card " in r.stdout:
        return {"status": "warn", "label": "Microphone", "detail": "Device found (not ReSpeaker)"}
    return {"status": "fail", "label": "Microphone", "detail": "No capture devices"}


def check_network() -> dict:
    """WiFi SSID and IP addresses."""
    result = {"status": "ok", "label": "Network", "detail": "", "ips": [], "ssid": None, "tailscale": None}

    # WiFi SSID
    r = _run(["iwgetid", "-r"])
    if r and r.stdout.strip():
        result["ssid"] = r.stdout.strip()

    # IP addresses (non-loopback)
    r = _run(["hostname", "-I"])
    if r and r.stdout.strip():
        result["ips"] = r.stdout.strip().split()

    # Tailscale
    r = _run(["tailscale", "status", "--json"])
    if r and r.returncode == 0:
        try:
            import json
            ts = json.loads(r.stdout)
            self_node = ts.get("Self", {})
            ts_ips = self_node.get("TailscaleIPs", [])
            result["tailscale"] = ts_ips[0] if ts_ips else "connected"
        except (ValueError, KeyError, IndexError):
            result["tailscale"] = "connected"
    elif r is not None:
        result["tailscale"] = "not connected"

    parts = []
    if result["ssid"]:
        parts.append(result["ssid"])
    if result["ips"]:
        parts.append(result["ips"][0])
    result["detail"] = " · ".join(parts) if parts else "No network info"

    return result


def check_systemd() -> dict:
    """Systemd service status and uptime."""
    r = _run(["systemctl", "is-active", "biardtz"])
    if r is None:
        return {"status": "warn", "label": "Service", "detail": "systemctl not found"}

    active = r.stdout.strip()
    if active == "active":
        # Get uptime
        r2 = _run(["systemctl", "show", "biardtz", "--property=ActiveEnterTimestamp"])
        uptime_str = None
        if r2 and r2.stdout.strip():
            uptime_str = r2.stdout.strip().split("=", 1)[-1]
        return {
            "status": "ok",
            "label": "Service",
            "detail": "active",
            "active": True,
            "since": uptime_str,
        }

    return {
        "status": "fail" if active == "failed" else "warn",
        "label": "Service",
        "detail": active,
        "active": False,
        "since": None,
    }


def check_system_uptime() -> dict:
    """System uptime from /proc/uptime."""
    try:
        raw = Path("/proc/uptime").read_text().split()[0]
        seconds = int(float(raw))
        days, rem = divmod(seconds, 86400)
        hours, rem = divmod(rem, 3600)
        minutes = rem // 60
        parts = []
        if days:
            parts.append(f"{days}d")
        if hours:
            parts.append(f"{hours}h")
        parts.append(f"{minutes}m")
        return {
            "status": "ok",
            "label": "System Uptime",
            "detail": " ".join(parts),
            "seconds": seconds,
        }
    except (OSError, ValueError):
        return {"status": "warn", "label": "System Uptime", "detail": "Unavailable"}


def check_birdnet(config) -> dict:
    """BirdNET model validation."""
    birdnet_path = config.birdnet_path
    if birdnet_path is None or not birdnet_path.exists():
        return {"status": "fail", "label": "BirdNET", "detail": "Path not found"}

    # Check for model file
    model_file = birdnet_path / "checkpoints" / "V2.4" / "BirdNET_GLOBAL_6K_V2.4_Model_FP16.tflite"
    if not model_file.exists():
        # Try older model paths
        model_file = birdnet_path / "checkpoints" / "V2.4" / "BirdNET_GLOBAL_6K_V2.4_Model_FP32.tflite"

    model_found = model_file.exists() if model_file else False

    # Count labels
    label_count = 0
    labels_file = birdnet_path / "checkpoints" / "V2.4" / "BirdNET_GLOBAL_6K_V2.4_Labels.txt"
    if labels_file.exists():
        label_count = len(labels_file.read_text().strip().splitlines())

    status = "ok" if model_found else "warn"
    detail = f"{label_count} species" if label_count else "Model found" if model_found else "Model not found"

    return {
        "status": status,
        "label": "BirdNET",
        "detail": detail,
        "path": str(birdnet_path),
        "model_found": model_found,
        "label_count": label_count,
    }


def check_db_integrity(db_path: Path) -> dict:
    """DB integrity check, row counts, WAL size (heavier query)."""
    if not db_path.exists():
        return {"status": "fail", "label": "DB Integrity", "detail": "File not found"}

    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row

        # Quick integrity check
        result = conn.execute("PRAGMA quick_check(1)").fetchone()
        integrity = result[0] if result else "unknown"

        # Row counts
        det_count = conn.execute("SELECT COUNT(*) FROM detections").fetchone()[0]
        species_count = conn.execute(
            "SELECT COUNT(DISTINCT common_name) FROM detections"
        ).fetchone()[0]

        # Audio clips count (table may not exist)
        try:
            audio_count = conn.execute("SELECT COUNT(*) FROM audio_clips").fetchone()[0]
        except sqlite3.OperationalError:
            audio_count = 0

        conn.close()

        ok = integrity == "ok"
        return {
            "status": "ok" if ok else "fail",
            "label": "DB Integrity",
            "detail": integrity,
            "total_detections": det_count,
            "total_species": species_count,
            "audio_clips": audio_count,
        }
    except Exception as e:
        return {"status": "fail", "label": "DB Integrity", "detail": str(e)}


def tier2_checks(config) -> dict:
    """Run all Tier 2 (heavier) checks. Returns combined dict."""
    return {
        "hardware": {
            "cpu_temp": check_cpu_temp(),
            "memory": check_memory(),
            "disk": check_disk(),
            "microphone": check_microphone(),
        },
        "network": check_network(),
        "service": check_systemd(),
        "uptime": check_system_uptime(),
        "birdnet": check_birdnet(config),
        "db_integrity": check_db_integrity(config.db_path),
    }


def quick_status() -> str:
    """Fast health check for the dot colour: 'green', 'yellow', or 'red'."""
    hb = read_heartbeat()
    if hb is None:
        return "red"

    pid = hb.get("pid")
    alive = False
    if pid:
        try:
            os.kill(pid, 0)
            alive = True
        except (OSError, TypeError):
            pass

    if not alive:
        return "red"

    # Check heartbeat freshness
    hb_time = hb.get("heartbeat", "")
    if hb_time:
        try:
            hb_dt = datetime.fromisoformat(hb_time)
            age = (datetime.now(timezone.utc) - hb_dt).total_seconds()
            if age > 120:
                return "red"
            if age > 30:
                return "yellow"
        except ValueError:
            return "yellow"

    if hb.get("status") == "degraded":
        return "yellow"

    return "green"
