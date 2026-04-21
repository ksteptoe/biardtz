"""Tests for biardtz.web — dashboard app, routes, db queries, image cache."""

from __future__ import annotations

import asyncio
import sqlite3
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from zoneinfo import ZoneInfo

import httpx

from biardtz.config import Config
from biardtz.web import _make_format_time, create_app
from biardtz.web import db as web_db
from biardtz.web.image_cache import _fetch_image_url, _slug, get_image_path

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
        assert "/partials/tab/live" in route_paths
        assert "/partials/tab/charts" in route_paths
        assert "/partials/tab/species" in route_paths
        assert "/api/detections" in route_paths
        assert "/api/image/{sci_name:path}" in route_paths
        assert "/api/charts/timeline" in route_paths
        assert "/api/charts/species" in route_paths
        assert "/api/charts/heatmap" in route_paths
        assert "/api/charts/trend" in route_paths
        assert "/api/species" in route_paths
        assert "/api/audio/{filename}" in route_paths
        assert "/partials/health" in route_paths
        assert "/api/health" in route_paths
        assert "/api/health/quick" in route_paths
        assert "/api/health/tier2/db" in route_paths
        assert "/api/health/tier2/birdnet" in route_paths
        assert "/api/health/tier2/hardware" in route_paths
        assert "/api/health/tier2/network" in route_paths
        assert "/api/health/tier2/uptime" in route_paths

    def test_app_title(self, tmp_path):
        db_path = tmp_path / "test.db"
        _create_test_db(db_path)
        config = Config(db_path=db_path, bird_image_cache=tmp_path / "img_cache")
        app = create_app(config)
        assert app.title == "biardtz"


# ---------------------------------------------------------------------------
# Routes (using httpx.AsyncClient as ASGI transport)
# ---------------------------------------------------------------------------
_AUDIO_CLIPS_SCHEMA = """\
CREATE TABLE IF NOT EXISTS audio_clips (
    common_name TEXT PRIMARY KEY,
    confidence  REAL NOT NULL,
    filename    TEXT NOT NULL
);
"""


def _create_audio_clips(path, clips=None):
    """Add audio_clips table and optional rows to an existing test database."""
    conn = sqlite3.connect(str(path))
    conn.executescript(_AUDIO_CLIPS_SCHEMA)
    if clips:
        conn.executemany(
            "INSERT INTO audio_clips (common_name, confidence, filename) VALUES (?, ?, ?)",
            clips,
        )
        conn.commit()
    conn.close()


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

    def test_partial_detections_confidence_filter(self, tmp_path):
        """Slider sends 0-100; route converts to 0.0-1.0 for the db layer."""
        now = _now_iso()
        rows = [
            (now, "Robin", "Erithacus rubecula", 0.85, 45.0, "NE"),
            (now, "Blackbird", "Turdus merula", 0.30, 180.0, "S"),
        ]
        app = _make_app(tmp_path, rows)

        async def _run():
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
                return await c.get("/partials/detections?min_confidence=50")

        resp = asyncio.run(_run())
        assert resp.status_code == 200
        assert "Robin" in resp.text
        assert "Blackbird" not in resp.text

    def test_partial_detections_with_offset(self, tmp_path):
        now = _now_iso()
        rows = [
            (now, "Robin", "Erithacus rubecula", 0.85, 45.0, "NE"),
            (now, "Blackbird", "Turdus merula", 0.70, 180.0, "S"),
            (now, "Wren", "Troglodytes troglodytes", 0.60, None, None),
        ]
        app = _make_app(tmp_path, rows)

        async def _run():
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
                return await c.get("/partials/detections?offset=1&limit=10")

        resp = asyncio.run(_run())
        assert resp.status_code == 200
        # 3 rows minus offset=1 => 2 results; newest first so first skipped
        text = resp.text
        # Should have 2 of the 3 birds (the first in order is skipped)
        bird_count = sum(1 for b in ["Robin", "Blackbird", "Wren"] if b in text)
        assert bird_count == 2

    def test_partial_detections_with_date_range(self, tmp_path):
        rows = [
            ("2025-01-15T08:00:00", "Robin", "Erithacus rubecula", 0.85, None, None),
            ("2025-06-15T09:00:00", "Blackbird", "Turdus merula", 0.70, None, None),
        ]
        app = _make_app(tmp_path, rows)

        async def _run():
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
                return await c.get(
                    "/partials/detections?date_from=2025-06-01T00:00:00&date_to=2025-07-01T00:00:00"
                )

        resp = asyncio.run(_run())
        assert resp.status_code == 200
        assert "Blackbird" in resp.text
        assert "Robin" not in resp.text

    def test_index_contains_filter_bar(self, tmp_path):
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
        assert 'id="filters"' in resp.text

    def test_index_contains_detection_results_div(self, tmp_path):
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
        assert 'id="detection-results"' in resp.text

    def test_partial_detections_load_more_shown(self, tmp_path):
        """When result count == limit (default 20), 'Load more' button appears."""
        now = _now_iso()
        rows = [
            (now, f"Bird{i}", f"Species {i}", 0.80, None, None)
            for i in range(20)
        ]
        app = _make_app(tmp_path, rows)

        async def _run():
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
                return await c.get("/partials/detections")

        resp = asyncio.run(_run())
        assert resp.status_code == 200
        assert "Load more" in resp.text

    def test_partial_detections_load_more_hidden(self, tmp_path):
        """When result count < limit, 'Load more' button should not appear."""
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
        assert "Load more" not in resp.text

    # -- Milestone 3: tab partials -------------------------------------------

    def test_tab_live_returns_html(self, tmp_path):
        now = _now_iso()
        rows = [
            (now, "Robin", "Erithacus rubecula", 0.85, 45.0, "NE"),
        ]
        app = _make_app(tmp_path, rows)

        async def _run():
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
                return await c.get("/partials/tab/live")

        resp = asyncio.run(_run())
        assert resp.status_code == 200
        assert "Recent Detections" in resp.text

    def test_tab_charts_returns_html(self, tmp_path):
        app = _make_app(tmp_path)

        async def _run():
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
                return await c.get("/partials/tab/charts")

        resp = asyncio.run(_run())
        assert resp.status_code == 200
        assert "Charts" in resp.text

    def test_tab_species_returns_html(self, tmp_path):
        now = _now_iso()
        rows = [
            (now, "Robin", "Erithacus rubecula", 0.85, 45.0, "NE"),
        ]
        app = _make_app(tmp_path, rows)

        async def _run():
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
                return await c.get("/partials/tab/species")

        resp = asyncio.run(_run())
        assert resp.status_code == 200
        assert "Species Leaderboard" in resp.text

    def test_index_contains_tab_navigation(self, tmp_path):
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
        assert "tab-btn" in resp.text

    # -- Milestone 6: cache-control headers ----------------------------------

    def test_chart_timeline_cache_control(self, tmp_path):
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
        assert "max-age=60" in resp.headers.get("cache-control", "")

    def test_chart_species_cache_control(self, tmp_path):
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
        assert "max-age=60" in resp.headers.get("cache-control", "")

    def test_chart_heatmap_cache_control(self, tmp_path):
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
        assert "max-age=60" in resp.headers.get("cache-control", "")

    def test_chart_trend_cache_control(self, tmp_path):
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
        assert "max-age=60" in resp.headers.get("cache-control", "")


# ---------------------------------------------------------------------------
# db.species_audio_map
# ---------------------------------------------------------------------------
class TestSpeciesAudioMap:
    def test_returns_empty_dict_when_no_table(self, tmp_path):
        """Returns empty dict when audio_clips table doesn't exist."""
        db_path = tmp_path / "test.db"
        _create_test_db(db_path)
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        result = web_db.species_audio_map(conn)
        conn.close()
        assert result == {}

    def test_returns_map_with_data(self, tmp_path):
        """Returns {common_name: filename} when audio_clips has data."""
        db_path = tmp_path / "test.db"
        _create_test_db(db_path)
        _create_audio_clips(db_path, [
            ("Robin", 0.85, "robin_001.wav"),
            ("Wren", 0.70, "wren_002.wav"),
        ])
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        result = web_db.species_audio_map(conn)
        conn.close()
        assert result == {"Robin": "robin_001.wav", "Wren": "wren_002.wav"}


# ---------------------------------------------------------------------------
# Audio routes
# ---------------------------------------------------------------------------
class TestAudioRoutes:
    def test_api_audio_serves_file(self, tmp_path):
        """GET /api/audio/{filename} returns 200 with audio/wav for existing file."""
        app = _make_app(tmp_path)
        audio_dir = tmp_path / "audio_clips"
        audio_dir.mkdir(parents=True, exist_ok=True)
        wav_file = audio_dir / "test.wav"
        wav_file.write_bytes(b"RIFF\x00\x00\x00\x00WAVEfmt ")

        async def _run():
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
                return await c.get("/api/audio/test.wav")

        resp = asyncio.run(_run())
        assert resp.status_code == 200
        assert "audio/wav" in resp.headers.get("content-type", "").lower()

    def test_api_audio_missing_returns_404(self, tmp_path):
        """GET /api/audio/nonexistent.wav returns 404."""
        app = _make_app(tmp_path)
        audio_dir = tmp_path / "audio_clips"
        audio_dir.mkdir(parents=True, exist_ok=True)

        async def _run():
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
                return await c.get("/api/audio/nonexistent.wav")

        resp = asyncio.run(_run())
        assert resp.status_code == 404

    def test_api_audio_path_traversal_slash_blocked(self, tmp_path):
        """Slash in filename is blocked by the framework (never reaches handler)."""
        app = _make_app(tmp_path)

        async def _run():
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
                return await c.get("/api/audio/foo%2Fbar.wav")

        resp = asyncio.run(_run())
        assert resp.status_code in (400, 404)

    def test_api_audio_backslash_rejected(self, tmp_path):
        """Path traversal with backslash is rejected."""
        app = _make_app(tmp_path)
        # Create the file so we know 400 is from the check, not 404
        (tmp_path / "audio" / "foo\\bar.wav").parent.mkdir(parents=True, exist_ok=True)

        async def _run():
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
                return await c.get("/api/audio/foo%5Cbar.wav")

        resp = asyncio.run(_run())
        assert resp.status_code == 400

    def test_api_audio_dotdot_rejected(self, tmp_path):
        """Filename containing '..' is rejected."""
        app = _make_app(tmp_path)

        async def _run():
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
                return await c.get("/api/audio/..secret.wav")

        resp = asyncio.run(_run())
        assert resp.status_code == 400

    def test_detection_card_has_audio_file(self, tmp_path):
        """When audio_clips table has data, _detections partial includes audio element."""
        now = _now_iso()
        rows = [
            (now, "Robin", "Erithacus rubecula", 0.85, 45.0, "NE"),
        ]
        db_path = tmp_path / "test.db"
        _create_test_db(db_path, rows)
        _create_audio_clips(db_path, [("Robin", 0.85, "robin.wav")])
        config = Config(
            db_path=db_path,
            bird_image_cache=tmp_path / "img_cache",
            audio_clip_dir=tmp_path / "audio_clips",
        )
        app = create_app(config)

        async def _run():
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
                return await c.get("/partials/detections")

        resp = asyncio.run(_run())
        assert resp.status_code == 200
        # The partial should contain a reference to the audio file
        assert "robin.wav" in resp.text or "audio" in resp.text.lower()


# ---------------------------------------------------------------------------
# Drill-down feature
# ---------------------------------------------------------------------------
class TestDrillDown:
    def test_partials_detections_species_filter(self, tmp_path):
        """GET /partials/detections?species=Robin returns only Robin detections."""
        now = _now_iso()
        rows = [
            (now, "Robin", "Erithacus rubecula", 0.85, 45.0, "NE"),
            (now, "Blackbird", "Turdus merula", 0.70, 180.0, "S"),
            (now, "Wren", "Troglodytes troglodytes", 0.60, None, None),
        ]
        app = _make_app(tmp_path, rows)

        async def _run():
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
                return await c.get("/partials/detections?species=Robin")

        resp = asyncio.run(_run())
        assert resp.status_code == 200
        assert "Robin" in resp.text
        assert "Blackbird" not in resp.text
        assert "Wren" not in resp.text

    def test_partials_detections_combined_species_and_date(self, tmp_path):
        """GET /partials/detections?species=Robin&date_from=X&date_to=Y filters both."""
        rows = [
            ("2025-01-15T08:00:00", "Robin", "Erithacus rubecula", 0.85, None, None),
            ("2025-06-15T09:00:00", "Robin", "Erithacus rubecula", 0.90, None, None),
            ("2025-06-15T10:00:00", "Blackbird", "Turdus merula", 0.70, None, None),
        ]
        app = _make_app(tmp_path, rows)

        async def _run():
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
                return await c.get(
                    "/partials/detections?species=Robin"
                    "&date_from=2025-06-01T00:00:00&date_to=2025-07-01T00:00:00"
                )

        resp = asyncio.run(_run())
        assert resp.status_code == 200
        assert "Robin" in resp.text
        # January Robin excluded by date range
        # Blackbird excluded by species filter
        assert "Blackbird" not in resp.text

    def test_index_contains_drill_down_panel(self, tmp_path):
        """GET / response contains the drill-down panel div."""
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
        assert 'id="drill-down-panel"' in resp.text

    def test_index_contains_drill_down_js(self, tmp_path):
        """GET / response contains the drillDown JavaScript function."""
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
        assert "function drillDown" in resp.text


# ---------------------------------------------------------------------------
# image_cache — async functions
# ---------------------------------------------------------------------------
class TestImageCache:
    def test_cache_hit_returns_path_without_fetch(self, tmp_path):
        """When the cached .jpg already exists, return it immediately."""
        cache_dir = tmp_path / "img_cache"
        cache_dir.mkdir()
        cached_file = cache_dir / "erithacus_rubecula.jpg"
        cached_file.write_bytes(b"\xff\xd8\xff")

        async def _run():
            return await get_image_path("Erithacus rubecula", cache_dir)

        result = asyncio.run(_run())
        assert result == cached_file

    def test_cache_miss_fetches_and_saves(self, tmp_path):
        """On cache miss, fetch from Wikidata and save to cache_dir."""
        cache_dir = tmp_path / "img_cache"
        cache_dir.mkdir()

        # Build a minimal valid JPEG-like image via PIL
        from io import BytesIO

        from PIL import Image

        img_buf = BytesIO()
        Image.new("RGB", (100, 100), "red").save(img_buf, "JPEG")
        img_bytes = img_buf.getvalue()

        mock_thumb_url = "https://upload.wikimedia.org/thumb/test.jpg"

        async def _run():
            with patch(
                "biardtz.web.image_cache._fetch_image_url",
                new_callable=AsyncMock,
                return_value=mock_thumb_url,
            ):
                mock_resp = AsyncMock()
                mock_resp.status_code = 200
                mock_resp.content = img_bytes

                mock_client = AsyncMock()
                mock_client.get = AsyncMock(return_value=mock_resp)
                mock_client.__aenter__ = AsyncMock(return_value=mock_client)
                mock_client.__aexit__ = AsyncMock(return_value=False)

                with patch("biardtz.web.image_cache.httpx.AsyncClient", return_value=mock_client):
                    return await get_image_path("Erithacus rubecula", cache_dir)

        result = asyncio.run(_run())
        assert result is not None
        assert result.exists()
        assert result.name == "erithacus_rubecula.jpg"

    def test_fetch_failure_creates_marker(self, tmp_path):
        """When fetch fails, a .none marker is created and None returned."""
        cache_dir = tmp_path / "img_cache"
        cache_dir.mkdir()

        async def _run():
            with patch(
                "biardtz.web.image_cache._fetch_image_url",
                new_callable=AsyncMock,
                return_value=None,
            ):
                return await get_image_path("Erithacus rubecula", cache_dir)

        result = asyncio.run(_run())
        assert result is None
        assert (cache_dir / "erithacus_rubecula.none").exists()

    def test_marker_file_returns_none_immediately(self, tmp_path):
        """When .none marker exists, return None without fetching."""
        cache_dir = tmp_path / "img_cache"
        cache_dir.mkdir()
        marker = cache_dir / "erithacus_rubecula.none"
        marker.touch()

        async def _run():
            return await get_image_path("Erithacus rubecula", cache_dir)

        result = asyncio.run(_run())
        assert result is None

    def test_fetch_image_url_extracts_url(self):
        """_fetch_image_url parses Wikidata API response to get image URL."""

        async def _run():
            search_resp = MagicMock()
            search_resp.json.return_value = {
                "search": [{"id": "Q25394"}],
            }
            claims_resp = MagicMock()
            claims_resp.json.return_value = {
                "claims": {
                    "P18": [
                        {"mainsnak": {"datavalue": {"value": "Robin_test.jpg"}}},
                    ],
                },
            }

            mock_client = AsyncMock()
            mock_client.get = AsyncMock(side_effect=[search_resp, claims_resp])
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)

            with patch("biardtz.web.image_cache.httpx.AsyncClient", return_value=mock_client):
                return await _fetch_image_url("Erithacus rubecula")

        result = asyncio.run(_run())
        assert result is not None
        assert "Robin_test.jpg" in result

    def test_fetch_image_url_returns_none_when_no_results(self):
        """_fetch_image_url returns None when Wikidata search finds nothing."""

        async def _run():
            search_resp = MagicMock()
            search_resp.json.return_value = {"search": []}

            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=search_resp)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)

            with patch("biardtz.web.image_cache.httpx.AsyncClient", return_value=mock_client):
                return await _fetch_image_url("Nonexistent bird")

        result = asyncio.run(_run())
        assert result is None

    def test_fetch_image_url_returns_none_when_no_p18_claim(self):
        """_fetch_image_url returns None when entity has no P18 (image) claim."""

        async def _run():
            search_resp = MagicMock()
            search_resp.json.return_value = {
                "search": [{"id": "Q12345"}],
            }
            claims_resp = MagicMock()
            claims_resp.json.return_value = {"claims": {}}

            mock_client = AsyncMock()
            mock_client.get = AsyncMock(side_effect=[search_resp, claims_resp])
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)

            with patch("biardtz.web.image_cache.httpx.AsyncClient", return_value=mock_client):
                return await _fetch_image_url("Some bird")

        result = asyncio.run(_run())
        assert result is None


# ---------------------------------------------------------------------------
# Health route tests
# ---------------------------------------------------------------------------


def _mock_health_probes():
    """Return a tuple of patch objects that mock all health check probes to
    avoid subprocess calls, /proc reads, and os.statvfs on the test machine."""
    tier1_result = {
        "pipeline": {
            "status": "fail", "label": "Pipeline", "detail": "No heartbeat",
            "pid": None, "detections": 0, "species": 0,
            "heartbeat_age": None, "audio": "unknown", "errors": [],
        },
        "software": {
            "status": "ok", "label": "Software",
            "biardtz_version": "1.0.0", "python_version": "3.12.0",
        },
        "database": {
            "status": "ok", "label": "Database", "detail": "0.1 MB",
            "size_mb": 0.1, "wal_mb": 0, "path": "/tmp/test.db",
        },
        "config": {
            "status": "ok", "label": "Config", "location": "London",
            "latitude": 51.5, "longitude": -0.1,
            "confidence_threshold": 0.25, "sample_rate": 48000,
            "channels": 1, "timezone": "Europe/London",
        },
    }
    tier2_result = {
        "hardware": {
            "cpu_temp": {
                "status": "ok", "label": "CPU Temp",
                "detail": "45.0\u00b0C", "temp_c": 45.0,
            },
            "memory": {
                "status": "ok", "label": "Memory", "detail": "50% used",
                "total_mb": 7812, "used_mb": 3906, "percent": 50,
            },
            "disk": {
                "status": "ok", "label": "Disk",
                "detail": "50% used (50 GB free)",
                "total_gb": 100.0, "free_gb": 50.0, "percent": 50,
            },
            "microphone": {
                "status": "ok", "label": "Microphone",
                "detail": "ReSpeaker detected",
            },
        },
        "network": {
            "status": "ok", "label": "Network",
            "detail": "MyWiFi \u00b7 192.168.1.50",
            "ips": ["192.168.1.50"], "ssid": "MyWiFi", "tailscale": None,
        },
        "service": {
            "status": "ok", "label": "Service", "detail": "active",
            "active": True, "since": "Mon 2026-04-20 10:00:00 BST",
        },
        "uptime": {
            "status": "ok", "label": "System Uptime",
            "detail": "1d 2h 30m", "seconds": 95400,
        },
        "birdnet": {
            "status": "ok", "label": "BirdNET", "detail": "6000 species",
            "path": "/opt/BirdNET", "model_found": True, "label_count": 6000,
        },
        "db_integrity": {
            "status": "ok", "label": "DB Integrity", "detail": "ok",
            "total_detections": 100, "total_species": 20, "audio_clips": 5,
        },
    }

    return (
        patch("biardtz.web.health_checks.tier1_checks", return_value=tier1_result),
        patch("biardtz.web.health_checks.tier2_checks", return_value=tier2_result),
        patch("biardtz.web.health_checks.quick_status", return_value="green"),
        patch("biardtz.web.health_checks.check_cpu_temp", return_value=tier2_result["hardware"]["cpu_temp"]),
        patch("biardtz.web.health_checks.check_memory", return_value=tier2_result["hardware"]["memory"]),
        patch("biardtz.web.health_checks.check_disk", return_value=tier2_result["hardware"]["disk"]),
        patch("biardtz.web.health_checks.check_microphone", return_value=tier2_result["hardware"]["microphone"]),
        patch("biardtz.web.health_checks.check_network", return_value=tier2_result["network"]),
        patch("biardtz.web.health_checks.check_systemd", return_value=tier2_result["service"]),
        patch("biardtz.web.health_checks.check_system_uptime", return_value=tier2_result["uptime"]),
        patch("biardtz.web.health_checks.check_birdnet", return_value=tier2_result["birdnet"]),
        patch("biardtz.web.health_checks.check_db_integrity", return_value=tier2_result["db_integrity"]),
    )


class TestHealthRoutes:
    """Tests for the health panel and health API routes."""

    def _run_with_mocks(self, tmp_path, path: str):
        """Helper: create app, mock all health probes, GET the path."""
        app = _make_app(tmp_path)
        patches = _mock_health_probes()

        async def _run():
            for p in patches:
                p.start()
            try:
                transport = httpx.ASGITransport(app=app)
                async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
                    return await c.get(path)
            finally:
                for p in patches:
                    p.stop()

        return asyncio.run(_run())

    def test_partials_health_returns_200(self, tmp_path):
        resp = self._run_with_mocks(tmp_path, "/partials/health")
        assert resp.status_code == 200
        assert "text/html" in resp.headers.get("content-type", "")

    def test_api_health_quick_returns_json_with_color(self, tmp_path):
        resp = self._run_with_mocks(tmp_path, "/api/health/quick")
        assert resp.status_code == 200
        data = resp.json()
        assert "color" in data
        assert data["color"] in ("green", "yellow", "red")

    def test_api_health_returns_json_with_sections(self, tmp_path):
        resp = self._run_with_mocks(tmp_path, "/api/health")
        assert resp.status_code == 200
        data = resp.json()
        # Tier 1 sections
        assert "pipeline" in data
        assert "software" in data
        assert "database" in data
        assert "config" in data
        # Tier 2 sections
        assert "hardware" in data
        assert "network" in data
        assert "service" in data
        assert "uptime" in data
        assert "birdnet" in data
        assert "db_integrity" in data

    def test_tier2_db_returns_200(self, tmp_path):
        resp = self._run_with_mocks(tmp_path, "/api/health/tier2/db")
        assert resp.status_code == 200
        assert "text/html" in resp.headers.get("content-type", "")
        assert "Integrity" in resp.text

    def test_tier2_birdnet_returns_200(self, tmp_path):
        resp = self._run_with_mocks(tmp_path, "/api/health/tier2/birdnet")
        assert resp.status_code == 200
        assert "text/html" in resp.headers.get("content-type", "")
        assert "BirdNET" in resp.text

    def test_tier2_hardware_returns_200(self, tmp_path):
        resp = self._run_with_mocks(tmp_path, "/api/health/tier2/hardware")
        assert resp.status_code == 200
        assert "text/html" in resp.headers.get("content-type", "")
        assert "Hardware" in resp.text

    def test_tier2_network_returns_200(self, tmp_path):
        resp = self._run_with_mocks(tmp_path, "/api/health/tier2/network")
        assert resp.status_code == 200
        assert "text/html" in resp.headers.get("content-type", "")
        assert "Network" in resp.text

    def test_tier2_uptime_returns_200(self, tmp_path):
        resp = self._run_with_mocks(tmp_path, "/api/health/tier2/uptime")
        assert resp.status_code == 200
        assert "text/html" in resp.headers.get("content-type", "")
        assert "Uptime" in resp.text

    def test_api_health_quick_red_when_no_heartbeat(self, tmp_path):
        """quick_status returns red when pipeline is down."""
        app = _make_app(tmp_path)

        async def _run():
            with patch("biardtz.web.health_checks.quick_status", return_value="red"):
                transport = httpx.ASGITransport(app=app)
                async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
                    return await c.get("/api/health/quick")

        resp = asyncio.run(_run())
        assert resp.json()["color"] == "red"

    def test_api_health_quick_yellow_when_degraded(self, tmp_path):
        """quick_status returns yellow when pipeline is degraded."""
        app = _make_app(tmp_path)

        async def _run():
            with patch("biardtz.web.health_checks.quick_status", return_value="yellow"):
                transport = httpx.ASGITransport(app=app)
                async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
                    return await c.get("/api/health/quick")

        resp = asyncio.run(_run())
        assert resp.json()["color"] == "yellow"

    def test_tier2_hardware_contains_progress_bars(self, tmp_path):
        """Hardware fragment includes memory and disk progress bars."""
        resp = self._run_with_mocks(tmp_path, "/api/health/tier2/hardware")
        assert resp.status_code == 200
        # Progress bars use width style
        assert "style=" in resp.text
        assert "50%" in resp.text  # memory and disk both at 50%

    def test_tier2_db_shows_counts(self, tmp_path):
        """DB fragment shows detection and species counts."""
        resp = self._run_with_mocks(tmp_path, "/api/health/tier2/db")
        assert "100" in resp.text  # total_detections
        assert "20" in resp.text   # total_species

    def test_tier2_network_shows_service_info(self, tmp_path):
        """Network fragment includes service status."""
        resp = self._run_with_mocks(tmp_path, "/api/health/tier2/network")
        assert "Service" in resp.text
        assert "active" in resp.text
