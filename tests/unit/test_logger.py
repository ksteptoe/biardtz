"""Tests for biardtz.logger using real aiosqlite."""

import asyncio

import pytest

from biardtz.config import Config
from biardtz.detector import Detection
from biardtz.logger import DetectionLogger


@pytest.fixture
def config(tmp_path):
    return Config(db_path=tmp_path / "test.db")


@pytest.fixture
def logger(config):
    return DetectionLogger(config)


class TestInitDb:
    def test_creates_database_file(self, config, logger):
        asyncio.run(self._run(config, logger))

    @staticmethod
    async def _run(config, logger):
        await logger.init_db()
        try:
            assert config.db_path.exists()
        finally:
            await logger.close()

    def test_creates_detections_table(self, config, logger):
        asyncio.run(self._run_check_table(logger))

    @staticmethod
    async def _run_check_table(logger):
        await logger.init_db()
        try:
            cursor = await logger._db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='detections'")
            row = await cursor.fetchone()
            assert row is not None
            assert row[0] == "detections"
        finally:
            await logger.close()

    def test_sets_pragmas(self, config, logger):
        asyncio.run(self._run_pragmas(logger))

    @staticmethod
    async def _run_pragmas(logger):
        await logger.init_db()
        try:
            cursor = await logger._db.execute("PRAGMA busy_timeout")
            row = await cursor.fetchone()
            assert row[0] == 5000

            cursor = await logger._db.execute("PRAGMA synchronous")
            row = await cursor.fetchone()
            assert row[0] == 1  # NORMAL = 1
        finally:
            await logger.close()

    def test_creates_parent_directories(self, tmp_path):
        db_path = tmp_path / "sub" / "dir" / "test.db"
        config = Config(db_path=db_path)
        logger = DetectionLogger(config)
        asyncio.run(self._run_parents(config, logger))

    @staticmethod
    async def _run_parents(config, logger):
        await logger.init_db()
        try:
            assert config.db_path.exists()
        finally:
            await logger.close()


class TestLog:
    def test_inserts_row_with_correct_fields(self, config, logger):
        asyncio.run(self._run(config, logger))

    @staticmethod
    async def _run(config, logger):
        await logger.init_db()
        try:
            det = Detection(common_name="Robin", sci_name="Erithacus rubecula", confidence=0.85)
            await logger.log(det)

            cursor = await logger._db.execute(
                "SELECT common_name, sci_name, confidence, latitude, longitude" " FROM detections"
            )
            row = await cursor.fetchone()
            assert row is not None
            assert row[0] == "Robin"
            assert row[1] == "Erithacus rubecula"
            assert abs(row[2] - 0.85) < 1e-6
            assert abs(row[3] - config.latitude) < 1e-6
            assert abs(row[4] - config.longitude) < 1e-6
        finally:
            await logger.close()

    def test_increments_count(self, config, logger):
        asyncio.run(self._run_count(logger))

    @staticmethod
    async def _run_count(logger):
        await logger.init_db()
        try:
            det = Detection(common_name="Robin", sci_name="Erithacus rubecula", confidence=0.85)
            assert logger._count == 0
            await logger.log(det)
            assert logger._count == 1
            await logger.log(det)
            assert logger._count == 2
        finally:
            await logger.close()


class TestSessionSummary:
    def test_returns_meaningful_string(self, config, logger):
        asyncio.run(self._run(logger))

    @staticmethod
    async def _run(logger):
        await logger.init_db()
        try:
            det = Detection(common_name="Robin", sci_name="Erithacus rubecula", confidence=0.85)
            await logger.log(det)
            summary = await logger.session_summary()
            assert "Detections: 1" in summary
            assert "Unique species: 1" in summary
            assert "Session:" in summary
        finally:
            await logger.close()

    def test_counts_unique_species(self, config, logger):
        asyncio.run(self._run_unique(logger))

    @staticmethod
    async def _run_unique(logger):
        await logger.init_db()
        try:
            await logger.log(Detection("Robin", "Erithacus rubecula", 0.8))
            await logger.log(Detection("Blackbird", "Turdus merula", 0.7))
            await logger.log(Detection("Robin", "Erithacus rubecula", 0.9))
            summary = await logger.session_summary()
            assert "Detections: 3" in summary
            assert "Unique species: 2" in summary
        finally:
            await logger.close()


class TestClose:
    def test_close_works_cleanly(self, config, logger):
        asyncio.run(self._run(logger))

    @staticmethod
    async def _run(logger):
        await logger.init_db()
        await logger.close()
        assert logger._db is None

    def test_close_without_init(self, config, logger):
        asyncio.run(self._run_no_init(logger))

    @staticmethod
    async def _run_no_init(logger):
        # Should not raise
        await logger.close()
        assert logger._db is None
