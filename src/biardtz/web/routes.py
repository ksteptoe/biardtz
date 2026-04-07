"""Web dashboard routes."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Query, Request
from fastapi.responses import FileResponse, HTMLResponse

from . import db, image_cache


def register(app: FastAPI) -> None:
    """Register all routes on the FastAPI app."""

    @app.get("/", response_class=HTMLResponse)
    async def index(request: Request):
        config = request.app.state.config
        conn = db.get_connection(config.db_path)
        try:
            detections = db.recent_detections(conn, limit=20)
            stats = db.species_stats(conn)
        finally:
            conn.close()
        return request.app.state.templates.TemplateResponse(
            request,
            "index.html",
            {"detections": detections, "stats": stats, "config": config},
        )

    @app.get("/partials/detections", response_class=HTMLResponse)
    async def partial_detections(
        request: Request, limit: int = Query(20),
    ):
        config = request.app.state.config
        conn = db.get_connection(config.db_path)
        try:
            detections = db.recent_detections(conn, limit=limit)
        finally:
            conn.close()
        return request.app.state.templates.TemplateResponse(
            request,
            "_detections.html",
            {"detections": detections},
        )

    @app.get("/partials/stats", response_class=HTMLResponse)
    async def partial_stats(request: Request):
        config = request.app.state.config
        conn = db.get_connection(config.db_path)
        try:
            stats = db.species_stats(conn)
        finally:
            conn.close()
        return request.app.state.templates.TemplateResponse(
            request,
            "_stats.html",
            {"stats": stats},
        )

    @app.get("/api/detections")
    async def api_detections(
        request: Request, limit: int = Query(20),
    ):
        config = request.app.state.config
        conn = db.get_connection(config.db_path)
        try:
            return db.recent_detections(conn, limit=limit)
        finally:
            conn.close()

    @app.get("/api/image/{sci_name:path}")
    async def bird_image(request: Request, sci_name: str):
        config = request.app.state.config
        config.bird_image_cache.mkdir(parents=True, exist_ok=True)
        path = await image_cache.get_image_path(
            sci_name, config.bird_image_cache,
        )
        if path and path.exists():
            return FileResponse(path, media_type="image/jpeg")
        fallback = Path(__file__).parent.parent / "static" / "fallback-bird.svg"
        if fallback.exists():
            return FileResponse(fallback, media_type="image/svg+xml")
        return HTMLResponse("", status_code=404)
