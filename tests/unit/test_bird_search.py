"""Tests for bird search filters on chart DB functions and API routes."""

from __future__ import annotations

import asyncio
import sqlite3
from datetime import datetime, timezone

import httpx

from biardtz.config import Config
from biardtz.web import create_app
from biardtz.web import db as web_db

_SCHEMA = """\
CREATE TABLE IF NOT EXISTS detections (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp     TEXT NOT NULL,
    common_name   TEXT NOT NULL,
    sci_name      TEXT NOT NULL,
    confidence    REAL NOT NULL,
    latitude      REAL,
    longitude     REAL,
    bearing       REAL,
    direction     TEXT
);
"""


def _create_test_db(path, rows=None):
    """Create a test database with the full schema and optional sample rows."""
    conn = sqlite3.connect(str(path))
    conn.executescript(_SCHEMA)
    if rows:
        conn.executemany(
            "INSERT INTO detections "
            "(timestamp, common_name, sci_name, confidence, bearing, direction) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            rows,
        )
        conn.commit()
    conn.close()


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00")


def _make_app(tmp_path, rows=None):
    """Helper to create a FastAPI app with a test database."""
    db_path = tmp_path / "test.db"
    _create_test_db(db_path, rows)
    config = Config(
        db_path=db_path,
        bird_image_cache=tmp_path / "img_cache",
        audio_clip_dir=tmp_path / "audio_clips",
    )
    return create_app(config)


# ---------------------------------------------------------------------------
# DB: _search_clause helper
# ---------------------------------------------------------------------------
class TestSearchClause:
    def test_search_clause_like(self):
        """Plain text search returns a LIKE clause."""
        params: list = []
        clause = web_db._search_clause("Robin", params)
        assert "LIKE" in clause
        assert len(params) == 1
        assert "%" in params[0]  # wrapped with %

    def test_search_clause_glob(self):
        """Glob characters in search return a GLOB clause."""
        params: list = []
        clause = web_db._search_clause("Rob*", params)
        assert "GLOB" in clause
        assert len(params) == 1
        assert params[0] == "Rob*"

    def test_search_clause_none(self):
        """None search returns empty string and no params."""
        params: list = []
        clause = web_db._search_clause(None, params)
        assert clause == ""
        assert params == []


# ---------------------------------------------------------------------------
# DB: chart functions with search filter
# ---------------------------------------------------------------------------
class TestDetectionTimelineSearch:
    def test_detection_timeline_with_search(self, tmp_path):
        """detection_timeline filters by species name when search is given."""
        db_path = tmp_path / "test.db"
        now = _now_iso()
        rows = [
            (now, "Robin", "Erithacus rubecula", 0.85, None, None),
            (now, "Robin", "Erithacus rubecula", 0.80, None, None),
            (now, "Blackbird", "Turdus merula", 0.70, None, None),
        ]
        _create_test_db(db_path, rows)
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row

        # Without search: all 3
        all_result = web_db.detection_timeline(conn, days=1)
        total = sum(r["count"] for r in all_result)
        assert total == 3

        # With search: only Robin (2)
        filtered = web_db.detection_timeline(conn, days=1, search="Robin")
        filtered_total = sum(r["count"] for r in filtered)
        assert filtered_total == 2

        conn.close()


class TestSpeciesFrequencySearch:
    def test_species_frequency_with_search(self, tmp_path):
        """species_frequency filters by species name when search is given."""
        db_path = tmp_path / "test.db"
        now = _now_iso()
        rows = [
            (now, "Robin", "Erithacus rubecula", 0.85, None, None),
            (now, "Blackbird", "Turdus merula", 0.70, None, None),
            (now, "Blue Tit", "Cyanistes caeruleus", 0.60, None, None),
        ]
        _create_test_db(db_path, rows)
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row

        result = web_db.species_frequency(conn, days=1, search="Robin")
        assert len(result) == 1
        assert result[0]["common_name"] == "Robin"

        conn.close()


class TestActivityHeatmapSearch:
    def test_activity_heatmap_with_search(self, tmp_path):
        """activity_heatmap filters by species name when search is given."""
        db_path = tmp_path / "test.db"
        now = _now_iso()
        rows = [
            (now, "Robin", "Erithacus rubecula", 0.85, None, None),
            (now, "Blackbird", "Turdus merula", 0.70, None, None),
        ]
        _create_test_db(db_path, rows)
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row

        # Without search
        all_result = web_db.activity_heatmap(conn, days=1)
        all_total = sum(r["count"] for r in all_result)
        assert all_total == 2

        # With search: only Robin
        filtered = web_db.activity_heatmap(conn, days=1, search="Robin")
        filtered_total = sum(r["count"] for r in filtered)
        assert filtered_total == 1

        conn.close()


class TestDailyTrendSearch:
    def test_daily_trend_with_search(self, tmp_path):
        """daily_trend filters by species name when search is given."""
        db_path = tmp_path / "test.db"
        now = _now_iso()
        rows = [
            (now, "Robin", "Erithacus rubecula", 0.85, None, None),
            (now, "Blackbird", "Turdus merula", 0.70, None, None),
            (now, "Wren", "Troglodytes troglodytes", 0.60, None, None),
        ]
        _create_test_db(db_path, rows)
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row

        result = web_db.daily_trend(conn, days=1, search="Robin")
        assert len(result) == 1
        assert result[0]["count"] == 1
        assert result[0]["species"] == 1

        conn.close()


# ---------------------------------------------------------------------------
# DB: species breakdown functions
# ---------------------------------------------------------------------------
class TestTimelineSpeciesBreakdown:
    def test_timeline_species_breakdown(self, tmp_path):
        """Returns {hour: {species: count}} structure."""
        db_path = tmp_path / "test.db"
        now = _now_iso()
        rows = [
            (now, "Robin", "Erithacus rubecula", 0.85, None, None),
            (now, "Robin", "Erithacus rubecula", 0.80, None, None),
            (now, "Blackbird", "Turdus merula", 0.70, None, None),
        ]
        _create_test_db(db_path, rows)
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row

        result = web_db.timeline_species_breakdown(conn, days=1)

        # Should be a dict of {hour_string: {species_name: count}}
        assert isinstance(result, dict)
        assert len(result) >= 1
        for hour_key, species_dict in result.items():
            assert isinstance(hour_key, str)
            assert isinstance(species_dict, dict)
            for sp_name, count in species_dict.items():
                assert isinstance(sp_name, str)
                assert isinstance(count, int)

        # Total counts across all hours should be 3
        total = sum(
            count
            for species_dict in result.values()
            for count in species_dict.values()
        )
        assert total == 3

        conn.close()

    def test_timeline_species_breakdown_with_search(self, tmp_path):
        """Filtered breakdown only includes matching species."""
        db_path = tmp_path / "test.db"
        now = _now_iso()
        rows = [
            (now, "Robin", "Erithacus rubecula", 0.85, None, None),
            (now, "Robin", "Erithacus rubecula", 0.80, None, None),
            (now, "Blackbird", "Turdus merula", 0.70, None, None),
        ]
        _create_test_db(db_path, rows)
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row

        result = web_db.timeline_species_breakdown(conn, days=1, search="Robin")

        total = sum(
            count
            for species_dict in result.values()
            for count in species_dict.values()
        )
        assert total == 2

        # Only Robin should appear
        all_species = set()
        for species_dict in result.values():
            all_species.update(species_dict.keys())
        assert all_species == {"Robin"}

        conn.close()


class TestHeatmapSpeciesBreakdown:
    def test_heatmap_species_breakdown(self, tmp_path):
        """Returns {"dow-hour": {species: count}} structure."""
        db_path = tmp_path / "test.db"
        now = _now_iso()
        rows = [
            (now, "Robin", "Erithacus rubecula", 0.85, None, None),
            (now, "Blackbird", "Turdus merula", 0.70, None, None),
        ]
        _create_test_db(db_path, rows)
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row

        result = web_db.heatmap_species_breakdown(conn, days=1)

        assert isinstance(result, dict)
        assert len(result) >= 1
        for cell_key, species_dict in result.items():
            assert isinstance(cell_key, str)
            # Key should be "dow-hour" format
            assert "-" in cell_key
            assert isinstance(species_dict, dict)

        # Total should be 2
        total = sum(
            count
            for species_dict in result.values()
            for count in species_dict.values()
        )
        assert total == 2

        conn.close()


# ---------------------------------------------------------------------------
# Routes: search param on chart endpoints
# ---------------------------------------------------------------------------
class TestChartSearchRoutes:
    def test_chart_timeline_search_param(self, tmp_path):
        """GET /api/charts/timeline?search=Robin passes search through."""
        now = _now_iso()
        rows = [
            (now, "Robin", "Erithacus rubecula", 0.85, None, None),
            (now, "Robin", "Erithacus rubecula", 0.80, None, None),
            (now, "Blackbird", "Turdus merula", 0.70, None, None),
        ]
        app = _make_app(tmp_path, rows)

        async def _run():
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
                return await c.get("/api/charts/timeline?days=1&search=Robin")

        resp = asyncio.run(_run())
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        total = sum(d["count"] for d in data)
        assert total == 2  # Only Robin

    def test_chart_species_search_param(self, tmp_path):
        """GET /api/charts/species?search=Robin passes search through."""
        now = _now_iso()
        rows = [
            (now, "Robin", "Erithacus rubecula", 0.85, None, None),
            (now, "Blackbird", "Turdus merula", 0.70, None, None),
        ]
        app = _make_app(tmp_path, rows)

        async def _run():
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
                return await c.get("/api/charts/species?days=1&search=Robin")

        resp = asyncio.run(_run())
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["common_name"] == "Robin"

    def test_chart_heatmap_search_param(self, tmp_path):
        """GET /api/charts/heatmap?search=Robin passes search through."""
        now = _now_iso()
        rows = [
            (now, "Robin", "Erithacus rubecula", 0.85, None, None),
            (now, "Blackbird", "Turdus merula", 0.70, None, None),
        ]
        app = _make_app(tmp_path, rows)

        async def _run():
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
                return await c.get("/api/charts/heatmap?days=1&search=Robin")

        resp = asyncio.run(_run())
        assert resp.status_code == 200
        data = resp.json()
        total = sum(d["count"] for d in data)
        assert total == 1

    def test_chart_trend_search_param(self, tmp_path):
        """GET /api/charts/trend?search=Robin passes search through."""
        now = _now_iso()
        rows = [
            (now, "Robin", "Erithacus rubecula", 0.85, None, None),
            (now, "Blackbird", "Turdus merula", 0.70, None, None),
        ]
        app = _make_app(tmp_path, rows)

        async def _run():
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
                return await c.get("/api/charts/trend?days=1&search=Robin")

        resp = asyncio.run(_run())
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["count"] == 1

    def test_chart_timeline_species_endpoint(self, tmp_path):
        """GET /api/charts/timeline/species returns species breakdown dict."""
        now = _now_iso()
        rows = [
            (now, "Robin", "Erithacus rubecula", 0.85, None, None),
            (now, "Blackbird", "Turdus merula", 0.70, None, None),
        ]
        app = _make_app(tmp_path, rows)

        async def _run():
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
                return await c.get("/api/charts/timeline/species?days=1")

        resp = asyncio.run(_run())
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, dict)
        # Each value should be a dict of {species: count}
        for _hour_key, species_dict in data.items():
            assert isinstance(species_dict, dict)

    def test_chart_heatmap_species_endpoint(self, tmp_path):
        """GET /api/charts/heatmap/species returns species breakdown dict."""
        now = _now_iso()
        rows = [
            (now, "Robin", "Erithacus rubecula", 0.85, None, None),
            (now, "Blackbird", "Turdus merula", 0.70, None, None),
        ]
        app = _make_app(tmp_path, rows)

        async def _run():
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
                return await c.get("/api/charts/heatmap/species?days=1")

        resp = asyncio.run(_run())
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, dict)
        for _cell_key, species_dict in data.items():
            assert isinstance(species_dict, dict)

    def test_chart_cache_includes_search(self, tmp_path):
        """Different search terms don't return cached results from other searches."""
        from biardtz.web import routes as _routes_mod
        _routes_mod._cache.clear()

        now = _now_iso()
        rows = [
            (now, "Robin", "Erithacus rubecula", 0.85, None, None),
            (now, "Blackbird", "Turdus merula", 0.70, None, None),
        ]
        app = _make_app(tmp_path, rows)

        async def _run():
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
                # First request with search=Robin
                r1 = await c.get("/api/charts/timeline?days=1&search=Robin")
                # Second request with search=Blackbird (should NOT get Robin's cached result)
                r2 = await c.get("/api/charts/timeline?days=1&search=Blackbird")
                # Third request with no search
                r3 = await c.get("/api/charts/timeline?days=1")
                return r1, r2, r3

        r1, r2, r3 = asyncio.run(_run())

        d1 = r1.json()
        d2 = r2.json()
        d3 = r3.json()

        total_robin = sum(d["count"] for d in d1)
        total_blackbird = sum(d["count"] for d in d2)
        total_all = sum(d["count"] for d in d3)

        assert total_robin == 1  # Only Robin
        assert total_blackbird == 1  # Only Blackbird
        assert total_all == 2  # All detections


# ---------------------------------------------------------------------------
# Route existence: new endpoints should be registered
# ---------------------------------------------------------------------------
class TestNewEndpointsExist:
    def test_app_has_timeline_species_route(self, tmp_path):
        app = _make_app(tmp_path)
        route_paths = [r.path for r in app.routes if hasattr(r, "path")]
        assert "/api/charts/timeline/species" in route_paths

    def test_app_has_heatmap_species_route(self, tmp_path):
        app = _make_app(tmp_path)
        route_paths = [r.path for r in app.routes if hasattr(r, "path")]
        assert "/api/charts/heatmap/species" in route_paths
