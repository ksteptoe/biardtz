"""System-test fixtures — real Detector and DetectionLogger."""
from __future__ import annotations

import asyncio

import pytest


@pytest.fixture(scope="session")
def real_detector(tmp_path_factory):
    """Session-scoped real Detector (loads TFLite model once)."""
    from biardtz.config import Config
    from biardtz.detector import Detector

    db_path = tmp_path_factory.mktemp("det") / "det.db"
    config = Config(db_path=db_path)
    try:
        return Detector(config)
    except (ImportError, OSError) as exc:
        pytest.skip(f"Cannot load BirdNET model: {exc}")


@pytest.fixture
def real_logger(live_config):
    """Per-test DetectionLogger backed by a tmp_path database."""
    from biardtz.logger import DetectionLogger

    logger = DetectionLogger(live_config)
    asyncio.get_event_loop().run_until_complete(logger.init_db())
    yield logger
    asyncio.get_event_loop().run_until_complete(logger.close())
