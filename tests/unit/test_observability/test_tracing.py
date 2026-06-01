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
    return Settings(**defaults, _env_file=None)


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

    fastapi_args, fastapi_kwargs = calls["fastapi_app"][0]
    assert [args for args, _ in calls["fastapi_app"]] == [(app,)]
    assert fastapi_args == (app,)
    assert fastapi_kwargs["tracer_provider"] is provider
    fastapi_kwargs_without_provider = {
        key: value for key, value in fastapi_kwargs.items() if key != "tracer_provider"
    }
    assert fastapi_kwargs_without_provider == {
        "excluded_urls": tracing._EXCLUDED_URLS,
        "server_request_hook": tracing._strip_sensitive_request_headers,
        "http_capture_headers_server_request": [],
        "http_capture_headers_sanitize_fields": [
            "authorization",
            "x-api-token",
            "cookie",
        ],
    }


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

    span_projection = []
    for span in server_spans:
        attributes = span.attributes
        span_projection.append(
            {
                "method": attributes.get("http.method"),
                "route": attributes.get("http.route"),
                "status_code": attributes.get("http.status_code"),
                "captured_request_headers": sorted(
                    key
                    for key in attributes
                    if key.startswith("http.request.header.")
                ),
            }
        )

    assert span_projection == [
        {
            "method": "GET",
            "route": "/items/{item_id}",
            "status_code": 200,
            "captured_request_headers": [],
        }
    ]


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
