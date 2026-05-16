from __future__ import annotations

import logging
import time
from contextlib import asynccontextmanager
from typing import Any

import structlog
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text

from qaplatform.api.schemas import ErrorDetail, ErrorResponse
from qaplatform.config import Settings
from qaplatform.logging import configure_logging
from qaplatform.api.middleware.request_id import RequestIdMiddleware
from qaplatform.api.middleware.rate_limit import RateLimitMiddleware
from qaplatform.api.middleware.cors import setup_cors

logger = structlog.get_logger(__name__)

START_TIME = time.time()


def create_app(container: Any | None = None, settings: Settings | None = None) -> FastAPI:
    """FastAPI application factory."""

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # Startup: initialise container if not pre-injected
        nonlocal container
        if container is None:
            from qaplatform.dependencies import init_container

            _settings = settings or Settings()
            configure_logging(_settings)
            container = init_container(_settings)
            await container.init_db()
            await container.init_redis()
            await container.init_arq()
            app.state.container = container
        
        logger.info("application_started", version="0.1.0")
        yield
        # Shutdown
        logger.info("application_shutting_down")
        
        # Cancel all pending tasks
        import asyncio
        tasks = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
        if tasks:
            logger.info("cancelling_pending_tasks", count=len(tasks))
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

        if hasattr(container, "close"):
            await container.close()

    app = FastAPI(
        title="QA Platform",
        version="0.1.0",
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
    )

    # Store container on app state
    if container is not None:
        app.state.container = container

    _settings_obj = settings or (container.settings if container else Settings())

    # ── Middlewares ──────────────────────────────────────────────────────
    app.add_middleware(RequestIdMiddleware)
    
    # Rate limiting middleware needs redis_client from container
    # Since container might not be fully initialized here (it is in lifespan),
    # we might need to access it lazily if possible, or ensure it's available.
    # In create_app, if container is passed, we use it. 
    # Otherwise it's initialized in lifespan. 
    # For BaseHTTPMiddleware, it's added during app creation.
    
    if container and container.redis_client:
        app.add_middleware(RateLimitMiddleware, settings=_settings_obj, redis_client=container.redis_client)
    else:
        # If container is not yet available, we can't easily add RateLimitMiddleware here 
        # if it strictly requires redis_client at init time.
        # However, we can make RateLimitMiddleware fetch it from app.state.container at request time.
        # Let's adjust RateLimitMiddleware to be more flexible.
        app.add_middleware(RateLimitMiddleware, settings=_settings_obj, redis_client=None)

    # ── CORS ──────────────────────────────────────────────────────────────
    setup_cors(app, _settings_obj)

    # ── Auth middleware ───────────────────────────────────────────────────
    # Placeholder: worker-2 will provide the actual middleware.
    # The middleware is registered here once available:
    # from qaplatform.api.middleware.auth import AuthMiddleware
    # app.add_middleware(AuthMiddleware)

    # ── Routers ──────────────────────────────────────────────────────────
    from qaplatform.api.v1.artifacts import router as artifact_router
    from qaplatform.api.v1.auth import router as auth_router
    from qaplatform.api.v1.environments import router as env_router
    from qaplatform.api.v1.pipelines import router as pipeline_router
    from qaplatform.api.v1.projects import router as project_router
    from qaplatform.api.v1.runs import router as run_router
    from qaplatform.api.v1.sse import router as sse_router

    api_prefix = "/api/v1"
    app.include_router(auth_router, prefix=api_prefix)
    app.include_router(project_router, prefix=api_prefix)
    app.include_router(env_router, prefix=api_prefix)
    app.include_router(pipeline_router, prefix=api_prefix)
    app.include_router(run_router, prefix=api_prefix)
    app.include_router(artifact_router, prefix=api_prefix)
    app.include_router(sse_router, prefix=api_prefix)

    # ── Health checks ────────────────────────────────────────────────────
    @app.get("/health", tags=["ops"])
    async def health():
        return {
            "status": "ok",
            "version": app.version,
            "uptime": f"{time.time() - START_TIME:.2f}s",
        }

    @app.get("/ready", tags=["ops"])
    async def ready():
        container = getattr(app.state, "container", None)
        if not container:
            return JSONResponse(
                status_code=503,
                content={"status": "initializing", "version": app.version},
            )

        checks: dict = {}
        try:
            async with container.db_session_factory() as session:
                await session.execute(text("SELECT 1"))
            checks["db"] = "ok"
        except Exception as e:
            logger.error("health_check_db_failed", error=str(e))
            checks["db"] = "error"

        try:
            await container.redis_client.ping()
            checks["redis"] = "ok"
        except Exception as e:
            logger.error("health_check_redis_failed", error=str(e))
            checks["redis"] = "error"

        all_ok = all(v == "ok" for v in checks.values())
        return JSONResponse(
            status_code=200 if all_ok else 503,
            content={
                "status": "ok" if all_ok else "degraded",
                "version": app.version,
                "uptime": f"{time.time() - START_TIME:.2f}s",
                "checks": checks,
            },
        )

    # ── Unified error handling ───────────────────────────────────────────
    _register_error_handlers(app)

    return app


def _register_error_handlers(app: FastAPI) -> None:
    """Register unified error response handlers."""

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception):
        logger.error("unhandled_exception", exc_info=exc, path=request.url.path)
        body = ErrorResponse(
            error=ErrorDetail(
                code="INTERNAL_ERROR",
                message="An unexpected error occurred",
            )
        )
        return JSONResponse(status_code=500, content=body.model_dump())

    @app.exception_handler(404)
    async def not_found_handler(request: Request, exc):
        body = ErrorResponse(
            error=ErrorDetail(
                code="NOT_FOUND",
                message=str(exc.detail) if hasattr(exc, "detail") else "Resource not found",
            )
        )
        return JSONResponse(status_code=404, content=body.model_dump())

    @app.exception_handler(422)
    async def validation_error_handler(request: Request, exc):
        details: list[str] = []
        if hasattr(exc, "detail"):
            for err in exc.detail if isinstance(exc.detail, list) else []:
                loc = " -> ".join(str(l) for l in err.get("loc", []))
                details.append(f"{loc}: {err.get('msg', '')}")
        body = ErrorResponse(
            error=ErrorDetail(
                code="VALIDATION_ERROR",
                message="Request validation failed",
                details=details,
            )
        )
        return JSONResponse(status_code=422, content=body.model_dump())
