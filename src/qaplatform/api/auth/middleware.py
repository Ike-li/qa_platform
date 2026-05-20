from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from qaplatform.api.auth.jwt_service import JWTService
from qaplatform.api.auth.token_service import TokenService

if TYPE_CHECKING:
    from qaplatform.dependencies import DependencyContainer

_bearer_scheme = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class CurrentUser:
    user_id: str
    role: str
    tenant_id: str
    is_platform_admin: bool = False
    scopes: list[str] | None = None


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
    return await _authenticate_jwt(token, container)


async def _authenticate_jwt(token: str, container: DependencyContainer) -> CurrentUser:
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

    # Blacklist check — only when jti is present (old tokens without jti pass through)
    jti = payload.get("jti")
    if jti is not None:
        from qaplatform.api.auth.jwt_service import JWTService
        import logging

        jwt_svc = JWTService(settings, redis=container.redis_client)
        try:
            revoked = await jwt_svc.is_revoked(jti)
        except Exception:
            # P1 fail-open: Redis blip must not 500 the request.
            # Fail-open prevents site-wide outage when Redis is degraded.
            # Trade-off: revoked tokens may pass through during Redis failure window
            # (max window = max(redis_downtime, token_ttl), typically acceptable).
            logger = logging.getLogger(__name__)
            logger.warning(
                "jwt_blacklist_lookup_failed",
                extra={"jti": jti},
                exc_info=True,
            )
            revoked = False
        if revoked:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token has been revoked",
            )

    # Verify is_platform_admin against database to handle stale tokens
    is_admin_claim = bool(payload.get("is_platform_admin", False))
    is_admin_verified = False
    if is_admin_claim and container.db_session_factory is not None:
        from sqlalchemy import select
        from qaplatform.infra.database.models import AppUser

        async with container.db_session_factory() as session:
            result = await session.execute(
                select(AppUser.is_platform_admin).where(AppUser.id == payload["sub"])
            )
            row = result.scalar_one_or_none()
            is_admin_verified = bool(row) if row is not None else False

    return CurrentUser(
        user_id=payload["sub"],
        role=payload.get("role", "viewer"),
        tenant_id=payload["tenant_id"],
        is_platform_admin=is_admin_verified,
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
        is_platform_admin=bool(getattr(token.user, "is_platform_admin", False)),
        scopes=list(token.scopes) if token.scopes else None,
    )


def _get_container():
    from qaplatform.dependencies import get_container

    return get_container()
