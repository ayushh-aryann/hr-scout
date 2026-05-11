"""HR Scout — FastAPI application entrypoint."""

import logging
from pathlib import Path

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api.routes import router
from app.config import get_settings

settings = get_settings()

logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="HR Scout",
    description="AI-powered candidate shortlisting agent",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

# CORS — allow the frontend (served from filesystem or a dev server)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Tighten this in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)

# Serve the index.html frontend at root
_frontend = Path(__file__).parent / "index.html"
if _frontend.exists():
    @app.get("/", include_in_schema=False)
    async def serve_frontend():
        from fastapi.responses import HTMLResponse
        return HTMLResponse(_frontend.read_text(encoding="utf-8"))


if __name__ == "__main__":
    logger.info("Starting HR Scout on %s:%s", settings.host, settings.port)
    uvicorn.run(
        "main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug,
        log_level=settings.log_level.lower(),
    )
