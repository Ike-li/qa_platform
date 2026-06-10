"""Tests for user repositories."""

import pytest
from datetime import datetime, timezone
from uuid import uuid4

from qaplatform.infra.database.repositories.user_repo import (
    UserRepository,
    TenantRepository,
    ApiTokenRepository,
)


@pytest.mark.asyncio
async def test_user_repo_get_by_email(integration_db_session, seed_run):
    """Test get user by email."""
    repo = UserRepository(integration_db_session)
    tenant = seed_run["tenant"]
    user = seed_run["user"]

    result = await repo.get_by_email(tenant.id, user.email)

    assert result is not None
    assert result.email == user.email


@pytest.mark.asyncio
async def test_user_repo_get_by_email_not_found(integration_db_session, seed_run):
    """Test get user by email returns None when not found."""
    repo = UserRepository(integration_db_session)
    tenant = seed_run["tenant"]

    result = await repo.get_by_email(tenant.id, "nonexistent@example.com")

    assert result is None


@pytest.mark.asyncio
async def test_user_repo_list_by_tenant(integration_db_session, seed_run):
    """Test list users by tenant."""
    repo = UserRepository(integration_db_session)
    tenant = seed_run["tenant"]

    users, count = await repo.list_by_tenant(tenant.id, offset=0, limit=20)

    assert count >= 1


@pytest.mark.asyncio
async def test_user_repo_update_last_login(integration_db_session, seed_run):
    """Test update user last login."""
    repo = UserRepository(integration_db_session)
    user = seed_run["user"]
    now = datetime.now(timezone.utc)

    updated = await repo.update_last_login(user, now)

    assert updated.last_login_at == now


@pytest.mark.asyncio
async def test_user_repo_is_platform_admin_false(integration_db_session, seed_run):
    """Test is_platform_admin returns False for regular user."""
    repo = UserRepository(integration_db_session)
    user = seed_run["user"]

    result = await repo.is_platform_admin(user.id)

    assert result is False


@pytest.mark.asyncio
async def test_user_repo_is_platform_admin_not_found(integration_db_session):
    """Test is_platform_admin returns False for nonexistent user."""
    repo = UserRepository(integration_db_session)

    result = await repo.is_platform_admin(uuid4())

    assert result is False


@pytest.mark.asyncio
async def test_tenant_repo_get_first(integration_db_session, seed_run):
    """Test get first tenant."""
    repo = TenantRepository(integration_db_session)

    result = await repo.get_first()

    assert result is not None


@pytest.mark.asyncio
async def test_tenant_repo_get_by_name(integration_db_session, seed_run):
    """Test get tenant by name."""
    repo = TenantRepository(integration_db_session)
    tenant = seed_run["tenant"]

    result = await repo.get_by_name(tenant.name)

    assert result is not None
    assert result.id == tenant.id


@pytest.mark.asyncio
async def test_tenant_repo_get_by_name_not_found(integration_db_session):
    """Test get tenant by name returns None when not found."""
    repo = TenantRepository(integration_db_session)

    result = await repo.get_by_name("nonexistent")

    assert result is None


@pytest.mark.asyncio
async def test_api_token_repo_list_by_user(integration_db_session, seed_run):
    """Test list API tokens by user."""
    repo = ApiTokenRepository(integration_db_session)
    user = seed_run["user"]

    tokens, count = await repo.list_by_user(user.id, offset=0, limit=20)

    assert count >= 0


@pytest.mark.asyncio
async def test_api_token_repo_get_by_token_id(integration_db_session, seed_run):
    """Test get API token by token_id."""
    from qaplatform.infra.database.models import ApiToken
    repo = ApiTokenRepository(integration_db_session)
    user = seed_run["user"]

    token = ApiToken(
        user_id=user.id,
        token_id="test-token-id",
        secret_hash="test-hash",
        name="Test Token",
        expires_at=datetime.now(timezone.utc),
    )
    integration_db_session.add(token)
    await integration_db_session.flush()

    result = await repo.get_by_token_id("test-token-id")

    assert result is not None
    assert result.token_id == "test-token-id"


@pytest.mark.asyncio
async def test_api_token_repo_revoke(integration_db_session, seed_run):
    """Test revoke API token."""
    from qaplatform.infra.database.models import ApiToken
    repo = ApiTokenRepository(integration_db_session)
    user = seed_run["user"]

    token = ApiToken(
        user_id=user.id,
        token_id="test-token-revoke",
        secret_hash="test-hash",
        name="Test Token",
        expires_at=datetime.now(timezone.utc),
    )
    integration_db_session.add(token)
    await integration_db_session.flush()

    updated = await repo.revoke(token)

    assert updated.is_revoked is True


@pytest.mark.asyncio
async def test_api_token_repo_update_last_used(integration_db_session, seed_run):
    """Test update API token last used."""
    from qaplatform.infra.database.models import ApiToken
    repo = ApiTokenRepository(integration_db_session)
    user = seed_run["user"]

    token = ApiToken(
        user_id=user.id,
        token_id="test-token-last-used",
        secret_hash="test-hash",
        name="Test Token",
        expires_at=datetime.now(timezone.utc),
    )
    integration_db_session.add(token)
    await integration_db_session.flush()

    now = datetime.now(timezone.utc)
    ip = "192.168.1.1"

    updated = await repo.update_last_used(token, now, ip)

    assert updated.last_used_at == now
    assert str(updated.last_used_ip) == ip
