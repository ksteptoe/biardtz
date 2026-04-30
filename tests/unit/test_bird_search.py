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
        """Glob characters in search return a case-insensitive GLOB clause."""
        params: list = []
        clause = web_db._search_clause("Rob*", params)
        assert "GLOB" in clause
        assert "UPPER" in clause
        assert len(params) == 1
        assert params[0] == "ROB*"

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


# ---------------------------------------------------------------------------
# Shared test data for glob / case-insensitive tests
# ---------------------------------------------------------------------------
def _mixed_species_rows():
    """Return rows with owls and non-owls, built with the current timestamp."""
    now = _now_iso()
    return [
        (now, "Tawny Owl", "Strix aluco", 0.90, None, None),
        (now, "Barn Owl", "Tyto alba", 0.85, None, None),
        (now, "Blue Tit", "Cyanistes caeruleus", 0.80, None, None),
        (now, "Robin", "Erithacus rubecula", 0.75, None, None),
        (now, "Blackbird", "Turdus merula", 0.70, None, None),
        (now, "Great Tit", "Parus major", 0.65, None, None),
    ]


def _owl_db(tmp_path):
    """Create a test DB with mixed species and return a connection."""
    db_path = tmp_path / "test.db"
    _create_test_db(db_path, _mixed_species_rows())
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    return conn


# ---------------------------------------------------------------------------
# DB: case-insensitive glob tests
# ---------------------------------------------------------------------------
class TestGlobCaseInsensitive:
    """Verify that GLOB searches work case-insensitively at the DB layer."""

    def test_glob_case_insensitive_lowercase(self, tmp_path):
        """Lowercase glob *owl* matches 'Tawny Owl' and 'Barn Owl'."""
        conn = _owl_db(tmp_path)
        result = web_db.species_frequency(conn, days=1, search="*owl*")
        names = {r["common_name"] for r in result}
        assert names == {"Tawny Owl", "Barn Owl"}
        conn.close()

    def test_glob_case_insensitive_uppercase(self, tmp_path):
        """Uppercase glob *OWL* matches 'Tawny Owl' and 'Barn Owl'."""
        conn = _owl_db(tmp_path)
        result = web_db.species_frequency(conn, days=1, search="*OWL*")
        names = {r["common_name"] for r in result}
        assert names == {"Tawny Owl", "Barn Owl"}
        conn.close()

    def test_glob_case_insensitive_mixed(self, tmp_path):
        """Mixed-case glob *OwL* matches 'Tawny Owl' and 'Barn Owl'."""
        conn = _owl_db(tmp_path)
        result = web_db.species_frequency(conn, days=1, search="*OwL*")
        names = {r["common_name"] for r in result}
        assert names == {"Tawny Owl", "Barn Owl"}
        conn.close()

    def test_glob_bracket_case_insensitive(self, tmp_path):
        """Bracket glob [bt]* matches names starting with B or T (case-insensitive)."""
        conn = _owl_db(tmp_path)
        result = web_db.species_frequency(conn, days=1, limit=20, search="[bt]*")
        names = {r["common_name"] for r in result}
        # UPPER makes it [BT]*, matching Blue Tit, Blackbird, Barn Owl, Tawny Owl
        assert "Blue Tit" in names
        assert "Blackbird" in names
        assert "Tawny Owl" in names
        assert "Barn Owl" in names
        # Robin and Great Tit should NOT match
        assert "Robin" not in names
        conn.close()

    def test_glob_question_mark_case_insensitive(self, tmp_path):
        """Question-mark glob ?lue* matches 'Blue Tit' (case-insensitive)."""
        conn = _owl_db(tmp_path)
        result = web_db.species_frequency(conn, days=1, search="?lue*")
        names = {r["common_name"] for r in result}
        assert "Blue Tit" in names
        # Should not match other species
        assert len(names) == 1
        conn.close()


# ---------------------------------------------------------------------------
# DB: _search_clause upper-casing behaviour
# ---------------------------------------------------------------------------
class TestSearchClauseUpperCasing:
    """Verify that _search_clause uppercases glob params but not LIKE params."""

    def test_search_clause_glob_uppercases_param(self):
        """Glob search uppercases the parameter for case-insensitive matching."""
        params: list = []
        clause = web_db._search_clause("*owl*", params)
        assert "GLOB" in clause
        assert "UPPER" in clause
        assert len(params) == 1
        assert params[0] == "*OWL*"

    def test_search_clause_like_preserves_case(self):
        """Plain text search does NOT uppercase the parameter (LIKE is case-insensitive)."""
        params: list = []
        clause = web_db._search_clause("owl", params)
        assert "LIKE" in clause
        assert len(params) == 1
        assert params[0] == "%owl%"  # preserved lowercase


# ---------------------------------------------------------------------------
# Routes: chart filtering with glob search
# ---------------------------------------------------------------------------
class TestChartGlobSearchRoutes:
    """Verify that glob search patterns filter chart API endpoints correctly."""

    def test_timeline_filtered_by_glob_search(self, tmp_path):
        """GET /api/charts/timeline?search=*owl* returns only owl detections."""
        app = _make_app(tmp_path, _mixed_species_rows())

        async def _run():
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
                return await c.get("/api/charts/timeline?days=1&search=*owl*")

        resp = asyncio.run(_run())
        assert resp.status_code == 200
        data = resp.json()
        total = sum(d["count"] for d in data)
        assert total == 2  # Tawny Owl + Barn Owl

    def test_species_filtered_by_glob_search(self, tmp_path):
        """GET /api/charts/species?search=*owl* returns only owl species."""
        app = _make_app(tmp_path, _mixed_species_rows())

        async def _run():
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
                return await c.get("/api/charts/species?days=1&search=*owl*")

        resp = asyncio.run(_run())
        assert resp.status_code == 200
        data = resp.json()
        names = {d["common_name"] for d in data}
        assert names == {"Tawny Owl", "Barn Owl"}

    def test_heatmap_filtered_by_glob_search(self, tmp_path):
        """GET /api/charts/heatmap?search=*owl* returns only owl data."""
        app = _make_app(tmp_path, _mixed_species_rows())

        async def _run():
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
                return await c.get("/api/charts/heatmap?days=1&search=*owl*")

        resp = asyncio.run(_run())
        assert resp.status_code == 200
        data = resp.json()
        total = sum(d["count"] for d in data)
        assert total == 2

    def test_trend_filtered_by_glob_search(self, tmp_path):
        """GET /api/charts/trend?search=*owl* returns only owl data."""
        app = _make_app(tmp_path, _mixed_species_rows())

        async def _run():
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
                return await c.get("/api/charts/trend?days=1&search=*owl*")

        resp = asyncio.run(_run())
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["count"] == 2
        assert data[0]["species"] == 2  # two distinct owl species


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------
class TestSearchEdgeCases:
    """Edge cases for both plain text and glob search."""

    def test_glob_no_match_returns_empty(self, tmp_path):
        """Glob pattern *xyz* returns no results when nothing matches."""
        conn = _owl_db(tmp_path)
        result = web_db.species_frequency(conn, days=1, search="*xyz*")
        assert result == []
        conn.close()

    def test_plain_search_partial_match(self, tmp_path):
        """Plain text 'tit' matches 'Blue Tit' and 'Great Tit' but not 'Robin'."""
        conn = _owl_db(tmp_path)
        result = web_db.species_frequency(conn, days=1, limit=20, search="tit")
        names = {r["common_name"] for r in result}
        assert "Blue Tit" in names
        assert "Great Tit" in names
        assert "Robin" not in names
        assert "Tawny Owl" not in names
        conn.close()

    def test_empty_search_returns_all(self, tmp_path):
        """Empty string search returns all detections."""
        conn = _owl_db(tmp_path)
        result = web_db.species_frequency(conn, days=1, limit=20, search="")
        names = {r["common_name"] for r in result}
        assert len(names) == 6  # all species
        conn.close()

    def test_search_species_list_case_insensitive(self, tmp_path):
        """species_list(conn, q='*owl*') matches case-insensitively."""
        conn = _owl_db(tmp_path)
        result = web_db.species_list(conn, q="*owl*")
        names = {r["common_name"] for r in result}
        assert names == {"Barn Owl", "Tawny Owl"}
        conn.close()


# ---------------------------------------------------------------------------
# DB + Route: species_stats with search filter (leaderboard filtering)
# ---------------------------------------------------------------------------
class TestSpeciesStatsSearch:
    """Verify that species_stats() filters leaderboard and counts when search is given."""

    def test_species_stats_no_search_returns_all(self, tmp_path):
        """Baseline: without search, leaderboard contains all species."""
        conn = _owl_db(tmp_path)
        stats = web_db.species_stats(conn)
        names = {row["common_name"] for row in stats["leaderboard"]}
        # All 6 species from _mixed_species_rows should appear
        assert names == {"Tawny Owl", "Barn Owl", "Blue Tit", "Robin", "Blackbird", "Great Tit"}
        conn.close()

    def test_species_stats_with_glob_search(self, tmp_path):
        """search='*owl*' restricts leaderboard to owl species only."""
        conn = _owl_db(tmp_path)
        stats = web_db.species_stats(conn, search="*owl*")
        names = {row["common_name"] for row in stats["leaderboard"]}
        assert names == {"Tawny Owl", "Barn Owl"}
        conn.close()

    def test_species_stats_with_plain_search(self, tmp_path):
        """search='tit' restricts leaderboard to tit species only."""
        conn = _owl_db(tmp_path)
        stats = web_db.species_stats(conn, search="tit")
        names = {row["common_name"] for row in stats["leaderboard"]}
        assert names == {"Blue Tit", "Great Tit"}
        conn.close()

    def test_species_stats_search_affects_counts(self, tmp_path):
        """today_count and all_time_species reflect the filtered data."""
        conn = _owl_db(tmp_path)

        # Unfiltered baseline
        all_stats = web_db.species_stats(conn)

        # Filtered to owls only
        owl_stats = web_db.species_stats(conn, search="*owl*")

        # Filtered today_count should be <= unfiltered
        assert owl_stats["today_count"] <= all_stats["today_count"]
        # Filtered today_count should equal number of owl rows (2)
        assert owl_stats["today_count"] == 2
        # Filtered all_time_species should be 2 (Tawny Owl, Barn Owl)
        assert owl_stats["all_time_species"] == 2
        # Filtered today_species should be 2
        assert owl_stats["today_species"] == 2

        conn.close()

    def test_partial_stats_search_param(self, tmp_path):
        """/partials/stats?search=*owl* returns 200 and filtered HTML."""
        app = _make_app(tmp_path, _mixed_species_rows())

        async def _run():
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
                return await c.get("/partials/stats?search=*owl*")

        resp = asyncio.run(_run())
        assert resp.status_code == 200
        html = resp.text
        # Owl species should appear in the rendered HTML
        assert "Tawny Owl" in html
        assert "Barn Owl" in html
        # Non-owl species should NOT appear in the leaderboard
        assert "Robin" not in html
        assert "Blackbird" not in html


# ---------------------------------------------------------------------------
# Routes: chart drill-down with combined filters
# ---------------------------------------------------------------------------
class TestDrillDownFilters:
    """Verify that /partials/detections supports date range + species + search combos."""

    def test_detections_with_date_range_and_search(self, tmp_path):
        """/partials/detections?date_from=X&date_to=Y&search=*owl* returns filtered HTML."""
        rows = _mixed_species_rows()
        app = _make_app(tmp_path, rows)

        # Use a date range that includes today
        date_from = datetime.now(timezone.utc).strftime("%Y-%m-%dT00:00:00+00:00")
        date_to = datetime.now(timezone.utc).strftime("%Y-%m-%dT23:59:59+00:00")

        async def _run():
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
                return await c.get(
                    "/partials/detections",
                    params={
                        "date_from": date_from,
                        "date_to": date_to,
                        "search": "*owl*",
                    },
                )

        resp = asyncio.run(_run())
        assert resp.status_code == 200
        html = resp.text
        # Owl species should appear
        assert "Tawny Owl" in html or "Barn Owl" in html
        # Non-owl species should NOT appear
        assert "Robin" not in html
        assert "Blue Tit" not in html

    def test_detections_with_species_and_search(self, tmp_path):
        """/partials/detections?species=Tawny+Owl&search=*owl* returns filtered HTML."""
        rows = _mixed_species_rows()
        app = _make_app(tmp_path, rows)

        async def _run():
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
                return await c.get(
                    "/partials/detections",
                    params={
                        "species": "Tawny Owl",
                        "search": "*owl*",
                    },
                )

        resp = asyncio.run(_run())
        assert resp.status_code == 200
        html = resp.text
        # Only Tawny Owl should appear (species= is exact match, search is additive)
        assert "Tawny Owl" in html
        # Barn Owl matches search but not the species= exact filter
        assert "Barn Owl" not in html
