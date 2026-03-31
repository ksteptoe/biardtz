"""Tests for biardtz.dashboard."""

import asyncio
from unittest.mock import MagicMock, patch

from rich.table import Table
from rich.text import Text

from biardtz.dashboard import Dashboard
from biardtz.detector import Detection


class TestBuildTable:
    def test_returns_rich_table(self):
        dash = Dashboard()
        table = dash._build_table()
        assert isinstance(table, Table)

    def test_table_has_four_columns(self):
        dash = Dashboard()
        table = dash._build_table()
        assert len(table.columns) == 4

    def test_table_title_contains_stats(self):
        dash = Dashboard()
        table = dash._build_table()
        assert "biardtz" in table.title
        assert "0 detections" in table.title
        assert "0 species" in table.title

    def test_table_with_detections(self):
        dash = Dashboard()
        det = Detection("Robin", "Erithacus rubecula", 0.85)
        dash._recent.append(("12:00:00", det))
        dash._total = 1
        dash._species.add("Robin")

        table = dash._build_table()
        assert "1 detections" in table.title
        assert "1 species" in table.title
        assert table.row_count == 1


class TestConfidenceColoring:
    """Test that _build_table applies the right style per confidence band."""

    @staticmethod
    def _get_conf_cell(confidence: float) -> Text:
        dash = Dashboard()
        det = Detection("Robin", "Erithacus rubecula", confidence)
        dash._recent.append(("12:00:00", det))
        dash._total = 1
        table = dash._build_table()
        # Rich Table stores cell renderables in columns[col_idx]._cells
        return table.columns[3]._cells[0]

    def test_high_confidence_green(self):
        cell = self._get_conf_cell(0.85)
        assert isinstance(cell, Text)
        assert cell.style == "bold green"

    def test_medium_confidence_yellow(self):
        cell = self._get_conf_cell(0.55)
        assert isinstance(cell, Text)
        assert cell.style == "yellow"

    def test_low_confidence_dim(self):
        cell = self._get_conf_cell(0.30)
        assert isinstance(cell, Text)
        assert cell.style == "dim"


class TestDashboardRun:
    """Tests for Dashboard.run() async method — covers lines 53-60."""

    def test_run_processes_detections(self):
        det = Detection("Robin", "Erithacus rubecula", 0.85)

        async def run_test():
            dashboard = Dashboard()
            q = asyncio.Queue()
            q.put_nowait(det)

            with patch("biardtz.dashboard.Live") as mock_live_cls:
                mock_live = MagicMock()
                mock_live.__enter__ = MagicMock(return_value=mock_live)
                mock_live.__exit__ = MagicMock(return_value=False)
                mock_live_cls.return_value = mock_live

                task = asyncio.create_task(dashboard.run(q))
                await asyncio.sleep(0.05)
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

            assert dashboard._total == 1
            assert "Robin" in dashboard._species
            assert len(dashboard._recent) == 1

        asyncio.run(run_test())

    def test_run_processes_multiple_detections(self):
        det1 = Detection("Robin", "Erithacus rubecula", 0.85)
        det2 = Detection("Blackbird", "Turdus merula", 0.55)

        async def run_test():
            dashboard = Dashboard()
            q = asyncio.Queue()
            q.put_nowait(det1)
            q.put_nowait(det2)

            with patch("biardtz.dashboard.Live") as mock_live_cls:
                mock_live = MagicMock()
                mock_live.__enter__ = MagicMock(return_value=mock_live)
                mock_live.__exit__ = MagicMock(return_value=False)
                mock_live_cls.return_value = mock_live

                task = asyncio.create_task(dashboard.run(q))
                await asyncio.sleep(0.05)
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

            assert dashboard._total == 2
            assert dashboard._species == {"Robin", "Blackbird"}

        asyncio.run(run_test())
