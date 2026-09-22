"""Command handlers for auth API workflows."""

from __future__ import annotations

import json
import logging
import secrets
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any
from uuid import UUID

from argon2 import PasswordHasher as _PasswordHasher
from argon2.exceptions import VerifyMismatchError as _VerifyMismatchError
from fastapi import HTTPException, Request, Response, status

from qaplatform.api.auth.permissions import Role
from qaplatform.api.auth.refresh_cookie import (
    _clear_refresh_cookie,
    _raise_refresh_unauthorized_clearing_cookie,
    _refresh_cookie_secure,
    _set_refresh_cookie,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from qaplatform.api.auth.jwt_service import JWTService
    from qaplatform.api.auth.middleware import CurrentUser


log = logging.getLogger(__name__)
_password_hasher = _PasswordHasher()

RepositoryFactory = Callable[[Any], Any]
TokenServiceFactory = Callable[[Any], Any]
ResolveTenantId = Callable[[Any, UUID | None], Awaitable[UUID]]


@dataclass(frozen=True)
class AuthCommandDependencies:
    tenant_repository: RepositoryFactory
    user_repository: RepositoryFactory
    api_token_repository: RepositoryFactory
    audit_event_repository: RepositoryFactory
    token_service: TokenServiceFactory
    resolve_tenant_id: ResolveTenantId


@dataclass(frozen=True)
class LoginCommandResult:
    access_token: str
    user: dict[str, str]


@dataclass(frozen=True)
class TokenPairCommandResult:
    access_token: str


@dataclass(frozen=True)
class ApiTokenCommandResult:
    token_id: str
    token: str | None
    name: str
    scopes: list[str]
    expires_at: datetime
    created_at: datetime


@dataclass(frozen=True)
class ApiTokenListCommandItem:
    token_id: str
    name: str
    scopes: list[str]
    expires_at: datetime
    last_used_at: datetime | None
    is_revoked: bool
    created_at: datetime


@dataclass(frozen=True)
class ApiTokenListCommandResult:
    data: list[ApiTokenListCommandItem]
    page: int
    per_page: int
    total: int


@dataclass(frozen=True)
class SSETicketCommandResult:
    ticket: str


def _client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


def _user_agent(request: Request) -> str | None:
    return request.headers.get("user-agent")


def _login_result_for_user(
    *,
    jwt_svc: JWTService,
    user_id: str,
    username: str,
    email: str,
    role: str,
    tenant_id: str,
    is_platform_admin: bool,
) -> LoginCommandResult:
    access_token = jwt_svc.create_access_token(
        user_id=user_id,
        role=role,
        tenant_id=tenant_id,
        is_platform_admin=is_platform_admin,
    )
    return LoginCommandResult(
        access_token=access_token,
        user={
            "id": user_id,
            "username": username,
            "email": email,
            "role": role,
            "tenant_id": tenant_id,
        },
    )


async def resolve_tenant_id(
    session: AsyncSession,
    tenant_id: UUID | None,
    *,
    tenant_repository: RepositoryFactory,
) -> UUID:
    """Resolve tenant_id for MVP single-tenant fallback."""
    if tenant_id is not None:
        return tenant_id
    tenant = await tenant_repository(session).get_first()
    if tenant is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="No tenant configured",
        )
    return tenant.id


async def register_user_command(
    body: Any,
    *,
    request: Request,
    response: Response,
    jwt_svc: JWTService,
    settings: Any,
    session_factory: async_sessionmaker,
    deps: AuthCommandDependencies,
) -> LoginCommandResult:
    password_hash = _password_hasher.hash(body.password)
    TenantRepository = deps.tenant_repository
    UserRepository = deps.user_repository
    AuditEventRepository = deps.audit_event_repository

    async with session_factory() as session:
        try:
            tenant_repo = TenantRepository(session)
            if await tenant_repo.get_by_name(body.username) is not None:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Username already taken",
                )

            tenant = await tenant_repo.create(name=body.username)
            user = await UserRepository(session).create(
                tenant_id=tenant.id,
                username=body.username,
                email=body.email,
                password_hash=password_hash,
                role=Role.OWNER.value,
            )

            user_id = str(user.id)
            user_tenant_id = str(user.tenant_id)
            user_role = user.role
            user_is_platform_admin = bool(getattr(user, "is_platform_admin", False))
            user_email = user.email
            user_username = user.username

            audit_repo = AuditEventRepository(session)
            await audit_repo.create(
                tenant_id=user.tenant_id,
                user_id=user.id,
                action="auth.register",
                resource_type="auth",
                resource_id=None,
                after_state={"username": body.username, "email": body.email},
                ip_address=_client_ip(request),
                user_agent=_user_agent(request),
            )
            await session.commit()
        except Exception:
            await session.rollback()
            raise

    refresh_token = jwt_svc.create_refresh_token(user_id=user_id)
    _set_refresh_cookie(
        response,
        refresh_token,
        settings.jwt_refresh_token_ttl,
        secure=_refresh_cookie_secure(request, settings),
    )

    return _login_result_for_user(
        jwt_svc=jwt_svc,
        user_id=user_id,
        username=user_username,
        email=user_email,
        role=user_role,
        tenant_id=user_tenant_id,
        is_platform_admin=user_is_platform_admin,
    )


async def login_user_command(
    body: Any,
    *,
    request: Request,
    response: Response,
    jwt_svc: JWTService,
    settings: Any,
    session_factory: async_sessionmaker,
    deps: AuthCommandDependencies,
) -> LoginCommandResult:
    client_ip = _client_ip(request)
    user_agent = _user_agent(request)
    UserRepository = deps.user_repository
    AuditEventRepository = deps.audit_event_repository

    async def _write_failed_audit(
        reason: str,
        *,
        tenant_id: UUID | None = None,
        user_id: UUID | None = None,
    ) -> None:
        async with session_factory() as audit_session:
            try:
                audit_repo = AuditEventRepository(audit_session)
                await audit_repo.create(
                    tenant_id=tenant_id,
                    user_id=user_id,
                    action="auth.login_failed",
                    resource_type="auth",
                    resource_id=None,
                    after_state={"reason": reason, "username": body.username},
                    ip_address=client_ip,
                    user_agent=user_agent,
                )
                await audit_session.commit()
            except Exception:
                await audit_session.rollback()
                log.warning(
                    "audit_write_failed",
                    extra={"action": "auth.login_failed"},
                    exc_info=True,
                )

    async with session_factory() as session:
        try:
            user_repo = UserRepository(session)
            tenant_id = await deps.resolve_tenant_id(session, body.tenant_id)
            user = await user_repo.get_by_username(tenant_id, body.username)

            if user is None:
                await _write_failed_audit("invalid_credentials")
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid credentials",
                )

            if not user.is_active:
                await _write_failed_audit(
                    "account_deactivated", tenant_id=user.tenant_id, user_id=user.id
                )
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Account is deactivated",
                )

            ph = _password_hasher
            try:
                ph.verify(user.password_hash, body.password)
            except _VerifyMismatchError:
                await _write_failed_audit(
                    "invalid_credentials", tenant_id=user.tenant_id, user_id=user.id
                )
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid credentials",
                )

            if ph.check_needs_rehash(user.password_hash):
                user.password_hash = ph.hash(body.password)

            await user_repo.update_last_login(user, datetime.now(timezone.utc))

            audit_repo = AuditEventRepository(session)
            await audit_repo.create(
                tenant_id=user.tenant_id,
                user_id=user.id,
                action="auth.login",
                resource_type="auth",
                resource_id=None,
                after_state={"username": user.username},
                ip_address=client_ip,
                user_agent=user_agent,
            )
            await session.commit()
        except Exception:
            await session.rollback()
            raise

    refresh_token = jwt_svc.create_refresh_token(user_id=str(user.id))
    _set_refresh_cookie(
        response,
        refresh_token,
        settings.jwt_refresh_token_ttl,
        secure=_refresh_cookie_secure(request, settings),
    )

    return _login_result_for_user(
        jwt_svc=jwt_svc,
        user_id=str(user.id),
        username=user.username,
        email=user.email,
        role=user.role,
        tenant_id=str(user.tenant_id),
        is_platform_admin=bool(getattr(user, "is_platform_admin", False)),
    )


async def refresh_tokens_command(
    *,
    request: Request,
    response: Response,
    refresh_token: str | None,
    jwt_svc: JWTService,
    settings: Any,
    session_factory: async_sessionmaker,
    deps: AuthCommandDependencies,
) -> TokenPairCommandResult:
    client_ip = _client_ip(request)
    user_agent = _user_agent(request)
    refresh_cookie_secure = _refresh_cookie_secure(request, settings)
    UserRepository = deps.user_repository
    AuditEventRepository = deps.audit_event_repository

    async def _write_refresh_failed_audit(reason: str) -> None:
        async with session_factory() as audit_session:
            try:
                await AuditEventRepository(audit_session).create(
                    tenant_id=None,
                    user_id=None,
                    action="auth.refresh_failed",
                    resource_type="auth",
                    resource_id=None,
                    after_state={"reason": reason},
                    ip_address=client_ip,
                    user_agent=user_agent,
                )
                await audit_session.commit()
            except Exception:
                await audit_session.rollback()
                log.warning(
                    "audit_write_failed",
                    extra={"action": "auth.refresh_failed"},
                    exc_info=True,
                )

    if refresh_token is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing refresh token",
        )

    try:
        payload = jwt_svc.decode_token(refresh_token)
    except Exception:
        await _write_refresh_failed_audit("invalid_refresh_token")
        _raise_refresh_unauthorized_clearing_cookie(
            response,
            "Invalid refresh token",
            secure=refresh_cookie_secure,
        )

    if payload.get("type") != "refresh":
        await _write_refresh_failed_audit("invalid_token_type")
        _raise_refresh_unauthorized_clearing_cookie(
            response,
            "Invalid token type",
            secure=refresh_cookie_secure,
        )

    old_jti = payload.get("jti")
    if old_jti:
        try:
            revoked = await jwt_svc.is_revoked(old_jti)
        except Exception:
            log.warning(
                "refresh_blacklist_lookup_failed",
                extra={"jti": old_jti},
                exc_info=True,
            )
            revoked = False
        if revoked:
            await _write_refresh_failed_audit("revoked_refresh_token")
            _raise_refresh_unauthorized_clearing_cookie(
                response,
                "Refresh token has been revoked",
                secure=refresh_cookie_secure,
            )

    old_exp = payload.get("exp")
    user_id = payload["sub"]

    async with session_factory() as session:
        try:
            user_repo = UserRepository(session)
            user = await user_repo.get_by_id(UUID(user_id))

            if user is None or not user.is_active:
                _raise_refresh_unauthorized_clearing_cookie(
                    response,
                    "User not found or deactivated",
                    secure=refresh_cookie_secure,
                )

            if old_jti and old_exp:
                ttl = max(0, int(old_exp) - int(time.time()))
                try:
                    await jwt_svc.revoke(old_jti, ttl)
                except Exception:
                    log.warning(
                        "token_revoke_failed",
                        extra={"jti": old_jti},
                        exc_info=True,
                    )

            access_token = jwt_svc.create_access_token(
                user_id=str(user.id),
                role=user.role,
                tenant_id=str(user.tenant_id),
                is_platform_admin=bool(getattr(user, "is_platform_admin", False)),
            )
            new_refresh_token = jwt_svc.create_refresh_token(user_id=str(user.id))
            new_jti = jwt_svc.decode_token(new_refresh_token).get("jti")

            audit_repo = AuditEventRepository(session)
            await audit_repo.create(
                tenant_id=user.tenant_id,
                user_id=user.id,
                action="auth.refresh",
                resource_type="auth",
                resource_id=None,
                before_state={"old_jti": old_jti},
                after_state={"new_jti": new_jti},
                ip_address=client_ip,
                user_agent=user_agent,
            )
            await session.commit()
        except Exception:
            await session.rollback()
            raise

    _set_refresh_cookie(
        response,
        new_refresh_token,
        settings.jwt_refresh_token_ttl,
        secure=refresh_cookie_secure,
    )

    return TokenPairCommandResult(access_token=access_token)


async def _revoke_payload_token(jwt_svc: JWTService, payload: dict[str, Any]) -> None:
    jti = payload.get("jti")
    exp = payload.get("exp")
    if not (jti and exp):
        return

    ttl = max(0, int(exp) - int(time.time()))
    try:
        await jwt_svc.revoke(jti, ttl)
    except Exception:
        log.warning(
            "token_revoke_failed",
            extra={"jti": jti},
            exc_info=True,
        )


def _uuid_from_claim(value: Any) -> UUID | None:
    if not value:
        return None
    try:
        return UUID(value)
    except ValueError:
        return None


async def logout_user_command(
    *,
    request: Request,
    response: Response,
    refresh_token: str | None,
    jwt_svc: JWTService,
    session_factory: async_sessionmaker,
    deps: AuthCommandDependencies,
) -> None:
    client_ip = _client_ip(request)
    user_agent = _user_agent(request)
    auth_header = request.headers.get("authorization", "")
    audit_user_id: UUID | None = None
    audit_tenant_id: UUID | None = None

    if auth_header.lower().startswith("bearer "):
        try:
            payload = jwt_svc.decode_token(auth_header[7:])
            await _revoke_payload_token(jwt_svc, payload)
            audit_user_id = _uuid_from_claim(payload.get("sub"))
            audit_tenant_id = _uuid_from_claim(payload.get("tenant_id"))
        except Exception:
            pass

    if refresh_token:
        try:
            payload = jwt_svc.decode_token(refresh_token)
            await _revoke_payload_token(jwt_svc, payload)
        except Exception:
            pass

    settings = getattr(getattr(request.app.state, "container", None), "settings", None)
    _clear_refresh_cookie(
        response,
        secure=_refresh_cookie_secure(request, settings),
    )

    AuditEventRepository = deps.audit_event_repository
    async with session_factory() as audit_session:
        try:
            await AuditEventRepository(audit_session).create(
                tenant_id=audit_tenant_id,
                user_id=audit_user_id,
                action="auth.logout",
                resource_type="auth",
                resource_id=None,
                after_state={
                    "had_access_token": auth_header.lower().startswith("bearer ")
                },
                ip_address=client_ip,
                user_agent=user_agent,
            )
            await audit_session.commit()
        except Exception:
            await audit_session.rollback()
            log.warning(
                "audit_write_failed",
                extra={"action": "auth.logout"},
                exc_info=True,
            )


async def create_api_token_command(
    body: Any,
    *,
    request: Request,
    current_user: CurrentUser,
    session_factory: async_sessionmaker,
    deps: AuthCommandDependencies,
) -> ApiTokenCommandResult:
    ApiTokenRepository = deps.api_token_repository
    TokenService = deps.token_service
    AuditEventRepository = deps.audit_event_repository

    async with session_factory() as session:
        try:
            api_token_repo = ApiTokenRepository(session)
            token_service = TokenService(api_token_repo)

            expires_at = datetime.now(timezone.utc) + timedelta(days=body.expires_days)
            result = await token_service.create_api_token(
                user_id=UUID(current_user.user_id),
                name=body.name,
                scopes=body.scopes,
                expires_at=expires_at,
            )
            record = result["record"]

            await AuditEventRepository(session).create(
                tenant_id=UUID(current_user.tenant_id),
                user_id=UUID(current_user.user_id),
                action="auth.api_token_create",
                resource_type="auth",
                resource_id=record.id,
                after_state={"name": body.name, "scopes": body.scopes},
                ip_address=_client_ip(request),
                user_agent=_user_agent(request),
            )
            payload = ApiTokenCommandResult(
                token_id=record.token_id,
                token=result["token"],
                name=record.name,
                scopes=record.scopes,
                expires_at=record.expires_at,
                created_at=record.created_at,
            )
            await session.commit()
        except Exception:
            await session.rollback()
            raise

    return payload


async def revoke_api_token_command(
    token_id: str,
    *,
    request: Request,
    current_user: CurrentUser,
    session_factory: async_sessionmaker,
    deps: AuthCommandDependencies,
) -> None:
    ApiTokenRepository = deps.api_token_repository
    AuditEventRepository = deps.audit_event_repository

    async with session_factory() as session:
        try:
            api_token_repo = ApiTokenRepository(session)
            token = await api_token_repo.get_by_token_id(token_id)

            if token is None or str(token.user_id) != current_user.user_id:
                raise HTTPException(status_code=404, detail="Token not found")

            token_name = token.name
            token_db_id = token.id

            await api_token_repo.revoke(token)

            await AuditEventRepository(session).create(
                tenant_id=UUID(current_user.tenant_id),
                user_id=UUID(current_user.user_id),
                action="auth.api_token_revoke",
                resource_type="auth",
                resource_id=token_db_id,
                before_state={"name": token_name},
                ip_address=_client_ip(request),
                user_agent=_user_agent(request),
            )
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def list_api_tokens_command(
    *,
    current_user: CurrentUser,
    session_factory: async_sessionmaker,
    page: int,
    per_page: int,
    deps: AuthCommandDependencies,
) -> ApiTokenListCommandResult:
    ApiTokenRepository = deps.api_token_repository
    async with session_factory() as session:
        api_token_repo = ApiTokenRepository(session)
        tokens, total = await api_token_repo.list_by_user(
            UUID(current_user.user_id),
            offset=(page - 1) * per_page,
            limit=per_page,
        )

    return ApiTokenListCommandResult(
        data=[
            ApiTokenListCommandItem(
                token_id=t.token_id,
                name=t.name,
                scopes=t.scopes,
                expires_at=t.expires_at,
                last_used_at=t.last_used_at,
                is_revoked=t.is_revoked,
                created_at=t.created_at,
            )
            for t in tokens
        ],
        page=page,
        per_page=per_page,
        total=total,
    )


async def create_sse_ticket_command(
    *,
    request: Request,
    current_user: CurrentUser,
    session_factory: async_sessionmaker,
    deps: AuthCommandDependencies,
    ttl_seconds: int,
) -> SSETicketCommandResult:
    redis = request.app.state.container.redis_client
    ticket = secrets.token_urlsafe(32)
    key = f"sse_ticket:{ticket}"
    payload = json.dumps(
        {
            "user_id": current_user.user_id,
            "role": current_user.role,
            "tenant_id": current_user.tenant_id,
            "scopes": current_user.scopes,
        }
    )
    await redis.setex(key, ttl_seconds, payload)

    AuditEventRepository = deps.audit_event_repository
    async with session_factory() as audit_session:
        try:
            await AuditEventRepository(audit_session).create(
                tenant_id=UUID(current_user.tenant_id),
                user_id=UUID(current_user.user_id),
                action="auth.sse_ticket_create",
                resource_type="auth",
                resource_id=None,
                after_state={
                    "ttl_seconds": ttl_seconds,
                    "single_use": True,
                },
                ip_address=_client_ip(request),
                user_agent=_user_agent(request),
            )
            await audit_session.commit()
        except Exception:
            await audit_session.rollback()
            log.warning(
                "audit_write_failed",
                extra={"action": "auth.sse_ticket_create"},
                exc_info=True,
            )
    return SSETicketCommandResult(ticket=ticket)
