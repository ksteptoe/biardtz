"""Web dashboard routes."""

from __future__ import annotations

import time
from pathlib import Path

from fastapi import FastAPI, Query, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse

from . import db, image_cache

# Simple TTL cache for chart data (avoids repeated expensive queries)
_cache: dict[str, tuple[float, list]] = {}
_CACHE_TTL = 60  # seconds


def _cached(key: str, ttl: int = _CACHE_TTL):
    """Return cached value if still valid, else None."""
    entry = _cache.get(key)
    if entry and (time.monotonic() - entry[0]) < ttl:
        return entry[1]
    return None


def _set_cache(key: str, value: list) -> list:
    _cache[key] = (time.monotonic(), value)
    return value


def register(app: FastAPI) -> None:
    """Register all routes on the FastAPI app."""

    @app.get("/", response_class=HTMLResponse)
    async def index(request: Request):
        config = request.app.state.config
        conn = db.get_connection(config.db_path)
        try:
            detections = db.recent_detections(conn, limit=20)
            stats = db.species_stats(conn, config.tz)
        finally:
            conn.close()
        filters = {"search": None, "min_confidence": None, "date_from": None, "date_to": None}
        return request.app.state.templates.TemplateResponse(
            request,
            "index.html",
            {
                "detections": detections,
                "stats": stats,
                "config": config,
                "filters": filters,
                "limit": 20,
                "offset": 0,
            },
        )

    @app.get("/partials/detections", response_class=HTMLResponse)
    async def partial_detections(
        request: Request,
        limit: int = Query(20),
        offset: int = Query(0),
        species: str = Query(None),
        min_confidence: float = Query(None),
        date_from: str = Query(None),
        date_to: str = Query(None),
        search: str = Query(None),
    ):
        # Slider sends 0-100, db expects 0.0-1.0
        db_confidence = min_confidence / 100.0 if min_confidence else None
        config = request.app.state.config
        conn = db.get_connection(config.db_path)
        try:
            detections = db.recent_detections(
                conn,
                limit=limit,
                offset=offset,
                species=species,
                min_confidence=db_confidence,
                date_from=date_from,
                date_to=date_to,
                search=search,
            )
        finally:
            conn.close()
        return request.app.state.templates.TemplateResponse(
            request,
            "_detections.html",
            {"detections": detections, "limit": limit, "offset": offset},
        )

    @app.get("/partials/stats", response_class=HTMLResponse)
    async def partial_stats(request: Request):
        config = request.app.state.config
        conn = db.get_connection(config.db_path)
        try:
            stats = db.species_stats(conn, config.tz)
        finally:
            conn.close()
        return request.app.state.templates.TemplateResponse(
            request,
            "_stats.html",
            {"stats": stats},
        )

    @app.get("/partials/tab/live", response_class=HTMLResponse)
    async def partial_tab_live(request: Request):
        config = request.app.state.config
        conn = db.get_connection(config.db_path)
        try:
            detections = db.recent_detections(conn, limit=20)
        finally:
            conn.close()
        filters = {"search": None, "min_confidence": None, "date_from": None, "date_to": None}
        return request.app.state.templates.TemplateResponse(
            request,
            "_tab_live.html",
            {"detections": detections, "filters": filters, "limit": 20, "offset": 0},
        )

    @app.get("/partials/tab/charts", response_class=HTMLResponse)
    async def partial_tab_charts(request: Request):
        return request.app.state.templates.TemplateResponse(
            request,
            "_tab_charts.html",
            {},
        )

    @app.get("/partials/tab/species", response_class=HTMLResponse)
    async def partial_tab_species(request: Request):
        config = request.app.state.config
        conn = db.get_connection(config.db_path)
        try:
            stats = db.species_stats(conn, config.tz)
        finally:
            conn.close()
        return request.app.state.templates.TemplateResponse(
            request,
            "_tab_species.html",
            {"stats": stats},
        )

    @app.get("/api/detections")
    async def api_detections(
        request: Request,
        limit: int = Query(20),
        offset: int = Query(0),
        species: str = Query(None),
        min_confidence: float = Query(None),
        date_from: str = Query(None),
        date_to: str = Query(None),
        search: str = Query(None),
    ):
        config = request.app.state.config
        conn = db.get_connection(config.db_path)
        try:
            return db.recent_detections(
                conn,
                limit=limit,
                offset=offset,
                species=species,
                min_confidence=min_confidence,
                date_from=date_from,
                date_to=date_to,
                search=search,
            )
        finally:
            conn.close()

    def _chart_response(data: list) -> JSONResponse:
        return JSONResponse(data, headers={"Cache-Control": "max-age=60"})

    @app.get("/api/charts/timeline")
    async def api_chart_timeline(
        request: Request, days: int = Query(7),
    ):
        key = f"timeline:{days}"
        cached = _cached(key)
        if cached is not None:
            return _chart_response(cached)
        config = request.app.state.config
        conn = db.get_connection(config.db_path)
        try:
            data = _set_cache(key, db.detection_timeline(conn, days=days, local_tz=config.tz))
        finally:
            conn.close()
        return _chart_response(data)

    @app.get("/api/charts/species")
    async def api_chart_species(
        request: Request,
        days: int = Query(30),
        limit: int = Query(15),
    ):
        key = f"species:{days}:{limit}"
        cached = _cached(key)
        if cached is not None:
            return _chart_response(cached)
        config = request.app.state.config
        conn = db.get_connection(config.db_path)
        try:
            data = _set_cache(key, db.species_frequency(conn, days=days, limit=limit, local_tz=config.tz))
        finally:
            conn.close()
        return _chart_response(data)

    @app.get("/api/charts/heatmap")
    async def api_chart_heatmap(
        request: Request, days: int = Query(30),
    ):
        key = f"heatmap:{days}"
        cached = _cached(key)
        if cached is not None:
            return _chart_response(cached)
        config = request.app.state.config
        conn = db.get_connection(config.db_path)
        try:
            data = _set_cache(key, db.activity_heatmap(conn, days=days, local_tz=config.tz))
        finally:
            conn.close()
        return _chart_response(data)

    @app.get("/api/charts/trend")
    async def api_chart_trend(
        request: Request, days: int = Query(30),
    ):
        key = f"trend:{days}"
        cached = _cached(key)
        if cached is not None:
            return _chart_response(cached)
        config = request.app.state.config
        conn = db.get_connection(config.db_path)
        try:
            data = _set_cache(key, db.daily_trend(conn, days=days, local_tz=config.tz))
        finally:
            conn.close()
        return _chart_response(data)

    @app.get("/api/species")
    async def api_species(
        request: Request, q: str = Query(None),
    ):
        config = request.app.state.config
        conn = db.get_connection(config.db_path)
        try:
            return db.species_list(conn, q=q)
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
