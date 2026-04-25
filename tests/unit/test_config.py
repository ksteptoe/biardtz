"""Tests for biardtz.config."""

from pathlib import Path

from biardtz.config import AudioConfig, Config, PipelineConfig


class TestAudioConfig:
    def test_defaults(self):
        ac = AudioConfig()
        assert ac.sample_rate == 16_000
        assert ac.channels == 6
        assert ac.device_index is None
        assert ac.chunk_duration == 3.0

    def test_chunk_samples(self):
        ac = AudioConfig(sample_rate=44_100, chunk_duration=5.0)
        assert ac.chunk_samples == int(44_100 * 5.0)

    def test_chunk_samples_is_int(self):
        ac = AudioConfig(sample_rate=22_050, chunk_duration=1.5)
        assert isinstance(ac.chunk_samples, int)


class TestPipelineConfig:
    def test_defaults(self):
        pc = PipelineConfig()
        assert pc.enabled is True
        assert pc.confidence_threshold == 0.25
        assert pc.model_path is None

    def test_model_path_coerced(self):
        pc = PipelineConfig(model_path="/some/model")
        assert isinstance(pc.model_path, Path)

    def test_audio_is_audio_config(self):
        pc = PipelineConfig()
        assert isinstance(pc.audio, AudioConfig)


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
        bird = PipelineConfig(
            audio=AudioConfig(sample_rate=44_100, chunk_duration=5.0),
        )
        cfg = Config(bird=bird)
        assert cfg.chunk_samples == int(44_100 * 5.0)

    def test_chunk_samples_is_int(self):
        bird = PipelineConfig(
            audio=AudioConfig(sample_rate=22_050, chunk_duration=1.5),
        )
        cfg = Config(bird=bird)
        assert isinstance(cfg.chunk_samples, int)


class TestConfigBirdnetPath:
    def test_default_birdnet_path_is_sibling_of_repo_root(self):
        cfg = Config()
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
        bird = PipelineConfig(
            audio=AudioConfig(sample_rate=22_050, channels=2, device_index=3, chunk_duration=5.0),
            confidence_threshold=0.5,
        )
        cfg = Config(
            bird=bird,
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

    def test_location_name_default_is_london(self):
        cfg = Config()
        assert cfg.location_name == "London"

    def test_location_name_stored(self):
        cfg = Config(location_name="Biarritz, France", latitude=43.48, longitude=-1.56)
        assert cfg.location_name == "Biarritz, France"
        assert cfg.latitude == 43.48

    def test_db_path_string_coerced_to_path(self):
        cfg = Config(db_path="/tmp/test.db")
        assert isinstance(cfg.db_path, Path)
        assert cfg.db_path == Path("/tmp/test.db")


class TestConfigBatPipeline:
    def test_bat_disabled_by_default(self):
        cfg = Config()
        assert cfg.bat.enabled is False

    def test_bat_default_sample_rate(self):
        cfg = Config()
        assert cfg.bat.audio.sample_rate == 256_000

    def test_bat_default_channels(self):
        cfg = Config()
        assert cfg.bat.audio.channels == 1

    def test_bat_default_chunk_duration(self):
        cfg = Config()
        assert cfg.bat.audio.chunk_duration == 0.5

    def test_bird_enabled_by_default(self):
        cfg = Config()
        assert cfg.bird.enabled is True

    def test_backward_compat_properties_delegate_to_bird(self):
        bird = PipelineConfig(
            audio=AudioConfig(sample_rate=48_000, channels=2, device_index=5, chunk_duration=2.0),
            confidence_threshold=0.8,
        )
        cfg = Config(bird=bird)
        assert cfg.sample_rate == 48_000
        assert cfg.channels == 2
        assert cfg.device_index == 5
        assert cfg.chunk_duration == 2.0
        assert cfg.confidence_threshold == 0.8
