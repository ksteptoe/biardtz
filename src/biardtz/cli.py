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
@click.option("--location", "-l", type=str, default="London", show_default=True,
              help="Town or city name for species filtering")
@click.option("--threshold", type=float, default=0.25, show_default=True, help="Minimum confidence (0.0–1.0)")
@click.option(
    "--db-path",
    type=click.Path(),
    default="/mnt/ssd/detections.db",
    show_default=True,
    help="SQLite database path",
)
@click.option("--device", type=int, default=None, help="Audio device index (None = system default)")
@click.option("--birdnet-path", type=click.Path(exists=True), default=None, help="Path to BirdNET-Analyzer directory")
@click.option("--array-bearing", type=float, default=0.0, show_default=True,
              help="Compass bearing (degrees) the mic array faces (0=North)")
@click.option("--dashboard/--no-dashboard", default=True, show_default=True, help="Enable Rich live dashboard")
@click.option("--web/--no-web", default=True, show_default=True, help="Enable web dashboard")
@click.option("--web-port", type=int, default=8080, show_default=True, help="Web dashboard port")
@click.option("-v", "--verbose", count=True, help="-v for info, -vv for debug")
def cli(location, threshold, db_path, device, birdnet_path, array_bearing, dashboard, web, web_port, verbose):
    """biardtz — real-time bird identification on Raspberry Pi."""
    _setup_logging(verbose)

    lat, lon = Config.latitude, Config.longitude  # London defaults
    if location and location != "London":
        from .geocode import resolve_location
        try:
            lat, lon, display = resolve_location(location)
            click.echo(f"Location: {display} ({lat:.4f}, {lon:.4f})")
        except ValueError as exc:
            raise click.BadParameter(str(exc), param_hint="'--location'") from exc

    kwargs = dict(
        latitude=lat,
        longitude=lon,
        location_name=location,
        array_bearing=array_bearing,
        confidence_threshold=threshold,
        db_path=Path(db_path),
        device_index=device,
        enable_dashboard=dashboard,
        enable_web=web,
        web_port=web_port,
    )
    if birdnet_path is not None:
        kwargs["birdnet_path"] = Path(birdnet_path)

    config = Config(**kwargs)

    from .main import run

    try:
        asyncio.run(run(config))
    except (KeyboardInterrupt, SystemExit):
        pass


if __name__ == "__main__":
    cli()
