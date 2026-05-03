"""
Personal Running Coach — FastAPI application entry point.

Responsibilities:
  - Structured JSON logging (python-json-logger)
  - CORS middleware (all origins — LAN-only app)
  - IP filter middleware (RFC-1918 allowlist)
  - Lifespan: DB init + scheduler start/stop
  - Router registration
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pythonjsonlogger import jsonlogger

from app.config import get_settings
from app.database import init_db
from app.middleware.ip_filter import IPFilterMiddleware
from app.routers import (
    health,
    profiles,
    settings as settings_router,
    zones,
    plans,
    race_goals,
    workouts,
    runs,
    stats,
    strava,
    export,
    analysis,
    weather,
    routes,
    taper,
    data_export,
    backup,
)
from app.scheduler import setup_scheduler, start_scheduler, stop_scheduler

# ---------------------------------------------------------------------------
# Structured JSON logging
# ---------------------------------------------------------------------------

settings = get_settings()

_log_handler = logging.StreamHandler()
_log_handler.setFormatter(
    jsonlogger.JsonFormatter(
        fmt="%(asctime)s %(name)s %(levelname)s %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )
)

logging.root.setLevel(settings.log_level.upper())
logging.root.addHandler(_log_handler)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup: initialise DB and start scheduler. Shutdown: stop scheduler."""
    logger.info("Starting up Personal Running Coach backend")
    init_db()
    setup_scheduler(get_settings)
    start_scheduler()
    logger.info("Startup complete")
    yield
    logger.info("Shutting down — stopping scheduler")
    stop_scheduler()
    logger.info("Shutdown complete")


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------

app = FastAPI(
    title="Personal Running Coach",
    description="AI-powered personal running training application",
    version="1.0.0",
    lifespan=lifespan,
)

# IP filter must be the outermost middleware so it runs first.
app.add_middleware(IPFilterMiddleware)

# CORS — allow all origins (LAN-only deployment; no public exposure)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Routers
# ---------------------------------------------------------------------------

# Health check is at root level (no /api/v1 prefix) per spec requirement 13.5
app.include_router(health.router)

# API v1 routers
app.include_router(profiles.router, prefix="/api/v1")
app.include_router(settings_router.router, prefix="/api/v1")
app.include_router(zones.router, prefix="/api/v1")
app.include_router(plans.router, prefix="/api/v1")
app.include_router(race_goals.router, prefix="/api/v1")
app.include_router(workouts.router, prefix="/api/v1")
app.include_router(runs.router, prefix="/api/v1")
app.include_router(stats.router, prefix="/api/v1")
app.include_router(strava.router, prefix="/api/v1")
app.include_router(export.router, prefix="/api/v1")
app.include_router(analysis.router, prefix="/api/v1")
app.include_router(weather.router, prefix="/api/v1")
app.include_router(routes.router, prefix="/api/v1")
app.include_router(taper.router, prefix="/api/v1")
app.include_router(data_export.router, prefix="/api/v1")
app.include_router(backup.router, prefix="/api/v1")
