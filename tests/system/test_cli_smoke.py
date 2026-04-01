"""CLI smoke tests — verify the entry point works."""
from __future__ import annotations

import signal
import subprocess
import sys
import time

import pytest

pytestmark = pytest.mark.live


class TestCliSmoke:
    def test_help_exits_zero(self):
        result = subprocess.run(
            [sys.executable, "-m", "biardtz", "--help"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert result.returncode == 0
        assert "Usage" in result.stdout or "usage" in result.stdout.lower()

    def test_version_exits_zero(self):
        result = subprocess.run(
            [sys.executable, "-m", "biardtz", "--version"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert result.returncode == 0
