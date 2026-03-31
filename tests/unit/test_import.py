"""Unit smoke tests (fast)."""

import importlib


def test_package_importable():
    importlib.import_module("biardtz")
