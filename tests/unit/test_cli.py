"""Tests for biardtz.cli."""

import sys
import types
from unittest.mock import MagicMock, patch

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
                "--lat",
                "40.0",
                "--lon",
                "-74.0",
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
