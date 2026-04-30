"""Web dashboard routes."""

from __future__ import annotations

import time
from pathlib import Path

from fastapi import FastAPI, Query, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse

from . import db, health_checks, image_cache

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

    def _attach_audio(detections: list[dict], conn) -> list[dict]:
        audio_map = db.species_audio_map(conn)
        for det in detections:
            det["audio_file"] = audio_map.get(det["common_name"])
        return detections

    @app.get("/", response_class=HTMLResponse)
    async def index(request: Request):
        config = request.app.state.config
        conn = db.get_connection(config.db_path)
        try:
            detections = db.recent_detections(conn, limit=20)
            _attach_audio(detections, conn)
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
            _attach_audio(detections, conn)
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
            _attach_audio(detections, conn)
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
        request: Request,
        days: int = Query(7),
        search: str = Query(None),
    ):
        key = f"timeline:{days}:{search or ''}"
        cached = _cached(key)
        if cached is not None:
            return _chart_response(cached)
        config = request.app.state.config
        conn = db.get_connection(config.db_path)
        try:
            data = _set_cache(
                key,
                db.detection_timeline(conn, days=days, local_tz=config.tz, search=search),
            )
        finally:
            conn.close()
        return _chart_response(data)

    @app.get("/api/charts/timeline/species")
    async def api_chart_timeline_species(
        request: Request,
        days: int = Query(7),
        search: str = Query(None),
    ):
        """Per-hour species breakdown for tooltip detail."""
        key = f"timeline_species:{days}:{search or ''}"
        cached = _cached(key)
        if cached is not None:
            return _chart_response(cached)
        config = request.app.state.config
        conn = db.get_connection(config.db_path)
        try:
            data = _set_cache(
                key,
                db.timeline_species_breakdown(conn, days=days, local_tz=config.tz, search=search),
            )
        finally:
            conn.close()
        return _chart_response(data)

    @app.get("/api/charts/species")
    async def api_chart_species(
        request: Request,
        days: int = Query(30),
        limit: int = Query(15),
        search: str = Query(None),
    ):
        key = f"species:{days}:{limit}:{search or ''}"
        cached = _cached(key)
        if cached is not None:
            return _chart_response(cached)
        config = request.app.state.config
        conn = db.get_connection(config.db_path)
        try:
            data = _set_cache(
                key,
                db.species_frequency(conn, days=days, limit=limit, local_tz=config.tz, search=search),
            )
        finally:
            conn.close()
        return _chart_response(data)

    @app.get("/api/charts/heatmap")
    async def api_chart_heatmap(
        request: Request,
        days: int = Query(30),
        search: str = Query(None),
    ):
        key = f"heatmap:{days}:{search or ''}"
        cached = _cached(key)
        if cached is not None:
            return _chart_response(cached)
        config = request.app.state.config
        conn = db.get_connection(config.db_path)
        try:
            data = _set_cache(
                key,
                db.activity_heatmap(conn, days=days, local_tz=config.tz, search=search),
            )
        finally:
            conn.close()
        return _chart_response(data)

    @app.get("/api/charts/heatmap/species")
    async def api_chart_heatmap_species(
        request: Request,
        days: int = Query(30),
        search: str = Query(None),
    ):
        """Per-cell species breakdown for heatmap tooltip detail."""
        key = f"heatmap_species:{days}:{search or ''}"
        cached = _cached(key)
        if cached is not None:
            return _chart_response(cached)
        config = request.app.state.config
        conn = db.get_connection(config.db_path)
        try:
            data = _set_cache(
                key,
                db.heatmap_species_breakdown(conn, days=days, local_tz=config.tz, search=search),
            )
        finally:
            conn.close()
        return _chart_response(data)

    @app.get("/api/charts/trend")
    async def api_chart_trend(
        request: Request,
        days: int = Query(30),
        search: str = Query(None),
    ):
        key = f"trend:{days}:{search or ''}"
        cached = _cached(key)
        if cached is not None:
            return _chart_response(cached)
        config = request.app.state.config
        conn = db.get_connection(config.db_path)
        try:
            data = _set_cache(
                key,
                db.daily_trend(conn, days=days, local_tz=config.tz, search=search),
            )
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

    @app.get("/api/audio/{filename}")
    async def audio_clip(request: Request, filename: str):
        if "/" in filename or "\\" in filename or ".." in filename:
            return HTMLResponse("", status_code=400)
        config = request.app.state.config
        path = config.audio_clip_dir / filename
        if path.exists():
            return FileResponse(path, media_type="audio/wav")
        return HTMLResponse("", status_code=404)

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

    # ── Health panel endpoints ──────────────────────────────────────────

    @app.get("/partials/health", response_class=HTMLResponse)
    async def partial_health(request: Request):
        """Tier 1 health panel — instant data, skeletons for Tier 2."""
        config = request.app.state.config
        tier1 = health_checks.tier1_checks(config)
        return request.app.state.templates.TemplateResponse(
            request,
            "_health_panel.html",
            {"tier1": tier1},
        )

    @app.get("/api/health")
    async def api_health(request: Request):
        """Full health check — Tier 1 + Tier 2 combined."""
        import asyncio
        config = request.app.state.config
        tier1 = health_checks.tier1_checks(config)
        loop = asyncio.get_event_loop()
        tier2 = await loop.run_in_executor(None, health_checks.tier2_checks, config)
        return JSONResponse({**tier1, **tier2})

    @app.get("/api/health/quick")
    async def api_health_quick():
        """Fast dot colour: returns {color: 'green'|'yellow'|'red'}."""
        import asyncio
        loop = asyncio.get_event_loop()
        color = await loop.run_in_executor(None, health_checks.quick_status)
        return JSONResponse({"color": color})

    # ── Tier 2 fragment endpoints (loaded async by the panel) ──────────

    @app.get("/api/health/tier2/hardware", response_class=HTMLResponse)
    async def health_tier2_hardware(request: Request):
        import asyncio
        loop = asyncio.get_event_loop()
        hw = await loop.run_in_executor(None, lambda: {
            "cpu_temp": health_checks.check_cpu_temp(),
            "memory": health_checks.check_memory(),
            "disk": health_checks.check_disk(),
            "microphone": health_checks.check_microphone(),
        })
        # Build inline HTML fragment
        lines = []
        lines.append('<div class="flex items-center gap-2 mb-2">')
        # Overall status: worst of sub-checks
        statuses = [v["status"] for v in hw.values()]
        worst = "fail" if "fail" in statuses else ("warn" if "warn" in statuses else "ok")
        color = {"ok": "emerald", "warn": "amber", "fail": "red"}[worst]
        lines.append(f'<div class="w-2.5 h-2.5 rounded-full bg-{color}-400"></div>')
        lines.append('<h3 class="font-semibold text-sm text-stone-700">Hardware</h3>')
        lines.append('</div>')
        lines.append('<div class="grid grid-cols-2 gap-x-4 gap-y-1 text-xs text-stone-600">')

        for key in ("cpu_temp", "memory", "disk", "microphone"):
            check = hw[key]
            lines.append(f'<div>{check["label"]}</div>')
            sc = {"ok": "emerald", "warn": "amber", "fail": "red"}.get(check["status"], "stone")
            lines.append(f'<div class="text-right text-{sc}-600 font-medium">{check["detail"]}</div>')

        # Memory progress bar
        mem = hw["memory"]
        if "percent" in mem:
            mc = {"ok": "emerald", "warn": "amber", "fail": "red"}[mem["status"]]
            lines.append('<div class="col-span-2 mt-1">')
            lines.append('<div class="w-full bg-stone-100 rounded-full h-1.5">')
            lines.append(f'<div class="bg-{mc}-400 h-1.5 rounded-full" style="width:{mem["percent"]}%"></div>')
            lines.append('</div></div>')

        # Disk progress bar
        disk = hw["disk"]
        if "percent" in disk:
            dkc = {"ok": "emerald", "warn": "amber", "fail": "red"}[disk["status"]]
            lines.append('<div class="col-span-2 mt-1">')
            lines.append('<div class="w-full bg-stone-100 rounded-full h-1.5">')
            lines.append(f'<div class="bg-{dkc}-400 h-1.5 rounded-full" style="width:{disk["percent"]}%"></div>')
            lines.append('</div></div>')

        lines.append('</div>')
        return HTMLResponse("\n".join(lines))

    @app.get("/api/health/tier2/db", response_class=HTMLResponse)
    async def health_tier2_db(request: Request):
        import asyncio
        config = request.app.state.config
        loop = asyncio.get_event_loop()
        check = await loop.run_in_executor(None, health_checks.check_db_integrity, config.db_path)
        sc = {"ok": "emerald", "warn": "amber", "fail": "red"}.get(check["status"], "stone")
        lines = ['<div class="grid grid-cols-2 gap-x-4 gap-y-1 text-xs text-stone-600">']
        lines.append('<div>Integrity</div>')
        lines.append(f'<div class="text-right text-{sc}-600 font-medium">{check["detail"]}</div>')
        if "total_detections" in check:
            lines.append('<div>Total detections</div>')
            lines.append(f'<div class="text-right font-mono">{check["total_detections"]:,}</div>')
        if "total_species" in check:
            lines.append('<div>Total species</div>')
            lines.append(f'<div class="text-right font-mono">{check["total_species"]}</div>')
        if check.get("audio_clips"):
            lines.append('<div>Audio clips</div>')
            lines.append(f'<div class="text-right font-mono">{check["audio_clips"]}</div>')
        lines.append('</div>')
        return HTMLResponse("\n".join(lines))

    @app.get("/api/health/tier2/birdnet", response_class=HTMLResponse)
    async def health_tier2_birdnet(request: Request):
        config = request.app.state.config
        check = health_checks.check_birdnet(config)
        sc = {"ok": "emerald", "warn": "amber", "fail": "red"}.get(check["status"], "stone")
        lines = ['<div class="grid grid-cols-2 gap-x-4 gap-y-1 text-xs text-stone-600">']
        lines.append('<div>BirdNET</div>')
        lines.append(f'<div class="text-right text-{sc}-600 font-medium">{check["detail"]}</div>')
        if check.get("path"):
            lines.append('<div>Path</div>')
            path = check["path"]
            lines.append(
                f'<div class="text-right font-mono text-[10px] truncate"'
                f' title="{path}">{path}</div>'
            )
        lines.append('</div>')
        return HTMLResponse("\n".join(lines))

    @app.get("/api/health/tier2/network", response_class=HTMLResponse)
    async def health_tier2_network(request: Request):
        import asyncio
        loop = asyncio.get_event_loop()
        check = await loop.run_in_executor(None, health_checks.check_network)
        svc = await loop.run_in_executor(None, health_checks.check_systemd)
        lines = []
        lines.append('<div class="flex items-center gap-2 mb-2">')
        sc = {"ok": "emerald", "warn": "amber", "fail": "red"}.get(check["status"], "stone")
        lines.append(f'<div class="w-2.5 h-2.5 rounded-full bg-{sc}-400"></div>')
        lines.append('<h3 class="font-semibold text-sm text-stone-700">Network</h3>')
        lines.append('</div>')
        lines.append('<div class="grid grid-cols-2 gap-x-4 gap-y-1 text-xs text-stone-600">')
        if check.get("ssid"):
            lines.append(f'<div>WiFi</div><div class="text-right">{check["ssid"]}</div>')
        for ip in check.get("ips", [])[:3]:
            label = "Tailscale" if ip.startswith("100.") else "IP"
            lines.append(f'<div>{label}</div><div class="text-right font-mono">{ip}</div>')
        if check.get("tailscale") and not any(ip.startswith("100.") for ip in check.get("ips", [])):
            lines.append(f'<div>Tailscale</div><div class="text-right font-mono">{check["tailscale"]}</div>')
        # Service info
        svc_sc = {"ok": "emerald", "warn": "amber", "fail": "red"}.get(svc["status"], "stone")
        lines.append(f'<div>Service</div><div class="text-right text-{svc_sc}-600 font-medium">{svc["detail"]}</div>')
        if svc.get("since"):
            lines.append(f'<div>Since</div><div class="text-right text-[10px]">{svc["since"]}</div>')
        lines.append('</div>')
        return HTMLResponse("\n".join(lines))

    @app.get("/api/health/tier2/uptime", response_class=HTMLResponse)
    async def health_tier2_uptime(request: Request):
        import asyncio
        loop = asyncio.get_event_loop()
        check = await loop.run_in_executor(None, health_checks.check_system_uptime)
        lines = []
        lines.append('<div class="flex items-center gap-2 mb-2">')
        lines.append('<div class="w-2.5 h-2.5 rounded-full bg-emerald-400"></div>')
        lines.append('<h3 class="font-semibold text-sm text-stone-700">Uptime</h3>')
        lines.append('</div>')
        lines.append('<div class="grid grid-cols-2 gap-x-4 gap-y-1 text-xs text-stone-600">')
        lines.append(f'<div>System</div><div class="text-right font-mono">{check["detail"]}</div>')
        lines.append('</div>')
        return HTMLResponse("\n".join(lines))
