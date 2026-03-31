"""CLI entry point for biardtz.

Install with ``pip install -e .`` then run ``biardtz`` or ``python -m biardtz``.
"""

from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path

import click

from biardtz import __version__
from .config import Config

__author__ = "Kevin Steptoe"
__copyright__ = "Kevin Steptoe"
__license__ = "MIT"


def _setup_logging(verbosity: int) -> None:
    level = {0: logging.WARNING, 1: logging.INFO}.get(verbosity, logging.DEBUG)
    logging.basicConfig(
        level=level,
        stream=sys.stdout,
        format="[%(asctime)s] %(levelname)s:%(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


@click.command()
@click.version_option(__version__, "--version")
@click.option("--lat", type=float, default=51.50, show_default=True, help="Latitude for species filtering")
@click.option("--lon", type=float, default=-0.12, show_default=True, help="Longitude for species filtering")
@click.option("--threshold", type=float, default=0.25, show_default=True, help="Minimum confidence (0.0–1.0)")
@click.option("--db-path", type=click.Path(), default="/mnt/ssd/detections.db", show_default=True, help="SQLite database path")
@click.option("--device", type=int, default=None, help="Audio device index (None = system default)")
@click.option("--birdnet-path", type=click.Path(exists=True), default=None, help="Path to BirdNET-Analyzer directory")
@click.option("--dashboard/--no-dashboard", default=True, show_default=True, help="Enable Rich live dashboard")
@click.option("-v", "--verbose", count=True, help="-v for info, -vv for debug")
def cli(lat, lon, threshold, db_path, device, birdnet_path, dashboard, verbose):
    """biardtz — real-time bird identification on Raspberry Pi."""
    _setup_logging(verbose)

    kwargs = dict(
        latitude=lat,
        longitude=lon,
        confidence_threshold=threshold,
        db_path=Path(db_path),
        device_index=device,
        enable_dashboard=dashboard,
    )
    if birdnet_path is not None:
        kwargs["birdnet_path"] = Path(birdnet_path)

    config = Config(**kwargs)

    from .main import run

    asyncio.run(run(config))


if __name__ == "__main__":
    cli()
