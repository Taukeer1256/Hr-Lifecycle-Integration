"""
HR Lifecycle Integration Service – FastAPI application entry point.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import get_settings
from app.db import connect_db, disconnect_db, get_db
from app.routers import admin, auth, employees, events
from app.workers.outbox_worker import run_outbox_worker

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
settings = get_settings()
logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------
_worker_task: asyncio.Task | None = None  # type: ignore[type-arg]


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    global _worker_task
    logger.info("Starting HR Lifecycle Integration Service...")
    await connect_db()
    # Bootstrap default users if empty
    db = get_db()
    existing_admin = await db.users.find_one({"username": "hr_admin"})
    if not existing_admin:
        from datetime import UTC, datetime

        from app.security.jwt_auth import hash_password

        await db.users.insert_many([
            {
                "_id": "admin-id",
                "username": "hr_admin",
                "hashed_password": hash_password("HrAdmin123!"),
                "role": "hr_admin",
                "active": True,
                "created_at": datetime.now(UTC),
            },
            {
                "_id": "int-admin-id",
                "username": "integration_admin",
                "hashed_password": hash_password("IntAdmin123!"),
                "role": "integration_admin",
                "active": True,
                "created_at": datetime.now(UTC),
            },
            {
                "_id": "viewer-id",
                "username": "hr_viewer",
                "hashed_password": hash_password("Viewer123!"),
                "role": "hr_viewer",
                "active": True,
                "created_at": datetime.now(UTC),
            },
        ])
        logger.info("Bootstrap users (hr_admin, integration_admin, hr_viewer) initialized.")

    # Start outbox worker as background task
    _worker_task = asyncio.create_task(run_outbox_worker())
    logger.info("Outbox worker task started.")
    yield
    # Shutdown
    if _worker_task and not _worker_task.done():
        _worker_task.cancel()
        try:
            await _worker_task
        except asyncio.CancelledError:
            pass
    await disconnect_db()
    logger.info("HR Lifecycle Integration Service stopped.")


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------
app = FastAPI(
    title="HR Lifecycle Integration Service",
    description=(
        "Manages employee records and Joiner/Mover/Leaver (JML) workflows, "
        "syncing changes to downstream systems via transactional outbox pattern."
    ),
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Correlation ID middleware
# ---------------------------------------------------------------------------
@app.middleware("http")
async def correlation_id_middleware(request: Request, call_next):  # type: ignore[no-untyped-def]
    correlation_id = request.headers.get(settings.correlation_id_header) or str(uuid.uuid4())
    start_time = time.monotonic()
    response: Response = await call_next(request)
    duration_ms = (time.monotonic() - start_time) * 1000
    response.headers[settings.correlation_id_header] = correlation_id
    logger.info(
        "method=%s path=%s status=%d duration_ms=%.1f correlation_id=%s",
        request.method,
        request.url.path,
        response.status_code,
        duration_ms,
        correlation_id,
    )
    return response


# ---------------------------------------------------------------------------
# Routers
# ---------------------------------------------------------------------------
app.include_router(auth.router, prefix="/api/v1")
app.include_router(employees.router, prefix="/api/v1")
app.include_router(events.router, prefix="/api/v1")
app.include_router(admin.router, prefix="/api/v1")


# ---------------------------------------------------------------------------
# Health / Readiness
# ---------------------------------------------------------------------------
@app.get("/health", tags=["Health"], summary="Liveness check")
async def health() -> dict:
    return {"status": "ok", "service": "hr-lifecycle-integration"}


@app.get("/ready", tags=["Health"], summary="Readiness check")
async def ready() -> dict:
    """Checks MongoDB connectivity."""
    try:
        db = get_db()
        await db.command("ping")
        return {"status": "ready", "db": "connected"}
    except Exception as exc:
        return JSONResponse(
            status_code=503,
            content={"status": "not_ready", "db": str(exc)},
        )


@app.get("/", tags=["Health"], summary="Root")
async def root() -> dict:
    return {
        "service": "HR Lifecycle Integration Service",
        "version": "1.0.0",
        "docs": "/docs",
    }
