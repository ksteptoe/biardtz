"""Tests for biardtz.config."""

from pathlib import Path

from biardtz.config import Config


class TestConfigDefaults:
    def test_default_sample_rate(self):
        cfg = Config()
        assert cfg.sample_rate == 16_000

    def test_default_chunk_duration(self):
        cfg = Config()
        assert cfg.chunk_duration == 3.0

    def test_default_channels(self):
        cfg = Config()
        assert cfg.channels == 6

    def test_default_device_index_is_none(self):
        cfg = Config()
        assert cfg.device_index is None

    def test_default_confidence_threshold(self):
        cfg = Config()
        assert cfg.confidence_threshold == 0.25

    def test_default_latitude(self):
        cfg = Config()
        assert cfg.latitude == 51.50

    def test_default_longitude(self):
        cfg = Config()
        assert cfg.longitude == -0.12

    def test_default_week(self):
        cfg = Config()
        assert cfg.week == -1

    def test_default_num_threads(self):
        cfg = Config()
        assert cfg.num_threads == 4

    def test_default_db_path(self):
        cfg = Config()
        assert cfg.db_path == Path("/mnt/ssd/detections.db")

    def test_default_enable_dashboard(self):
        cfg = Config()
        assert cfg.enable_dashboard is True


class TestConfigChunkSamples:
    def test_default_chunk_samples(self):
        cfg = Config()
        assert cfg.chunk_samples == 48_000

    def test_custom_chunk_samples(self):
        cfg = Config(sample_rate=44_100, chunk_duration=5.0)
        assert cfg.chunk_samples == int(44_100 * 5.0)

    def test_chunk_samples_is_int(self):
        cfg = Config(sample_rate=22_050, chunk_duration=1.5)
        assert isinstance(cfg.chunk_samples, int)


class TestConfigBirdnetPath:
    def test_default_birdnet_path_is_sibling_of_repo_root(self):
        cfg = Config()
        # Should be parents[3] of config.py / "BirdNET-Analyzer"
        # Just verify it ends with BirdNET-Analyzer and is a Path
        assert cfg.birdnet_path.name == "BirdNET-Analyzer"
        assert isinstance(cfg.birdnet_path, Path)

    def test_custom_birdnet_path(self, tmp_path):
        custom = tmp_path / "my_birdnet"
        cfg = Config(birdnet_path=custom)
        assert cfg.birdnet_path == custom

    def test_birdnet_path_string_coerced_to_path(self):
        cfg = Config(birdnet_path="/some/path")
        assert isinstance(cfg.birdnet_path, Path)
        assert cfg.birdnet_path == Path("/some/path")


class TestConfigCustomValues:
    def test_custom_constructor(self, tmp_path):
        db = tmp_path / "test.db"
        cfg = Config(
            sample_rate=22_050,
            chunk_duration=5.0,
            channels=2,
            device_index=3,
            confidence_threshold=0.5,
            latitude=40.0,
            longitude=-74.0,
            week=22,
            num_threads=2,
            db_path=db,
            enable_dashboard=False,
        )
        assert cfg.sample_rate == 22_050
        assert cfg.chunk_duration == 5.0
        assert cfg.channels == 2
        assert cfg.device_index == 3
        assert cfg.confidence_threshold == 0.5
        assert cfg.latitude == 40.0
        assert cfg.longitude == -74.0
        assert cfg.week == 22
        assert cfg.num_threads == 2
        assert cfg.db_path == db
        assert cfg.enable_dashboard is False

    def test_db_path_string_coerced_to_path(self):
        cfg = Config(db_path="/tmp/test.db")
        assert isinstance(cfg.db_path, Path)
        assert cfg.db_path == Path("/tmp/test.db")
