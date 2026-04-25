"""Tests for biardtz.api — public API re-exports."""

from biardtz import api


def test_api_exports_config():
    assert hasattr(api, "Config")
    from biardtz.config import Config

    assert api.Config is Config


def test_api_exports_detection():
    assert hasattr(api, "Detection")
    from biardtz.detector import Detection

    assert api.Detection is Detection


def test_api_exports_detector():
    assert hasattr(api, "Detector")
    from biardtz.detector import Detector

    assert api.Detector is Detector


def test_api_exports_detection_logger():
    assert hasattr(api, "DetectionLogger")
    from biardtz.logger import DetectionLogger

    assert api.DetectionLogger is DetectionLogger


def test_api_exports_audio_config():
    assert hasattr(api, "AudioConfig")
    from biardtz.config import AudioConfig

    assert api.AudioConfig is AudioConfig


def test_api_exports_pipeline_config():
    assert hasattr(api, "PipelineConfig")
    from biardtz.config import PipelineConfig

    assert api.PipelineConfig is PipelineConfig


def test_api_exports_detector_protocol():
    assert hasattr(api, "DetectorProtocol")
    from biardtz.protocols import DetectorProtocol

    assert api.DetectorProtocol is DetectorProtocol


def test_api_all():
    assert set(api.__all__) == {
        "AudioConfig", "Config", "PipelineConfig",
        "Detection", "Detector", "DetectorProtocol", "DetectionLogger",
    }
