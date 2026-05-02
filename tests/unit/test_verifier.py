"""Tests for biardtz.verifier — multi-chunk verification for rare/watchlist species."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from biardtz.config import Config
from biardtz.detector import Detection
from biardtz.verifier import Verifier


@pytest.fixture
def det_logger():
    lg = MagicMock()
    lg.verify_detections = AsyncMock()
    lg.rare_species = AsyncMock(return_value=set())
    return lg


def _make_config(**overrides):
    defaults = dict(
        watchlist=("Nightingale",),
        verify_min_detections=2,
        verify_window_seconds=60.0,
        auto_watchlist_threshold=0,
    )
    defaults.update(overrides)
    return Config(**defaults)


class TestNeedsVerification:
    """Tests for Verifier.needs_verification."""

    def test_returns_false_for_non_watchlist_species(self, det_logger):
        cfg = _make_config()
        v = Verifier(cfg, det_logger)
        assert v.needs_verification("Robin") is False

    def test_returns_true_for_explicit_watchlist_species(self, det_logger):
        cfg = _make_config(watchlist=("Nightingale", "Golden Eagle"))
        v = Verifier(cfg, det_logger)
        assert v.needs_verification("Nightingale") is True
        assert v.needs_verification("Golden Eagle") is True

    def test_returns_true_for_auto_watchlist_species(self, det_logger):
        cfg = _make_config(watchlist=())
        v = Verifier(cfg, det_logger)
        # Manually add to auto-watchlist (simulating refresh_auto_watchlist)
        v._auto_watchlist.add("Rare Warbler")
        assert v.needs_verification("Rare Warbler") is True

    def test_returns_false_when_watchlist_empty(self, det_logger):
        cfg = _make_config(watchlist=())
        v = Verifier(cfg, det_logger)
        assert v.needs_verification("Robin") is False


class TestSubmit:
    """Tests for Verifier.submit."""

    def test_returns_true_for_non_watchlist_species(self, det_logger):
        cfg = _make_config()
        v = Verifier(cfg, det_logger)
        det = Detection("Robin", "Erithacus rubecula", 0.9)

        result = asyncio.run(v.submit(det, row_id=1))
        assert result is True
        det_logger.verify_detections.assert_not_called()

    def test_returns_false_on_first_detection_of_watchlist_species(self, det_logger):
        cfg = _make_config(verify_min_detections=2)
        v = Verifier(cfg, det_logger)
        det = Detection("Nightingale", "Luscinia megarhynchos", 0.8)

        result = asyncio.run(v.submit(det, row_id=1))
        assert result is False
        det_logger.verify_detections.assert_not_called()

    def test_returns_true_once_threshold_reached(self, det_logger):
        cfg = _make_config(verify_min_detections=2)
        v = Verifier(cfg, det_logger)
        det = Detection("Nightingale", "Luscinia megarhynchos", 0.8)

        async def run():
            r1 = await v.submit(det, row_id=10)
            r2 = await v.submit(det, row_id=11)
            return r1, r2

        r1, r2 = asyncio.run(run())
        assert r1 is False
        assert r2 is True

    def test_calls_verify_detections_with_all_pending_row_ids(self, det_logger):
        cfg = _make_config(verify_min_detections=3)
        v = Verifier(cfg, det_logger)
        det = Detection("Nightingale", "Luscinia megarhynchos", 0.8)

        async def run():
            await v.submit(det, row_id=10)
            await v.submit(det, row_id=20)
            await v.submit(det, row_id=30)

        asyncio.run(run())
        det_logger.verify_detections.assert_called_once_with([10, 20, 30])

    def test_clears_pending_after_verification(self, det_logger):
        cfg = _make_config(verify_min_detections=2)
        v = Verifier(cfg, det_logger)
        det = Detection("Nightingale", "Luscinia megarhynchos", 0.8)

        async def run():
            await v.submit(det, row_id=1)
            await v.submit(det, row_id=2)
            # Pending should be cleared after verification
            assert "Nightingale" not in v._pending

        asyncio.run(run())

    def test_expired_entries_pruned_on_submit(self, det_logger):
        """Entries older than verify_window_seconds are pruned during submit."""
        cfg = _make_config(verify_min_detections=2, verify_window_seconds=10.0)
        v = Verifier(cfg, det_logger)
        det = Detection("Nightingale", "Luscinia megarhynchos", 0.8)

        from unittest.mock import patch

        # First call at time 100
        with patch("biardtz.verifier.time") as mock_time:
            mock_time.monotonic.return_value = 100.0

            async def first():
                return await v.submit(det, row_id=1)

            r1 = asyncio.run(first())
            assert r1 is False

        # Second call at time 200 — well past the 10s window
        with patch("biardtz.verifier.time") as mock_time:
            mock_time.monotonic.return_value = 200.0

            async def second():
                return await v.submit(det, row_id=2)

            r2 = asyncio.run(second())
            # First entry expired, so only 1 entry remains — still below threshold
            assert r2 is False
            det_logger.verify_detections.assert_not_called()

    def test_expired_entries_dont_count_toward_threshold(self, det_logger):
        """Only non-expired entries count toward verify_min_detections."""
        cfg = _make_config(verify_min_detections=2, verify_window_seconds=10.0)
        v = Verifier(cfg, det_logger)
        det = Detection("Nightingale", "Luscinia megarhynchos", 0.8)

        from unittest.mock import patch

        with patch("biardtz.verifier.time") as mock_time:
            # Submit first at t=0, second at t=100 (expired), third at t=100
            mock_time.monotonic.return_value = 0.0

            async def run():
                await v.submit(det, row_id=1)  # t=0

                mock_time.monotonic.return_value = 100.0
                r2 = await v.submit(det, row_id=2)  # t=100, entry #1 expired
                # Only entry #2 is valid, so still pending
                assert r2 is False

                r3 = await v.submit(det, row_id=3)  # t=100, entries #2 and #3 valid
                assert r3 is True

            asyncio.run(run())
            # verify_detections called with only the non-expired entries
            det_logger.verify_detections.assert_called_once_with([2, 3])


class TestExpirePending:
    """Tests for Verifier.expire_pending."""

    def test_removes_stale_species(self, det_logger):
        cfg = _make_config(verify_min_detections=3, verify_window_seconds=10.0)
        v = Verifier(cfg, det_logger)
        det = Detection("Nightingale", "Luscinia megarhynchos", 0.8)

        from unittest.mock import patch

        with patch("biardtz.verifier.time") as mock_time:
            mock_time.monotonic.return_value = 0.0

            async def run():
                await v.submit(det, row_id=1)  # t=0
                assert "Nightingale" in v._pending

                # Advance past window
                mock_time.monotonic.return_value = 100.0
                expired = await v.expire_pending()
                assert "Nightingale" in expired
                assert "Nightingale" not in v._pending

            asyncio.run(run())

    def test_returns_empty_when_nothing_expired(self, det_logger):
        cfg = _make_config(verify_min_detections=3, verify_window_seconds=60.0)
        v = Verifier(cfg, det_logger)
        det = Detection("Nightingale", "Luscinia megarhynchos", 0.8)

        from unittest.mock import patch

        with patch("biardtz.verifier.time") as mock_time:
            mock_time.monotonic.return_value = 100.0

            async def run():
                await v.submit(det, row_id=1)
                mock_time.monotonic.return_value = 105.0  # only 5s later
                expired = await v.expire_pending()
                assert expired == []
                assert "Nightingale" in v._pending

            asyncio.run(run())

    def test_returns_empty_when_no_pending(self, det_logger):
        cfg = _make_config()
        v = Verifier(cfg, det_logger)

        expired = asyncio.run(v.expire_pending())
        assert expired == []


class TestRefreshAutoWatchlist:
    """Tests for Verifier.refresh_auto_watchlist."""

    def test_queries_rare_species_and_updates_set(self, det_logger):
        cfg = _make_config(auto_watchlist_threshold=5)
        v = Verifier(cfg, det_logger)
        det_logger.rare_species = AsyncMock(return_value={"Rare Warbler", "Rare Bunting"})

        asyncio.run(v.refresh_auto_watchlist())
        det_logger.rare_species.assert_called_once_with(5)
        assert v._auto_watchlist == {"Rare Warbler", "Rare Bunting"}
        # Verify these are now on the watchlist
        assert v.needs_verification("Rare Warbler") is True
        assert v.needs_verification("Rare Bunting") is True

    def test_threshold_zero_clears_auto_watchlist(self, det_logger):
        cfg = _make_config(auto_watchlist_threshold=0)
        v = Verifier(cfg, det_logger)
        # Pre-populate
        v._auto_watchlist = {"Some Bird"}

        asyncio.run(v.refresh_auto_watchlist())
        assert v._auto_watchlist == set()
        det_logger.rare_species.assert_not_called()

    def test_replaces_previous_auto_watchlist(self, det_logger):
        cfg = _make_config(auto_watchlist_threshold=3)
        v = Verifier(cfg, det_logger)

        det_logger.rare_species = AsyncMock(return_value={"Bird A"})
        asyncio.run(v.refresh_auto_watchlist())
        assert v._auto_watchlist == {"Bird A"}

        det_logger.rare_species = AsyncMock(return_value={"Bird B"})
        asyncio.run(v.refresh_auto_watchlist())
        assert v._auto_watchlist == {"Bird B"}
        assert "Bird A" not in v._auto_watchlist
