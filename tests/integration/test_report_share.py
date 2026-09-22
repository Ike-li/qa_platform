"""Tests for report share service and repository."""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from qaplatform.infra.database.repositories.report_share_token_repo import (
    ReportShareTokenRepository,
)
from qaplatform.services.report_share_service import (
    generate_share_token,
    list_share_tokens,
    revoke_share_token,
    verify_share_token,
)


@pytest.mark.asyncio
async def test_generate_share_token(integration_db_session, seed_run):
    """Test generating a share token."""
    run = seed_run["run"]
    user = seed_run["user"]
    tenant = seed_run["tenant"]

    result = await generate_share_token(
        integration_db_session,
        run.id,
        user.id,
        tenant.id,
        expires_in_days=7,
        max_access_count=10,
    )

    assert "id" in result
    assert "token" in result
    assert "expires_at" in result
    assert result["max_access_count"] == 10


@pytest.mark.asyncio
async def test_verify_share_token_valid(integration_db_session, seed_run):
    """Test verifying a valid share token."""
    run = seed_run["run"]
    user = seed_run["user"]
    tenant = seed_run["tenant"]

    result = await generate_share_token(
        integration_db_session, run.id, user.id, tenant.id
    )
    token = result["token"]

    is_valid, token_obj = await verify_share_token(
        integration_db_session, token, run.id
    )

    assert is_valid is True
    assert token_obj is not None
    assert token_obj.access_count == 1


@pytest.mark.asyncio
async def test_verify_share_token_invalid(integration_db_session, seed_run):
    """Test verifying an invalid token."""
    run = seed_run["run"]

    is_valid, token_obj = await verify_share_token(
        integration_db_session, "invalid-token", run.id
    )

    assert is_valid is False
    assert token_obj is None


@pytest.mark.asyncio
async def test_verify_share_token_wrong_run(integration_db_session, seed_run):
    """Test verifying token with wrong run_id."""
    run = seed_run["run"]
    user = seed_run["user"]
    tenant = seed_run["tenant"]

    result = await generate_share_token(
        integration_db_session, run.id, user.id, tenant.id
    )
    token = result["token"]

    is_valid, token_obj = await verify_share_token(
        integration_db_session, token, uuid4()
    )

    assert is_valid is False
    assert token_obj is None


@pytest.mark.asyncio
async def test_verify_share_token_expired(integration_db_session, seed_run):
    """Test verifying an expired token."""
    from qaplatform.infra.database.models import ReportShareToken

    run = seed_run["run"]
    user = seed_run["user"]
    tenant = seed_run["tenant"]

    expired_token = ReportShareToken(
        tenant_id=tenant.id,
        run_id=run.id,
        token="expired-token",
        created_by=user.id,
        expires_at=datetime.now(timezone.utc) - timedelta(days=1),
        access_count=0,
    )
    integration_db_session.add(expired_token)
    await integration_db_session.flush()

    is_valid, token_obj = await verify_share_token(
        integration_db_session, "expired-token", run.id
    )

    assert is_valid is False
    assert token_obj is not None


@pytest.mark.asyncio
async def test_verify_share_token_max_access(integration_db_session, seed_run):
    """Test verifying token that reached max access count."""
    run = seed_run["run"]
    user = seed_run["user"]
    tenant = seed_run["tenant"]

    result = await generate_share_token(
        integration_db_session, run.id, user.id, tenant.id, max_access_count=1
    )
    token = result["token"]

    # First access - valid
    is_valid, _ = await verify_share_token(integration_db_session, token, run.id)
    assert is_valid is True

    # Second access - invalid (max reached)
    is_valid, token_obj = await verify_share_token(
        integration_db_session, token, run.id
    )
    assert is_valid is False
    assert token_obj is not None


@pytest.mark.asyncio
async def test_list_share_tokens(integration_db_session, seed_run):
    """Test listing share tokens for a run."""
    run = seed_run["run"]
    user = seed_run["user"]
    tenant = seed_run["tenant"]

    await generate_share_token(integration_db_session, run.id, user.id, tenant.id)
    await generate_share_token(integration_db_session, run.id, user.id, tenant.id)

    tokens = await list_share_tokens(integration_db_session, run.id)

    assert len(tokens) >= 2
    assert all("id" in t for t in tokens)
    assert all("token" in t for t in tokens)


@pytest.mark.asyncio
async def test_revoke_share_token(integration_db_session, seed_run):
    """Test revoking a share token."""
    run = seed_run["run"]
    user = seed_run["user"]
    tenant = seed_run["tenant"]

    result = await generate_share_token(
        integration_db_session, run.id, user.id, tenant.id
    )
    token_id = result["id"]

    success = await revoke_share_token(integration_db_session, token_id)

    assert success is True


@pytest.mark.asyncio
async def test_revoke_nonexistent_token(integration_db_session):
    """Test revoking a nonexistent token."""
    success = await revoke_share_token(integration_db_session, uuid4())

    assert success is False


@pytest.mark.asyncio
async def test_repo_get_by_token(integration_db_session, seed_run):
    """Test repository get_by_token."""
    run = seed_run["run"]
    user = seed_run["user"]
    tenant = seed_run["tenant"]

    result = await generate_share_token(
        integration_db_session, run.id, user.id, tenant.id
    )
    token = result["token"]

    repo = ReportShareTokenRepository(integration_db_session)
    token_obj = await repo.get_by_token(token)

    assert token_obj is not None
    assert token_obj.token == token


@pytest.mark.asyncio
async def test_repo_get_active_token(integration_db_session, seed_run):
    """Test repository get_active_token."""
    run = seed_run["run"]
    user = seed_run["user"]
    tenant = seed_run["tenant"]

    result = await generate_share_token(
        integration_db_session, run.id, user.id, tenant.id
    )
    token = result["token"]

    repo = ReportShareTokenRepository(integration_db_session)
    token_obj = await repo.get_active_token(token)

    assert token_obj is not None
    assert token_obj.token == token


@pytest.mark.asyncio
async def test_repo_list_by_run(integration_db_session, seed_run):
    """Test repository list_by_run."""
    run = seed_run["run"]
    user = seed_run["user"]
    tenant = seed_run["tenant"]

    await generate_share_token(integration_db_session, run.id, user.id, tenant.id)

    repo = ReportShareTokenRepository(integration_db_session)
    tokens = await repo.list_by_run(run.id)

    assert len(tokens) >= 1
