from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import jwt
import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials

from qaplatform.api.auth.middleware import (
    CurrentUser,
    _authenticate_api_token,
    _authenticate_jwt,
    get_current_user,
)
from qaplatform.config import Settings


@pytest.fixture
def mock_settings():
    settings = MagicMock(spec=Settings)
    settings.jwt_secret = 'test-secret-at-least-32bytes-long!'
    settings.jwt_access_token_ttl = 3600
    settings.jwt_refresh_token_ttl = 86400
    return settings


@pytest.fixture
def mock_container(mock_settings):
    container = MagicMock()
    container.settings = mock_settings
    container.redis_client = AsyncMock()
    container.db_session_factory = None
    return container


def _jwt_token(settings, **overrides):
    now = datetime.now(timezone.utc)
    payload = {
        'sub': str(overrides.pop('sub', uuid4())),
        'role': overrides.pop('role', 'viewer'),
        'tenant_id': str(overrides.pop('tenant_id', uuid4())),
        'is_platform_admin': overrides.pop('is_platform_admin', False),
        'exp': overrides.pop('exp', now + timedelta(hours=1)),
        'iat': overrides.pop('iat', now),
        'type': overrides.pop('type', 'access'),
    }
    payload.update(overrides)
    return jwt.encode(payload, settings.jwt_secret, algorithm='HS256')


@asynccontextmanager
async def _session_context(session):
    yield session


@pytest.mark.asyncio
async def test_authenticate_jwt_passes_when_blacklist_lookup_fails(
    mock_container, mock_settings
):
    """P1 regression: Redis blip during is_revoked must not 500 the request.
    Fail-open prevents site-wide outage when Redis is degraded."""
    jti = uuid4().hex
    user_id = uuid4()
    tenant_id = uuid4()
    token = _jwt_token(
        mock_settings,
        sub=user_id,
        tenant_id=tenant_id,
        jti=jti,
    )

    # Mock is_revoked to raise an exception (simulating Redis failure)
    with patch(
        'qaplatform.api.auth.middleware.JWTService.is_revoked',
        new_callable=AsyncMock,
        side_effect=Exception('Redis connection failed'),
    ):
        # Should NOT raise an exception; should return CurrentUser
        result = await _authenticate_jwt(token, mock_container)

    assert isinstance(result, CurrentUser)
    assert result.user_id == str(user_id)
    assert result.role == 'viewer'
    assert result.tenant_id == str(tenant_id)
    assert result.is_platform_admin is False


@pytest.mark.asyncio
async def test_authenticate_jwt_rejects_when_token_actually_revoked(
    mock_container, mock_settings
):
    """Sanity: real revocation still raises 401."""
    jti = uuid4().hex
    token = _jwt_token(mock_settings, jti=jti)

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


@pytest.mark.asyncio
async def test_get_current_user_rejects_missing_authorization_header():
    with pytest.raises(HTTPException) as exc_info:
        await get_current_user(credentials=None)

    assert exc_info.value.status_code == 401
    assert 'authorization' in exc_info.value.detail.lower()


@pytest.mark.asyncio
async def test_get_current_user_routes_api_tokens_to_api_token_auth():
    user = CurrentUser(user_id=str(uuid4()), role='developer', tenant_id=str(uuid4()))
    credentials = HTTPAuthorizationCredentials(
        scheme='Bearer',
        credentials='qap_tokenid_secret',
    )

    with (
        patch('qaplatform.api.auth.middleware._get_container', return_value=MagicMock()),
        patch(
            'qaplatform.api.auth.middleware._authenticate_api_token',
            new_callable=AsyncMock,
            return_value=user,
        ) as api_auth,
        patch('qaplatform.api.auth.middleware._authenticate_jwt', new_callable=AsyncMock) as jwt_auth,
    ):
        result = await get_current_user(credentials=credentials)

    assert result is user
    api_auth.assert_awaited_once()
    jwt_auth.assert_not_awaited()


@pytest.mark.asyncio
async def test_get_current_user_routes_non_api_tokens_to_jwt_auth():
    user = CurrentUser(user_id=str(uuid4()), role='viewer', tenant_id=str(uuid4()))
    credentials = HTTPAuthorizationCredentials(scheme='Bearer', credentials='jwt-token')

    with (
        patch('qaplatform.api.auth.middleware._get_container', return_value=MagicMock()),
        patch('qaplatform.api.auth.middleware._authenticate_api_token', new_callable=AsyncMock) as api_auth,
        patch(
            'qaplatform.api.auth.middleware._authenticate_jwt',
            new_callable=AsyncMock,
            return_value=user,
        ) as jwt_auth,
    ):
        result = await get_current_user(credentials=credentials)

    assert result is user
    jwt_auth.assert_awaited_once()
    api_auth.assert_not_awaited()


@pytest.mark.asyncio
async def test_authenticate_jwt_rejects_expired_tokens(mock_container, mock_settings):
    token = _jwt_token(
        mock_settings,
        exp=datetime.now(timezone.utc) - timedelta(seconds=1),
    )

    with pytest.raises(HTTPException) as exc_info:
        await _authenticate_jwt(token, mock_container)

    assert exc_info.value.status_code == 401
    assert 'expired' in exc_info.value.detail.lower()


@pytest.mark.asyncio
async def test_authenticate_jwt_rejects_invalid_tokens(mock_container):
    with pytest.raises(HTTPException) as exc_info:
        await _authenticate_jwt('not-a-jwt', mock_container)

    assert exc_info.value.status_code == 401
    assert exc_info.value.detail == 'Invalid token'


@pytest.mark.asyncio
async def test_authenticate_jwt_rejects_refresh_token_type(mock_container, mock_settings):
    token = _jwt_token(mock_settings, type='refresh')

    with pytest.raises(HTTPException) as exc_info:
        await _authenticate_jwt(token, mock_container)

    assert exc_info.value.status_code == 401
    assert exc_info.value.detail == 'Invalid token type'


@pytest.mark.asyncio
async def test_authenticate_jwt_verifies_platform_admin_claim_against_database(
    mock_container, mock_settings
):
    session = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = True
    session.execute.return_value = result
    mock_container.db_session_factory = MagicMock(
        return_value=_session_context(session)
    )

    user_id = uuid4()
    token = _jwt_token(
        mock_settings,
        sub=user_id,
        is_platform_admin=True,
    )

    user = await _authenticate_jwt(token, mock_container)

    assert user.user_id == str(user_id)
    assert user.is_platform_admin is True
    session.execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_authenticate_api_token_rejects_malformed_token(mock_container):
    with pytest.raises(HTTPException) as exc_info:
        await _authenticate_api_token('qap_missing-secret', mock_container)

    assert exc_info.value.status_code == 401
    assert 'format' in exc_info.value.detail.lower()


@pytest.mark.asyncio
async def test_authenticate_api_token_rejects_when_database_unavailable(mock_container):
    with pytest.raises(HTTPException) as exc_info:
        await _authenticate_api_token('qap_tokenid_secret', mock_container)

    assert exc_info.value.status_code == 401
    assert 'not available' in exc_info.value.detail.lower()


def _api_token_record(**overrides):
    user = SimpleNamespace(
        role=overrides.pop('user_role', 'developer'),
        tenant_id=overrides.pop('tenant_id', uuid4()),
        is_platform_admin=overrides.pop('is_platform_admin', False),
    )
    return SimpleNamespace(
        user_id=overrides.pop('user_id', uuid4()),
        user=user,
        is_revoked=overrides.pop('is_revoked', False),
        expires_at=overrides.pop(
            'expires_at',
            datetime.now(timezone.utc) + timedelta(days=1),
        ),
        secret_hash=overrides.pop('secret_hash', 'hash'),
        scopes=overrides.pop('scopes', ['runs:read']),
        **overrides,
    )


@pytest.mark.asyncio
async def test_authenticate_api_token_returns_current_user_and_updates_last_used(
    mock_container,
):
    session = AsyncMock()
    mock_container.db_session_factory = MagicMock(
        return_value=_session_context(session)
    )
    token = _api_token_record(scopes=['runs:read', 'runs:write'])
    repo = AsyncMock()
    repo.get_by_token_id.return_value = token

    with (
        patch('qaplatform.infra.database.repositories.user_repo.ApiTokenRepository', return_value=repo),
        patch('qaplatform.api.auth.middleware.TokenService.verify_token', return_value=True),
    ):
        user = await _authenticate_api_token('qap_tokenid_secret', mock_container)

    assert user.user_id == str(token.user_id)
    assert user.role == 'developer'
    assert user.tenant_id == str(token.user.tenant_id)
    assert user.scopes == ['runs:read', 'runs:write']
    repo.get_by_token_id.assert_awaited_once_with('tokenid')
    repo.update_last_used.assert_awaited_once()
    session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_authenticate_api_token_rolls_back_last_used_failure_but_allows_user(
    mock_container,
):
    session = AsyncMock()
    mock_container.db_session_factory = MagicMock(
        return_value=_session_context(session)
    )
    repo = AsyncMock()
    repo.get_by_token_id.return_value = _api_token_record()
    repo.update_last_used.side_effect = RuntimeError('audit write failed')

    with (
        patch('qaplatform.infra.database.repositories.user_repo.ApiTokenRepository', return_value=repo),
        patch('qaplatform.api.auth.middleware.TokenService.verify_token', return_value=True),
    ):
        user = await _authenticate_api_token('qap_tokenid_secret', mock_container)

    assert user.role == 'developer'
    session.commit.assert_not_awaited()
    session.rollback.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ('token_record', 'verify_result', 'expected_detail'),
    [
        (None, True, 'invalid or revoked'),
        (_api_token_record(is_revoked=True), True, 'invalid or revoked'),
        (
            _api_token_record(expires_at=datetime.now(timezone.utc) - timedelta(seconds=1)),
            True,
            'expired',
        ),
        (_api_token_record(), False, 'invalid or revoked'),
    ],
)
async def test_authenticate_api_token_rejects_invalid_records(
    mock_container,
    token_record,
    verify_result,
    expected_detail,
):
    session = AsyncMock()
    mock_container.db_session_factory = MagicMock(
        return_value=_session_context(session)
    )
    repo = AsyncMock()
    repo.get_by_token_id.return_value = token_record

    with (
        patch('qaplatform.infra.database.repositories.user_repo.ApiTokenRepository', return_value=repo),
        patch('qaplatform.api.auth.middleware.TokenService.verify_token', return_value=verify_result),
    ):
        with pytest.raises(HTTPException) as exc_info:
            await _authenticate_api_token('qap_tokenid_secret', mock_container)

    assert exc_info.value.status_code == 401
    assert expected_detail in exc_info.value.detail.lower()
