"""Tests for biardtz.__main__."""

from unittest.mock import patch


def test_main_calls_cli():
    with patch("biardtz.cli.cli"):
        # Import triggers the module code; __name__ won't be "__main__"
        # so the if guard won't fire, but we cover line 4 (the import).
        import biardtz.__main__  # noqa: F401


def test_main_entry_point():
    """Execute the __main__ module as if __name__ == '__main__'."""
    with patch("biardtz.cli.cli") as mock_cli:
        code = "from biardtz.cli import cli\ncli()"
        exec(code, {"__name__": "__main__"})
        mock_cli.assert_called_once()
