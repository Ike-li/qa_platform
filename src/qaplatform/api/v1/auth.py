from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Annotated
from uuid import UUID

from fastapi import APIRouter, Cookie, Depends, Query, Request, Response
from pydantic import AfterValidator, BaseModel, EmailStr, Field, field_validator

from qaplatform.api import deps as auth_deps
from qaplatform.api.auth.commands import (
    AuthCommandDependencies,
    create_api_token_command,
    create_sse_ticket_command,
    list_api_tokens_command,
    login_user_command,
    logout_user_command,
    refresh_tokens_command,
    register_user_command,
    revoke_api_token_command,
)
from qaplatform.api.auth.commands import (
    resolve_tenant_id as _resolve_tenant_id_command,
)
from qaplatform.api.auth.jwt_service import JWTService
from qaplatform.api.auth.middleware import CurrentUser, get_current_user
from qaplatform.api.auth.refresh_cookie import (
    REFRESH_TOKEN_COOKIE,
)
from qaplatform.api.auth.refresh_cookie import (
    _clear_refresh_cookie as _clear_refresh_cookie,
)
from qaplatform.api.auth.refresh_cookie import (
    _raise_refresh_unauthorized_clearing_cookie as _raise_refresh_unauthorized_clearing_cookie,
)
from qaplatform.api.auth.refresh_cookie import (
    _refresh_cookie_clear_headers as _refresh_cookie_clear_headers,
)
from qaplatform.api.auth.refresh_cookie import (
    _refresh_cookie_secure as _refresh_cookie_secure,
)
from qaplatform.api.auth.refresh_cookie import (
    _set_refresh_cookie as _set_refresh_cookie,
)
from qaplatform.api.auth.token_service import TokenService
from qaplatform.api.schemas import PaginatedResponse
from qaplatform.infra.database.repositories.audit_repo import AuditEventRepository
from qaplatform.infra.database.repositories.user_repo import (
    ApiTokenRepository,
    TenantRepository,
    UserRepository,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


router = APIRouter(prefix="/auth", tags=["auth"])


# --- Request / Response schemas ---

_USERNAME_PATTERN = r"^[a-zA-Z0-9_]+$"


class LoginRequest(BaseModel):
    username: str = Field(min_length=3, max_length=32, pattern=_USERNAME_PATTERN)
    password: str = Field(min_length=1, max_length=128)
    tenant_id: UUID | None = None  # MVP: optional, defaults to first tenant

    @field_validator("password")
    @classmethod
    def _validate_password_not_blank(cls, value: str) -> str:
        if value.strip() == "":
            raise ValueError("login password must not be blank")
        return value


class RegisterRequest(BaseModel):
    username: str = Field(min_length=3, max_length=32, pattern=_USERNAME_PATTERN)
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)

    @field_validator("password")
    @classmethod
    def _validate_password_not_blank(cls, value: str) -> str:
        if value.strip() == "":
            raise ValueError("register password must not be blank")
        return value


class TokenPair(BaseModel):
    access_token: str
    token_type: str = "bearer"


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: dict


def _validate_api_token_scope(scope: str) -> str:
    if scope.strip() == "":
        raise ValueError("api token scope must not be blank")
    return scope


ApiTokenScope = Annotated[
    str,
    Field(min_length=1, max_length=100),
    AfterValidator(_validate_api_token_scope),
]


class CreateTokenRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    scopes: list[ApiTokenScope] = Field(default_factory=lambda: ["*"], max_length=100)
    expires_days: int = Field(default=90, ge=1, le=365)

    @field_validator("name")
    @classmethod
    def _validate_name_not_blank(cls, value: str) -> str:
        if value.strip() == "":
            raise ValueError("api token name must not be blank")
        return value


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


async def _resolve_tenant_id(session: AsyncSession, tenant_id: UUID | None) -> UUID:
    """Resolve tenant_id for MVP (single-tenant fallback)."""
    return await _resolve_tenant_id_command(
        session,
        tenant_id,
        tenant_repository=TenantRepository,
    )


def _auth_command_dependencies() -> AuthCommandDependencies:
    return AuthCommandDependencies(
        tenant_repository=TenantRepository,
        user_repository=UserRepository,
        api_token_repository=ApiTokenRepository,
        audit_event_repository=AuditEventRepository,
        token_service=TokenService,
        resolve_tenant_id=_resolve_tenant_id,
    )


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
    result = await register_user_command(
        body,
        request=request,
        response=response,
        jwt_svc=jwt_svc,
        settings=settings,
        session_factory=session_factory,
        deps=_auth_command_dependencies(),
    )
    return LoginResponse(access_token=result.access_token, user=result.user)


@router.post("/login", response_model=LoginResponse)
async def login(
    body: LoginRequest,
    request: Request,
    response: Response,
    jwt_svc: JWTService = Depends(auth_deps.get_jwt_service),
    settings=Depends(auth_deps.get_settings),
    session_factory: async_sessionmaker = Depends(auth_deps.get_session_factory),
) -> LoginResponse:
    result = await login_user_command(
        body,
        request=request,
        response=response,
        jwt_svc=jwt_svc,
        settings=settings,
        session_factory=session_factory,
        deps=_auth_command_dependencies(),
    )
    return LoginResponse(access_token=result.access_token, user=result.user)


@router.post("/refresh", response_model=TokenPair)
async def refresh(
    request: Request,
    response: Response,
    refresh_token: str | None = Cookie(None, alias=REFRESH_TOKEN_COOKIE),
    jwt_svc: JWTService = Depends(auth_deps.get_jwt_service),
    settings=Depends(auth_deps.get_settings),
    session_factory: async_sessionmaker = Depends(auth_deps.get_session_factory),
) -> TokenPair:
    result = await refresh_tokens_command(
        request=request,
        response=response,
        refresh_token=refresh_token,
        jwt_svc=jwt_svc,
        settings=settings,
        session_factory=session_factory,
        deps=_auth_command_dependencies(),
    )
    return TokenPair(access_token=result.access_token)


@router.post("/logout", status_code=204)
async def logout(
    response: Response,
    request: Request,
    refresh_token: str | None = Cookie(None, alias=REFRESH_TOKEN_COOKIE),
    jwt_svc: JWTService = Depends(auth_deps.get_jwt_service),
    session_factory: async_sessionmaker = Depends(auth_deps.get_session_factory),
) -> None:
    await logout_user_command(
        request=request,
        response=response,
        refresh_token=refresh_token,
        jwt_svc=jwt_svc,
        session_factory=session_factory,
        deps=_auth_command_dependencies(),
    )


@router.post("/tokens", response_model=ApiTokenResponse, status_code=201)
async def create_token(
    body: CreateTokenRequest,
    request: Request,
    current_user: CurrentUser = Depends(get_current_user),
    session_factory: async_sessionmaker = Depends(auth_deps.get_session_factory),
) -> ApiTokenResponse:
    result = await create_api_token_command(
        body,
        request=request,
        current_user=current_user,
        session_factory=session_factory,
        deps=_auth_command_dependencies(),
    )
    return ApiTokenResponse(
        token_id=result.token_id,
        token=result.token,
        name=result.name,
        scopes=result.scopes,
        expires_at=result.expires_at,
        created_at=result.created_at,
    )


@router.delete("/tokens/{token_id}", status_code=204)
async def revoke_token(
    token_id: str,
    request: Request,
    current_user: CurrentUser = Depends(get_current_user),
    session_factory: async_sessionmaker = Depends(auth_deps.get_session_factory),
) -> None:
    await revoke_api_token_command(
        token_id,
        request=request,
        current_user=current_user,
        session_factory=session_factory,
        deps=_auth_command_dependencies(),
    )


@router.get("/tokens", response_model=PaginatedResponse[ApiTokenListItem])
async def list_tokens(
    current_user: CurrentUser = Depends(get_current_user),
    session_factory: async_sessionmaker = Depends(auth_deps.get_session_factory),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
) -> PaginatedResponse[ApiTokenListItem]:
    result = await list_api_tokens_command(
        current_user=current_user,
        session_factory=session_factory,
        page=page,
        per_page=per_page,
        deps=_auth_command_dependencies(),
    )
    return PaginatedResponse(
        data=[
            ApiTokenListItem(
                token_id=item.token_id,
                name=item.name,
                scopes=item.scopes,
                expires_at=item.expires_at,
                last_used_at=item.last_used_at,
                is_revoked=item.is_revoked,
                created_at=item.created_at,
            )
            for item in result.data
        ],
        page=result.page,
        per_page=result.per_page,
        total=result.total,
    )


# --- SSE Ticket ---

SSE_TICKET_TTL = 90  # seconds (increased for slow networks; GETDEL prevents replay)


class SSETicketResponse(BaseModel):
    ticket: str


@router.post("/sse-ticket", response_model=SSETicketResponse)
async def create_sse_ticket(
    request: Request,
    current_user: CurrentUser = Depends(get_current_user),
    session_factory: async_sessionmaker = Depends(auth_deps.get_session_factory),
) -> SSETicketResponse:
    """Issue a short-lived, single-use ticket for SSE authentication."""
    result = await create_sse_ticket_command(
        request=request,
        current_user=current_user,
        session_factory=session_factory,
        deps=_auth_command_dependencies(),
        ttl_seconds=SSE_TICKET_TTL,
    )
    return SSETicketResponse(ticket=result.ticket)
