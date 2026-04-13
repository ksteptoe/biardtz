"""CLI entry point for biardtz.

Install with ``pip install -e .`` then run ``biardtz`` or ``python -m biardtz``.
"""

from __future__ import annotations

import asyncio
import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

import click

from biardtz import __version__

from .config import Config

__author__ = "Kevin Steptoe"
__copyright__ = "Kevin Steptoe"
__license__ = "MIT"

DEFAULT_LOG_DIR = Path("/mnt/ssd/biardtz/logs")


def _setup_logging(verbosity: int, log_dir: Path = DEFAULT_LOG_DIR) -> None:
    level = {0: logging.WARNING, 1: logging.INFO}.get(verbosity, logging.DEBUG)

    fmt = "[%(asctime)s] %(levelname)s:%(name)s: %(message)s"
    datefmt = "%Y-%m-%d %H:%M:%S"

    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stdout)]

    # Always log to file at INFO level (even if console is WARNING)
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        file_handler = RotatingFileHandler(
            log_dir / "biardtz.log",
            maxBytes=5 * 1024 * 1024,  # 5 MB per file
            backupCount=5,
        )
        file_handler.setLevel(logging.INFO)
        file_handler.setFormatter(logging.Formatter(fmt, datefmt=datefmt))
        handlers.append(file_handler)
    except OSError as exc:
        print(f"Warning: could not set up file logging at {log_dir}: {exc}", file=sys.stderr)

    logging.basicConfig(
        level=min(level, logging.INFO),
        handlers=handlers,
        format=fmt,
        datefmt=datefmt,
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

    lat, lon, tz_name = Config.latitude, Config.longitude, Config.tz_name
    if location and location != "London":
        from .geocode import resolve_location
        try:
            lat, lon, display, tz_name = resolve_location(location)
            click.echo(f"Location: {display} ({lat:.4f}, {lon:.4f}, {tz_name})")
        except ValueError as exc:
            raise click.BadParameter(str(exc), param_hint="'--location'") from exc

    kwargs = dict(
        latitude=lat,
        longitude=lon,
        location_name=location,
        tz_name=tz_name,
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
