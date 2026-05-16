"""Dependency injection container for QA Platform."""

from __future__ import annotations

import os
from functools import lru_cache
from typing import TYPE_CHECKING

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from qaplatform.config import Settings

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from sqlalchemy.ext.asyncio import AsyncEngine


class CryptoService:
    """AES-256-GCM encryption service with key rotation support.

    Ciphertext format: header(1) + nonce(12) + ciphertext(N)
    header high 4 bits = format_version, low 4 bits = key_version.
    """

    def __init__(self, keys: dict[int, bytes]) -> None:
        if not keys:
            raise ValueError("At least one encryption key is required")
        invalid = [v for v in keys if v < 0 or v > 15]
        if invalid:
            raise ValueError(f"Key version must be 0-15, got: {invalid}")
        self._keys = keys
        self._current_key_version: int = max(keys.keys())

    def encrypt(self, plaintext: str, context_id: str = "") -> bytes:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM

        nonce = os.urandom(12)
        aad = context_id.encode() if context_id else None
        cipher = AESGCM(self._keys[self._current_key_version])
        ciphertext = cipher.encrypt(nonce, plaintext.encode(), aad)
        header = (0x1 << 4) | self._current_key_version
        return bytes([header]) + nonce + ciphertext

    def decrypt(self, data: bytes, context_id: str = "") -> str:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM

        header = data[0]
        format_version = (header >> 4) & 0x0F
        key_version = header & 0x0F
        if format_version != 1:
            raise ValueError(f"Unsupported format version: {format_version}")
        if key_version not in self._keys:
            raise ValueError(f"Unknown key version: {key_version}")
        nonce = data[1:13]
        ciphertext = data[13:]
        aad = context_id.encode() if context_id else None
        cipher = AESGCM(self._keys[key_version])
        return cipher.decrypt(nonce, ciphertext, aad).decode()


class DependencyContainer:
    """Dependency injection container holding all shared services."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.db_engine: AsyncEngine | None = None
        self.db_session_factory: async_sessionmaker[AsyncSession] | None = None
        self.redis_client = None
        self.s3_client = None
        self.crypto_service: CryptoService | None = None
        self.event_bus = None
        self.plugin_registry = None
        self.arq_pool = None

    async def init_db(self) -> None:
        self.db_engine = create_async_engine(
            self.settings.database_url,
            pool_size=self.settings.database_pool_size,
            max_overflow=self.settings.database_max_overflow,
            echo=self.settings.debug,
        )
        self.db_session_factory = async_sessionmaker(
            self.db_engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )

    async def init_redis(self) -> None:
        import redis.asyncio as aioredis

        self.redis_client = aioredis.from_url(
            self.settings.redis_url,
            max_connections=self.settings.redis_max_connections,
            decode_responses=True,
        )

    async def init_arq(self) -> None:
        from arq.connections import RedisSettings, create_pool

        self.arq_pool = await create_pool(
            RedisSettings.from_dsn(self.settings.redis_url)
        )

    async def init_s3(self) -> None:
        from aiobotocore.session import get_session

        session = get_session()
        self.s3_client = await session.create_client(
            "s3",
            endpoint_url=self.settings.s3_endpoint,
            aws_access_key_id=self.settings.s3_access_key,
            aws_secret_access_key=self.settings.s3_secret_key,
            region_name=self.settings.s3_region,
        ).__aenter__()

    def init_crypto(self) -> None:
        keys: dict[int, bytes] = {}
        if self.settings.encryption_keys:
            for version, key_hex in self.settings.encryption_keys.items():
                keys[version] = bytes.fromhex(key_hex)
        else:
            keys[0] = bytes.fromhex(self.settings.encryption_key)
        self.crypto_service = CryptoService(keys)

    def get_repositories(self, session: AsyncSession) -> RepositoryBundle:
        """Create repository instances scoped to a session."""
        from qaplatform.infra.database.repositories.audit_repo import AuditEventRepository
        from qaplatform.infra.database.repositories.project_repo import (
            CredentialRepository,
            EnvironmentRepository,
            PipelineRepository,
            ProjectRepository,
        )
        from qaplatform.infra.database.repositories.run_repo import (
            ArtifactRepository,
            RunRepository,
            TestResultRepository,
        )
        from qaplatform.infra.database.repositories.user_repo import (
            ApiTokenRepository,
            UserRepository,
        )

        return RepositoryBundle(
            user=UserRepository(session),
            api_token=ApiTokenRepository(session),
            project=ProjectRepository(session),
            environment=EnvironmentRepository(session),
            pipeline=PipelineRepository(session),
            credential=CredentialRepository(session),
            run=RunRepository(session),
            test_result=TestResultRepository(session),
            artifact=ArtifactRepository(session),
            audit=AuditEventRepository(session),
        )

    async def close(self) -> None:
        if self.s3_client is not None:
            await self.s3_client.__aexit__(None, None, None)
        if self.db_engine is not None:
            await self.db_engine.dispose()
        if self.redis_client is not None:
            await self.redis_client.aclose()


class RepositoryBundle:
    """All repository instances scoped to a single session."""

    __slots__ = (
        "user",
        "api_token",
        "project",
        "environment",
        "pipeline",
        "credential",
        "run",
        "test_result",
        "artifact",
        "audit",
    )

    def __init__(
        self,
        *,
        user,
        api_token,
        project,
        environment,
        pipeline,
        credential,
        run,
        test_result,
        artifact,
        audit,
    ) -> None:
        self.user = user
        self.api_token = api_token
        self.project = project
        self.environment = environment
        self.pipeline = pipeline
        self.credential = credential
        self.run = run
        self.test_result = test_result
        self.artifact = artifact
        self.audit = audit


# --- Global container management ---

_container: DependencyContainer | None = None


def get_container() -> DependencyContainer:
    global _container
    if _container is None:
        raise RuntimeError("DependencyContainer not initialised; call init_container() first")
    return _container


def init_container(settings: Settings) -> DependencyContainer:
    global _container
    _container = DependencyContainer(settings)
    return _container


def get_settings() -> Settings:
    return get_container().settings


async def get_db_session() -> AsyncIterator[AsyncSession]:
    factory = get_container().db_session_factory
    if factory is None:
        raise RuntimeError("Database not initialised")
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


def get_repos(session: AsyncSession = Depends(get_db_session)) -> RepositoryBundle:
    """FastAPI dependency: repositories scoped to a request's DB session."""
    return get_container().get_repositories(session)


# FastAPI Depends helpers
def inject_settings() -> Settings:
    return get_settings()
