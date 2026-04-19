"""Integration-ish smoke tests (filesystem/layout)."""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.integration
def test_project_layout_exists():
    assert (ROOT / "pyproject.toml").exists()
    assert (ROOT / "src" / "biardtz").exists()


# ---------------------------------------------------------------------------
# Makefile service-control targets
# ---------------------------------------------------------------------------

_MAKEFILE_TEXT = (ROOT / "Makefile").read_text()


def _makefile_has_target(name: str) -> bool:
    """Return True if *name* is defined as a Makefile target (starts a rule)."""
    return re.search(rf"^{re.escape(name)}\s*:", _MAKEFILE_TEXT, re.MULTILINE) is not None


def _target_body(name: str) -> str:
    """Return the recipe lines (tab-indented) for a Makefile target."""
    match = re.search(
        rf"^{re.escape(name)}\s*:.*?\n((?:\t.*\n)*)",
        _MAKEFILE_TEXT,
        re.MULTILINE,
    )
    return match.group(1) if match else ""


@pytest.mark.integration
class TestMakefileServiceTargets:
    """Verify the stop/start/restart Makefile targets exist and reference the correct service."""

    @pytest.mark.parametrize("target", ["stop", "start", "restart"])
    def test_target_exists(self, target):
        assert _makefile_has_target(target), f"Makefile missing '{target}' target"

    @pytest.mark.parametrize("target", ["stop", "start", "restart"])
    def test_target_uses_systemctl(self, target):
        body = _target_body(target)
        assert "systemctl" in body, f"'{target}' target does not call systemctl"

    @pytest.mark.parametrize("target", ["stop", "start", "restart"])
    def test_target_references_biardtz_service(self, target):
        body = _target_body(target)
        assert re.search(r"systemctl\s+\w+\s+biardtz", body), (
            f"'{target}' target does not reference the 'biardtz' service"
        )

    @pytest.mark.parametrize("target", ["stop", "start", "restart"])
    def test_target_is_phony(self, target):
        """Service targets should be declared .PHONY."""
        # .PHONY may span multiple continuation lines (backslash + newline)
        phony_match = re.search(
            r"^\.PHONY\s*:((?:.*\\\n)*.*)", _MAKEFILE_TEXT, re.MULTILINE
        )
        assert phony_match, "No .PHONY declaration found in Makefile"
        phony_text = phony_match.group(1).replace("\\", " ").replace("\n", " ")
        assert target in phony_text.split(), f"'{target}' is not declared .PHONY"

    def test_stop_calls_systemctl_stop(self):
        body = _target_body("stop")
        assert "systemctl stop biardtz" in body

    def test_start_calls_systemctl_start(self):
        body = _target_body("start")
        assert "systemctl start biardtz" in body

    def test_restart_calls_systemctl_restart(self):
        body = _target_body("restart")
        assert "systemctl restart biardtz" in body
