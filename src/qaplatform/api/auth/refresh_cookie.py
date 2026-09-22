"""Refresh-token cookie helpers."""

from __future__ import annotations

from fastapi import HTTPException, Request, Response, status

REFRESH_TOKEN_COOKIE = "refresh_token"
_LOCAL_HTTP_COOKIE_HOSTS = {"localhost", "127.0.0.1", "::1"}


def _refresh_cookie_secure(request: Request, settings: object | None = None) -> bool:
    configured = getattr(settings, "refresh_cookie_secure", None)
    if isinstance(configured, bool):
        return configured

    if request.url.scheme != "http":
        return True

    host = request.url.hostname or ""
    is_local_http = host in _LOCAL_HTTP_COOKIE_HOSTS
    is_development = (
        getattr(settings, "debug", False) is True
        or getattr(settings, "environment", None) == "development"
    )
    return not (is_local_http and is_development)


def _set_refresh_cookie(
    response: Response,
    token: str,
    max_age: int,
    *,
    secure: bool = True,
) -> None:
    response.set_cookie(
        key=REFRESH_TOKEN_COOKIE,
        value=token,
        httponly=True,
        secure=secure,
        samesite="strict",
        max_age=max_age,
        path="/api/v1/auth",
    )


def _clear_refresh_cookie(response: Response, *, secure: bool = True) -> None:
    response.delete_cookie(
        key=REFRESH_TOKEN_COOKIE,
        httponly=True,
        secure=secure,
        samesite="strict",
        path="/api/v1/auth",
    )


def _refresh_cookie_clear_headers(*, secure: bool = True) -> dict[str, str]:
    clear_response = Response()
    _clear_refresh_cookie(clear_response, secure=secure)
    return {"Set-Cookie": clear_response.headers["set-cookie"]}


def _raise_refresh_unauthorized_clearing_cookie(
    response: Response,
    detail: str,
    *,
    secure: bool = True,
) -> None:
    _clear_refresh_cookie(response, secure=secure)
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers=_refresh_cookie_clear_headers(secure=secure),
    )
