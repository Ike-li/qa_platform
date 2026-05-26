from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from opentelemetry import trace
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.redis import RedisInstrumentor
from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SpanExporter
from opentelemetry.sdk.trace.sampling import ParentBased, TraceIdRatioBased

from qaplatform.config import Settings

if TYPE_CHECKING:
    from fastapi import FastAPI

log = logging.getLogger(__name__)

_EXCLUDED_URLS = (
    r".*/health(?:\?.*)?$,.*/ready(?:\?.*)?$,.*/metrics(?:\?.*)?$"
)
_SENSITIVE_REQUEST_HEADERS = ("authorization", "x-api-token", "cookie")
_SENSITIVE_HEADER_ATTRS = tuple(
    f"http.request.header.{header}" for header in _SENSITIVE_REQUEST_HEADERS
)

_provider: TracerProvider | None = None
_fastapi_app_ids: set[int] = set()
_sqlalchemy_engine_ids: set[int] = set()
_redis_instrumented = False


def setup_tracing(settings: Settings) -> TracerProvider | None:
    """Configure OpenTelemetry tracing if enabled.

    The OTLP HTTP exporter package is not part of the current dependency set.
    We only attempt that optional import when an endpoint is explicitly
    configured, so enabling local tracing never hard-fails on an undeclared
    exporter dependency.
    """
    if settings.otel_enabled is not True:
        return None

    return _get_or_create_provider(settings)


def _get_or_create_provider(settings: Settings) -> TracerProvider:
    global _provider
    if _provider is not None:
        return _provider

    provider = TracerProvider(
        resource=Resource.create({"service.name": settings.otel_service_name}),
        sampler=ParentBased(root=TraceIdRatioBased(settings.otel_sample_rate)),
    )
    exporter = _build_otlp_exporter(settings)
    if exporter is not None:
        provider.add_span_processor(BatchSpanProcessor(exporter))

    trace.set_tracer_provider(provider)
    _provider = provider
    return provider


def _build_otlp_exporter(settings: Settings) -> SpanExporter | None:
    if not settings.otel_exporter_endpoint:
        return None
    try:
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
            OTLPSpanExporter,
        )
    except ModuleNotFoundError:
        log.warning(
            "otel_otlp_http_exporter_missing",
            extra={"endpoint_configured": True},
        )
        return None
    return OTLPSpanExporter(endpoint=settings.otel_exporter_endpoint)


def instrument_fastapi(app: FastAPI, provider: TracerProvider) -> None:
    """Instrument a specific FastAPI app once."""
    app_id = id(app)
    if app_id in _fastapi_app_ids:
        return
    FastAPIInstrumentor.instrument_app(
        app,
        tracer_provider=provider,
        excluded_urls=_EXCLUDED_URLS,
        server_request_hook=_strip_sensitive_request_headers,
        http_capture_headers_server_request=[],
        http_capture_headers_sanitize_fields=list(_SENSITIVE_REQUEST_HEADERS),
    )
    _fastapi_app_ids.add(app_id)


def instrument_infra(container: Any, provider: TracerProvider) -> None:
    """Instrument database and Redis clients after the container is ready."""
    _instrument_sqlalchemy(container, provider)
    _instrument_redis(provider)


def _instrument_sqlalchemy(container: Any, provider: TracerProvider) -> None:
    db_engine = getattr(container, "db_engine", None)
    if db_engine is None:
        return

    sync_engine = getattr(db_engine, "sync_engine", db_engine)
    engine_id = id(sync_engine)
    if engine_id in _sqlalchemy_engine_ids:
        return

    SQLAlchemyInstrumentor().instrument(engine=sync_engine, tracer_provider=provider)
    _sqlalchemy_engine_ids.add(engine_id)


def _instrument_redis(provider: TracerProvider) -> None:
    global _redis_instrumented
    if _redis_instrumented:
        return
    RedisInstrumentor().instrument(tracer_provider=provider)
    _redis_instrumented = True


def _strip_sensitive_request_headers(span: Any, scope: dict[str, Any]) -> None:
    if span is None or not getattr(span, "is_recording", lambda: False)():
        return
    attributes = getattr(span, "_attributes", None)
    if attributes is None:
        return
    for key in _SENSITIVE_HEADER_ATTRS:
        attributes.pop(key, None)
