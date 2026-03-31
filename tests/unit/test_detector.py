"""Tests for biardtz.detector."""

import asyncio
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from biardtz.config import Config
from biardtz.detector import Detection, Detector


class TestDetectorInit:
    def test_raises_file_not_found_when_birdnet_missing(self, tmp_path):
        fake_path = tmp_path / "nonexistent"
        config = Config(birdnet_path=fake_path)
        with pytest.raises(FileNotFoundError, match="BirdNET-Analyzer not found"):
            Detector(config)


class TestParseCsvOutput:
    def test_parses_valid_csv(self):
        csv_text = (
            "Start (s)\tEnd (s)\tScientific name\tCommon name\tConfidence\n"
            "0.0\t3.0\tErithacus rubecula\tEuropean Robin\t0.92\n"
            "0.0\t3.0\tTurdus merula\tCommon Blackbird\t0.78\n"
        )
        result = Detector._parse_csv_output(csv_text)
        assert len(result) == 2
        assert result[0] == Detection("European Robin", "Erithacus rubecula", 0.92)
        assert result[1] == Detection("Common Blackbird", "Turdus merula", 0.78)

    def test_empty_csv(self):
        assert Detector._parse_csv_output("") == []

    def test_header_only(self):
        csv_text = "Start (s)\tEnd (s)\tScientific name\tCommon name\tConfidence\n"
        assert Detector._parse_csv_output(csv_text) == []

    def test_skips_malformed_lines(self):
        csv_text = "header\n" "only\ttwo\tfields\n" "0.0\t3.0\tParus major\tGreat Tit\t0.65\n"
        result = Detector._parse_csv_output(csv_text)
        assert len(result) == 1
        assert result[0].common_name == "Great Tit"


class TestPredictDirect:
    def test_predict_filters_by_confidence(self, tmp_path):
        birdnet_dir = tmp_path / "BirdNET-Analyzer"
        birdnet_dir.mkdir()
        config = Config(birdnet_path=birdnet_dir, confidence_threshold=0.5)

        mock_predict = MagicMock(
            return_value={
                "Erithacus rubecula_European Robin": 0.92,
                "Turdus merula_Common Blackbird": 0.3,  # below threshold
                "Parus major_Great Tit": 0.75,
            }
        )

        with patch("biardtz.detector.sys") as mock_sys:
            mock_sys.path = []
            # Prevent the real import, manually set up
            with patch.object(Detector, "_load_model"):
                detector = Detector(config)
                detector._predict_fn = mock_predict
                detector._use_subprocess = False

                chunk = np.zeros(144_000, dtype=np.float32)
                result = detector._predict_direct(chunk)

        assert len(result) == 2
        names = {d.common_name for d in result}
        assert "European Robin" in names
        assert "Great Tit" in names
        assert "Common Blackbird" not in names


class TestPredictSubprocess:
    def test_subprocess_fallback(self, tmp_path):
        birdnet_dir = tmp_path / "BirdNET-Analyzer"
        birdnet_dir.mkdir()
        (birdnet_dir / "analyze.py").touch()
        config = Config(birdnet_path=birdnet_dir, confidence_threshold=0.25)

        csv_output = (
            "Start (s)\tEnd (s)\tScientific name\tCommon name\tConfidence\n"
            "0.0\t3.0\tErithacus rubecula\tEuropean Robin\t0.92\n"
        )

        with patch.object(Detector, "_load_model"):
            detector = Detector(config)
            detector._use_subprocess = True

        with patch("biardtz.detector.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(stdout=csv_output)
            chunk = np.zeros(144_000, dtype=np.float32)
            result = detector._predict_subprocess(chunk)

        assert len(result) == 1
        assert result[0].common_name == "European Robin"
        mock_run.assert_called_once()


class TestPredictAsync:
    def test_predict_async_calls_sync(self, tmp_path):
        birdnet_dir = tmp_path / "BirdNET-Analyzer"
        birdnet_dir.mkdir()
        config = Config(birdnet_path=birdnet_dir)

        with patch.object(Detector, "_load_model"):
            detector = Detector(config)

        expected = [Detection("Robin", "Erithacus rubecula", 0.9)]
        with patch.object(detector, "_predict_sync", return_value=expected):
            chunk = np.zeros(144_000, dtype=np.float32)
            result = asyncio.run(detector.predict(chunk))

        assert result == expected
