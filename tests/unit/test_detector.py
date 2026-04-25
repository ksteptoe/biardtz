"""Tests for biardtz.detector."""

import asyncio
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from biardtz.config import Config, PipelineConfig
from biardtz.detector import Detection, Detector


class TestDetectorInit:
    def test_raises_file_not_found_when_birdnet_missing(self, tmp_path):
        fake_path = tmp_path / "nonexistent"
        config = Config(birdnet_path=fake_path)
        with pytest.raises(FileNotFoundError, match="BirdNET-Analyzer not found"):
            Detector(config)


class TestLoadModel:
    """Tests for _load_model — covers the birdnet_analyzer import path."""

    def test_load_model_success(self, tmp_path):
        birdnet_dir = tmp_path / "BirdNET-Analyzer"
        birdnet_dir.mkdir()
        config = Config(birdnet_path=birdnet_dir)

        mock_birdnet_cfg = MagicMock()
        mock_birdnet_cfg.BIRDNET_MODEL_PATH = "checkpoints/model.tflite"
        mock_birdnet_cfg.BIRDNET_LABELS_FILE = "labels.txt"
        mock_birdnet_cfg.BIRDNET_SAMPLE_RATE = 48000
        mock_birdnet_cfg.BIRDNET_SIG_LENGTH = 3.0
        mock_birdnet_cfg.LOCATION_FILTER_THRESHOLD = 0.03
        mock_birdnet_model = MagicMock()
        mock_read_lines = MagicMock(return_value=["Species1_Common1", "Species2_Common2"])
        mock_get_species = MagicMock(return_value=["Species1_Common1"])

        mock_parent = MagicMock()
        mock_parent.config = mock_birdnet_cfg
        mock_parent.model = mock_birdnet_model

        with patch.dict("sys.modules", {
            "birdnet_analyzer": mock_parent,
            "birdnet_analyzer.config": mock_birdnet_cfg,
            "birdnet_analyzer.model": mock_birdnet_model,
            "birdnet_analyzer.species": MagicMock(),
            "birdnet_analyzer.species.utils": MagicMock(get_species_list=mock_get_species),
            "birdnet_analyzer.utils": MagicMock(read_lines=mock_read_lines),
        }):
            detector = Detector(config)

        assert detector._birdnet_model is mock_birdnet_model
        assert detector._labels == ["Species1_Common1", "Species2_Common2"]
        mock_birdnet_model.load_model.assert_called_once()

    def test_load_model_import_fails_raises(self, tmp_path):
        birdnet_dir = tmp_path / "BirdNET-Analyzer"
        birdnet_dir.mkdir()
        config = Config(birdnet_path=birdnet_dir)

        import builtins

        original_import = builtins.__import__

        def fail_birdnet(name, *args, **kwargs):
            if name == "birdnet_analyzer":
                raise ImportError("no birdnet_analyzer module")
            return original_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=fail_birdnet):
            with pytest.raises(ImportError, match="Failed to import birdnet_analyzer"):
                Detector(config)


class TestPredictSync:
    def test_predict_filters_by_confidence(self, tmp_path):
        birdnet_dir = tmp_path / "BirdNET-Analyzer"
        birdnet_dir.mkdir()
        config = Config(bird=PipelineConfig(confidence_threshold=0.5), birdnet_path=birdnet_dir)

        labels = [
            "Erithacus rubecula_European Robin",
            "Turdus merula_Common Blackbird",
            "Parus major_Great Tit",
        ]
        # Prediction: batch of 1 sample, scores for each label
        predictions = np.array([[0.92, 0.3, 0.75]])

        mock_model = MagicMock()
        mock_model.predict.return_value = predictions
        mock_cfg = MagicMock()
        mock_cfg.BIRDNET_SAMPLE_RATE = 48000
        mock_cfg.SPECIES_LIST = []

        with patch.object(Detector, "_load_model"):
            detector = Detector(config)
            detector._birdnet_model = mock_model
            detector._birdnet_cfg = mock_cfg
            detector._labels = labels

            chunk = np.zeros(48_000, dtype=np.float32)
            result = detector._predict_sync(chunk)

        assert len(result) == 2
        names = {d.common_name for d in result}
        assert "European Robin" in names
        assert "Great Tit" in names
        assert "Common Blackbird" not in names

    def test_predict_filters_by_species_list(self, tmp_path):
        birdnet_dir = tmp_path / "BirdNET-Analyzer"
        birdnet_dir.mkdir()
        config = Config(birdnet_path=birdnet_dir)

        labels = [
            "Erithacus rubecula_European Robin",
            "Parus major_Great Tit",
        ]
        predictions = np.array([[0.92, 0.75]])

        mock_model = MagicMock()
        mock_model.predict.return_value = predictions
        mock_cfg = MagicMock()
        mock_cfg.BIRDNET_SAMPLE_RATE = 48000
        mock_cfg.SPECIES_LIST = ["Erithacus rubecula_European Robin"]

        with patch.object(Detector, "_load_model"):
            detector = Detector(config)
            detector._birdnet_model = mock_model
            detector._birdnet_cfg = mock_cfg
            detector._labels = labels

            chunk = np.zeros(48_000, dtype=np.float32)
            result = detector._predict_sync(chunk)

        assert len(result) == 1
        assert result[0].common_name == "European Robin"

    def test_predict_resamples_from_16khz(self, tmp_path):
        birdnet_dir = tmp_path / "BirdNET-Analyzer"
        birdnet_dir.mkdir()
        config = Config(birdnet_path=birdnet_dir)

        labels = ["Erithacus rubecula_European Robin"]
        predictions = np.array([[0.92]])

        mock_model = MagicMock()
        mock_model.predict.return_value = predictions
        mock_cfg = MagicMock()
        mock_cfg.BIRDNET_SAMPLE_RATE = 48000
        mock_cfg.SPECIES_LIST = []

        with patch.object(Detector, "_load_model"):
            detector = Detector(config)
            detector._birdnet_model = mock_model
            detector._birdnet_cfg = mock_cfg
            detector._labels = labels

            # 3 seconds at 16kHz = 48000 samples
            chunk = np.zeros(48_000, dtype=np.float32)
            detector._predict_sync(chunk)

        # Model should receive resampled audio (48kHz = 144000 samples)
        call_args = mock_model.predict.call_args[0][0]
        assert len(call_args[0]) == 144_000


class TestPredictAsync:
    def test_predict_async_calls_sync(self, tmp_path):
        birdnet_dir = tmp_path / "BirdNET-Analyzer"
        birdnet_dir.mkdir()
        config = Config(birdnet_path=birdnet_dir)

        with patch.object(Detector, "_load_model"):
            detector = Detector(config)

        expected = [Detection("Robin", "Erithacus rubecula", 0.9)]
        with patch.object(detector, "_predict_sync", return_value=expected):
            chunk = np.zeros(48_000, dtype=np.float32)
            result = asyncio.run(detector.predict(chunk))

        assert result == expected
