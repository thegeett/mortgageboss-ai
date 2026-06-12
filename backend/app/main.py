"""mortgageboss-ai backend application entry point."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.activity import router as activity_router
from app.api.auth import router as auth_router
from app.api.borrowers import router as borrowers_router
from app.api.lenders import router as lenders_router
from app.api.loan_files import router as loan_files_router
from app.api.needs import router as needs_router
from app.api.property import router as property_router
from app.core.config import settings
from app.core.database import (
    check_database_connection,
    close_database_connections,
)
from app.core.logging import get_logger, setup_logging
from app.core.redis import check_redis_connection, close_redis_connections

# The versioned API prefix under which feature routers are mounted. The auth
# refresh cookie is path-scoped to "{API_V1_PREFIX}/auth/refresh"; keep
# app.api.auth.REFRESH_COOKIE_PATH in sync if this changes.
API_V1_PREFIX = "/api/v1"

# Configure logging before anything else
setup_logging()
log = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Application lifespan: startup and shutdown logic."""
    log.info(
        "starting_application",
        app=settings.app_name,
        version=settings.app_version,
        environment=settings.environment,
    )

    # Verify critical dependencies are reachable
    db_ok = await check_database_connection()
    if not db_ok:
        log.error("database_connection_failed", url=str(settings.database_url))
        raise RuntimeError("Cannot start: database is unreachable")
    log.info("database_connected")

    redis_ok = await check_redis_connection()
    if not redis_ok:
        log.error("redis_connection_failed", url=str(settings.redis_url))
        raise RuntimeError("Cannot start: Redis is unreachable")
    log.info("redis_connected")

    log.info("application_ready")

    yield

    # Shutdown
    log.info("shutting_down")
    await close_database_connections()
    await close_redis_connections()
    log.info("shutdown_complete")


app = FastAPI(
    title=settings.app_name,
    description="AI-powered loan processing assistant",
    version=settings.app_version,
    lifespan=lifespan,
)


# CORS configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)

# Feature routers. Each router carries its own resource prefix under /api/v1, so
# login lives at "/api/v1/auth/login" and loan files at "/api/v1/loan-files".
app.include_router(auth_router, prefix=API_V1_PREFIX)
app.include_router(loan_files_router, prefix=API_V1_PREFIX)
app.include_router(borrowers_router, prefix=API_V1_PREFIX)
app.include_router(property_router, prefix=API_V1_PREFIX)
app.include_router(lenders_router, prefix=API_V1_PREFIX)
app.include_router(needs_router, prefix=API_V1_PREFIX)
app.include_router(activity_router, prefix=API_V1_PREFIX)


@app.get("/")
async def root() -> dict[str, str]:
    """Welcome endpoint."""
    return {
        "service": settings.app_name,
        "version": settings.app_version,
        "environment": settings.environment,
        "status": "running",
    }


@app.get("/health")
async def health_check() -> JSONResponse:
    """Comprehensive health check including dependency verification."""
    db_ok = await check_database_connection()
    redis_ok = await check_redis_connection()

    overall_healthy = db_ok and redis_ok

    return JSONResponse(
        status_code=status.HTTP_200_OK if overall_healthy else status.HTTP_503_SERVICE_UNAVAILABLE,
        content={
            "status": "healthy" if overall_healthy else "degraded",
            "service": settings.app_name,
            "version": settings.app_version,
            "checks": {
                "database": "ok" if db_ok else "fail",
                "redis": "ok" if redis_ok else "fail",
            },
        },
    )


@app.get("/health/live")
async def liveness_check() -> dict[str, str]:
    """Liveness probe: returns 200 if the application is running.

    Does not check dependencies. Used by orchestrators to determine
    if the application should be restarted.
    """
    return {"status": "alive"}


@app.get("/health/ready")
async def readiness_check() -> JSONResponse:
    """Readiness probe: returns 200 if the application can serve traffic.

    Checks all critical dependencies. Used by orchestrators to determine
    if the application should receive traffic.
    """
    db_ok = await check_database_connection()
    redis_ok = await check_redis_connection()

    ready = db_ok and redis_ok

    return JSONResponse(
        status_code=status.HTTP_200_OK if ready else status.HTTP_503_SERVICE_UNAVAILABLE,
        content={
            "ready": ready,
            "checks": {
                "database": "ok" if db_ok else "fail",
                "redis": "ok" if redis_ok else "fail",
            },
        },
    )
