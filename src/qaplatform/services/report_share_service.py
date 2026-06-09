"""Service layer for report share token operations."""
from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from qaplatform.infra.database.models import ReportShareToken
from qaplatform.infra.database.repositories.report_share_token_repo import (
    ReportShareTokenRepository,
)


async def generate_share_token(
    session: AsyncSession,
    run_id: UUID,
    user_id: UUID,
    tenant_id: UUID,
    expires_in_days: int = 7,
    max_access_count: int | None = None,
) -> dict:
    """Generate a new share token for a report.

    Args:
        session: Database session
        run_id: Run ID to share
        user_id: User creating the share
        tenant_id: Tenant ID
        expires_in_days: Expiration in days (default 7)
        max_access_count: Optional max access count limit

    Returns:
        dict with token, expires_at, and share token ID
    """
    # Generate secure token
    token = secrets.token_urlsafe(32)
    expires_at = datetime.now(timezone.utc) + timedelta(days=expires_in_days)

    # Create share token record
    share_token = ReportShareToken(
        tenant_id=tenant_id,
        run_id=run_id,
        token=token,
        created_by=user_id,
        expires_at=expires_at,
        access_count=0,
        max_access_count=max_access_count,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )

    session.add(share_token)
    await session.flush()

    return {
        "id": share_token.id,
        "token": token,
        "expires_at": expires_at,
        "max_access_count": max_access_count,
    }


async def verify_share_token(
    session: AsyncSession,
    token: str,
    run_id: UUID,
) -> tuple[bool, ReportShareToken | None]:
    """Verify a share token is valid and increment access count.

    Args:
        session: Database session
        token: Token string to verify
        run_id: Expected run ID

    Returns:
        Tuple of (is_valid, token_object)
    """
    repo = ReportShareTokenRepository(session)

    # Get token
    share_token = await repo.get_by_token(token)

    if not share_token:
        return False, None

    # Verify run_id matches
    if share_token.run_id != run_id:
        return False, None

    # Check expiration
    now = datetime.now(timezone.utc)
    if share_token.expires_at < now:
        return False, share_token

    # Check access count limit
    if (
        share_token.max_access_count is not None
        and share_token.access_count >= share_token.max_access_count
    ):
        return False, share_token

    # Valid - increment access count
    await repo.increment_access_count(share_token.id)
    await session.commit()

    return True, share_token


async def list_share_tokens(
    session: AsyncSession,
    run_id: UUID,
) -> list[dict]:
    """List all share tokens for a run.

    Args:
        session: Database session
        run_id: Run ID

    Returns:
        List of share token dicts
    """
    repo = ReportShareTokenRepository(session)
    tokens = await repo.list_by_run(run_id)

    now = datetime.now(timezone.utc)

    return [
        {
            "id": token.id,
            "token": token.token,
            "created_by": token.created_by,
            "expires_at": token.expires_at,
            "is_expired": token.expires_at < now,
            "access_count": token.access_count,
            "max_access_count": token.max_access_count,
            "last_accessed_at": token.last_accessed_at,
            "created_at": token.created_at,
        }
        for token in tokens
    ]


async def revoke_share_token(
    session: AsyncSession,
    token_id: UUID,
) -> bool:
    """Revoke a share token by setting its expiry to now.

    Args:
        session: Database session
        token_id: Token ID to revoke

    Returns:
        True if revoked, False if not found
    """
    repo = ReportShareTokenRepository(session)

    token = await repo.get_by_id(token_id)
    if not token:
        return False

    # Set expiry to now
    token.expires_at = datetime.now(timezone.utc)
    await session.flush()
    await session.commit()

    return True
