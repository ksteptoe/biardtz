"""Tests for biardtz.web.db — wildcard/glob search support."""

from __future__ import annotations

import sqlite3

import pytest

from biardtz.web.db import _GLOB_CHARS, recent_detections, species_list

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

_SAMPLE_ROWS = [
    ("2026-04-20T08:00:00", "Blue Tit", "Cyanistes caeruleus", 0.85, None, None),
    ("2026-04-20T08:05:00", "Great Tit", "Parus major", 0.90, None, None),
    ("2026-04-20T08:10:00", "Robin", "Erithacus rubecula", 0.75, None, None),
    ("2026-04-20T08:15:00", "Wren", "Troglodytes troglodytes", 0.80, None, None),
    ("2026-04-20T08:20:00", "Blackbird", "Turdus merula", 0.88, None, None),
    ("2026-04-20T08:25:00", "Chaffinch", "Fringilla coelebs", 0.70, None, None),
    ("2026-04-20T08:30:00", "Goldfinch", "Carduelis carduelis", 0.82, None, None),
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
        _SAMPLE_ROWS,
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

    def test_glob_is_case_sensitive(self, db_conn):
        """GLOB is case-sensitive, so 'blue*' should NOT match 'Blue Tit'."""
        results = recent_detections(db_conn, search="blue*")
        assert results == []


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
        assert len(results) == len(_SAMPLE_ROWS)

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
