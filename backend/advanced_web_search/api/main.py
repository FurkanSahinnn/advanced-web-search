"""FastAPI application factory.

Serves the JSON+SSE API under `/api` and the built SPA from `/` (history
fallback). When the SPA has not been built yet, the catch-all returns a short
HTML hint instead.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

import advanced_web_search

from ..db import database
from .routes_export import router as export_router
from .routes_projects import router as projects_router
from .routes_research import router as research_router
from .routes_settings import router as settings_router
from .routes_sources import router as sources_router

WEB_DIR = Path(advanced_web_search.__file__).parent / "web"

_DEV_HINT = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>Advanced Web Search</title>
<style>body{font-family:system-ui,sans-serif;max-width:42rem;margin:4rem auto;padding:0 1rem;
line-height:1.6;color:#222}code{background:#f3f3f3;padding:.15rem .35rem;border-radius:.25rem}</style>
</head><body>
<h1>Advanced Web Search</h1>
<p>The frontend has not been built yet. Build the SPA and reload:</p>
<pre><code>cd frontend
pnpm install
pnpm build</code></pre>
<p>Or run the dev servers with hot reload:</p>
<pre><code>python scripts/dev.py</code></pre>
<p>The API is live at <a href="/api/health">/api/health</a>.</p>
</body></html>"""


def create_app() -> FastAPI:
    app = FastAPI(title="Advanced Web Search", version=advanced_web_search.__version__)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.on_event("startup")
    async def _startup() -> None:
        await asyncio.to_thread(database.init_db)

    @app.get("/api/health")
    async def health() -> dict:
        return {"status": "ok", "version": advanced_web_search.__version__}

    # API routers (registered BEFORE the SPA catch-all so /api 404s normally).
    for r in (settings_router, projects_router, research_router, sources_router, export_router):
        app.include_router(r, prefix="/api")

    # --- Serve the built SPA from the same origin ---
    index_file = WEB_DIR / "index.html"
    assets_dir = WEB_DIR / "assets"
    if index_file.exists():
        if assets_dir.is_dir():
            app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="assets")

        @app.get("/{full_path:path}", include_in_schema=False)
        async def spa_fallback(full_path: str):
            # Let unmatched /api routes fall through to a normal 404.
            if full_path.startswith("api/") or full_path == "api":
                from fastapi import HTTPException

                raise HTTPException(status_code=404, detail="Not Found")
            # Serve a real static file when one exists (favicon, manifest, ...).
            candidate = WEB_DIR / full_path
            if full_path and candidate.is_file():
                return FileResponse(str(candidate))
            return FileResponse(str(index_file))
    else:
        @app.get("/{full_path:path}", include_in_schema=False)
        async def dev_hint(full_path: str):
            if full_path.startswith("api/") or full_path == "api":
                from fastapi import HTTPException

                raise HTTPException(status_code=404, detail="Not Found")
            return HTMLResponse(_DEV_HINT)

    return app


app = create_app()
