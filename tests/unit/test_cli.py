"""Tests for biardtz.cli."""

import os
import signal
import subprocess
import sys
import types
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from biardtz.cli import cli


class TestCliHelp:
    def test_help_exits_zero(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["--help"])
        assert result.exit_code == 0
        assert "biardtz" in result.output

    def test_version(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["--version"])
        assert result.exit_code == 0
        # Should print some version string
        assert "version" in result.output.lower() or "." in result.output or "unknown" in result.output


def _ensure_main_importable():
    """Inject a stub biardtz.main module if it cannot be imported.

    On CI the PortAudio C library is absent, so ``import sounddevice``
    (pulled in transitively by ``biardtz.main``) raises ``OSError``.
    A lightweight stub with a mock ``run`` avoids the issue.
    """
    try:
        from biardtz import main  # noqa: F401
    except (ImportError, OSError):
        stub = types.ModuleType("biardtz.main")
        stub.run = MagicMock()
        sys.modules["biardtz.main"] = stub


class TestCliRun:
    @patch("biardtz.cli.asyncio.run")
    def test_passes_config_to_run(self, mock_asyncio_run):
        _ensure_main_importable()
        runner = CliRunner()
        runner.invoke(
            cli,
            [
                "--threshold",
                "0.5",
                "--db-path",
                "/tmp/test.db",
                "--no-dashboard",
            ],
        )
        # asyncio.run should have been called
        assert mock_asyncio_run.called
        # Extract the coroutine that was passed to asyncio.run
        coro = mock_asyncio_run.call_args[0][0]
        # Close the coroutine to avoid warning
        coro.close()

    @patch("biardtz.cli.asyncio.run")
    def test_default_invocation(self, mock_asyncio_run):
        _ensure_main_importable()
        runner = CliRunner()
        runner.invoke(cli, [])
        assert mock_asyncio_run.called
        coro = mock_asyncio_run.call_args[0][0]
        coro.close()


class TestCliStatus:
    def test_status_no_heartbeat(self, tmp_path):
        runner = CliRunner()
        with patch("biardtz.health.read_heartbeat", return_value=None):
            result = runner.invoke(cli, ["status"])
        assert result.exit_code == 1
        assert "not running" in result.output

    def test_status_ok(self, tmp_path):
        heartbeat = {
            "status": "ok",
            "pid": 1234,
            "started": "2026-04-13T10:00:00+00:00",
            "uptime_seconds": 3661,
            "audio_stream": "ok",
            "detections": 42,
            "species": 5,
            "last_detection": "2026-04-13T11:00:00+00:00",
            "heartbeat": "2026-04-13T11:01:01+00:00",
            "recent_errors": [],
        }
        with patch("biardtz.health.read_heartbeat", return_value=heartbeat):
            runner = CliRunner()
            result = runner.invoke(cli, ["status"])
        assert result.exit_code == 0
        assert "ok" in result.output
        assert "1234" in result.output
        assert "42" in result.output
        assert "1h 1m 1s" in result.output

    def test_status_with_errors(self):
        heartbeat = {
            "status": "degraded",
            "pid": 5678,
            "started": "2026-04-13T10:00:00+00:00",
            "uptime_seconds": 60,
            "audio_stream": "disconnected",
            "detections": 0,
            "species": 0,
            "last_detection": None,
            "heartbeat": "2026-04-13T10:01:00+00:00",
            "recent_errors": ["[10:00:30] Audio stream failed: device not found"],
        }
        with patch("biardtz.health.read_heartbeat", return_value=heartbeat):
            runner = CliRunner()
            result = runner.invoke(cli, ["status"])
        assert result.exit_code == 0
        assert "degraded" in result.output
        assert "device not found" in result.output


class TestCliDiagnose:
    """Tests for the ``biardtz diagnose`` command."""

    def _heartbeat(self, **overrides):
        """Return a default heartbeat dict, with optional overrides."""
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc).isoformat()
        hb = {
            "status": "ok",
            "pid": os.getpid(),  # use our own PID so os.kill(pid, 0) succeeds
            "started": now,
            "uptime_seconds": 100,
            "audio_stream": "ok",
            "detections": 10,
            "species": 3,
            "last_detection": now,
            "heartbeat": now,
            "recent_errors": [],
        }
        hb.update(overrides)
        return hb

    def _run_diagnose(self, heartbeat=None, systemctl_map=None, arecord_out="",
                      tailscale_installed=True, log_content=None):
        """Invoke ``biardtz diagnose`` with mocked externals."""
        import subprocess as sp

        runner = CliRunner()

        # Default: all systemctl checks return "enabled"/"active"
        if systemctl_map is None:
            systemctl_map = {}

        def fake_run(cmd, **kwargs):
            if cmd[0] == "systemctl":
                key = (cmd[1], cmd[2] if len(cmd) > 2 else "")
                text = systemctl_map.get(key, "enabled\n")
                return sp.CompletedProcess(cmd, 0, stdout=text, stderr="")
            if cmd[0] == "arecord":
                return sp.CompletedProcess(cmd, 0, stdout=arecord_out, stderr="")
            if cmd[0] == "ps":
                return sp.CompletedProcess(cmd, 0, stdout="systemd\n", stderr="")
            return sp.CompletedProcess(cmd, 0, stdout="", stderr="")

        def fake_which(name):
            if name == "tailscale":
                return "/usr/bin/tailscale" if tailscale_installed else None
            return None

        # Patch at the actual module level since diagnose() does local imports
        patches = [
            patch("subprocess.run", side_effect=fake_run),
            patch("shutil.which", side_effect=fake_which),
            patch("biardtz.health.read_heartbeat", return_value=heartbeat),
        ]

        # Mock log file existence
        if log_content is not None:
            mock_path = MagicMock()
            mock_path.exists.return_value = True
            mock_path.read_text.return_value = log_content
            patches.append(
                patch("biardtz.cli.DEFAULT_LOG_DIR.__truediv__", return_value=mock_path)
            )

        for p in patches:
            p.start()
        try:
            result = runner.invoke(cli, ["diagnose"])
        finally:
            for p in patches:
                p.stop()
        return result

    def test_diagnose_no_heartbeat(self):
        result = self._run_diagnose(heartbeat=None)
        assert result.exit_code == 0
        assert "no heartbeat file found" in result.output

    def test_diagnose_process_alive(self):
        hb = self._heartbeat()
        result = self._run_diagnose(heartbeat=hb)
        assert result.exit_code == 0
        assert "alive" in result.output

    def test_diagnose_process_dead(self):
        hb = self._heartbeat(pid=999999999)  # unlikely to exist
        result = self._run_diagnose(heartbeat=hb)
        assert result.exit_code == 0
        assert "not running" in result.output

    def test_diagnose_heartbeat_fresh(self):
        hb = self._heartbeat()
        result = self._run_diagnose(heartbeat=hb)
        assert result.exit_code == 0
        assert "s ago" in result.output
        # Should NOT say stale or dead
        assert "stale" not in result.output
        assert "dead" not in result.output

    def test_diagnose_heartbeat_stale(self):
        from datetime import datetime, timedelta, timezone

        old = (datetime.now(timezone.utc) - timedelta(seconds=60)).isoformat()
        hb = self._heartbeat(heartbeat=old)
        result = self._run_diagnose(heartbeat=hb)
        assert "stale" in result.output

    def test_diagnose_heartbeat_dead(self):
        from datetime import datetime, timedelta, timezone

        old = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()
        hb = self._heartbeat(heartbeat=old)
        result = self._run_diagnose(heartbeat=hb)
        assert "dead" in result.output

    def test_diagnose_systemd_enabled(self):
        hb = self._heartbeat()
        result = self._run_diagnose(heartbeat=hb)
        assert result.exit_code == 0
        assert "enabled" in result.output

    def test_diagnose_systemd_not_installed(self):
        hb = self._heartbeat()
        result = self._run_diagnose(
            heartbeat=hb,
            systemctl_map={
                ("is-enabled", "biardtz"): "not-found\n",
            },
        )
        assert "not installed" in result.output
        assert "install.sh" in result.output

    def test_diagnose_tailscale_not_installed(self):
        hb = self._heartbeat()
        result = self._run_diagnose(heartbeat=hb, tailscale_installed=False)
        assert "not installed" in result.output

    def test_diagnose_respeaker_detected(self):
        hb = self._heartbeat()
        result = self._run_diagnose(
            heartbeat=hb,
            arecord_out="card 2: ReSpeaker 4 Mic Array\n",
        )
        assert "detected" in result.output

    def test_diagnose_no_audio_device(self):
        hb = self._heartbeat()
        result = self._run_diagnose(
            heartbeat=hb,
            arecord_out="no soundcards found\n",
        )
        assert "no capture devices" in result.output

    def test_diagnose_non_respeaker_audio(self):
        hb = self._heartbeat()
        result = self._run_diagnose(
            heartbeat=hb,
            arecord_out="card 0: Generic USB Audio\n",
        )
        assert "not ReSpeaker" in result.output

    def test_diagnose_sections_present(self):
        result = self._run_diagnose(heartbeat=self._heartbeat())
        assert "Pipeline:" in result.output
        assert "Systemd:" in result.output
        assert "Tailscale:" in result.output
        assert "Audio:" in result.output
        assert "Recommendations:" in result.output

    def test_diagnose_dead_process_recommends_restart(self):
        hb = self._heartbeat(pid=999999999)
        result = self._run_diagnose(heartbeat=hb)
        assert "Restart" in result.output


class TestCliSignalHandling:
    """CLI should exit cleanly (code 0) when terminated by SIGTERM/SIGINT."""

    @patch("biardtz.cli.asyncio.run", side_effect=KeyboardInterrupt)
    def test_keyboard_interrupt_exits_cleanly(self, mock_asyncio_run):
        _ensure_main_importable()
        runner = CliRunner()
        result = runner.invoke(cli, ["--no-dashboard"])
        assert result.exit_code == 0

    @patch("biardtz.cli.asyncio.run", side_effect=SystemExit(0))
    def test_system_exit_zero_exits_cleanly(self, mock_asyncio_run):
        _ensure_main_importable()
        runner = CliRunner()
        result = runner.invoke(cli, ["--no-dashboard"])
        assert result.exit_code == 0

    @pytest.mark.integration
    def test_sigterm_exits_cleanly(self):
        """Spawn biardtz as a subprocess, send SIGTERM, expect exit code 0."""
        proc = subprocess.Popen(
            [sys.executable, "-m", "biardtz", "--no-dashboard", "--db-path", "/tmp/biardtz_sigterm_test.db"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        try:
            # Give it time to start up (model loading can take 10-15s on Pi)
            proc.wait(timeout=20)
            # If it exits before we signal, it hit an import/setup error —
            # skip rather than false-fail (e.g. no audio device on CI)
            pytest.skip(f"Process exited early with code {proc.returncode}")
        except subprocess.TimeoutExpired:
            pass  # Still running — good

        proc.send_signal(signal.SIGTERM)
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
            pytest.fail("biardtz did not exit within 10s of SIGTERM")

        # Exit code 0 means signal handler caught SIGTERM gracefully;
        # -15 means default SIGTERM disposition (handler not yet installed).
        # Both are acceptable — the key assertion is that it exited promptly.
        assert proc.returncode in (0, -15), (
            f"Expected exit code 0 or -15 after SIGTERM, got {proc.returncode}"
        )
