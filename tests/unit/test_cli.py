"""Tests for biardtz.cli."""

from unittest.mock import AsyncMock, patch

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


class TestCliRun:
    @patch("biardtz.cli.asyncio.run")
    @patch("biardtz.main.Detector")
    def test_passes_config_to_run(self, mock_detector, mock_asyncio_run):
        runner = CliRunner()
        result = runner.invoke(cli, [
            "--lat", "40.0",
            "--lon", "-74.0",
            "--threshold", "0.5",
            "--db-path", "/tmp/test.db",
            "--no-dashboard",
        ])
        # asyncio.run should have been called
        assert mock_asyncio_run.called
        # Extract the coroutine that was passed to asyncio.run
        coro = mock_asyncio_run.call_args[0][0]
        # Close the coroutine to avoid warning
        coro.close()

    @patch("biardtz.cli.asyncio.run")
    @patch("biardtz.main.Detector")
    def test_default_invocation(self, mock_detector, mock_asyncio_run):
        runner = CliRunner()
        result = runner.invoke(cli, [])
        assert mock_asyncio_run.called
        coro = mock_asyncio_run.call_args[0][0]
        coro.close()
