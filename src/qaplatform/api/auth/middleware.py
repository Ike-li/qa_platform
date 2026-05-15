from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from qaplatform.api.auth.jwt_service import JWTService
from qaplatform.api.auth.permissions import Action, PermissionContext, check_permission
from qaplatform.api.auth.token_service import TokenService

if TYPE_CHECKING:
    from qaplatform.dependencies import DependencyContainer

_bearer_scheme = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class CurrentUser:
    user_id: str
    role: str
    tenant_id: str


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> CurrentUser:
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Authorization header",
        )

    token = credentials.credentials
    container = _get_container()
    if token.startswith("qap_"):
        return await _authenticate_api_token(token, container)
    return _authenticate_jwt(token, container)


def _authenticate_jwt(token: str, container: DependencyContainer) -> CurrentUser:
    settings = container.settings
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=["HS256"],
        )
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has expired",
        )
    except jwt.InvalidTokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
        )

    if payload.get("type") != "access":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token type",
        )

    return CurrentUser(
        user_id=payload["sub"],
        role=payload.get("role", "viewer"),
        tenant_id=payload["tenant_id"],
    )


async def _authenticate_api_token(
    raw_token: str, container: DependencyContainer
) -> CurrentUser:
    parsed = TokenService.parse_bearer_token(raw_token)
    if parsed is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API token format",
        )

    token_id, secret = parsed
    if container.db_session_factory is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="API token authentication not available",
        )

    async with container.db_session_factory() as session:
        from qaplatform.infra.database.repositories.user_repo import ApiTokenRepository

        api_token_repo = ApiTokenRepository(session)
        token = await api_token_repo.get_by_token_id(token_id)

        if token is None or token.is_revoked:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or revoked API token",
            )

        from datetime import datetime, timezone

        if token.expires_at < datetime.now(timezone.utc):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="API token has expired",
            )

        if not TokenService.verify_token(secret, token.secret_hash):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or revoked API token",
            )

        # Update last_used_at (best-effort)
        try:
            await api_token_repo.update_last_used(
                token, datetime.now(timezone.utc)
            )
            await session.commit()
        except Exception:
            await session.rollback()

    # user is eagerly loaded via relationship
    return CurrentUser(
        user_id=str(token.user_id),
        role=token.user.role,
        tenant_id=str(token.user.tenant_id),
    )


def _get_container():
    from qaplatform.dependencies import get_container

    return get_container()


def require_roles(*roles: str):
    """FastAPI dependency factory: reject if current user's role is not in the allowed set."""

    async def _check(
        current_user: CurrentUser = Depends(get_current_user),
    ) -> CurrentUser:
        if current_user.role not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Role '{current_user.role}' is not allowed",
            )
        return current_user

    return _check


def require_permission(action: Action, is_own_resource: bool = False):
    """FastAPI dependency factory: check RBAC permission."""

    async def _check(
        current_user: CurrentUser = Depends(get_current_user),
    ) -> CurrentUser:
        ctx = PermissionContext(
            user_id=current_user.user_id,
            role=current_user.role,
            tenant_id=current_user.tenant_id,
            is_own_resource=is_own_resource,
        )
        if not check_permission(ctx, action):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Permission denied",
            )
        return current_user

    return _check
