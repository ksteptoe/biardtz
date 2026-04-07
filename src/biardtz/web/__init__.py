"""Web dashboard for biardtz — FastAPI + HTMX + Tailwind."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from ..config import Config
from . import routes

__all__ = ["create_app", "serve_standalone"]


def _make_format_time(local_tz: ZoneInfo):
    """Create a format_time filter bound to a local timezone."""

    def format_time(iso_str: str) -> str:
        """Convert ISO timestamp to human-friendly local time."""
        try:
            dt = datetime.fromisoformat(iso_str).astimezone(local_tz)
            now = datetime.now(local_tz)
            if dt.date() == now.date():
                return dt.strftime("%H:%M")
            if dt.date() == (now - timedelta(days=1)).date():
                return f"Yesterday {dt.strftime('%H:%M')}"
            return dt.strftime("%d %b %H:%M")
        except (ValueError, TypeError):
            return str(iso_str)

    return format_time


def create_app(config: Config) -> FastAPI:
    """Create the FastAPI dashboard application."""
    app = FastAPI(title="biardtz", docs_url=None, redoc_url=None)

    template_dir = Path(__file__).parent.parent / "templates"
    templates = Jinja2Templates(directory=str(template_dir))
    templates.env.filters["format_time"] = _make_format_time(config.tz)

    static_dir = Path(__file__).parent.parent / "static"
    if static_dir.exists():
        app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    app.state.config = config
    app.state.templates = templates

    routes.register(app)

    return app


def serve_standalone() -> None:
    """Entry point for standalone web dashboard (biardtz-web)."""
    import click
    import uvicorn

    @click.command()
    @click.option("--db-path", default="/mnt/ssd/detections.db", show_default=True)
    @click.option("--port", default=8080, show_default=True)
    @click.option("--host", default="0.0.0.0", show_default=True)
    def _serve(db_path, port, host):
        """biardtz web dashboard — standalone mode."""
        config = Config(db_path=db_path, web_port=port)
        app = create_app(config)
        uvicorn.run(app, host=host, port=port)

    _serve()
