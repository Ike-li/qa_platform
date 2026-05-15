from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Any

import structlog
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from qaplatform.api.schemas import ErrorDetail, ErrorResponse
from qaplatform.config import Settings

logger = structlog.get_logger(__name__)


def create_app(container: Any | None = None, settings: Settings | None = None) -> FastAPI:
    """FastAPI application factory."""

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # Startup: initialise container if not pre-injected
        nonlocal container
        if container is None:
            from qaplatform.dependencies import init_container

            _settings = settings or Settings()
            container = init_container(_settings)
            app.state.container = container
        yield
        # Shutdown
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

    # ── CORS ──────────────────────────────────────────────────────────────
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ── Auth middleware ───────────────────────────────────────────────────
    # Placeholder: worker-2 will provide the actual middleware.
    # The middleware is registered here once available:
    # from qaplatform.api.middleware.auth import AuthMiddleware
    # app.add_middleware(AuthMiddleware)

    # ── Routers ──────────────────────────────────────────────────────────
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
    app.include_router(sse_router, prefix=api_prefix)

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
