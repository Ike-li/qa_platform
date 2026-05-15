from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from testcontainers.postgres import PostgresContainer
from testcontainers.redis import RedisContainer

from qaplatform.config import Settings


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="session")
def pg_container():
    with PostgresContainer("postgres:16-alpine") as pg:
        yield pg


@pytest.fixture(scope="session")
def redis_container():
    with RedisContainer("redis:7-alpine") as redis:
        yield redis


@pytest.fixture(scope="session")
def test_settings(pg_container, redis_container) -> Settings:
    return Settings(
        database_url=pg_container.get_connection_url().replace(
            "psycopg2", "asyncpg"
        ),
        redis_url=redis_container.get_connection_url(),
        s3_endpoint="http://localhost:9000",
        s3_access_key="minioadmin",
        s3_secret_key="minioadmin",
        s3_bucket="qa-platform-test",
        jwt_secret="test-secret",
        encryption_key="0" * 64,
        debug=True,
        environment="test",
    )


@pytest_asyncio.fixture
async def db_engine(test_settings):
    engine = create_async_engine(test_settings.database_url)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def db_session(db_engine) -> AsyncIterator[AsyncSession]:
    session_factory = async_sessionmaker(db_engine, expire_on_commit=False)
    async with session_factory() as session:
        yield session


@pytest_asyncio.fixture
async def client(test_settings) -> AsyncIterator[AsyncClient]:
    from qaplatform.api import create_app
    from qaplatform.dependencies import init_container

    container = init_container(test_settings)
    app = create_app(container)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    await container.close()


@pytest_asyncio.fixture
async def admin_user(db_session: AsyncSession):
    from qaplatform.domain.models.user import User

    user = User(
        username="admin",
        email="admin@test.local",
        role="admin",
        is_active=True,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user
