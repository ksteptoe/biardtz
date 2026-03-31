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


def test_api_all():
    assert set(api.__all__) == {"Config", "Detection", "Detector", "DetectionLogger"}
