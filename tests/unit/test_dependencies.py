from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from qaplatform import dependencies
from qaplatform.api import deps as api_deps
from qaplatform.config import Settings
from qaplatform.dependencies import CryptoService


def _settings() -> Settings:
    return Settings(
        database_url="sqlite+aiosqlite:///:memory:",
        redis_url="redis://localhost:6379/0",
        s3_endpoint="http://s3.local",
        s3_access_key="access",
        s3_secret_key="secret",
        jwt_secret="x" * 32,
        encryption_key="0" * 64,
        _env_file=None,
    )


class _SessionContext:
    def __init__(self, session) -> None:
        self.session = session
        self.entered = False
        self.exit_args = None

    async def __aenter__(self):
        self.entered = True
        return self.session

    async def __aexit__(self, exc_type, exc, tb):
        self.exit_args = (exc_type, exc, tb)
        return False


def _session_factory_pair():
    session = MagicMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    context = _SessionContext(session)
    factory = MagicMock(return_value=context)
    return session, context, factory


async def _close_successfully(generator) -> None:
    with pytest.raises(StopAsyncIteration):
        await anext(generator)


def _request_for(container):
    return SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(container=container)))


@pytest.mark.parametrize("key", [b"", b"\x00" * 16, b"\x00" * 24, b"\x00" * 31])
def test_crypto_service_rejects_non_256_bit_keys_before_encrypt(key: bytes):
    with pytest.raises(ValueError) as exc_info:
        CryptoService({0: key})

    assert exc_info.value.args == ("Encryption key 0 must be 32 bytes",)


@pytest.mark.asyncio
async def test_global_get_db_session_commits_successful_request(monkeypatch):
    session, context, factory = _session_factory_pair()
    container = dependencies.DependencyContainer(_settings())
    container.db_session_factory = factory
    monkeypatch.setattr(dependencies, "_container", container)

    generator = dependencies.get_db_session()

    assert await anext(generator) is session
    await _close_successfully(generator)

    factory.assert_called_once_with()
    assert context.entered is True
    assert context.exit_args == (None, None, None)
    session.commit.assert_awaited_once_with()
    session.rollback.assert_not_awaited()


@pytest.mark.asyncio
async def test_global_get_db_session_rolls_back_and_reraises(monkeypatch):
    session, context, factory = _session_factory_pair()
    container = dependencies.DependencyContainer(_settings())
    container.db_session_factory = factory
    monkeypatch.setattr(dependencies, "_container", container)

    generator = dependencies.get_db_session()
    assert await anext(generator) is session

    error = RuntimeError("write failed")
    with pytest.raises(RuntimeError) as exc_info:
        await generator.athrow(error)

    assert exc_info.value is error
    session.commit.assert_not_awaited()
    session.rollback.assert_awaited_once_with()
    assert context.exit_args[0] is RuntimeError
    assert context.exit_args[1] is error


@pytest.mark.asyncio
async def test_global_get_db_session_requires_initialized_database(monkeypatch):
    container = dependencies.DependencyContainer(_settings())
    monkeypatch.setattr(dependencies, "_container", container)

    with pytest.raises(RuntimeError) as exc_info:
        await anext(dependencies.get_db_session())

    assert exc_info.value.args == ("Database not initialised",)


@pytest.mark.asyncio
async def test_api_get_db_session_commits_successful_request():
    session, context, factory = _session_factory_pair()
    container = SimpleNamespace(db_session_factory=factory)
    request = _request_for(container)

    generator = api_deps._get_db_session(request)

    assert await anext(generator) is session
    await _close_successfully(generator)

    factory.assert_called_once_with()
    assert context.exit_args == (None, None, None)
    session.commit.assert_awaited_once_with()
    session.rollback.assert_not_awaited()


@pytest.mark.asyncio
async def test_api_get_db_session_rolls_back_and_reraises():
    session, context, factory = _session_factory_pair()
    container = SimpleNamespace(db_session_factory=factory)
    request = _request_for(container)

    generator = api_deps._get_db_session(request)
    assert await anext(generator) is session

    error = RuntimeError("route failed")
    with pytest.raises(RuntimeError) as exc_info:
        await generator.athrow(error)

    assert exc_info.value is error
    session.commit.assert_not_awaited()
    session.rollback.assert_awaited_once_with()
    assert context.exit_args[0] is RuntimeError
    assert context.exit_args[1] is error


@pytest.mark.asyncio
async def test_api_get_repos_uses_request_container_and_session():
    session = object()
    bundle = object()
    container = MagicMock()
    container.get_repositories.return_value = bundle
    request = _request_for(container)

    assert await api_deps._get_repos(request, session=session) is bundle

    container.get_repositories.assert_called_once_with(session)


def test_api_get_session_factory_returns_configured_factory():
    factory = object()
    request = _request_for(SimpleNamespace(db_session_factory=factory))

    assert api_deps.get_session_factory(request) is factory


def test_api_get_session_factory_returns_503_when_database_uninitialized():
    request = _request_for(SimpleNamespace(db_session_factory=None))

    with pytest.raises(HTTPException) as exc_info:
        api_deps.get_session_factory(request)

    assert exc_info.value.status_code == 503
    assert exc_info.value.detail == "Database not initialized"
