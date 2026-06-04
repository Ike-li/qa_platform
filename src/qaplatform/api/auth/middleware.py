from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING
from uuid import UUID

from fastapi import Depends, HTTPException, Request, status
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


def _invalid_token_claims_error() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid token claims",
    )


def _required_string_claim(payload: dict, name: str) -> str:
    value = payload.get(name)
    if not isinstance(value, str) or not value:
        raise _invalid_token_claims_error()
    return value


def _validate_uuid_claim(value: str) -> UUID:
    try:
        return UUID(value)
    except ValueError:
        raise _invalid_token_claims_error() from None


async def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> CurrentUser:
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Authorization header",
        )

    token = credentials.credentials
    container = _get_container(request)
    if token.startswith("qap_"):
        return await _authenticate_api_token(token, container)
    return await _authenticate_jwt(token, container)


async def _authenticate_jwt(token: str, container: DependencyContainer) -> CurrentUser:
    settings = container.settings
    import jwt

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

    user_id = _required_string_claim(payload, "sub")
    tenant_id = _required_string_claim(payload, "tenant_id")
    user_uuid = _validate_uuid_claim(user_id)
    _validate_uuid_claim(tenant_id)

    role = payload.get("role", "viewer")
    if not isinstance(role, str) or not role:
        raise _invalid_token_claims_error()

    is_admin_claim = payload.get("is_platform_admin", False)
    if not isinstance(is_admin_claim, bool):
        raise _invalid_token_claims_error()

    # Blacklist check — only when jti is present (old tokens without jti pass through)
    jti = payload.get("jti")
    if jti is not None:
        if not isinstance(jti, str) or not jti:
            raise _invalid_token_claims_error()
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

    is_admin_verified = False
    if container.db_session_factory is not None:
        from qaplatform.infra.database.repositories.user_repo import UserRepository

        async with container.db_session_factory() as session:
            user = await UserRepository(session).get_by_id(user_uuid)

        user_tenant = getattr(user, "tenant", None)
        user_role = getattr(user, "role", None)
        user_tenant_id = getattr(user, "tenant_id", None)
        if (
            user is None
            or not getattr(user, "is_active", False)
            or getattr(user, "deleted_at", None) is not None
            or (
                user_tenant is not None
                and getattr(user_tenant, "deleted_at", None) is not None
            )
            or str(user_tenant_id) != tenant_id
            or not isinstance(user_role, str)
            or not user_role
            or user_role != role
        ):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token",
            )

        # Verify platform-admin privilege against the current database row.
        is_admin_verified = (
            is_admin_claim and bool(getattr(user, "is_platform_admin", False))
        )

    return CurrentUser(
        user_id=user_id,
        role=role,
        tenant_id=tenant_id,
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

        if not TokenService.verify_token(secret, token.secret_hash):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or revoked API token",
            )

        owner = token.user
        owner_tenant = getattr(owner, "tenant", None)
        if (
            owner is None
            or not getattr(owner, "is_active", False)
            or getattr(owner, "deleted_at", None) is not None
            or (
                owner_tenant is not None
                and getattr(owner_tenant, "deleted_at", None) is not None
            )
        ):
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

        # Update last_used_at (best-effort)
        try:
            await api_token_repo.update_last_used(
                token, datetime.now(timezone.utc)
            )
            await session.commit()
        except Exception:
            await session.rollback()

        # Eagerly read ORM relationship attributes before session closes
        user_role = owner.role
        user_tenant_id = str(owner.tenant_id)
        user_is_platform_admin = bool(getattr(owner, "is_platform_admin", False))

    return CurrentUser(
        user_id=str(token.user_id),
        role=user_role,
        tenant_id=user_tenant_id,
        is_platform_admin=user_is_platform_admin,
        scopes=list(token.scopes) if token.scopes is not None else None,
    )


def _get_container(request: Request):
    return request.app.state.container
