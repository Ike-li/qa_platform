from __future__ import annotations

import secrets
import time
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING
from uuid import UUID

from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select

from qaplatform.api import deps as auth_deps
from qaplatform.api.auth.jwt_service import JWTService
from qaplatform.api.auth.middleware import CurrentUser, get_current_user
from qaplatform.api.auth.token_service import TokenService
from qaplatform.infra.database.models import AppUser, Tenant
from qaplatform.infra.database.repositories.audit_repo import AuditEventRepository
from qaplatform.infra.database.repositories.user_repo import (
    ApiTokenRepository,
    UserRepository,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

router = APIRouter(prefix="/auth", tags=["auth"])


# --- Request / Response schemas ---


class LoginRequest(BaseModel):
    username: str
    password: str
    tenant_id: UUID | None = None  # MVP: optional, defaults to first tenant


class RegisterRequest(BaseModel):
    username: str = Field(min_length=3, max_length=32, pattern=r"^[a-zA-Z0-9_]+$")
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)


class TokenPair(BaseModel):
    access_token: str
    token_type: str = "bearer"


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: dict


class CreateTokenRequest(BaseModel):
    name: str
    scopes: list[str] = Field(default_factory=lambda: ["*"])
    expires_days: int = 90


class ApiTokenResponse(BaseModel):
    token_id: str
    token: str | None = None
    name: str
    scopes: list[str]
    expires_at: datetime
    created_at: datetime


class ApiTokenListItem(BaseModel):
    token_id: str
    name: str
    scopes: list[str]
    expires_at: datetime
    last_used_at: datetime | None
    is_revoked: bool
    created_at: datetime


# --- Helpers ---


REFRESH_TOKEN_COOKIE = "refresh_token"


def _set_refresh_cookie(response: Response, token: str, max_age: int) -> None:
    response.set_cookie(
        key=REFRESH_TOKEN_COOKIE,
        value=token,
        httponly=True,
        secure=True,
        samesite="strict",
        max_age=max_age,
        path="/api/v1/auth",
    )


def _clear_refresh_cookie(response: Response) -> None:
    response.delete_cookie(
        key=REFRESH_TOKEN_COOKIE,
        httponly=True,
        secure=True,
        samesite="strict",
        path="/api/v1/auth",
    )


async def _resolve_tenant_id(
    session: AsyncSession, tenant_id: UUID | None
) -> UUID:
    """Resolve tenant_id for MVP (single-tenant fallback)."""
    if tenant_id is not None:
        return tenant_id
    result = await session.execute(select(Tenant).limit(1))
    tenant = result.scalar_one_or_none()
    if tenant is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="No tenant configured",
        )
    return tenant.id


# --- Routes ---


@router.post("/register", response_model=LoginResponse, status_code=201)
async def register(
    body: RegisterRequest,
    request: Request,
    response: Response,
    jwt_svc: JWTService = Depends(auth_deps.get_jwt_service),
    settings=Depends(auth_deps.get_settings),
    session_factory: async_sessionmaker = Depends(auth_deps.get_session_factory),
) -> LoginResponse:
    """Self-service registration: create a new tenant and its first owner.

    Each registration provisions an isolated workspace (one tenant per user).
    The registrant becomes that tenant's Owner; cross-tenant super-user
    privileges are gated separately via ``app_user.is_platform_admin``.
    """
    from argon2 import PasswordHasher

    ph = PasswordHasher()
    password_hash = ph.hash(body.password)

    async with session_factory() as session:
        try:
            existing_tenant = await session.execute(
                select(Tenant).where(Tenant.name == body.username)
            )
            if existing_tenant.scalar_one_or_none() is not None:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Username already taken",
                )

            tenant = Tenant(name=body.username)
            session.add(tenant)
            await session.flush()

            user = AppUser(
                tenant_id=tenant.id,
                username=body.username,
                email=body.email,
                password_hash=password_hash,
                role="owner",
            )
            session.add(user)
            await session.flush()

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
                ip_address=request.client.host if request.client else None,
                user_agent=request.headers.get("user-agent"),
            )
            await session.commit()
        except Exception:
            await session.rollback()
            raise

    access_token = jwt_svc.create_access_token(
        user_id=user_id,
        role=user_role,
        tenant_id=user_tenant_id,
        is_platform_admin=user_is_platform_admin,
    )
    refresh_token = jwt_svc.create_refresh_token(user_id=user_id)
    _set_refresh_cookie(response, refresh_token, settings.jwt_refresh_token_ttl)

    return LoginResponse(
        access_token=access_token,
        user={
            "id": user_id,
            "username": user_username,
            "email": user_email,
            "role": user_role,
            "tenant_id": user_tenant_id,
        },
    )


@router.post("/login", response_model=LoginResponse)
async def login(
    body: LoginRequest,
    request: Request,
    response: Response,
    jwt_svc: JWTService = Depends(auth_deps.get_jwt_service),
    settings=Depends(auth_deps.get_settings),
    session_factory: async_sessionmaker = Depends(auth_deps.get_session_factory),
) -> LoginResponse:
    from argon2 import PasswordHasher
    from argon2.exceptions import VerifyMismatchError

    client_ip = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent")

    async def _write_failed_audit(
        reason: str,
        *,
        tenant_id: UUID | None = None,
        user_id: UUID | None = None,
    ) -> None:
        """Write a login_failed audit in an independent session (failure path)."""
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
                raise

    async with session_factory() as session:
        try:
            user_repo = UserRepository(session)
            tenant_id = await _resolve_tenant_id(session, body.tenant_id)
            user: AppUser | None = await user_repo.get_by_username(tenant_id, body.username)

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

            ph = PasswordHasher()
            try:
                ph.verify(user.password_hash, body.password)
            except VerifyMismatchError:
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

    access_token = jwt_svc.create_access_token(
        user_id=str(user.id),
        role=user.role,
        tenant_id=str(user.tenant_id),
        is_platform_admin=bool(getattr(user, "is_platform_admin", False)),
    )
    refresh_token = jwt_svc.create_refresh_token(user_id=str(user.id))
    _set_refresh_cookie(response, refresh_token, settings.jwt_refresh_token_ttl)

    return LoginResponse(
        access_token=access_token,
        user={
            "id": str(user.id),
            "username": user.username,
            "email": user.email,
            "role": user.role,
            "tenant_id": str(user.tenant_id),
        },
    )


@router.post("/refresh", response_model=TokenPair)
async def refresh(
    request: Request,
    response: Response,
    refresh_token: str | None = Cookie(None, alias=REFRESH_TOKEN_COOKIE),
    jwt_svc: JWTService = Depends(auth_deps.get_jwt_service),
    settings=Depends(auth_deps.get_settings),
    session_factory: async_sessionmaker = Depends(auth_deps.get_session_factory),
) -> TokenPair:
    client_ip = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent")

    if refresh_token is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing refresh token",
        )

    try:
        payload = jwt_svc.decode_token(refresh_token)
    except Exception:
        _clear_refresh_cookie(response)
        async with session_factory() as audit_session:
            try:
                await AuditEventRepository(audit_session).create(
                    tenant_id=None,
                    user_id=None,
                    action="auth.refresh_failed",
                    resource_type="auth",
                    after_state={"reason": "invalid_refresh_token"},
                    ip_address=client_ip,
                    user_agent=user_agent,
                )
                await audit_session.commit()
            except Exception:
                await audit_session.rollback()
                raise
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid refresh token",
        )

    if payload.get("type") != "refresh":
        _clear_refresh_cookie(response)
        async with session_factory() as audit_session:
            try:
                await AuditEventRepository(audit_session).create(
                    tenant_id=None,
                    user_id=None,
                    action="auth.refresh_failed",
                    resource_type="auth",
                    after_state={"reason": "invalid_token_type"},
                    ip_address=client_ip,
                    user_agent=user_agent,
                )
                await audit_session.commit()
            except Exception:
                await audit_session.rollback()
                raise
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token type",
        )

    # Revoke the old refresh token so it cannot be reused
    old_jti = payload.get("jti")
    old_exp = payload.get("exp")
    if old_jti and old_exp:
        ttl = max(0, int(old_exp) - int(time.time()))
        await jwt_svc.revoke(old_jti, ttl)

    user_id = payload["sub"]

    async with session_factory() as session:
        try:
            user_repo = UserRepository(session)
            user: AppUser | None = await user_repo.get_by_id(UUID(user_id))

            if user is None or not user.is_active:
                _clear_refresh_cookie(response)
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="User not found or deactivated",
                )

            new_jti_placeholder = None
            audit_repo = AuditEventRepository(session)
            await audit_repo.create(
                tenant_id=user.tenant_id,
                user_id=user.id,
                action="auth.refresh",
                resource_type="auth",
                before_state={"old_jti": old_jti},
                after_state={"new_jti": new_jti_placeholder},
                ip_address=client_ip,
                user_agent=user_agent,
            )
            await session.commit()
        except Exception:
            await session.rollback()
            raise

    access_token = jwt_svc.create_access_token(
        user_id=str(user.id),
        role=user.role,
        tenant_id=str(user.tenant_id),
        is_platform_admin=bool(getattr(user, "is_platform_admin", False)),
    )
    new_refresh_token = jwt_svc.create_refresh_token(user_id=str(user.id))
    _set_refresh_cookie(response, new_refresh_token, settings.jwt_refresh_token_ttl)

    return TokenPair(
        access_token=access_token,
    )


@router.post("/logout", status_code=204)
async def logout(
    response: Response,
    request: Request,
    refresh_token: str | None = Cookie(None, alias=REFRESH_TOKEN_COOKIE),
    jwt_svc: JWTService = Depends(auth_deps.get_jwt_service),
    session_factory: async_sessionmaker = Depends(auth_deps.get_session_factory),
) -> None:
    client_ip = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent")

    audit_user_id: UUID | None = None
    audit_tenant_id: UUID | None = None

    auth_header = request.headers.get("authorization", "")
    if auth_header.lower().startswith("bearer "):
        try:
            payload = jwt_svc.decode_token(auth_header[7:])
            jti = payload.get("jti")
            exp = payload.get("exp")
            if jti and exp:
                ttl = max(0, int(exp) - int(time.time()))
                await jwt_svc.revoke(jti, ttl)
            sub = payload.get("sub")
            tid = payload.get("tenant_id")
            if sub:
                try:
                    audit_user_id = UUID(sub)
                except ValueError:
                    pass
            if tid:
                try:
                    audit_tenant_id = UUID(tid)
                except ValueError:
                    pass
        except Exception:
            pass

    if refresh_token:
        try:
            payload = jwt_svc.decode_token(refresh_token)
            jti = payload.get("jti")
            exp = payload.get("exp")
            if jti and exp:
                ttl = max(0, int(exp) - int(time.time()))
                await jwt_svc.revoke(jti, ttl)
        except Exception:
            pass

    _clear_refresh_cookie(response)

    async with session_factory() as audit_session:
        try:
            await AuditEventRepository(audit_session).create(
                tenant_id=audit_tenant_id,
                user_id=audit_user_id,
                action="auth.logout",
                resource_type="auth",
                after_state={"had_access_token": auth_header.lower().startswith("bearer ")},
                ip_address=client_ip,
                user_agent=user_agent,
            )
            await audit_session.commit()
        except Exception:
            await audit_session.rollback()
            raise


@router.post("/tokens", response_model=ApiTokenResponse, status_code=201)
async def create_token(
    body: CreateTokenRequest,
    request: Request,
    current_user: CurrentUser = Depends(get_current_user),
    session_factory: async_sessionmaker = Depends(auth_deps.get_session_factory),
) -> ApiTokenResponse:
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
                ip_address=request.client.host if request.client else None,
                user_agent=request.headers.get("user-agent"),
            )
            await session.commit()
        except Exception:
            await session.rollback()
            raise

    return ApiTokenResponse(
        token_id=record.token_id,
        token=result["token"],
        name=record.name,
        scopes=record.scopes,
        expires_at=record.expires_at,
        created_at=record.created_at,
    )


@router.delete("/tokens/{token_id}", status_code=204)
async def revoke_token(
    token_id: str,
    request: Request,
    current_user: CurrentUser = Depends(get_current_user),
    session_factory: async_sessionmaker = Depends(auth_deps.get_session_factory),
) -> None:
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
                ip_address=request.client.host if request.client else None,
                user_agent=request.headers.get("user-agent"),
            )
            await session.commit()
        except Exception:
            await session.rollback()
            raise


@router.get("/tokens", response_model=list[ApiTokenListItem])
async def list_tokens(
    current_user: CurrentUser = Depends(get_current_user),
    session_factory: async_sessionmaker = Depends(auth_deps.get_session_factory),
) -> list[ApiTokenListItem]:
    async with session_factory() as session:
        api_token_repo = ApiTokenRepository(session)
        tokens, _ = await api_token_repo.list_by_user(UUID(current_user.user_id))

    return [
        ApiTokenListItem(
            token_id=t.token_id,
            name=t.name,
            scopes=t.scopes,
            expires_at=t.expires_at,
            last_used_at=t.last_used_at,
            is_revoked=t.is_revoked,
            created_at=t.created_at,
        )
        for t in tokens
    ]


# --- SSE Ticket ---

SSE_TICKET_TTL = 90  # seconds (increased for slow networks; GETDEL prevents replay)


class SSETicketResponse(BaseModel):
    ticket: str


@router.post("/sse-ticket", response_model=SSETicketResponse)
async def create_sse_ticket(
    request: Request,
    current_user: CurrentUser = Depends(get_current_user),
) -> SSETicketResponse:
    """Issue a short-lived, single-use ticket for SSE authentication."""
    redis = request.app.state.container.redis_client
    ticket = secrets.token_urlsafe(32)
    key = f"sse_ticket:{ticket}"
    payload = f"{current_user.user_id}:{current_user.role}:{current_user.tenant_id}"
    await redis.setex(key, SSE_TICKET_TTL, payload)
    return SSETicketResponse(ticket=ticket)
