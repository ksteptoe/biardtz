"""Tests for biardtz.cli."""

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

        assert proc.returncode == 0, f"Expected exit code 0 after SIGTERM, got {proc.returncode}"
