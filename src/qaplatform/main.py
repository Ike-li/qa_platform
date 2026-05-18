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
from qaplatform.api.middleware.security_headers import SecurityHeadersMiddleware
from qaplatform.api.middleware.cors import setup_cors
from qaplatform.api.metrics import (
    http_request_duration,
    metrics_route,
    run_queue_depth,
    runs_in_flight,
)

logger = structlog.get_logger(__name__)

START_TIME = time.time()


def _ensure_plugin_registry(container: Any) -> None:
    if getattr(container, "plugin_registry", None) is None:
        from qaplatform.plugins.registry import PluginRegistry

        plugin_registry = PluginRegistry()
        plugin_registry.register_builtins()
        container.plugin_registry = plugin_registry


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
            await container.init_s3()
            container.init_crypto()
            _ensure_plugin_registry(container)
            app.state.container = container
        
        logger.info("application_started", version="0.1.0")
        yield
        # Shutdown
        # NOTE: do NOT cancel asyncio.all_tasks() here.
        #
        # Every asyncio.create_task() call in this codebase (heartbeat_task in
        # worker/tasks.py, cancel_task and log_task in engine/executor.py) holds
        # an explicit reference and is cleaned up in its own finally block.
        # There are no "orphan" tasks that need a global sweep.
        #
        # Cancelling all tasks at this point would race with:
        #   - in-flight HTTP request handlers still being drained by uvicorn
        #     (uvicorn waits up to graceful_timeout=30 s before SIGKILL)
        #   - SSE long-poll generators blocked on redis.xread(..., block=5000)
        #     — they self-terminate within 5 s once the client disconnects or
        #     the run reaches a terminal status
        #   - asyncio.gather() sub-tasks that share a CancelledError scope
        #
        # Rely on uvicorn's own graceful shutdown instead; container.close()
        # handles all connection-pool teardown.
        logger.info("application_shutting_down")

        if hasattr(container, "close"):
            await container.close()

    app = FastAPI(
        title="QA Platform API",
        version="0.1.0",
        description="QA 自动化执行平台 API",
        contact={
            "name": "QA Platform Team",
            "url": "https://github.com/qa-platform/qa-platform",
        },
        license_info={
            "name": "MIT",
        },
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
    )

    # Store container on app state
    if container is not None:
        _ensure_plugin_registry(container)
        app.state.container = container

    _settings_obj = settings or (container.settings if container else Settings())

    # ── Middlewares ──────────────────────────────────────────────────────
    app.add_middleware(SecurityHeadersMiddleware, settings=_settings_obj)
    app.add_middleware(RequestIdMiddleware)

    # HTTP request duration histogram — wraps all routes including /metrics itself
    @app.middleware("http")
    async def _record_request_duration(request: Request, call_next):
        import time as _time
        route = request.url.path
        start = _time.perf_counter()
        response = await call_next(request)
        duration = _time.perf_counter() - start
        http_request_duration.labels(
            method=request.method,
            route=route,
            status_code=str(response.status_code),
        ).observe(duration)
        return response
    
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
    from qaplatform.api.v1.analytics import router as analytics_router
    from qaplatform.api.v1.artifacts import router as artifact_router
    from qaplatform.api.v1.auth import router as auth_router
    from qaplatform.api.v1.credentials import router as credential_router
    from qaplatform.api.v1.environments import router as env_router
    from qaplatform.api.v1.notifications import router as notification_router
    from qaplatform.api.v1.pipelines import router as pipeline_router
    from qaplatform.api.v1.project_members import router as project_member_router
    from qaplatform.api.v1.projects import router as project_router
    from qaplatform.api.v1.runs import router as run_router
    from qaplatform.api.v1.schedules import router as schedule_router
    from qaplatform.api.v1.sse import router as sse_router
    from qaplatform.api.v1.webhooks import router as webhook_router

    api_prefix = "/api/v1"
    app.include_router(auth_router, prefix=api_prefix)
    app.include_router(analytics_router, prefix=api_prefix)
    app.include_router(project_router, prefix=api_prefix)
    app.include_router(project_member_router, prefix=api_prefix)
    app.include_router(credential_router, prefix=api_prefix)
    app.include_router(env_router, prefix=api_prefix)
    app.include_router(pipeline_router, prefix=api_prefix)
    app.include_router(notification_router, prefix=api_prefix)
    app.include_router(run_router, prefix=api_prefix)
    app.include_router(schedule_router, prefix=api_prefix)
    app.include_router(artifact_router, prefix=api_prefix)
    app.include_router(sse_router, prefix=api_prefix)
    app.include_router(webhook_router, prefix=api_prefix)

    # ── Health checks ────────────────────────────────────────────────────
    app.add_route("/metrics", metrics_route.endpoint, methods=["GET"], include_in_schema=False)

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
