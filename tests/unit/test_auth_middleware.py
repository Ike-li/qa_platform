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


API_TOKEN_ID = 'a' * 32
API_TOKEN_SECRET = 'b' * 64
API_BEARER_TOKEN = f'qap_{API_TOKEN_ID}_{API_TOKEN_SECRET}'


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


def _signed_jwt(settings, payload):
    return jwt.encode(payload, settings.jwt_secret, algorithm='HS256')


def _jwt_user_record(user_id, tenant_id, **overrides):
    tenant_deleted_at = overrides.pop('tenant_deleted_at', None)
    return SimpleNamespace(
        id=user_id,
        tenant_id=overrides.pop('tenant_id', tenant_id),
        role=overrides.pop('role', 'viewer'),
        is_active=overrides.pop('is_active', True),
        deleted_at=overrides.pop('deleted_at', None),
        is_platform_admin=overrides.pop('is_platform_admin', False),
        tenant=SimpleNamespace(deleted_at=tenant_deleted_at),
    )


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
    ) as is_revoked:
        # Should NOT raise an exception; should return CurrentUser
        result = await _authenticate_jwt(token, mock_container)

    is_revoked.assert_awaited_once_with(jti)
    assert mock_container.db_session_factory is None
    assert result == CurrentUser(
        user_id=str(user_id),
        role='viewer',
        tenant_id=str(tenant_id),
        is_platform_admin=False,
    )


@pytest.mark.asyncio
async def test_authenticate_jwt_rejects_when_token_actually_revoked(
    mock_container, mock_settings
):
    """Sanity: real revocation still raises 401."""
    jti = uuid4().hex
    token = _jwt_token(mock_settings, jti=jti)
    mock_container.db_session_factory = MagicMock(
        side_effect=AssertionError("revoked JWT must not open a DB session")
    )

    # Mock is_revoked to return True (token is revoked)
    with patch(
        'qaplatform.api.auth.middleware.JWTService.is_revoked',
        new_callable=AsyncMock,
        return_value=True,
    ) as is_revoked:
        with pytest.raises(HTTPException) as exc_info:
            await _authenticate_jwt(token, mock_container)

    assert exc_info.value.status_code == 401
    assert exc_info.value.detail == 'Token has been revoked'
    is_revoked.assert_awaited_once_with(jti)
    mock_container.db_session_factory.assert_not_called()


@pytest.mark.asyncio
async def test_get_current_user_rejects_missing_authorization_header():
    with pytest.raises(HTTPException) as exc_info:
        await get_current_user(credentials=None)

    assert exc_info.value.status_code == 401
    assert exc_info.value.detail == 'Missing Authorization header'


@pytest.mark.asyncio
async def test_get_current_user_routes_api_tokens_to_api_token_auth():
    user = CurrentUser(user_id=str(uuid4()), role='developer', tenant_id=str(uuid4()))
    container = MagicMock()
    credentials = HTTPAuthorizationCredentials(
        scheme='Bearer',
        credentials=API_BEARER_TOKEN,
    )

    with (
        patch('qaplatform.api.auth.middleware._get_container', return_value=container),
        patch(
            'qaplatform.api.auth.middleware._authenticate_api_token',
            new_callable=AsyncMock,
            return_value=user,
        ) as api_auth,
        patch('qaplatform.api.auth.middleware._authenticate_jwt', new_callable=AsyncMock) as jwt_auth,
    ):
        result = await get_current_user(credentials=credentials)

    assert result is user
    api_auth.assert_awaited_once_with(API_BEARER_TOKEN, container)
    jwt_auth.assert_not_awaited()


@pytest.mark.asyncio
async def test_get_current_user_routes_non_api_tokens_to_jwt_auth():
    user = CurrentUser(user_id=str(uuid4()), role='viewer', tenant_id=str(uuid4()))
    container = MagicMock()
    credentials = HTTPAuthorizationCredentials(scheme='Bearer', credentials='jwt-token')

    with (
        patch('qaplatform.api.auth.middleware._get_container', return_value=container),
        patch('qaplatform.api.auth.middleware._authenticate_api_token', new_callable=AsyncMock) as api_auth,
        patch(
            'qaplatform.api.auth.middleware._authenticate_jwt',
            new_callable=AsyncMock,
            return_value=user,
        ) as jwt_auth,
    ):
        result = await get_current_user(credentials=credentials)

    assert result is user
    jwt_auth.assert_awaited_once_with('jwt-token', container)
    api_auth.assert_not_awaited()


@pytest.mark.asyncio
async def test_authenticate_jwt_rejects_expired_tokens(mock_container, mock_settings):
    token = _jwt_token(
        mock_settings,
        exp=datetime.now(timezone.utc) - timedelta(seconds=1),
    )
    mock_container.db_session_factory = MagicMock(
        side_effect=AssertionError("expired JWT must not open a DB session")
    )

    with patch(
        'qaplatform.api.auth.middleware.JWTService.is_revoked',
        new_callable=AsyncMock,
        side_effect=AssertionError("expired JWT must not check blacklist"),
    ) as is_revoked:
        with pytest.raises(HTTPException) as exc_info:
            await _authenticate_jwt(token, mock_container)

    assert exc_info.value.status_code == 401
    assert exc_info.value.detail == 'Token has expired'
    is_revoked.assert_not_awaited()
    mock_container.db_session_factory.assert_not_called()


@pytest.mark.asyncio
async def test_authenticate_jwt_rejects_invalid_tokens(mock_container):
    mock_container.db_session_factory = MagicMock(
        side_effect=AssertionError("invalid JWT must not open a DB session")
    )

    with pytest.raises(HTTPException) as exc_info:
        await _authenticate_jwt('not-a-jwt', mock_container)

    assert exc_info.value.status_code == 401
    assert exc_info.value.detail == 'Invalid token'
    mock_container.db_session_factory.assert_not_called()


@pytest.mark.asyncio
async def test_authenticate_jwt_rejects_refresh_token_type(mock_container, mock_settings):
    token = _jwt_token(mock_settings, type='refresh')
    mock_container.db_session_factory = MagicMock(
        side_effect=AssertionError("refresh JWT must not open a DB session")
    )

    with patch(
        'qaplatform.api.auth.middleware.JWTService.is_revoked',
        new_callable=AsyncMock,
        side_effect=AssertionError("refresh JWT must not check blacklist"),
    ) as is_revoked:
        with pytest.raises(HTTPException) as exc_info:
            await _authenticate_jwt(token, mock_container)

    assert exc_info.value.status_code == 401
    assert exc_info.value.detail == 'Invalid token type'
    is_revoked.assert_not_awaited()
    mock_container.db_session_factory.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    'payload',
    [
        {
            'tenant_id': str(uuid4()),
            'exp': datetime.now(timezone.utc) + timedelta(hours=1),
            'iat': datetime.now(timezone.utc),
            'type': 'access',
            'jti': uuid4().hex,
        },
        {
            'sub': str(uuid4()),
            'exp': datetime.now(timezone.utc) + timedelta(hours=1),
            'iat': datetime.now(timezone.utc),
            'type': 'access',
            'jti': uuid4().hex,
        },
        {
            'sub': '',
            'tenant_id': str(uuid4()),
            'exp': datetime.now(timezone.utc) + timedelta(hours=1),
            'iat': datetime.now(timezone.utc),
            'type': 'access',
            'jti': uuid4().hex,
        },
    ],
)
async def test_authenticate_jwt_rejects_missing_required_claims_before_side_effects(
    mock_container,
    mock_settings,
    payload,
):
    token = _signed_jwt(mock_settings, payload)
    mock_container.db_session_factory = MagicMock(
        side_effect=AssertionError("invalid JWT claims must not open a DB session")
    )

    with patch(
        'qaplatform.api.auth.middleware.JWTService.is_revoked',
        new_callable=AsyncMock,
        side_effect=AssertionError("invalid JWT claims must not check blacklist"),
    ) as is_revoked:
        with pytest.raises(HTTPException) as exc_info:
            await _authenticate_jwt(token, mock_container)

    assert exc_info.value.status_code == 401
    assert exc_info.value.detail == 'Invalid token claims'
    is_revoked.assert_not_awaited()
    mock_container.db_session_factory.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ('overrides', 'leaked_claim'),
    [
        ({'sub': 'not-a-uuid-secret-user'}, 'not-a-uuid-secret-user'),
        ({'tenant_id': 'not-a-uuid-secret-tenant'}, 'not-a-uuid-secret-tenant'),
        ({'role': ['admin-secret-role']}, 'admin-secret-role'),
        ({'jti': ''}, None),
        ({'is_platform_admin': 'true', 'jti': uuid4().hex}, 'true'),
    ],
)
async def test_authenticate_jwt_rejects_malformed_claim_shapes_before_side_effects(
    mock_container,
    mock_settings,
    overrides,
    leaked_claim,
):
    token = _jwt_token(mock_settings, **overrides)
    mock_container.db_session_factory = MagicMock(
        side_effect=AssertionError("malformed JWT claims must not open a DB session")
    )

    with patch(
        'qaplatform.api.auth.middleware.JWTService.is_revoked',
        new_callable=AsyncMock,
        side_effect=AssertionError("malformed JWT claims must not check blacklist"),
    ) as is_revoked:
        with pytest.raises(HTTPException) as exc_info:
            await _authenticate_jwt(token, mock_container)

    assert exc_info.value.status_code == 401
    assert exc_info.value.detail == 'Invalid token claims'
    if leaked_claim is not None:
        assert leaked_claim not in exc_info.value.detail
    is_revoked.assert_not_awaited()
    mock_container.db_session_factory.assert_not_called()


@pytest.mark.asyncio
async def test_authenticate_jwt_rejects_platform_admin_claim_with_non_uuid_subject(
    mock_container,
    mock_settings,
):
    token = _jwt_token(mock_settings, sub='not-a-uuid', is_platform_admin=True)
    mock_container.db_session_factory = MagicMock(
        side_effect=AssertionError("invalid platform-admin subject must not query DB")
    )

    with pytest.raises(HTTPException) as exc_info:
        await _authenticate_jwt(token, mock_container)

    assert exc_info.value.status_code == 401
    assert exc_info.value.detail == 'Invalid token claims'
    mock_container.db_session_factory.assert_not_called()


@pytest.mark.asyncio
async def test_authenticate_jwt_verifies_platform_admin_claim_against_database(
    mock_container, mock_settings
):
    session = AsyncMock()
    session.execute = AsyncMock(
        side_effect=AssertionError("JWT auth must use UserRepository")
    )
    mock_container.db_session_factory = MagicMock(
        return_value=_session_context(session)
    )
    user_repo = AsyncMock()

    user_id = uuid4()
    tenant_id = uuid4()
    user_repo.get_by_id.return_value = _jwt_user_record(
        user_id,
        tenant_id,
        is_platform_admin=True,
    )
    token = _jwt_token(
        mock_settings,
        sub=user_id,
        tenant_id=tenant_id,
        is_platform_admin=True,
    )

    with patch(
        'qaplatform.infra.database.repositories.user_repo.UserRepository',
        return_value=user_repo,
    ):
        user = await _authenticate_jwt(token, mock_container)

    assert user.user_id == str(user_id)
    assert user.is_platform_admin is True
    user_repo.get_by_id.assert_awaited_once_with(user_id)
    session.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_authenticate_jwt_checks_current_user_record_when_database_available(
    mock_container,
    mock_settings,
):
    session = AsyncMock()
    session.execute = AsyncMock(
        side_effect=AssertionError("JWT auth must use UserRepository")
    )
    mock_container.db_session_factory = MagicMock(
        return_value=_session_context(session)
    )
    user_repo = AsyncMock()

    user_id = uuid4()
    tenant_id = uuid4()
    user_repo.get_by_id.return_value = _jwt_user_record(
        user_id,
        tenant_id,
        role='developer',
        is_platform_admin=True,
    )
    token = _jwt_token(
        mock_settings,
        sub=user_id,
        tenant_id=tenant_id,
        role='developer',
        is_platform_admin=False,
    )

    with patch(
        'qaplatform.infra.database.repositories.user_repo.UserRepository',
        return_value=user_repo,
    ):
        user = await _authenticate_jwt(token, mock_container)

    assert user.user_id == str(user_id)
    assert user.tenant_id == str(tenant_id)
    assert user.role == 'developer'
    assert user.is_platform_admin is False
    user_repo.get_by_id.assert_awaited_once_with(user_id)
    session.execute.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    'record_state',
    [
        'missing',
        'inactive',
        'user_deleted',
        'tenant_deleted',
        'tenant_changed',
        'role_changed',
    ],
)
async def test_authenticate_jwt_rejects_stale_user_record_before_returning_current_user(
    mock_container,
    mock_settings,
    record_state,
):
    session = AsyncMock()
    session.execute = AsyncMock(
        side_effect=AssertionError("JWT auth must use UserRepository")
    )
    mock_container.db_session_factory = MagicMock(
        return_value=_session_context(session)
    )
    user_repo = AsyncMock()

    user_id = uuid4()
    tenant_id = uuid4()
    user_record = _jwt_user_record(user_id, tenant_id, role='developer')
    if record_state == 'missing':
        user_record = None
    elif record_state == 'inactive':
        user_record.is_active = False
    elif record_state == 'user_deleted':
        user_record.deleted_at = datetime.now(timezone.utc)
    elif record_state == 'tenant_deleted':
        user_record.tenant.deleted_at = datetime.now(timezone.utc)
    elif record_state == 'tenant_changed':
        user_record.tenant_id = uuid4()
    elif record_state == 'role_changed':
        user_record.role = 'viewer'
    user_repo.get_by_id.return_value = user_record

    token = _jwt_token(
        mock_settings,
        sub=user_id,
        tenant_id=tenant_id,
        role='developer',
    )

    with patch(
        'qaplatform.infra.database.repositories.user_repo.UserRepository',
        return_value=user_repo,
    ):
        with pytest.raises(HTTPException) as exc_info:
            await _authenticate_jwt(token, mock_container)

    assert exc_info.value.status_code == 401
    assert exc_info.value.detail == 'Invalid token'
    user_repo.get_by_id.assert_awaited_once_with(user_id)
    session.execute.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    'raw_token',
    [
        'qap_missing-secret',
        'qap__secret',
        'qap_tokenid_',
        'qap_abc123_secret456',
        'qap_tokid_my_secret_with_underscores',
        f'qap_{"a" * 31}_{API_TOKEN_SECRET}',
        f'qap_{API_TOKEN_ID}_{"b" * 63}',
        f'qap_{"g" * 32}_{API_TOKEN_SECRET}',
        f'qap_{API_TOKEN_ID}_{"g" * 64}',
    ],
)
async def test_authenticate_api_token_rejects_malformed_token_without_database(
    mock_container,
    raw_token,
):
    mock_container.db_session_factory = MagicMock(
        side_effect=AssertionError("malformed API token must not open DB session")
    )

    with pytest.raises(HTTPException) as exc_info:
        await _authenticate_api_token(raw_token, mock_container)

    assert exc_info.value.status_code == 401
    assert exc_info.value.detail == 'Invalid API token format'
    mock_container.db_session_factory.assert_not_called()


@pytest.mark.asyncio
async def test_authenticate_api_token_rejects_when_database_unavailable(mock_container):
    with pytest.raises(HTTPException) as exc_info:
        await _authenticate_api_token(API_BEARER_TOKEN, mock_container)

    assert exc_info.value.status_code == 401
    assert exc_info.value.detail == 'API token authentication not available'


def _api_token_record(**overrides):
    user_deleted_at = overrides.pop('user_deleted_at', None)
    tenant_deleted_at = overrides.pop('tenant_deleted_at', None)
    tenant = SimpleNamespace(deleted_at=tenant_deleted_at)
    user = SimpleNamespace(
        role=overrides.pop('user_role', 'developer'),
        tenant_id=overrides.pop('tenant_id', uuid4()),
        is_platform_admin=overrides.pop('is_platform_admin', False),
        is_active=overrides.pop('user_is_active', True),
        deleted_at=user_deleted_at,
        tenant=tenant,
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
        patch(
            'qaplatform.api.auth.middleware.TokenService.verify_token',
            return_value=True,
        ) as verify_token,
    ):
        started_at = datetime.now(timezone.utc)
        user = await _authenticate_api_token(API_BEARER_TOKEN, mock_container)
        finished_at = datetime.now(timezone.utc)

    assert user == CurrentUser(
        user_id=str(token.user_id),
        role='developer',
        tenant_id=str(token.user.tenant_id),
        is_platform_admin=False,
        scopes=['runs:read', 'runs:write'],
    )
    repo.get_by_token_id.assert_awaited_once_with(API_TOKEN_ID)
    verify_token.assert_called_once_with(API_TOKEN_SECRET, token.secret_hash)
    repo.update_last_used.assert_awaited_once()
    update_args = repo.update_last_used.await_args.args
    assert update_args[0] is token
    assert started_at <= update_args[1] <= finished_at
    assert update_args[1].tzinfo is timezone.utc
    assert repo.update_last_used.await_args.kwargs == {}
    session.commit.assert_awaited_once_with()
    session.rollback.assert_not_awaited()


@pytest.mark.asyncio
async def test_authenticate_api_token_rolls_back_last_used_failure_but_allows_user(
    mock_container,
):
    session = AsyncMock()
    mock_container.db_session_factory = MagicMock(
        return_value=_session_context(session)
    )
    repo = AsyncMock()
    token = _api_token_record(
        secret_hash='stored-secret-hash',
        scopes=['runs:read', 'runs:write'],
    )
    repo.get_by_token_id.return_value = token
    repo.update_last_used.side_effect = RuntimeError('audit write failed')

    with (
        patch('qaplatform.infra.database.repositories.user_repo.ApiTokenRepository', return_value=repo),
        patch(
            'qaplatform.api.auth.middleware.TokenService.verify_token',
            return_value=True,
        ) as verify_token,
    ):
        user = await _authenticate_api_token(API_BEARER_TOKEN, mock_container)

    assert user.role == 'developer'
    assert user.user_id == str(token.user_id)
    assert user.tenant_id == str(token.user.tenant_id)
    assert user.scopes == ['runs:read', 'runs:write']
    repo.get_by_token_id.assert_awaited_once_with(API_TOKEN_ID)
    verify_token.assert_called_once_with(API_TOKEN_SECRET, token.secret_hash)
    repo.update_last_used.assert_awaited_once()
    assert repo.update_last_used.await_args.args[0] is token
    assert repo.update_last_used.await_args.args[1].tzinfo is not None
    assert repo.update_last_used.await_args.kwargs == {}
    session.commit.assert_not_awaited()
    session.rollback.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ('token_record', 'verify_result', 'expected_detail'),
    [
        (None, True, 'Invalid or revoked API token'),
        (_api_token_record(is_revoked=True), True, 'Invalid or revoked API token'),
        (
            _api_token_record(expires_at=datetime.now(timezone.utc) - timedelta(seconds=1)),
            True,
            'API token has expired',
        ),
        (_api_token_record(user_is_active=False), True, 'Invalid or revoked API token'),
        (
            _api_token_record(user_deleted_at=datetime.now(timezone.utc)),
            True,
            'Invalid or revoked API token',
        ),
        (
            _api_token_record(tenant_deleted_at=datetime.now(timezone.utc)),
            True,
            'Invalid or revoked API token',
        ),
        (
            _api_token_record(expires_at=datetime.now(timezone.utc) - timedelta(seconds=1)),
            False,
            'Invalid or revoked API token',
        ),
        (_api_token_record(), False, 'Invalid or revoked API token'),
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
        patch(
            'qaplatform.api.auth.middleware.TokenService.verify_token',
            return_value=verify_result,
        ) as verify_token,
    ):
        with pytest.raises(HTTPException) as exc_info:
            await _authenticate_api_token(API_BEARER_TOKEN, mock_container)

    assert exc_info.value.status_code == 401
    assert exc_info.value.detail == expected_detail
    assert API_TOKEN_ID not in exc_info.value.detail
    assert API_TOKEN_SECRET not in exc_info.value.detail
    assert API_BEARER_TOKEN not in exc_info.value.detail
    repo.get_by_token_id.assert_awaited_once_with(API_TOKEN_ID)
    if token_record is not None and not token_record.is_revoked:
        verify_token.assert_called_once_with(API_TOKEN_SECRET, token_record.secret_hash)
    else:
        verify_token.assert_not_called()
    repo.update_last_used.assert_not_awaited()
    session.commit.assert_not_awaited()
