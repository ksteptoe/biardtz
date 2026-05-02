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


class TestAudioClips:
    """Tests for audio_clips table and related methods."""

    def test_audio_clips_table_created(self, config, logger):
        asyncio.run(self._run_table_exists(logger))

    @staticmethod
    async def _run_table_exists(logger):
        await logger.init_db()
        try:
            cursor = await logger._db.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='audio_clips'"
            )
            row = await cursor.fetchone()
            assert row is not None
            assert row[0] == "audio_clips"
        finally:
            await logger.close()

    def test_save_audio_clip_insert(self, config, logger):
        asyncio.run(self._run_insert(logger))

    @staticmethod
    async def _run_insert(logger):
        await logger.init_db()
        try:
            await logger.save_audio_clip("Robin", 0.85, "robin_001.wav")
            cursor = await logger._db.execute(
                "SELECT common_name, confidence, filename FROM audio_clips WHERE common_name = ?",
                ("Robin",),
            )
            row = await cursor.fetchone()
            assert row is not None
            assert row[0] == "Robin"
            assert abs(row[1] - 0.85) < 1e-6
            assert row[2] == "robin_001.wav"
        finally:
            await logger.close()

    def test_save_audio_clip_higher_confidence_replaces(self, config, logger):
        asyncio.run(self._run_higher_replaces(logger))

    @staticmethod
    async def _run_higher_replaces(logger):
        await logger.init_db()
        try:
            await logger.save_audio_clip("Robin", 0.5, "robin_low.wav")
            await logger.save_audio_clip("Robin", 0.8, "robin_high.wav")
            cursor = await logger._db.execute(
                "SELECT confidence, filename FROM audio_clips WHERE common_name = ?",
                ("Robin",),
            )
            row = await cursor.fetchone()
            assert abs(row[0] - 0.8) < 1e-6
            assert row[1] == "robin_high.wav"
        finally:
            await logger.close()

    def test_save_audio_clip_lower_confidence_keeps_original(self, config, logger):
        asyncio.run(self._run_lower_keeps(logger))

    @staticmethod
    async def _run_lower_keeps(logger):
        await logger.init_db()
        try:
            await logger.save_audio_clip("Robin", 0.8, "robin_high.wav")
            await logger.save_audio_clip("Robin", 0.5, "robin_low.wav")
            cursor = await logger._db.execute(
                "SELECT confidence, filename FROM audio_clips WHERE common_name = ?",
                ("Robin",),
            )
            row = await cursor.fetchone()
            assert abs(row[0] - 0.8) < 1e-6
            assert row[1] == "robin_high.wav"
        finally:
            await logger.close()

    def test_get_audio_confidence_none(self, config, logger):
        asyncio.run(self._run_conf_none(logger))

    @staticmethod
    async def _run_conf_none(logger):
        await logger.init_db()
        try:
            result = await logger.get_audio_confidence("Unknown Bird")
            assert result is None
        finally:
            await logger.close()

    def test_get_audio_confidence_returns_value(self, config, logger):
        asyncio.run(self._run_conf_value(logger))

    @staticmethod
    async def _run_conf_value(logger):
        await logger.init_db()
        try:
            await logger.save_audio_clip("Robin", 0.75, "robin.wav")
            result = await logger.get_audio_confidence("Robin")
            assert result is not None
            assert abs(result - 0.75) < 1e-6
        finally:
            await logger.close()


class TestLogVerified:
    """Tests for the verified parameter of DetectionLogger.log."""

    def test_log_returns_row_id(self, config, logger):
        asyncio.run(self._run(logger))

    @staticmethod
    async def _run(logger):
        await logger.init_db()
        try:
            det = Detection("Robin", "Erithacus rubecula", 0.85)
            row_id = await logger.log(det)
            assert isinstance(row_id, int)
            assert row_id >= 1
        finally:
            await logger.close()

    def test_log_verified_true_by_default(self, config, logger):
        asyncio.run(self._run_default(logger))

    @staticmethod
    async def _run_default(logger):
        await logger.init_db()
        try:
            det = Detection("Robin", "Erithacus rubecula", 0.85)
            row_id = await logger.log(det)
            cursor = await logger._db.execute(
                "SELECT verified FROM detections WHERE id = ?", (row_id,)
            )
            row = await cursor.fetchone()
            assert row[0] == 1
        finally:
            await logger.close()

    def test_log_verified_false(self, config, logger):
        asyncio.run(self._run_unverified(logger))

    @staticmethod
    async def _run_unverified(logger):
        await logger.init_db()
        try:
            det = Detection("Nightingale", "Luscinia megarhynchos", 0.7)
            row_id = await logger.log(det, verified=False)
            cursor = await logger._db.execute(
                "SELECT verified FROM detections WHERE id = ?", (row_id,)
            )
            row = await cursor.fetchone()
            assert row[0] == 0
        finally:
            await logger.close()

    def test_sequential_row_ids(self, config, logger):
        asyncio.run(self._run_sequential(logger))

    @staticmethod
    async def _run_sequential(logger):
        await logger.init_db()
        try:
            det = Detection("Robin", "Erithacus rubecula", 0.85)
            id1 = await logger.log(det)
            id2 = await logger.log(det)
            assert id2 == id1 + 1
        finally:
            await logger.close()


class TestVerifyDetections:
    """Tests for DetectionLogger.verify_detections."""

    def test_marks_rows_as_verified(self, config, logger):
        asyncio.run(self._run(logger))

    @staticmethod
    async def _run(logger):
        await logger.init_db()
        try:
            det = Detection("Nightingale", "Luscinia megarhynchos", 0.7)
            id1 = await logger.log(det, verified=False)
            id2 = await logger.log(det, verified=False)

            await logger.verify_detections([id1, id2])

            cursor = await logger._db.execute(
                "SELECT verified FROM detections WHERE id IN (?, ?)", (id1, id2)
            )
            rows = await cursor.fetchall()
            assert all(row[0] == 1 for row in rows)
        finally:
            await logger.close()

    def test_does_not_affect_other_rows(self, config, logger):
        asyncio.run(self._run_other(logger))

    @staticmethod
    async def _run_other(logger):
        await logger.init_db()
        try:
            det = Detection("Nightingale", "Luscinia megarhynchos", 0.7)
            id1 = await logger.log(det, verified=False)
            id2 = await logger.log(det, verified=False)

            # Only verify id1
            await logger.verify_detections([id1])

            cursor = await logger._db.execute(
                "SELECT verified FROM detections WHERE id = ?", (id2,)
            )
            row = await cursor.fetchone()
            assert row[0] == 0
        finally:
            await logger.close()

    def test_empty_list_is_noop(self, config, logger):
        asyncio.run(self._run_empty(logger))

    @staticmethod
    async def _run_empty(logger):
        await logger.init_db()
        try:
            # Should not raise
            await logger.verify_detections([])
        finally:
            await logger.close()


class TestRareSpecies:
    """Tests for DetectionLogger.rare_species."""

    def test_returns_species_below_threshold(self, config, logger):
        asyncio.run(self._run(logger))

    @staticmethod
    async def _run(logger):
        await logger.init_db()
        try:
            # Robin: 3 detections, Nightingale: 1 detection
            for _ in range(3):
                await logger.log(Detection("Robin", "Erithacus rubecula", 0.8))
            await logger.log(Detection("Nightingale", "Luscinia megarhynchos", 0.7))

            rare = await logger.rare_species(2)
            assert "Nightingale" in rare  # 1 <= 2
            assert "Robin" not in rare     # 3 > 2
        finally:
            await logger.close()

    def test_threshold_equals_count(self, config, logger):
        asyncio.run(self._run_equal(logger))

    @staticmethod
    async def _run_equal(logger):
        await logger.init_db()
        try:
            await logger.log(Detection("Robin", "Erithacus rubecula", 0.8))
            await logger.log(Detection("Robin", "Erithacus rubecula", 0.9))

            rare = await logger.rare_species(2)
            assert "Robin" in rare  # 2 <= 2
        finally:
            await logger.close()

    def test_no_detections_returns_empty(self, config, logger):
        asyncio.run(self._run_empty(logger))

    @staticmethod
    async def _run_empty(logger):
        await logger.init_db()
        try:
            rare = await logger.rare_species(5)
            assert rare == set()
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
