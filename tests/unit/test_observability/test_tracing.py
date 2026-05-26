from __future__ import annotations

import builtins
from types import SimpleNamespace
from unittest.mock import MagicMock

from qaplatform.config import Settings


def _settings(**overrides) -> Settings:
    defaults = {
        "database_url": "postgresql+asyncpg://localhost/test",
        "redis_url": "redis://localhost:6379/0",
        "s3_endpoint": "http://localhost:9000",
        "s3_access_key": "minioadmin",
        "s3_secret_key": "minioadmin",
        "jwt_secret": "test-jwt-secret-at-least-32bytes!",
        "encryption_key": "0" * 64,
    }
    defaults.update(overrides)
    return Settings(**defaults)


def _reset_tracing_state(monkeypatch) -> None:
    from qaplatform.observability import tracing

    monkeypatch.setattr(tracing, "_provider", None)
    monkeypatch.setattr(tracing, "_fastapi_app_ids", set())
    monkeypatch.setattr(tracing, "_sqlalchemy_engine_ids", set())
    monkeypatch.setattr(tracing, "_redis_instrumented", False)


def _patch_instrumentors(monkeypatch):
    from qaplatform.observability import tracing

    calls: dict[str, list] = {
        "fastapi_app": [],
        "sqlalchemy": [],
        "redis": [],
    }

    def _instrument_app(*args, **kwargs):
        calls["fastapi_app"].append((args, kwargs))

    class _FastAPIInstrumentor:
        instrument_app = staticmethod(_instrument_app)

    class _SQLAlchemyInstrumentor:
        def instrument(self, **kwargs):
            calls["sqlalchemy"].append(kwargs)

    class _RedisInstrumentor:
        def instrument(self, **kwargs):
            calls["redis"].append(kwargs)

    monkeypatch.setattr(tracing, "FastAPIInstrumentor", _FastAPIInstrumentor)
    monkeypatch.setattr(tracing, "SQLAlchemyInstrumentor", _SQLAlchemyInstrumentor)
    monkeypatch.setattr(tracing, "RedisInstrumentor", _RedisInstrumentor)
    return calls


def test_setup_tracing_disabled_is_noop(monkeypatch):
    from qaplatform.observability import tracing

    _reset_tracing_state(monkeypatch)
    calls = _patch_instrumentors(monkeypatch)
    set_provider = MagicMock()
    monkeypatch.setattr(tracing.trace, "set_tracer_provider", set_provider)

    provider = tracing.setup_tracing(_settings(otel_enabled=False))

    assert provider is None
    set_provider.assert_not_called()
    assert calls == {
        "fastapi_app": [],
        "sqlalchemy": [],
        "redis": [],
    }


def test_setup_tracing_enabled_sets_provider_without_exporter_by_default(monkeypatch):
    from qaplatform.observability import tracing

    _reset_tracing_state(monkeypatch)
    calls = _patch_instrumentors(monkeypatch)
    set_provider = MagicMock()
    monkeypatch.setattr(tracing.trace, "set_tracer_provider", set_provider)

    provider = tracing.setup_tracing(
        _settings(
            otel_enabled=True,
            otel_service_name="qa-platform-test",
            otel_sample_rate=0.5,
        )
    )

    assert provider is not None
    assert provider.resource.attributes["service.name"] == "qa-platform-test"
    assert provider.sampler._root._rate == 0.5
    set_provider.assert_called_once_with(provider)
    assert calls == {
        "fastapi_app": [],
        "sqlalchemy": [],
        "redis": [],
    }


def test_setup_tracing_is_idempotent(monkeypatch):
    from qaplatform.observability import tracing

    _reset_tracing_state(monkeypatch)
    set_provider = MagicMock()
    monkeypatch.setattr(tracing.trace, "set_tracer_provider", set_provider)

    settings = _settings(otel_enabled=True)
    provider = tracing.setup_tracing(settings)
    again = tracing.setup_tracing(settings)

    assert again is provider
    set_provider.assert_called_once_with(provider)


def test_build_otlp_exporter_skips_when_endpoint_missing(monkeypatch):
    from qaplatform.observability import tracing

    import_attempted = MagicMock()

    def _blocked_import(name, *args, **kwargs):
        if name.startswith("opentelemetry.exporter"):
            import_attempted(name)
        return original_import(name, *args, **kwargs)

    original_import = builtins.__import__
    monkeypatch.setattr(builtins, "__import__", _blocked_import)

    exporter = tracing._build_otlp_exporter(_settings(otel_enabled=True))

    assert exporter is None
    import_attempted.assert_not_called()


def test_instrument_fastapi_app_once(monkeypatch):
    from qaplatform.observability import tracing

    _reset_tracing_state(monkeypatch)
    calls = _patch_instrumentors(monkeypatch)
    provider = MagicMock()
    app = object()

    tracing.instrument_fastapi(app, provider)
    tracing.instrument_fastapi(app, provider)

    assert calls["fastapi_app"][0][0][0] is app
    fastapi_kwargs = calls["fastapi_app"][0][1]
    assert fastapi_kwargs["tracer_provider"] is provider
    assert "metrics" in fastapi_kwargs["excluded_urls"]
    assert fastapi_kwargs["http_capture_headers_server_request"] == []
    assert "authorization" in fastapi_kwargs["http_capture_headers_sanitize_fields"]
    assert len(calls["fastapi_app"]) == 1


def test_instrument_fastapi_records_route_status_and_excludes_ops_paths(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
        InMemorySpanExporter,
    )
    from opentelemetry.trace import SpanKind

    from qaplatform.observability import tracing

    _reset_tracing_state(monkeypatch)
    app = FastAPI()

    @app.get("/items/{item_id}")
    def get_item(item_id: str):
        return {"item_id": item_id}

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.get("/metrics")
    def metrics():
        return "ok"

    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    tracing.instrument_fastapi(app, provider)

    with TestClient(app) as client:
        client.get(
            "/items/123",
            headers={
                "Authorization": "Bearer secret",
                "Cookie": "sid=secret",
                "X-API-Token": "legacy-secret",
            },
        )
        client.get("/health")
        client.get("/metrics?probe=1")

    server_spans = [
        span
        for span in exporter.get_finished_spans()
        if span.kind is SpanKind.SERVER
    ]

    assert len(server_spans) == 1
    attributes = server_spans[0].attributes
    assert attributes["http.method"] == "GET"
    assert attributes["http.route"] == "/items/{item_id}"
    assert attributes["http.status_code"] == 200
    assert not any(
        key.startswith("http.request.header.") for key in attributes
    )


def test_instrument_infra_uses_sync_engine_and_is_idempotent(monkeypatch):
    from qaplatform.observability import tracing

    _reset_tracing_state(monkeypatch)
    calls = _patch_instrumentors(monkeypatch)
    provider = MagicMock()
    sync_engine = object()
    container = SimpleNamespace(db_engine=SimpleNamespace(sync_engine=sync_engine))

    tracing.instrument_infra(container, provider)
    tracing.instrument_infra(container, provider)

    assert calls["sqlalchemy"] == [
        {"engine": sync_engine, "tracer_provider": provider}
    ]
    assert calls["redis"] == [{"tracer_provider": provider}]


def test_strip_sensitive_request_headers_removes_captured_attrs() -> None:
    from qaplatform.observability.tracing import _strip_sensitive_request_headers

    span = MagicMock()
    span.is_recording.return_value = True
    span._attributes = {
        "http.request.header.authorization": ["Bearer secret"],
        "http.request.header.x-api-token": ["token"],
        "http.request.header.cookie": ["sid=secret"],
        "http.method": "GET",
    }

    _strip_sensitive_request_headers(span, {"headers": []})

    assert span._attributes == {"http.method": "GET"}
