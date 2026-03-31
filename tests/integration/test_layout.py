"""Integration-ish smoke tests (filesystem/layout)."""

from pathlib import Path
import pytest


@pytest.mark.integration
def test_project_layout_exists():
    root = Path(__file__).resolve().parents[2]
    assert (root / "pyproject.toml").exists()
    assert (root / "src" / "biardtz").exists()
