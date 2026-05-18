from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from qaplatform.api.auth.middleware import CurrentUser, _authenticate_jwt
from qaplatform.config import Settings


@pytest.fixture
def mock_settings():
    settings = MagicMock(spec=Settings)
    settings.jwt_secret = 'test-secret'
    settings.jwt_access_token_ttl = 3600
    settings.jwt_refresh_token_ttl = 86400
    return settings


@pytest.fixture
def mock_container(mock_settings):
    container = MagicMock()
    container.settings = mock_settings
    container.redis_client = AsyncMock()
    return container


@pytest.mark.asyncio
async def test_authenticate_jwt_passes_when_blacklist_lookup_fails(
    mock_container, mock_settings
):
    """P1 regression: Redis blip during is_revoked must not 500 the request.
    Fail-open prevents site-wide outage when Redis is degraded."""
    # Create a valid JWT with jti
    import jwt
    from datetime import datetime, timedelta, timezone
    from uuid import uuid4

    now = datetime.now(timezone.utc)
    jti = uuid4().hex
    payload = {
        'sub': 'user123',
        'role': 'viewer',
        'tenant_id': 'tenant456',
        'is_platform_admin': False,
        'exp': now + timedelta(hours=1),
        'iat': now,
        'jti': jti,
        'type': 'access',
    }
    token = jwt.encode(payload, mock_settings.jwt_secret, algorithm='HS256')

    # Mock is_revoked to raise an exception (simulating Redis failure)
    with patch(
        'qaplatform.api.auth.middleware.JWTService.is_revoked',
        new_callable=AsyncMock,
        side_effect=Exception('Redis connection failed'),
    ):
        # Should NOT raise an exception; should return CurrentUser
        result = await _authenticate_jwt(token, mock_container)

    assert isinstance(result, CurrentUser)
    assert result.user_id == 'user123'
    assert result.role == 'viewer'
    assert result.tenant_id == 'tenant456'
    assert result.is_platform_admin is False


@pytest.mark.asyncio
async def test_authenticate_jwt_rejects_when_token_actually_revoked(
    mock_container, mock_settings
):
    """Sanity: real revocation still raises 401."""
    import jwt
    from datetime import datetime, timedelta, timezone
    from uuid import uuid4

    now = datetime.now(timezone.utc)
    jti = uuid4().hex
    payload = {
        'sub': 'user123',
        'role': 'viewer',
        'tenant_id': 'tenant456',
        'is_platform_admin': False,
        'exp': now + timedelta(hours=1),
        'iat': now,
        'jti': jti,
        'type': 'access',
    }
    token = jwt.encode(payload, mock_settings.jwt_secret, algorithm='HS256')

    # Mock is_revoked to return True (token is revoked)
    with patch(
        'qaplatform.api.auth.middleware.JWTService.is_revoked',
        new_callable=AsyncMock,
        return_value=True,
    ):
        with pytest.raises(HTTPException) as exc_info:
            await _authenticate_jwt(token, mock_container)

    assert exc_info.value.status_code == 401
    assert 'revoked' in exc_info.value.detail.lower()
