"""Tests for biardtz.web — dashboard app, routes, db queries, image cache."""

from __future__ import annotations

import asyncio
import sqlite3
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch
from zoneinfo import ZoneInfo

import httpx

from biardtz.config import Config
from biardtz.web import _make_format_time, create_app
from biardtz.web import db as web_db
from biardtz.web.image_cache import _slug

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


# ---------------------------------------------------------------------------
# db.recent_detections
# ---------------------------------------------------------------------------
class TestRecentDetections:
    def test_returns_empty_list_for_empty_db(self, tmp_path):
        db_path = tmp_path / "test.db"
        _create_test_db(db_path)
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        result = web_db.recent_detections(conn)
        conn.close()
        assert result == []

    def test_returns_correct_data_and_order(self, tmp_path):
        db_path = tmp_path / "test.db"
        rows = [
            ("2025-01-01T08:00:00", "Robin", "Erithacus rubecula", 0.85, 45.0, "NE"),
            ("2025-01-01T09:00:00", "Blackbird", "Turdus merula", 0.70, 180.0, "S"),
            ("2025-01-01T10:00:00", "Wren", "Troglodytes troglodytes", 0.60, None, None),
        ]
        _create_test_db(db_path, rows)
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        result = web_db.recent_detections(conn)
        conn.close()

        assert len(result) == 3
        # Newest first
        assert result[0]["common_name"] == "Wren"
        assert result[1]["common_name"] == "Blackbird"
        assert result[2]["common_name"] == "Robin"

    def test_respects_limit(self, tmp_path):
        db_path = tmp_path / "test.db"
        rows = [
            (f"2025-01-01T{h:02d}:00:00", f"Bird{h}", f"Sp{h}", 0.5, None, None)
            for h in range(10)
        ]
        _create_test_db(db_path, rows)
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        result = web_db.recent_detections(conn, limit=3)
        conn.close()
        assert len(result) == 3

    def test_offset(self, tmp_path):
        db_path = tmp_path / "test.db"
        rows = [
            ("2025-01-01T08:00:00", "Robin", "Erithacus rubecula", 0.85, None, None),
            ("2025-01-01T09:00:00", "Blackbird", "Turdus merula", 0.70, None, None),
            ("2025-01-01T10:00:00", "Wren", "Troglodytes troglodytes", 0.60, None, None),
        ]
        _create_test_db(db_path, rows)
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        result = web_db.recent_detections(conn, limit=2, offset=1)
        conn.close()
        assert len(result) == 2
        assert result[0]["common_name"] == "Blackbird"

    def test_filter_by_species(self, tmp_path):
        db_path = tmp_path / "test.db"
        rows = [
            ("2025-01-01T08:00:00", "Robin", "Erithacus rubecula", 0.85, None, None),
            ("2025-01-01T09:00:00", "Blackbird", "Turdus merula", 0.70, None, None),
        ]
        _create_test_db(db_path, rows)
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        result = web_db.recent_detections(conn, species="Robin")
        conn.close()
        assert len(result) == 1
        assert result[0]["common_name"] == "Robin"

    def test_filter_by_min_confidence(self, tmp_path):
        db_path = tmp_path / "test.db"
        rows = [
            ("2025-01-01T08:00:00", "Robin", "Erithacus rubecula", 0.85, None, None),
            ("2025-01-01T09:00:00", "Blackbird", "Turdus merula", 0.30, None, None),
        ]
        _create_test_db(db_path, rows)
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        result = web_db.recent_detections(conn, min_confidence=0.5)
        conn.close()
        assert len(result) == 1
        assert result[0]["common_name"] == "Robin"

    def test_filter_by_search(self, tmp_path):
        db_path = tmp_path / "test.db"
        rows = [
            ("2025-01-01T08:00:00", "Robin", "Erithacus rubecula", 0.85, None, None),
            ("2025-01-01T09:00:00", "Blackbird", "Turdus merula", 0.70, None, None),
        ]
        _create_test_db(db_path, rows)
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        result = web_db.recent_detections(conn, search="Rob")
        conn.close()
        assert len(result) == 1
        assert result[0]["common_name"] == "Robin"

    def test_filter_by_date_range(self, tmp_path):
        db_path = tmp_path / "test.db"
        rows = [
            ("2025-01-01T08:00:00", "Robin", "Erithacus rubecula", 0.85, None, None),
            ("2025-06-01T09:00:00", "Blackbird", "Turdus merula", 0.70, None, None),
        ]
        _create_test_db(db_path, rows)
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        result = web_db.recent_detections(
            conn, date_from="2025-05-01T00:00:00", date_to="2025-07-01T00:00:00",
        )
        conn.close()
        assert len(result) == 1
        assert result[0]["common_name"] == "Blackbird"

    def test_dict_keys(self, tmp_path):
        db_path = tmp_path / "test.db"
        rows = [
            ("2025-01-01T08:00:00", "Robin", "Erithacus rubecula", 0.85, 45.0, "NE"),
        ]
        _create_test_db(db_path, rows)
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        result = web_db.recent_detections(conn)
        conn.close()

        expected_keys = {
            "id", "timestamp", "common_name", "sci_name",
            "confidence", "bearing", "direction",
        }
        assert set(result[0].keys()) == expected_keys


# ---------------------------------------------------------------------------
# db.species_stats
# ---------------------------------------------------------------------------
class TestSpeciesStats:
    def test_empty_db(self, tmp_path):
        db_path = tmp_path / "test.db"
        _create_test_db(db_path)
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        result = web_db.species_stats(conn)
        conn.close()

        assert result["today_count"] == 0
        assert result["today_species"] == 0
        assert result["all_time_species"] == 0
        assert result["leaderboard"] == []

    def test_today_counts(self, tmp_path):
        db_path = tmp_path / "test.db"
        now = _now_iso()
        rows = [
            (now, "Robin", "Erithacus rubecula", 0.85, None, None),
            (now, "Robin", "Erithacus rubecula", 0.90, None, None),
            (now, "Wren", "Troglodytes troglodytes", 0.60, None, None),
        ]
        _create_test_db(db_path, rows)
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        result = web_db.species_stats(conn)
        conn.close()

        assert result["today_count"] == 3
        assert result["today_species"] == 2

    def test_all_time_species(self, tmp_path):
        db_path = tmp_path / "test.db"
        rows = [
            ("2024-06-01T10:00:00", "Robin", "Erithacus rubecula", 0.85, None, None),
            ("2024-07-01T10:00:00", "Wren", "Troglodytes troglodytes", 0.60, None, None),
            (_now_iso(), "Blackbird", "Turdus merula", 0.70, None, None),
        ]
        _create_test_db(db_path, rows)
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        result = web_db.species_stats(conn)
        conn.close()

        assert result["all_time_species"] == 3

    def test_leaderboard_order(self, tmp_path):
        db_path = tmp_path / "test.db"
        rows = [
            ("2025-01-01T08:00:00", "Robin", "Erithacus rubecula", 0.85, None, None),
            ("2025-01-01T09:00:00", "Robin", "Erithacus rubecula", 0.80, None, None),
            ("2025-01-01T10:00:00", "Robin", "Erithacus rubecula", 0.75, None, None),
            ("2025-01-01T08:00:00", "Wren", "Troglodytes troglodytes", 0.60, None, None),
        ]
        _create_test_db(db_path, rows)
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        result = web_db.species_stats(conn)
        conn.close()

        lb = result["leaderboard"]
        assert len(lb) == 2
        assert lb[0]["common_name"] == "Robin"
        assert lb[0]["count"] == 3
        assert lb[1]["common_name"] == "Wren"
        assert lb[1]["count"] == 1


# ---------------------------------------------------------------------------
# db.detection_timeline
# ---------------------------------------------------------------------------
class TestDetectionTimeline:
    def test_empty_db(self, tmp_path):
        db_path = tmp_path / "test.db"
        _create_test_db(db_path)
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        result = web_db.detection_timeline(conn, days=7)
        conn.close()
        assert result == []

    def test_groups_by_hour(self, tmp_path):
        db_path = tmp_path / "test.db"
        now = _now_iso()
        rows = [
            (now, "Robin", "Erithacus rubecula", 0.85, None, None),
            (now, "Blackbird", "Turdus merula", 0.70, None, None),
        ]
        _create_test_db(db_path, rows)
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        result = web_db.detection_timeline(conn, days=1)
        conn.close()
        assert len(result) >= 1
        assert result[0]["count"] == 2


# ---------------------------------------------------------------------------
# db.species_frequency
# ---------------------------------------------------------------------------
class TestSpeciesFrequency:
    def test_empty_db(self, tmp_path):
        db_path = tmp_path / "test.db"
        _create_test_db(db_path)
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        result = web_db.species_frequency(conn, days=30)
        conn.close()
        assert result == []

    def test_ranks_by_count(self, tmp_path):
        db_path = tmp_path / "test.db"
        now = _now_iso()
        rows = [
            (now, "Robin", "Erithacus rubecula", 0.85, None, None),
            (now, "Robin", "Erithacus rubecula", 0.80, None, None),
            (now, "Wren", "Troglodytes troglodytes", 0.60, None, None),
        ]
        _create_test_db(db_path, rows)
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        result = web_db.species_frequency(conn, days=1)
        conn.close()
        assert result[0]["common_name"] == "Robin"
        assert result[0]["count"] == 2
        assert result[1]["common_name"] == "Wren"

    def test_respects_limit(self, tmp_path):
        db_path = tmp_path / "test.db"
        now = _now_iso()
        rows = [
            (now, "Robin", "Erithacus rubecula", 0.85, None, None),
            (now, "Wren", "Troglodytes troglodytes", 0.60, None, None),
            (now, "Blackbird", "Turdus merula", 0.70, None, None),
        ]
        _create_test_db(db_path, rows)
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        result = web_db.species_frequency(conn, days=1, limit=2)
        conn.close()
        assert len(result) == 2


# ---------------------------------------------------------------------------
# db.activity_heatmap
# ---------------------------------------------------------------------------
class TestActivityHeatmap:
    def test_empty_db(self, tmp_path):
        db_path = tmp_path / "test.db"
        _create_test_db(db_path)
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        result = web_db.activity_heatmap(conn, days=30)
        conn.close()
        assert result == []

    def test_returns_dow_and_hour(self, tmp_path):
        db_path = tmp_path / "test.db"
        now = _now_iso()
        rows = [
            (now, "Robin", "Erithacus rubecula", 0.85, None, None),
        ]
        _create_test_db(db_path, rows)
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        result = web_db.activity_heatmap(conn, days=1)
        conn.close()
        assert len(result) == 1
        assert "dow" in result[0]
        assert "hour" in result[0]
        assert "count" in result[0]


# ---------------------------------------------------------------------------
# db.daily_trend
# ---------------------------------------------------------------------------
class TestDailyTrend:
    def test_empty_db(self, tmp_path):
        db_path = tmp_path / "test.db"
        _create_test_db(db_path)
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        result = web_db.daily_trend(conn, days=30)
        conn.close()
        assert result == []

    def test_groups_by_day(self, tmp_path):
        db_path = tmp_path / "test.db"
        now = _now_iso()
        rows = [
            (now, "Robin", "Erithacus rubecula", 0.85, None, None),
            (now, "Wren", "Troglodytes troglodytes", 0.60, None, None),
        ]
        _create_test_db(db_path, rows)
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        result = web_db.daily_trend(conn, days=1)
        conn.close()
        assert len(result) == 1
        assert result[0]["count"] == 2
        assert result[0]["species"] == 2


# ---------------------------------------------------------------------------
# db.species_list
# ---------------------------------------------------------------------------
class TestSpeciesList:
    def test_empty_db(self, tmp_path):
        db_path = tmp_path / "test.db"
        _create_test_db(db_path)
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        result = web_db.species_list(conn)
        conn.close()
        assert result == []

    def test_returns_distinct_species(self, tmp_path):
        db_path = tmp_path / "test.db"
        rows = [
            ("2025-01-01T08:00:00", "Robin", "Erithacus rubecula", 0.85, None, None),
            ("2025-01-01T09:00:00", "Robin", "Erithacus rubecula", 0.80, None, None),
            ("2025-01-01T10:00:00", "Wren", "Troglodytes troglodytes", 0.60, None, None),
        ]
        _create_test_db(db_path, rows)
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        result = web_db.species_list(conn)
        conn.close()
        assert len(result) == 2
        names = [r["common_name"] for r in result]
        assert "Robin" in names
        assert "Wren" in names

    def test_search_filter(self, tmp_path):
        db_path = tmp_path / "test.db"
        rows = [
            ("2025-01-01T08:00:00", "Robin", "Erithacus rubecula", 0.85, None, None),
            ("2025-01-01T09:00:00", "Wren", "Troglodytes troglodytes", 0.60, None, None),
        ]
        _create_test_db(db_path, rows)
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        result = web_db.species_list(conn, q="Rob")
        conn.close()
        assert len(result) == 1
        assert result[0]["common_name"] == "Robin"


# ---------------------------------------------------------------------------
# _make_format_time (timezone-aware)
# ---------------------------------------------------------------------------
class TestFormatTime:
    _format_time = staticmethod(_make_format_time(ZoneInfo("Europe/London")))

    def test_today_shows_time_only(self):
        local_tz = ZoneInfo("Europe/London")
        now = datetime.now(local_tz)
        iso = now.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00")
        result = self._format_time(iso)
        assert result == now.strftime("%H:%M")

    def test_yesterday_shows_prefix(self):
        local_tz = ZoneInfo("Europe/London")
        yesterday = datetime.now(local_tz) - timedelta(days=1)
        iso = yesterday.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00")
        result = self._format_time(iso)
        assert result.startswith("Yesterday ")
        assert yesterday.strftime("%H:%M") in result

    def test_older_date_shows_day_month(self):
        local_tz = ZoneInfo("Europe/London")
        old = datetime.now(local_tz) - timedelta(days=10)
        iso = old.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00")
        result = self._format_time(iso)
        assert old.strftime("%d %b") in result

    def test_invalid_string_returned_as_is(self):
        assert self._format_time("not-a-date") == "not-a-date"

    def test_none_returned_as_string(self):
        assert self._format_time(None) == "None"


# ---------------------------------------------------------------------------
# image_cache._slug
# ---------------------------------------------------------------------------
class TestImageSlug:
    def test_basic_slug(self):
        assert _slug("Erithacus rubecula") == "erithacus_rubecula"

    def test_special_characters(self):
        assert _slug("Parus (major)") == "parus_major"

    def test_leading_trailing_stripped(self):
        assert _slug("  Turdus merula  ") == "turdus_merula"

    def test_mixed_case(self):
        assert _slug("TROGLODYTES Troglodytes") == "troglodytes_troglodytes"

    def test_multiple_spaces(self):
        assert _slug("Corvus   corone") == "corvus_corone"


# ---------------------------------------------------------------------------
# create_app
# ---------------------------------------------------------------------------
class TestCreateApp:
    def test_returns_fastapi_app(self, tmp_path):
        db_path = tmp_path / "test.db"
        _create_test_db(db_path)
        config = Config(db_path=db_path, bird_image_cache=tmp_path / "img_cache")
        app = create_app(config)

        from fastapi import FastAPI

        assert isinstance(app, FastAPI)

    def test_app_has_expected_routes(self, tmp_path):
        db_path = tmp_path / "test.db"
        _create_test_db(db_path)
        config = Config(db_path=db_path, bird_image_cache=tmp_path / "img_cache")
        app = create_app(config)

        route_paths = [r.path for r in app.routes if hasattr(r, "path")]
        assert "/" in route_paths
        assert "/partials/detections" in route_paths
        assert "/partials/stats" in route_paths
        assert "/api/detections" in route_paths
        assert "/api/image/{sci_name:path}" in route_paths
        assert "/api/charts/timeline" in route_paths
        assert "/api/charts/species" in route_paths
        assert "/api/charts/heatmap" in route_paths
        assert "/api/charts/trend" in route_paths
        assert "/api/species" in route_paths

    def test_app_title(self, tmp_path):
        db_path = tmp_path / "test.db"
        _create_test_db(db_path)
        config = Config(db_path=db_path, bird_image_cache=tmp_path / "img_cache")
        app = create_app(config)
        assert app.title == "biardtz"


# ---------------------------------------------------------------------------
# Routes (using httpx.AsyncClient as ASGI transport)
# ---------------------------------------------------------------------------
def _make_app(tmp_path, rows=None):
    """Helper to create a FastAPI app with a test database."""
    db_path = tmp_path / "test.db"
    _create_test_db(db_path, rows)
    config = Config(
        db_path=db_path,
        bird_image_cache=tmp_path / "img_cache",
    )
    return create_app(config)


class TestRoutes:
    def test_index_returns_200(self, tmp_path):
        now = _now_iso()
        rows = [
            (now, "Robin", "Erithacus rubecula", 0.85, 45.0, "NE"),
        ]
        app = _make_app(tmp_path, rows)

        async def _run():
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
                return await c.get("/")

        resp = asyncio.run(_run())
        assert resp.status_code == 200

    def test_index_contains_biardtz(self, tmp_path):
        now = _now_iso()
        rows = [
            (now, "Robin", "Erithacus rubecula", 0.85, 45.0, "NE"),
        ]
        app = _make_app(tmp_path, rows)

        async def _run():
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
                return await c.get("/")

        resp = asyncio.run(_run())
        assert "biardtz" in resp.text

    def test_partial_detections_returns_html(self, tmp_path):
        now = _now_iso()
        rows = [
            (now, "Robin", "Erithacus rubecula", 0.85, 45.0, "NE"),
            (now, "Blackbird", "Turdus merula", 0.70, 180.0, "S"),
        ]
        app = _make_app(tmp_path, rows)

        async def _run():
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
                return await c.get("/partials/detections")

        resp = asyncio.run(_run())
        assert resp.status_code == 200
        assert "Robin" in resp.text

    def test_partial_stats_returns_html(self, tmp_path):
        now = _now_iso()
        rows = [
            (now, "Robin", "Erithacus rubecula", 0.85, 45.0, "NE"),
        ]
        app = _make_app(tmp_path, rows)

        async def _run():
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
                return await c.get("/partials/stats")

        resp = asyncio.run(_run())
        assert resp.status_code == 200
        assert "Robin" in resp.text

    def test_api_detections_returns_json(self, tmp_path):
        now = _now_iso()
        rows = [
            (now, "Robin", "Erithacus rubecula", 0.85, 45.0, "NE"),
            (now, "Blackbird", "Turdus merula", 0.70, 180.0, "S"),
        ]
        app = _make_app(tmp_path, rows)

        async def _run():
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
                return await c.get("/api/detections")

        resp = asyncio.run(_run())
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) == 2

    def test_api_detections_limit(self, tmp_path):
        now = _now_iso()
        rows = [
            (now, "Robin", "Erithacus rubecula", 0.85, 45.0, "NE"),
            (now, "Blackbird", "Turdus merula", 0.70, 180.0, "S"),
        ]
        app = _make_app(tmp_path, rows)

        async def _run():
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
                return await c.get("/api/detections?limit=1")

        resp = asyncio.run(_run())
        data = resp.json()
        assert len(data) == 1

    def test_api_image_nonexistent_returns_fallback(self, tmp_path):
        app = _make_app(tmp_path)

        async def _run():
            with patch(
                "biardtz.web.image_cache.get_image_path",
                new_callable=AsyncMock,
                return_value=None,
            ):
                transport = httpx.ASGITransport(app=app)
                async with httpx.AsyncClient(
                    transport=transport, base_url="http://test",
                ) as c:
                    return await c.get("/api/image/Nonexistent species")

        resp = asyncio.run(_run())
        assert resp.status_code == 200
        assert "svg" in resp.headers.get("content-type", "").lower()

    def test_api_image_cached_returns_jpeg(self, tmp_path):
        app = _make_app(tmp_path)

        cache_dir = tmp_path / "img_cache"
        cache_dir.mkdir(parents=True, exist_ok=True)
        cached_jpg = cache_dir / "erithacus_rubecula.jpg"
        cached_jpg.write_bytes(
            b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
        )

        async def _run():
            with patch(
                "biardtz.web.image_cache.get_image_path",
                new_callable=AsyncMock,
                return_value=cached_jpg,
            ):
                transport = httpx.ASGITransport(app=app)
                async with httpx.AsyncClient(
                    transport=transport, base_url="http://test",
                ) as c:
                    return await c.get("/api/image/Erithacus rubecula")

        resp = asyncio.run(_run())
        assert resp.status_code == 200
        assert "jpeg" in resp.headers.get("content-type", "").lower()

    def test_api_charts_timeline_returns_json(self, tmp_path):
        now = _now_iso()
        rows = [
            (now, "Robin", "Erithacus rubecula", 0.85, 45.0, "NE"),
        ]
        app = _make_app(tmp_path, rows)

        async def _run():
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
                return await c.get("/api/charts/timeline?days=1")

        resp = asyncio.run(_run())
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) >= 1
        assert "hour" in data[0]
        assert "count" in data[0]

    def test_api_charts_species_returns_json(self, tmp_path):
        now = _now_iso()
        rows = [
            (now, "Robin", "Erithacus rubecula", 0.85, 45.0, "NE"),
        ]
        app = _make_app(tmp_path, rows)

        async def _run():
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
                return await c.get("/api/charts/species?days=1")

        resp = asyncio.run(_run())
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert data[0]["common_name"] == "Robin"

    def test_api_charts_heatmap_returns_json(self, tmp_path):
        now = _now_iso()
        rows = [
            (now, "Robin", "Erithacus rubecula", 0.85, 45.0, "NE"),
        ]
        app = _make_app(tmp_path, rows)

        async def _run():
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
                return await c.get("/api/charts/heatmap?days=1")

        resp = asyncio.run(_run())
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)

    def test_api_charts_trend_returns_json(self, tmp_path):
        now = _now_iso()
        rows = [
            (now, "Robin", "Erithacus rubecula", 0.85, 45.0, "NE"),
        ]
        app = _make_app(tmp_path, rows)

        async def _run():
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
                return await c.get("/api/charts/trend?days=1")

        resp = asyncio.run(_run())
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert data[0]["count"] == 1

    def test_api_species_returns_json(self, tmp_path):
        now = _now_iso()
        rows = [
            (now, "Robin", "Erithacus rubecula", 0.85, 45.0, "NE"),
            (now, "Wren", "Troglodytes troglodytes", 0.60, None, None),
        ]
        app = _make_app(tmp_path, rows)

        async def _run():
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
                return await c.get("/api/species")

        resp = asyncio.run(_run())
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 2

    def test_api_species_search(self, tmp_path):
        now = _now_iso()
        rows = [
            (now, "Robin", "Erithacus rubecula", 0.85, 45.0, "NE"),
            (now, "Wren", "Troglodytes troglodytes", 0.60, None, None),
        ]
        app = _make_app(tmp_path, rows)

        async def _run():
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
                return await c.get("/api/species?q=Rob")

        resp = asyncio.run(_run())
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["common_name"] == "Robin"

    def test_partial_detections_with_filters(self, tmp_path):
        now = _now_iso()
        rows = [
            (now, "Robin", "Erithacus rubecula", 0.85, 45.0, "NE"),
            (now, "Blackbird", "Turdus merula", 0.30, 180.0, "S"),
        ]
        app = _make_app(tmp_path, rows)

        async def _run():
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
                return await c.get("/partials/detections?search=Robin")

        resp = asyncio.run(_run())
        assert resp.status_code == 200
        assert "Robin" in resp.text
        assert "Blackbird" not in resp.text

    def test_empty_index_shows_listening(self, tmp_path):
        app = _make_app(tmp_path)

        async def _run():
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(
                transport=transport, base_url="http://test",
            ) as c:
                return await c.get("/")

        resp = asyncio.run(_run())
        assert resp.status_code == 200
        assert "Listening" in resp.text or "No detections" in resp.text
