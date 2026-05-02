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


@click.group(invoke_without_command=True)
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
@click.option("--watchlist", type=str, default=None,
              help="Comma-separated species requiring verification (e.g. 'Common Nightingale,Common Cuckoo')")
@click.option("--watchlist-file", type=click.Path(exists=True), default=None,
              help="Text file with one species name per line")
@click.option("--auto-watchlist", type=int, default=0, show_default=True,
              help="Auto-verify species with <= N total detections (0=off)")
@click.option("--verify-count", type=int, default=2, show_default=True,
              help="Detections needed within window to verify")
@click.option("--verify-window", type=float, default=300.0, show_default=True,
              help="Verification time window in seconds")
@click.option("-v", "--verbose", count=True, help="-v for info, -vv for debug")
@click.pass_context
def cli(ctx, location, threshold, db_path, device, birdnet_path, array_bearing,
        dashboard, web, web_port, watchlist, watchlist_file, auto_watchlist,
        verify_count, verify_window, verbose):
    """biardtz — real-time bird identification on Raspberry Pi."""
    # If a subcommand was invoked, skip the main pipeline
    if ctx.invoked_subcommand is not None:
        return

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
        auto_watchlist_threshold=auto_watchlist,
        verify_min_detections=verify_count,
        verify_window_seconds=verify_window,
    )
    if birdnet_path is not None:
        kwargs["birdnet_path"] = Path(birdnet_path)
    if watchlist is not None:
        kwargs["watchlist"] = tuple(s.strip() for s in watchlist.split(",") if s.strip())
    if watchlist_file is not None:
        kwargs["watchlist_file"] = Path(watchlist_file)

    config = Config(**kwargs)

    from .main import run

    try:
        asyncio.run(run(config))
    except (KeyboardInterrupt, SystemExit):
        pass


@cli.command()
def status():
    """Show pipeline health status from the heartbeat file."""
    from .health import read_heartbeat

    hb = read_heartbeat()
    if hb is None:
        click.echo("No heartbeat found — pipeline is not running or never started.")
        raise SystemExit(1)

    click.echo(click.style(f"biardtz v{__version__}", bold=True))
    status_val = hb.get("status", "unknown")
    colors = {"ok": "green", "degraded": "yellow", "stopped": "red"}
    color = colors.get(status_val, "red")
    click.echo(click.style(f"Status: {status_val}", fg=color, bold=True))
    click.echo(f"  PID:            {hb.get('pid', '?')}")
    click.echo(f"  Started:        {hb.get('started', '?')}")

    uptime = hb.get("uptime_seconds", 0)
    hours, rem = divmod(uptime, 3600)
    mins, secs = divmod(rem, 60)
    click.echo(f"  Uptime:         {int(hours)}h {int(mins)}m {int(secs)}s")

    click.echo(f"  Audio stream:   {hb.get('audio_stream', '?')}")
    click.echo(f"  Detections:     {hb.get('detections', 0)}")
    click.echo(f"  Species:        {hb.get('species', 0)}")
    click.echo(f"  Last detection: {hb.get('last_detection', 'none')}")
    click.echo(f"  Heartbeat:      {hb.get('heartbeat', '?')}")

    errors = hb.get("recent_errors", [])
    if errors:
        click.echo(click.style("  Recent errors:", fg="yellow"))
        for err in errors:
            click.echo(f"    {err}")


@cli.command()
def diagnose():
    """Diagnose connection and pipeline issues."""
    import os
    import shutil
    import subprocess
    from datetime import datetime, timezone

    from .health import read_heartbeat

    ok_mark = click.style("OK", fg="green")
    warn_mark = click.style("WARN", fg="yellow")
    fail_mark = click.style("FAIL", fg="red")

    click.echo(click.style("=== biardtz diagnostics ===", bold=True))
    click.echo()

    # 1. Check if biardtz process is running
    click.echo(click.style("Pipeline:", bold=True))
    hb = read_heartbeat()
    if hb is None:
        click.echo(f"  Process:        {fail_mark} — no heartbeat file found")
    else:
        pid = hb.get("pid")
        try:
            os.kill(pid, 0)
            click.echo(f"  Process:        {ok_mark} — PID {pid} alive")
        except (OSError, TypeError):
            click.echo(f"  Process:        {fail_mark} — PID {pid} not running")

        hb_time = hb.get("heartbeat", "")
        if hb_time:
            try:
                hb_dt = datetime.fromisoformat(hb_time)
                age = (datetime.now(timezone.utc) - hb_dt).total_seconds()
                if age < 30:
                    click.echo(f"  Heartbeat:      {ok_mark} — {int(age)}s ago")
                elif age < 120:
                    click.echo(f"  Heartbeat:      {warn_mark} — {int(age)}s ago (stale)")
                else:
                    mins = int(age // 60)
                    click.echo(f"  Heartbeat:      {fail_mark} — {mins}m ago (dead)")
            except ValueError:
                click.echo(f"  Heartbeat:      {warn_mark} — unparseable")

        status_val = hb.get("status", "unknown")
        colors = {"ok": "green", "degraded": "yellow", "stopped": "red"}
        click.echo(f"  Status:         {click.style(status_val, fg=colors.get(status_val, 'red'))}")

    # 2. Systemd service
    click.echo()
    click.echo(click.style("Systemd:", bold=True))
    try:
        r = subprocess.run(
            ["systemctl", "is-enabled", "biardtz"], capture_output=True, text=True
        )
        enabled = r.stdout.strip() == "enabled"
        click.echo(f"  Service:        {ok_mark if enabled else warn_mark} — {r.stdout.strip()}")
    except FileNotFoundError:
        click.echo(f"  Service:        {warn_mark} — systemctl not found")
        enabled = False

    if enabled:
        r = subprocess.run(
            ["systemctl", "is-active", "biardtz"], capture_output=True, text=True
        )
        active = r.stdout.strip()
        mark = ok_mark if active == "active" else fail_mark
        click.echo(f"  Active:         {mark} — {active}")
    else:
        click.echo(f"  Active:         {warn_mark} — not installed")
        click.echo(click.style(
            "  Tip: sudo bash systemd/install.sh", fg="cyan"
        ))

    # 3. Tailscale
    click.echo()
    click.echo(click.style("Tailscale:", bold=True))
    if shutil.which("tailscale"):
        r = subprocess.run(
            ["systemctl", "is-active", "tailscaled"], capture_output=True, text=True
        )
        active = r.stdout.strip() == "active"
        click.echo(f"  Daemon:         {ok_mark if active else fail_mark} — {'active' if active else 'inactive'}")

        r = subprocess.run(
            ["systemctl", "is-enabled", "tailscaled"], capture_output=True, text=True
        )
        enabled = r.stdout.strip() == "enabled"
        click.echo(f"  Auto-start:     {ok_mark if enabled else warn_mark} — {'enabled' if enabled else 'disabled'}")
    else:
        click.echo(f"  Tailscale:      {warn_mark} — not installed")

    # 4. Audio device
    click.echo()
    click.echo(click.style("Audio:", bold=True))
    try:
        r = subprocess.run(["arecord", "-l"], capture_output=True, text=True)
        if "ReSpeaker" in r.stdout:
            click.echo(f"  ReSpeaker:      {ok_mark} — detected")
        elif "card " in r.stdout:
            click.echo(f"  Audio device:   {warn_mark} — found but not ReSpeaker")
        else:
            click.echo(f"  Audio device:   {fail_mark} — no capture devices")
    except FileNotFoundError:
        click.echo(f"  arecord:        {warn_mark} — not installed")

    # 5. Recent errors from log
    click.echo()
    click.echo(click.style("Recent errors:", bold=True))
    log_path = DEFAULT_LOG_DIR / "biardtz.log"
    if log_path.exists():
        try:
            lines = log_path.read_text().splitlines()
            errors = [line for line in lines[-100:] if "ERROR" in line]
            if errors:
                for err in errors[-5:]:
                    click.echo(f"  {err}")
            else:
                click.echo(f"  {ok_mark} — no recent errors")
        except OSError:
            click.echo(f"  {warn_mark} — could not read log")
    else:
        click.echo(f"  {warn_mark} — no log file at {log_path}")

    # 6. Summary / recommendations
    click.echo()
    click.echo(click.style("Recommendations:", bold=True))
    if hb and hb.get("pid"):
        try:
            os.kill(hb["pid"], 0)
        except (OSError, TypeError):
            click.echo("  - Pipeline is dead. Restart with: biardtz -v")
            click.echo("    Or if systemd service is installed: sudo systemctl start biardtz")

    # Check if running in foreground (not systemd)
    if hb and hb.get("pid"):
        try:
            os.kill(hb["pid"], 0)
            # Check if it's a child of sshd (foreground session)
            r = subprocess.run(
                ["ps", "-o", "ppid=", "-p", str(hb["pid"])],
                capture_output=True, text=True,
            )
            ppid = r.stdout.strip()
            if ppid:
                r2 = subprocess.run(
                    ["ps", "-o", "comm=", "-p", ppid],
                    capture_output=True, text=True,
                )
                parent = r2.stdout.strip()
                if parent in ("sshd", "bash", "zsh", "sh"):
                    click.echo(
                        "  - Running in foreground SSH session — will die if SSH drops!"
                    )
                    click.echo(
                        "    Fix: install systemd service with: sudo bash systemd/install.sh"
                    )
        except (OSError, TypeError):
            pass


if __name__ == "__main__":
    cli()
