from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import dataclass

import pytest
from httpx import ASGITransport, AsyncClient

from qaplatform.config import Settings
from qaplatform.main import create_app


def _settings() -> Settings:
    return Settings(
        database_url="postgresql+asyncpg://qa:qa@localhost:5432/qa",
        redis_url="redis://localhost:6379/0",
        s3_endpoint="http://localhost:9000",
        s3_access_key="minioadmin",
        s3_secret_key="minioadmin",
        jwt_secret="test-secret-key-at-least-32-bytes",
        encryption_key="0" * 64,
        debug=True,
        environment="test",
        _env_file=None,
    )


class _Session:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.statements: list[object] = []

    async def execute(self, statement: object) -> None:
        self.statements.append(statement)
        if self.fail:
            raise RuntimeError("database probe failed")


class _Redis:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.ping_count = 0

    async def ping(self) -> None:
        self.ping_count += 1
        if self.fail:
            raise RuntimeError("redis probe failed")


@dataclass
class _Container:
    session: _Session
    redis_client: _Redis
    settings: Settings
    plugin_registry: object

    def db_session_factory(self):
        @asynccontextmanager
        async def _factory():
            yield self.session

        return _factory()


def _container(*, db_fail: bool = False, redis_fail: bool = False) -> _Container:
    settings = _settings()
    return _Container(
        session=_Session(fail=db_fail),
        redis_client=_Redis(fail=redis_fail),
        settings=settings,
        plugin_registry=object(),
    )


def _client(app):
    transport = ASGITransport(app=app)
    return AsyncClient(transport=transport, base_url="http://test")


def _assert_uptime_seconds(value: str) -> float:
    assert value.endswith("s")
    seconds_text = value.removesuffix("s")
    whole, dot, fraction = seconds_text.partition(".")
    assert dot == "."
    assert whole == "0" or (whole.isdecimal() and not whole.startswith("0"))
    assert fraction.isdecimal()
    assert len(fraction) == 2
    seconds = float(seconds_text)
    assert seconds >= 0
    return seconds


@pytest.mark.asyncio
async def test_health_returns_lightweight_liveness_contract():
    app = create_app(container=_container(), settings=_settings())

    async with _client(app) as client:
        response = await client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body == {
        "status": "ok",
        "version": app.version,
        "uptime": body["uptime"],
    }
    _assert_uptime_seconds(body["uptime"])


@pytest.mark.asyncio
async def test_ready_returns_ok_when_database_and_redis_probes_pass():
    container = _container()
    app = create_app(container=container, settings=container.settings)

    async with _client(app) as client:
        response = await client.get("/ready")

    assert response.status_code == 200
    body = response.json()
    assert body == {
        "status": "ok",
        "version": app.version,
        "uptime": body["uptime"],
        "checks": {"db": "ok", "redis": "ok"},
    }
    _assert_uptime_seconds(body["uptime"])
    assert [str(statement) for statement in container.session.statements] == [
        "SELECT 1"
    ]
    assert container.redis_client.ping_count == 1


@pytest.mark.asyncio
async def test_ready_returns_degraded_when_database_probe_fails():
    container = _container(db_fail=True)
    app = create_app(container=container, settings=container.settings)

    async with _client(app) as client:
        response = await client.get("/ready")

    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "degraded"
    assert body["version"] == app.version
    _assert_uptime_seconds(body["uptime"])
    assert body["checks"] == {"db": "error", "redis": "ok"}
    assert [str(statement) for statement in container.session.statements] == [
        "SELECT 1"
    ]
    assert container.redis_client.ping_count == 1


@pytest.mark.asyncio
async def test_ready_returns_degraded_when_redis_probe_fails():
    container = _container(redis_fail=True)
    app = create_app(container=container, settings=container.settings)

    async with _client(app) as client:
        response = await client.get("/ready")

    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "degraded"
    assert body["version"] == app.version
    _assert_uptime_seconds(body["uptime"])
    assert body["checks"] == {"db": "ok", "redis": "error"}
    assert [str(statement) for statement in container.session.statements] == [
        "SELECT 1"
    ]
    assert container.redis_client.ping_count == 1


@pytest.mark.asyncio
async def test_ready_checks_all_dependencies_and_redacts_probe_errors_when_degraded():
    container = _container(db_fail=True, redis_fail=True)
    app = create_app(container=container, settings=container.settings)

    async with _client(app) as client:
        response = await client.get("/ready")

    assert response.status_code == 503
    body = response.json()
    assert body == {
        "status": "degraded",
        "version": app.version,
        "uptime": body["uptime"],
        "checks": {"db": "error", "redis": "error"},
    }
    _assert_uptime_seconds(body["uptime"])
    assert "database probe failed" not in response.text
    assert "redis probe failed" not in response.text
    assert [str(statement) for statement in container.session.statements] == [
        "SELECT 1"
    ]
    assert container.redis_client.ping_count == 1


@pytest.mark.asyncio
async def test_ready_reports_initializing_before_lifespan_injects_container():
    app = create_app(container=None, settings=_settings())

    async with _client(app) as client:
        response = await client.get("/ready")

    assert response.status_code == 503
    assert response.json() == {"status": "initializing", "version": app.version}
