from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING
from uuid import UUID

from fastapi import APIRouter, Cookie, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from qaplatform.api.auth.jwt_service import JWTService
from qaplatform.api.auth.middleware import CurrentUser, get_current_user
from qaplatform.api.auth.token_service import TokenService
from qaplatform.infra.database.models import AppUser, Tenant
from qaplatform.infra.database.repositories.user_repo import (
    ApiTokenRepository,
    UserRepository,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from qaplatform.dependencies import DependencyContainer

router = APIRouter(prefix="/auth", tags=["auth"])


# --- Request / Response schemas ---


class LoginRequest(BaseModel):
    username: str
    password: str
    tenant_id: UUID | None = None  # MVP: optional, defaults to first tenant


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


def _get_container() -> DependencyContainer:
    from qaplatform.dependencies import get_container

    return get_container()


def _get_jwt_service() -> JWTService:
    return JWTService(_get_container().settings)


def _get_session_factory():
    container = _get_container()
    if container.db_session_factory is None:
        raise HTTPException(status_code=503, detail="Database not initialized")
    return container.db_session_factory


@asynccontextmanager
async def _new_session():
    """Yield a new AsyncSession, committing on success and rolling back on error."""
    factory = _get_session_factory()
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


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


@router.post("/login", response_model=LoginResponse)
async def login(body: LoginRequest, response: Response) -> LoginResponse:
    async with _new_session() as session:
        user_repo = UserRepository(session)
        tenant_id = await _resolve_tenant_id(session, body.tenant_id)
        user: AppUser | None = await user_repo.get_by_username(tenant_id, body.username)

        if user is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid credentials",
            )

        if not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Account is deactivated",
            )

        from argon2 import PasswordHasher
        from argon2.exceptions import VerifyMismatchError

        ph = PasswordHasher()
        try:
            ph.verify(user.password_hash, body.password)
        except VerifyMismatchError:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid credentials",
            )

        if ph.check_needs_rehash(user.password_hash):
            user.password_hash = ph.hash(body.password)

        await user_repo.update_last_login(user, datetime.now(timezone.utc))

    jwt_svc = _get_jwt_service()
    settings = _get_container().settings
    access_token = jwt_svc.create_access_token(
        user_id=str(user.id),
        role=user.role,
        tenant_id=str(user.tenant_id),
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
    response: Response,
    refresh_token: str | None = Cookie(None, alias=REFRESH_TOKEN_COOKIE),
) -> TokenPair:
    if refresh_token is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing refresh token",
        )

    jwt_svc = _get_jwt_service()
    settings = _get_container().settings
    try:
        payload = jwt_svc.decode_token(refresh_token)
    except Exception:
        _clear_refresh_cookie(response)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid refresh token",
        )

    if payload.get("type") != "refresh":
        _clear_refresh_cookie(response)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token type",
        )

    user_id = payload["sub"]

    async with _new_session() as session:
        user_repo = UserRepository(session)
        user: AppUser | None = await user_repo.get_by_id(UUID(user_id))

        if user is None or not user.is_active:
            _clear_refresh_cookie(response)
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="User not found or deactivated",
            )

    access_token = jwt_svc.create_access_token(
        user_id=str(user.id),
        role=user.role,
        tenant_id=str(user.tenant_id),
    )
    new_refresh_token = jwt_svc.create_refresh_token(user_id=str(user.id))
    _set_refresh_cookie(response, new_refresh_token, settings.jwt_refresh_token_ttl)

    return TokenPair(
        access_token=access_token,
    )


@router.post("/logout", status_code=204)
async def logout(response: Response) -> None:
    _clear_refresh_cookie(response)


@router.post("/tokens", response_model=ApiTokenResponse, status_code=201)
async def create_token(
    body: CreateTokenRequest,
    current_user: CurrentUser = Depends(get_current_user),
) -> ApiTokenResponse:
    async with _new_session() as session:
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
    current_user: CurrentUser = Depends(get_current_user),
) -> None:
    async with _new_session() as session:
        api_token_repo = ApiTokenRepository(session)
        token = await api_token_repo.get_by_token_id(token_id)

        if token is None or str(token.user_id) != current_user.user_id:
            raise HTTPException(status_code=404, detail="Token not found")

        await api_token_repo.revoke(token)


@router.get("/tokens", response_model=list[ApiTokenListItem])
async def list_tokens(
    current_user: CurrentUser = Depends(get_current_user),
) -> list[ApiTokenListItem]:
    async with _new_session() as session:
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
