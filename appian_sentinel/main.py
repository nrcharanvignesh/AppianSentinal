from __future__ import annotations

import hmac
import logging
import os
from collections.abc import Awaitable, Callable
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.requests import Request
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from appian_sentinel.config import settings
from appian_sentinel.web.routes import router as api_router
from appian_sentinel.web.routes import ws_router

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Application factory
# ---------------------------------------------------------------------------

_WEB_DIR = Path(__file__).resolve().parent / "web"

app = FastAPI(
    title="Appian Sentinel",
    description="Agentic Appian development automation",
    version="0.1.0",
)

# CORS — the Electron renderer loads from file:// (origin "null") in production
# or http://localhost:3000 in dev, and calls this sidecar over localhost.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def require_loopback_token(
    request: Request,
    call_next: Callable[[Request], Awaitable[Response]],
) -> Response:
    """Require the optional desktop token except for the liveness probe.

    A CORS preflight is exempt because a browser never attaches custom headers
    to it. Rejecting the preflight strips the CORS headers and the renderer
    sees "Failed to fetch". The actual request that follows is still checked.
    """
    token = os.environ.get("SENTINEL_API_TOKEN")
    supplied = request.headers.get("X-Sentinel-Token", "")
    if (
        token
        and request.method != "OPTIONS"
        and request.url.path != "/api/health"
        and not hmac.compare_digest(supplied, token)
    ):
        return JSONResponse(
            status_code=401,
            content={"detail": {"reason": "invalid_sentinel_token"}},
        )
    return await call_next(request)

# Mount static assets (CSS, JS)
app.mount(
    "/static",
    StaticFiles(directory=str(_WEB_DIR / "static")),
    name="static",
)

# Jinja2 templates (for the single-page index.html)
templates = Jinja2Templates(directory=str(_WEB_DIR / "templates"))

# Include REST API routes (/api/...) and the WebSocket route (/ws)
app.include_router(api_router)
app.include_router(ws_router)


# ---------------------------------------------------------------------------
# Root page
# ---------------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
async def index(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request=request, name="index.html")


# ---------------------------------------------------------------------------
# Startup / shutdown
# ---------------------------------------------------------------------------

@app.on_event("startup")
async def on_startup() -> None:
    workspace = settings.sentinel_workspace.resolve()
    workspace.mkdir(parents=True, exist_ok=True)
    logger.info("Workspace directory: %s", workspace)
    logger.info(
        "Appian Sentinel starting on %s:%s",
        settings.sentinel_host,
        settings.sentinel_port,
    )


# ---------------------------------------------------------------------------
# CLI entry point  (called by `appian-sentinel` console script)
# ---------------------------------------------------------------------------

def main() -> None:
    import uvicorn

    uvicorn.run(
        "appian_sentinel.main:app",
        host=settings.sentinel_host,
        port=settings.sentinel_port,
        reload=False,
        log_level="info",
    )


if __name__ == "__main__":
    main()
