"""Tests for biardtz.web.db — wildcard/glob search and timeline."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pytest

from biardtz.web.db import (
    _GLOB_CHARS,
    _utc_offset_modifier,
    detection_timeline,
    recent_detections,
    species_frequency,
    species_list,
    species_stats,
)

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

_SCHEMA_WITH_VERIFIED = """\
CREATE TABLE IF NOT EXISTS detections (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp     TEXT NOT NULL,
    common_name   TEXT NOT NULL,
    sci_name      TEXT NOT NULL,
    confidence    REAL NOT NULL,
    latitude      REAL,
    longitude     REAL,
    bearing       REAL,
    direction     TEXT,
    verified      INTEGER DEFAULT 1
);
"""


def _today_at(hour: int, minute: int = 0) -> str:
    """Return an ISO timestamp for today at the given UTC hour/minute."""
    now = datetime.now(timezone.utc)
    return now.replace(hour=hour, minute=minute, second=0, microsecond=0).strftime(
        "%Y-%m-%dT%H:%M:%S"
    )


def _sample_rows():
    """Generate sample rows with today's date so they always fall within a 7-day window."""
    return [
        (_today_at(8, 0), "Blue Tit", "Cyanistes caeruleus", 0.85, None, None),
        (_today_at(8, 5), "Great Tit", "Parus major", 0.90, None, None),
        (_today_at(8, 10), "Robin", "Erithacus rubecula", 0.75, None, None),
        (_today_at(8, 15), "Wren", "Troglodytes troglodytes", 0.80, None, None),
        (_today_at(8, 20), "Blackbird", "Turdus merula", 0.88, None, None),
        (_today_at(8, 25), "Chaffinch", "Fringilla coelebs", 0.70, None, None),
        (_today_at(8, 30), "Goldfinch", "Carduelis carduelis", 0.82, None, None),
    ]


@pytest.fixture()
def db_conn():
    """In-memory SQLite database with sample detection data."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA)
    conn.executemany(
        "INSERT INTO detections "
        "(timestamp, common_name, sci_name, confidence, bearing, direction) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        _sample_rows(),
    )
    conn.commit()
    yield conn
    conn.close()


# ---------------------------------------------------------------------------
# _GLOB_CHARS regex detection
# ---------------------------------------------------------------------------

class TestGlobCharsRegex:
    """Verify the _GLOB_CHARS regex correctly identifies glob patterns."""

    def test_detects_star(self):
        assert _GLOB_CHARS.search("Blue*") is not None

    def test_detects_question_mark(self):
        assert _GLOB_CHARS.search("Wre?") is not None

    def test_detects_bracket(self):
        assert _GLOB_CHARS.search("[BG]*") is not None

    def test_plain_text_no_match(self):
        assert _GLOB_CHARS.search("Robin") is None

    def test_space_no_match(self):
        assert _GLOB_CHARS.search("Blue Tit") is None


# ---------------------------------------------------------------------------
# recent_detections — plain text search (LIKE)
# ---------------------------------------------------------------------------

class TestRecentDetectionsPlainSearch:
    """Plain text search uses LIKE %search% (substring match)."""

    def test_substring_match(self, db_conn):
        results = recent_detections(db_conn, search="Tit")
        names = {r["common_name"] for r in results}
        assert names == {"Blue Tit", "Great Tit"}

    def test_substring_case_insensitive(self, db_conn):
        # SQLite LIKE is case-insensitive for ASCII by default
        results = recent_detections(db_conn, search="tit")
        names = {r["common_name"] for r in results}
        assert names == {"Blue Tit", "Great Tit"}

    def test_no_match_returns_empty(self, db_conn):
        results = recent_detections(db_conn, search="Penguin")
        assert results == []


# ---------------------------------------------------------------------------
# recent_detections — wildcard search (GLOB)
# ---------------------------------------------------------------------------

class TestRecentDetectionsGlobSearch:
    """Wildcard patterns use SQLite GLOB (case-sensitive)."""

    def test_star_wildcard(self, db_conn):
        """'Blue*' matches 'Blue Tit' but not 'Great Tit'."""
        results = recent_detections(db_conn, search="Blue*")
        names = {r["common_name"] for r in results}
        assert "Blue Tit" in names
        assert "Great Tit" not in names

    def test_star_wildcard_multiple_matches(self, db_conn):
        """'*finch' matches 'Chaffinch' and 'Goldfinch'."""
        results = recent_detections(db_conn, search="*finch")
        names = {r["common_name"] for r in results}
        assert names == {"Chaffinch", "Goldfinch"}

    def test_question_mark_wildcard(self, db_conn):
        """'Wre?' matches 'Wren' (exactly 4 chars)."""
        results = recent_detections(db_conn, search="Wre?")
        names = {r["common_name"] for r in results}
        assert names == {"Wren"}

    def test_question_mark_no_match(self, db_conn):
        """'Wre??' does not match 'Wren' (too many chars)."""
        results = recent_detections(db_conn, search="Wre??")
        assert results == []

    def test_bracket_character_class(self, db_conn):
        """'[BG]*' matches names starting with B or G."""
        results = recent_detections(db_conn, search="[BG]*")
        names = {r["common_name"] for r in results}
        assert "Blue Tit" in names
        assert "Great Tit" in names
        assert "Blackbird" in names
        assert "Goldfinch" in names
        assert "Robin" not in names
        assert "Wren" not in names

    def test_bracket_range(self, db_conn):
        """'[A-C]*' matches names starting with A, B, or C."""
        results = recent_detections(db_conn, search="[A-C]*")
        names = {r["common_name"] for r in results}
        assert "Blue Tit" in names
        assert "Blackbird" in names
        assert "Chaffinch" in names
        assert "Great Tit" not in names
        assert "Robin" not in names

    def test_glob_is_case_insensitive(self, db_conn):
        """GLOB is case-insensitive, so 'blue*' matches 'Blue Tit'."""
        results = recent_detections(db_conn, search="blue*")
        assert len(results) == 1
        assert results[0]["common_name"] == "Blue Tit"


# ---------------------------------------------------------------------------
# species_list — plain text search (LIKE)
# ---------------------------------------------------------------------------

class TestSpeciesListPlainSearch:
    """species_list with plain text uses LIKE %q% substring match."""

    def test_substring_match(self, db_conn):
        results = species_list(db_conn, q="Tit")
        names = {r["common_name"] for r in results}
        assert names == {"Blue Tit", "Great Tit"}

    def test_no_filter_returns_all(self, db_conn):
        results = species_list(db_conn)
        assert len(results) == 7  # all species in sample data

    def test_no_match_returns_empty(self, db_conn):
        results = species_list(db_conn, q="Eagle")
        assert results == []


# ---------------------------------------------------------------------------
# species_list — wildcard search (GLOB)
# ---------------------------------------------------------------------------

class TestSpeciesListGlobSearch:
    """species_list with glob patterns uses SQLite GLOB."""

    def test_star_wildcard(self, db_conn):
        results = species_list(db_conn, q="*finch")
        names = {r["common_name"] for r in results}
        assert names == {"Chaffinch", "Goldfinch"}

    def test_bracket_pattern(self, db_conn):
        results = species_list(db_conn, q="[RW]*")
        names = {r["common_name"] for r in results}
        assert names == {"Robin", "Wren"}

    def test_question_mark(self, db_conn):
        results = species_list(db_conn, q="Wre?")
        names = {r["common_name"] for r in results}
        assert names == {"Wren"}

    def test_results_include_sci_name(self, db_conn):
        results = species_list(db_conn, q="Blue*")
        assert len(results) == 1
        assert results[0]["sci_name"] == "Cyanistes caeruleus"

    def test_results_ordered_alphabetically(self, db_conn):
        results = species_list(db_conn, q="[BG]*")
        names = [r["common_name"] for r in results]
        assert names == sorted(names)


# ---------------------------------------------------------------------------
# _utc_offset_modifier
# ---------------------------------------------------------------------------


class TestUtcOffsetModifier:
    """Verify the SQLite modifier string for timezone offsets."""

    def test_utc_returns_zero(self):
        result = _utc_offset_modifier(ZoneInfo("UTC"))
        assert result == "+0 hours"

    def test_positive_offset(self):
        # Europe/London is UTC+1 during BST
        result = _utc_offset_modifier(ZoneInfo("Europe/London"))
        assert result in ("+0 hours", "+1 hours")  # depends on DST

    def test_negative_offset(self):
        result = _utc_offset_modifier(ZoneInfo("America/New_York"))
        assert result in ("-5 hours", "-4 hours")  # depends on DST

    def test_none_defaults_to_utc(self):
        assert _utc_offset_modifier(None) == "+0 hours"


# ---------------------------------------------------------------------------
# detection_timeline — local hour grouping
# ---------------------------------------------------------------------------


class TestDetectionTimeline:
    """Verify timeline groups detections by local hour, not UTC."""

    def test_timeline_returns_hourly_counts(self, db_conn):
        # All sample rows are in the 08:xx UTC hour
        results = detection_timeline(db_conn, days=7, local_tz=ZoneInfo("UTC"))
        assert len(results) == 1
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        assert results[0]["hour"] == f"{today}T08:00:00"
        assert results[0]["count"] == 7

    def test_timeline_shifts_hour_for_positive_offset(self, db_conn):
        # UTC+2: 08:xx UTC becomes 10:xx local
        tz = ZoneInfo("Europe/Helsinki")  # UTC+2 in winter, UTC+3 in summer
        results = detection_timeline(db_conn, days=7, local_tz=tz)
        assert len(results) == 1
        hour = results[0]["hour"]
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        # Should be shifted forward from 08:00 UTC
        assert hour > f"{today}T08:00:00"

    def test_timeline_shifts_hour_for_negative_offset(self, db_conn):
        # UTC-5: 08:xx UTC becomes 03:xx local
        tz = ZoneInfo("America/New_York")
        results = detection_timeline(db_conn, days=7, local_tz=tz)
        assert len(results) == 1
        hour = results[0]["hour"]
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        # Should be shifted back from 08:00 UTC
        assert hour < f"{today}T08:00:00"


# ---------------------------------------------------------------------------
# Verification column tests
# ---------------------------------------------------------------------------


def _sample_rows_verified():
    """Sample rows including verified column — mix of verified and unverified."""
    return [
        (_today_at(8, 0), "Blue Tit", "Cyanistes caeruleus", 0.85, None, None, 1),
        (_today_at(8, 5), "Great Tit", "Parus major", 0.90, None, None, 1),
        (_today_at(8, 10), "Robin", "Erithacus rubecula", 0.75, None, None, 0),
        (_today_at(8, 15), "Wren", "Troglodytes troglodytes", 0.80, None, None, 1),
        (_today_at(8, 20), "Blackbird", "Turdus merula", 0.88, None, None, 0),
        (_today_at(8, 25), "Chaffinch", "Fringilla coelebs", 0.70, None, None, 1),
        (_today_at(8, 30), "Goldfinch", "Carduelis carduelis", 0.82, None, None, 1),
    ]


@pytest.fixture()
def db_conn_verified():
    """In-memory SQLite DB with verified column and mixed verified/unverified rows."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA_WITH_VERIFIED)
    conn.executemany(
        "INSERT INTO detections "
        "(timestamp, common_name, sci_name, confidence, bearing, direction, verified) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        _sample_rows_verified(),
    )
    conn.commit()
    yield conn
    conn.close()


class TestRecentDetectionsVerified:
    """Tests for recent_detections with the verified column."""

    def test_returns_verified_key(self, db_conn_verified):
        results = recent_detections(db_conn_verified, limit=10)
        assert all("verified" in r for r in results)

    def test_includes_both_verified_and_unverified(self, db_conn_verified):
        """recent_detections returns all rows regardless of verified status."""
        results = recent_detections(db_conn_verified, limit=10)
        verified_values = {r["verified"] for r in results}
        assert 0 in verified_values
        assert 1 in verified_values

    def test_unverified_rows_have_verified_zero(self, db_conn_verified):
        results = recent_detections(db_conn_verified, limit=10)
        robin = [r for r in results if r["common_name"] == "Robin"]
        assert len(robin) == 1
        assert robin[0]["verified"] == 0


class TestRecentDetectionsBackwardCompat:
    """DB without verified column should still work (all treated as verified)."""

    def test_no_verified_column_defaults_to_one(self, db_conn):
        """Old DB without verified column returns verified=1 for all rows."""
        results = recent_detections(db_conn, limit=10)
        assert all(r["verified"] == 1 for r in results)


class TestSpeciesStatsVerified:
    """species_stats should only count verified=1 detections."""

    def test_counts_only_verified(self, db_conn_verified):
        stats = species_stats(db_conn_verified, local_tz=ZoneInfo("UTC"))
        # 5 verified out of 7 total
        assert stats["today_count"] == 5

    def test_species_count_excludes_unverified_only_species(self, db_conn_verified):
        """Species with only unverified detections should not appear in counts."""
        # Robin and Blackbird are unverified — but they are the ONLY detections
        # for those species, so they should not count toward unique species
        stats = species_stats(db_conn_verified, local_tz=ZoneInfo("UTC"))
        assert stats["today_species"] == 5  # Blue Tit, Great Tit, Wren, Chaffinch, Goldfinch

    def test_leaderboard_excludes_unverified(self, db_conn_verified):
        stats = species_stats(db_conn_verified, local_tz=ZoneInfo("UTC"))
        leaderboard_names = {e["common_name"] for e in stats["leaderboard"]}
        assert "Robin" not in leaderboard_names  # only unverified detection
        assert "Blackbird" not in leaderboard_names
        assert "Blue Tit" in leaderboard_names  # verified


class TestSpeciesStatsBackwardCompat:
    """DB without verified column should count everything."""

    def test_all_counted_without_verified_column(self, db_conn):
        stats = species_stats(db_conn, local_tz=ZoneInfo("UTC"))
        assert stats["today_count"] == 7
        assert stats["today_species"] == 7


class TestChartQueriesVerified:
    """Chart queries should exclude unverified detections."""

    def test_timeline_excludes_unverified(self, db_conn_verified):
        results = detection_timeline(db_conn_verified, days=7, local_tz=ZoneInfo("UTC"))
        total = sum(r["count"] for r in results)
        assert total == 5  # 7 total minus 2 unverified

    def test_species_frequency_excludes_unverified(self, db_conn_verified):
        results = species_frequency(db_conn_verified, days=30, local_tz=ZoneInfo("UTC"))
        names = {r["common_name"] for r in results}
        assert "Robin" not in names
        assert "Blackbird" not in names
        assert "Blue Tit" in names

    def test_timeline_backward_compat(self, db_conn):
        """Old DB without verified column includes all rows."""
        results = detection_timeline(db_conn, days=7, local_tz=ZoneInfo("UTC"))
        total = sum(r["count"] for r in results)
        assert total == 7
