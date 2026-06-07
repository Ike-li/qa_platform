"""Real backend integration coverage for auth tokens, run results, and artifacts.

These tests intentionally exercise production wiring where it matters:

* JWT login -> API token creation -> API-token authenticated request -> revoke.
* Run result filtering and uniqueness against PostgreSQL constraints.
* Artifact soft-delete visibility through both repository and API paths.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone
import json
import logging
import os
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_INTEGRATION_TESTS") != "1",
    reason="set RUN_INTEGRATION_TESTS=1 to run integration tests",
)


def _assert_integrity_constraint(error: IntegrityError, constraint: str) -> None:
    haystack = " ".join(
        str(part)
        for part in (
            error,
            getattr(error, "orig", ""),
            repr(getattr(error, "orig", "")),
        )
    )
    assert constraint in haystack


def _json_datetime(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def _parse_sse_events(text: str) -> list[dict[str, str]]:
    events: list[dict[str, str]] = []
    for block in text.replace("\r\n", "\n").strip().split("\n\n"):
        if not block:
            continue
        event: dict[str, str] = {}
        data_lines: list[str] = []
        for line in block.split("\n"):
            if not line or line.startswith(":"):
                continue
            field, _, value = line.partition(":")
            if value.startswith(" "):
                value = value[1:]
            if field == "data":
                data_lines.append(value)
            else:
                event[field] = value
        if data_lines:
            event["data"] = "\n".join(data_lines)
        events.append(event)
    return events


def _decode_redis_entry(data: dict) -> dict:
    return {
        key.decode() if isinstance(key, bytes) else key: (
            value.decode() if isinstance(value, bytes) else value
        )
        for key, value in data.items()
    }


def _assert_token_revoke_warning(caplog, jti: str) -> None:
    records = [
        record
        for record in caplog.records
        if record.name == "qaplatform.api.auth.commands"
        and record.levelno == logging.WARNING
        and getattr(record, "jti", None) == jti
    ]
    assert [
        {
            "message": record.getMessage(),
            "jti": getattr(record, "jti", None),
            "exc_type": type(record.exc_info[1]) if record.exc_info else None,
            "exc_message": str(record.exc_info[1]) if record.exc_info else None,
        }
        for record in records
    ] == [
        {
            "message": "token_revoke_failed",
            "jti": jti,
            "exc_type": RuntimeError,
            "exc_message": "redis revoke unavailable",
        }
    ]


@pytest_asyncio.fixture
async def real_auth_app(test_settings, integration_db_schema):
    """FastAPI app with real auth dependencies and no current-user override."""
    from qaplatform.api import create_app
    from qaplatform.dependencies import init_container
    from qaplatform.plugins.registry import PluginRegistry

    settings = test_settings.model_copy(
        update={
            # This file intentionally registers multiple real users in one ASGI app.
            # Keep rate-limit middleware enabled, but avoid suite-order 429 noise.
            "rate_limit_auth_failure": 100,
            "rate_limit_auth_failure_window": 1,
        }
    )

    container = init_container(settings)
    await container.init_db()
    await container.init_redis()
    container.init_crypto()

    plugin_registry = PluginRegistry()
    plugin_registry.register_builtins()
    container.plugin_registry = plugin_registry

    app = create_app(container=container, settings=settings)
    app.state.container = container

    yield app

    app.dependency_overrides.clear()
    await container.close()


@pytest_asyncio.fixture
async def real_auth_client(real_auth_app):
    transport = ASGITransport(app=real_auth_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


async def _register_real_user(real_auth_client, prefix: str = "api_token") -> str:
    suffix = uuid4().hex[:8]
    username = f"{prefix}_{suffix}"
    password = "correct-horse-battery"

    register_resp = await real_auth_client.post(
        "/api/v1/auth/register",
        json={
            "username": username,
            "email": f"{username}@example.com",
            "password": password,
        },
    )
    assert register_resp.status_code == 201, register_resp.text
    return register_resp.json()["access_token"]


async def _create_real_api_token(
    real_auth_client,
    access_token: str,
    *,
    name: str,
    scopes: list[str],
) -> str:
    create_resp = await real_auth_client.post(
        "/api/v1/auth/tokens",
        headers={"Authorization": f"Bearer {access_token}"},
        json={"name": name, "scopes": scopes, "expires_days": 7},
    )
    assert create_resp.status_code == 201, create_resp.text
    return create_resp.json()["token"]


def _refresh_cookie(real_auth_client) -> str:
    cookie = real_auth_client.cookies.get("refresh_token")
    assert cookie
    return cookie


async def _create_project_environment_and_pipeline(
    real_auth_client,
    access_token: str,
) -> dict:
    suffix = uuid4().hex[:8]
    headers = {"Authorization": f"Bearer {access_token}"}

    project_resp = await real_auth_client.post(
        "/api/v1/projects",
        headers=headers,
        json={
            "name": f"scope-project-{suffix}",
            "slug": f"scope-project-{suffix}",
            "git_url": "https://example.com/scope-project.git",
            "default_branch": "main",
        },
    )
    assert project_resp.status_code == 201, project_resp.text
    project = project_resp.json()

    env_resp = await real_auth_client.post(
        f"/api/v1/projects/{project['id']}/environments",
        headers=headers,
        json={
            "name": "default",
            "base_image": "python:3.12-alpine",
            "memory_mb": 128,
            "cpu_cores": 0.5,
            "network_policy": "deny",
            "env_vars": {},
        },
    )
    assert env_resp.status_code == 201, env_resp.text

    pipeline_resp = await real_auth_client.post(
        f"/api/v1/projects/{project['id']}/pipelines",
        headers=headers,
        json={
            "name": "scope-pipeline",
            "stages": [
                {
                    "name": "run-tests",
                    "plugin": "pytest",
                    "phase": "execute",
                    "config": {},
                }
            ],
            "trigger_config": {"type": "manual"},
            "timeout_seconds": 120,
        },
    )
    assert pipeline_resp.status_code == 201, pipeline_resp.text

    return {
        "project_id": project["id"],
        "environment_id": env_resp.json()["id"],
        "pipeline_id": pipeline_resp.json()["id"],
    }


class _NoSuchKey(Exception):
    response = {"Error": {"Code": "NoSuchKey"}}


class _MemoryBody:
    def __init__(self, data: bytes) -> None:
        self._data = data

    async def read(self) -> bytes:
        return self._data


class _MemoryS3:
    def __init__(self) -> None:
        self.objects: dict[tuple[str, str], bytes] = {}
        self.presign_calls: list[dict] = []
        self.get_calls: list[dict] = []

    async def put_object(self, *, Bucket, Key, Body, **_kwargs):
        if hasattr(Body, "read"):
            data = Body.read()
            if hasattr(data, "__await__"):
                data = await data
        else:
            data = Body
        if isinstance(data, str):
            data = data.encode("utf-8")
        self.objects[(Bucket, Key)] = bytes(data)

    async def get_object(self, *, Bucket, Key):
        self.get_calls.append({"bucket": Bucket, "key": Key})
        try:
            data = self.objects[(Bucket, Key)]
        except KeyError:
            raise _NoSuchKey(Key)
        return {"Body": _MemoryBody(data)}

    async def generate_presigned_url(self, method, *, Params, ExpiresIn):
        self.presign_calls.append(
            {"method": method, "params": Params, "expires_in": ExpiresIn}
        )
        return f"http://s3.local/{Params['Key']}?expires={ExpiresIn}"

    async def __aexit__(self, *_args):
        return None


class _FailingS3:
    def __init__(self) -> None:
        self.put_calls: list[dict] = []

    async def put_object(self, *, Bucket, Key, Body, **_kwargs):
        self.put_calls.append({"bucket": Bucket, "key": Key})
        raise RuntimeError("s3 upload unavailable")


class _FlakyOnceS3(_MemoryS3):
    def __init__(self) -> None:
        super().__init__()
        self.failures_remaining = 1
        self.put_calls: list[dict] = []

    async def put_object(self, *, Bucket, Key, Body, **kwargs):
        self.put_calls.append({"bucket": Bucket, "key": Key})
        if self.failures_remaining:
            self.failures_remaining -= 1
            raise RuntimeError("s3 transient outage")
        await super().put_object(Bucket=Bucket, Key=Key, Body=Body, **kwargs)


@pytest.mark.asyncio
async def test_real_jwt_created_api_token_authenticates_updates_last_used_and_revokes(
    real_auth_client,
    integration_db_session,
):
    from qaplatform.api.auth.token_service import TokenService
    from qaplatform.infra.database.models import ApiToken, AuditEvent

    suffix = uuid4().hex[:8]
    username = f"api_token_{suffix}"
    password = "correct-horse-battery"

    register_resp = await real_auth_client.post(
        "/api/v1/auth/register",
        json={
            "username": username,
            "email": f"{username}@example.com",
            "password": password,
        },
    )
    assert register_resp.status_code == 201, register_resp.text
    access_token = register_resp.json()["access_token"]

    create_resp = await real_auth_client.post(
        "/api/v1/auth/tokens",
        headers={"Authorization": f"Bearer {access_token}"},
        json={"name": "ci-smoke", "scopes": ["project.read"], "expires_days": 7},
    )
    assert create_resp.status_code == 201, create_resp.text
    created = create_resp.json()
    full_api_token = created["token"]
    parsed = TokenService.parse_bearer_token(full_api_token)
    assert parsed is not None
    token_id, secret = parsed
    assert token_id == created["token_id"]

    record = (
        await integration_db_session.execute(
            select(ApiToken).where(ApiToken.token_id == token_id)
        )
    ).scalar_one()
    assert record.name == "ci-smoke"
    assert record.scopes == ["project.read"]
    assert record.secret_hash != secret
    assert TokenService.verify_token(secret, record.secret_hash)
    assert record.last_used_at is None

    token_auth_resp = await real_auth_client.get(
        "/api/v1/projects",
        headers={"Authorization": f"Bearer {full_api_token}"},
    )
    assert token_auth_resp.status_code == 200, token_auth_resp.text

    await integration_db_session.refresh(record)
    assert record.last_used_at is not None

    revoke_resp = await real_auth_client.delete(
        f"/api/v1/auth/tokens/{token_id}",
        headers={"Authorization": f"Bearer {access_token}"},
    )
    assert revoke_resp.status_code == 204, revoke_resp.text
    assert revoke_resp.content == b""

    await integration_db_session.refresh(record)
    assert record.is_revoked is True

    rejected_resp = await real_auth_client.get(
        "/api/v1/projects",
        headers={"Authorization": f"Bearer {full_api_token}"},
    )
    assert rejected_resp.status_code == 401, rejected_resp.text
    assert rejected_resp.json() == {"detail": "Invalid or revoked API token"}

    create_audit = (
        await integration_db_session.execute(
            select(AuditEvent).where(
                AuditEvent.user_id == record.user_id,
                AuditEvent.resource_id == record.id,
                AuditEvent.action == "auth.api_token_create",
            )
        )
    ).scalar_one()
    revoke_audit = (
        await integration_db_session.execute(
            select(AuditEvent).where(
                AuditEvent.user_id == record.user_id,
                AuditEvent.resource_id == record.id,
                AuditEvent.action == "auth.api_token_revoke",
            )
        )
    ).scalar_one()

    assert create_audit.resource_type == "auth"
    assert create_audit.before_state is None
    assert create_audit.after_state == {"name": "ci-smoke", "scopes": ["project.read"]}
    assert revoke_audit.resource_type == "auth"
    assert revoke_audit.before_state == {"name": "ci-smoke"}
    assert revoke_audit.after_state is None

    serialized_audit = repr(
        (
            create_audit.before_state,
            create_audit.after_state,
            revoke_audit.before_state,
            revoke_audit.after_state,
        )
    )
    assert full_api_token not in serialized_audit
    assert secret not in serialized_audit
    assert record.secret_hash not in serialized_audit


@pytest.mark.asyncio
async def test_auth_token_routes_require_authorization_without_side_effects(
    real_auth_client,
    integration_db_session,
):
    from qaplatform.infra.database.models import ApiToken, AuditEvent

    token_count_before = (
        await integration_db_session.execute(select(func.count()).select_from(ApiToken))
    ).scalar_one()
    audit_count_before = (
        await integration_db_session.execute(
            select(func.count())
            .select_from(AuditEvent)
            .where(
                AuditEvent.action.in_(
                    ["auth.api_token_create", "auth.api_token_revoke"]
                )
            )
        )
    ).scalar_one()

    responses = [
        await real_auth_client.post(
            "/api/v1/auth/tokens",
            json={"name": "unauth-token", "scopes": ["project.read"]},
        ),
        await real_auth_client.get("/api/v1/auth/tokens"),
        await real_auth_client.delete("/api/v1/auth/tokens/missing-token"),
    ]

    assert [
        {"status_code": response.status_code, "body": response.json()}
        for response in responses
    ] == [
        {
            "status_code": 401,
            "body": {"detail": "Missing Authorization header"},
        },
        {
            "status_code": 401,
            "body": {"detail": "Missing Authorization header"},
        },
        {
            "status_code": 401,
            "body": {"detail": "Missing Authorization header"},
        },
    ]
    token_count_after = (
        await integration_db_session.execute(select(func.count()).select_from(ApiToken))
    ).scalar_one()
    audit_count_after = (
        await integration_db_session.execute(
            select(func.count())
            .select_from(AuditEvent)
            .where(
                AuditEvent.action.in_(
                    ["auth.api_token_create", "auth.api_token_revoke"]
                )
            )
        )
    ).scalar_one()
    assert token_count_after == token_count_before
    assert audit_count_after == audit_count_before


@pytest.mark.asyncio
async def test_auth_tokens_list_is_paginated(real_auth_client):
    suffix = uuid4().hex[:8]
    username = f"api_token_page_{suffix}"
    password = "correct-horse-battery"

    register_resp = await real_auth_client.post(
        "/api/v1/auth/register",
        json={
            "username": username,
            "email": f"{username}@example.com",
            "password": password,
        },
    )
    assert register_resp.status_code == 201, register_resp.text
    access_token = register_resp.json()["access_token"]

    token_names = [f"ci-page-{idx}-{suffix}" for idx in range(3)]
    created_tokens = []
    for name in token_names:
        create_resp = await real_auth_client.post(
            "/api/v1/auth/tokens",
            headers={"Authorization": f"Bearer {access_token}"},
            json={"name": name, "scopes": ["project.read"], "expires_days": 7},
        )
        assert create_resp.status_code == 201, create_resp.text
        token_body = create_resp.json()
        created_tokens.append(
            {
                "token_id": token_body["token_id"],
                "name": token_body["name"],
                "scopes": token_body["scopes"],
                "expires_at": token_body["expires_at"],
                "last_used_at": None,
                "is_revoked": False,
                "created_at": token_body["created_at"],
            }
        )

    page_resp = await real_auth_client.get(
        "/api/v1/auth/tokens",
        headers={"Authorization": f"Bearer {access_token}"},
        params={"page": 2, "per_page": 2},
    )
    assert page_resp.status_code == 200, page_resp.text
    page_body = page_resp.json()
    assert page_body == {
        "data": [created_tokens[0]],
        "page": 2,
        "per_page": 2,
        "total": 3,
    }
    empty_resp = await real_auth_client.get(
        "/api/v1/auth/tokens",
        headers={"Authorization": f"Bearer {access_token}"},
        params={"page": 99, "per_page": 2},
    )
    assert empty_resp.status_code == 200, empty_resp.text
    empty_body = empty_resp.json()
    assert empty_body == {
        "data": [],
        "page": 99,
        "per_page": 2,
        "total": 3,
    }


@pytest.mark.asyncio
async def test_audit_events_api_token_requires_audit_read_scope_without_self_audit_on_denial(
    real_auth_app,
    real_auth_client,
    integration_db_session,
):
    from uuid import UUID

    from qaplatform.api.auth.jwt_service import JWTService
    from qaplatform.infra.database.models import AuditEvent

    access_token = await _register_real_user(real_auth_client, prefix="audit_scope")
    payload = JWTService(real_auth_app.state.container.settings).decode_token(
        access_token
    )
    tenant_id = UUID(payload["tenant_id"])
    user_id = UUID(payload["sub"])
    resource_id = uuid4()
    action = f"audit.scope_probe.{uuid4().hex}"

    audit_event = AuditEvent(
        tenant_id=tenant_id,
        user_id=user_id,
        action=action,
        resource_type="project",
        resource_id=resource_id,
        before_state=None,
        after_state={"marker": action},
    )
    integration_db_session.add(audit_event)
    await integration_db_session.commit()
    await integration_db_session.refresh(audit_event)

    async def count_self_audits() -> int:
        result = await integration_db_session.execute(
            select(func.count())
            .select_from(AuditEvent)
            .where(
                AuditEvent.tenant_id == tenant_id,
                AuditEvent.user_id == user_id,
                AuditEvent.action == "audit_events.list",
                AuditEvent.resource_type == "audit_event",
            )
        )
        return result.scalar_one()

    params = {
        "action": action,
        "resource_type": "project",
        "resource_id": str(resource_id),
        "page": 1,
        "per_page": 10,
    }
    run_read_token = await _create_real_api_token(
        real_auth_client,
        access_token,
        name="audit-run-read-denied",
        scopes=["run.read"],
    )
    project_read_token = await _create_real_api_token(
        real_auth_client,
        access_token,
        name="audit-project-read-denied",
        scopes=["project.read"],
    )
    empty_scope_token = await _create_real_api_token(
        real_auth_client,
        access_token,
        name="audit-empty-scope-denied",
        scopes=[],
    )
    audit_read_token = await _create_real_api_token(
        real_auth_client,
        access_token,
        name="audit-read-allowed",
        scopes=["audit.read"],
    )

    before_self_audits = await count_self_audits()
    denied_tokens = (
        ("run.read", run_read_token),
        ("project.read", project_read_token),
        ("empty scope", empty_scope_token),
    )
    for label, denied_token in denied_tokens:
        denied_resp = await real_auth_client.get(
            "/api/v1/audit-events",
            headers={"Authorization": f"Bearer {denied_token}"},
            params=params,
        )
        assert denied_resp.status_code == 403, f"{label}: {denied_resp.text}"
        assert denied_resp.json() == {"detail": "Insufficient permissions"}
        assert action not in denied_resp.text, label
        assert str(resource_id) not in denied_resp.text, label

    assert await count_self_audits() == before_self_audits

    allowed_resp = await real_auth_client.get(
        "/api/v1/audit-events",
        headers={"Authorization": f"Bearer {audit_read_token}"},
        params=params,
    )
    assert allowed_resp.status_code == 200, allowed_resp.text
    body = allowed_resp.json()
    assert body == {
        "data": [
            {
                "id": str(audit_event.id),
                "tenant_id": str(tenant_id),
                "user_id": str(user_id),
                "action": action,
                "resource_type": "project",
                "resource_id": str(resource_id),
                "before_state": None,
                "after_state": {"marker": action},
                "ip_address": None,
                "user_agent": None,
                "created_at": audit_event.created_at.isoformat().replace(
                    "+00:00",
                    "Z",
                ),
            }
        ],
        "page": 1,
        "per_page": 10,
        "total": 1,
    }
    assert await count_self_audits() == before_self_audits + 1
    self_audit = (
        await integration_db_session.execute(
            select(AuditEvent)
            .where(
                AuditEvent.tenant_id == tenant_id,
                AuditEvent.user_id == user_id,
                AuditEvent.action == "audit_events.list",
                AuditEvent.resource_type == "audit_event",
            )
            .order_by(AuditEvent.created_at.desc())
            .limit(1)
        )
    ).scalar_one()
    assert self_audit.after_state == {
        "actor_id": None,
        "action": action,
        "resource_type": "project",
        "resource_id": str(resource_id),
        "start_at": None,
        "end_at": None,
        "page": 1,
        "per_page": 10,
        "total": 1,
    }


@pytest.mark.asyncio
async def test_auth_refresh_logout_audits_do_not_store_tokens_or_passwords(
    real_auth_app,
    real_auth_client,
    integration_db_session,
):
    from uuid import UUID

    from qaplatform.api.auth.jwt_service import JWTService
    from qaplatform.infra.database.models import AuditEvent

    suffix = uuid4().hex[:8]
    username = f"audit_secret_{suffix}"
    email = f"{username}@example.com"
    password = f"password-not-in-audit-{suffix}"

    register_resp = await real_auth_client.post(
        "/api/v1/auth/register",
        json={
            "username": username,
            "email": email,
            "password": password,
        },
    )
    assert register_resp.status_code == 201, register_resp.text
    access_token = register_resp.json()["access_token"]
    first_refresh_token = _refresh_cookie(real_auth_client)

    jwt_svc = JWTService(real_auth_app.state.container.settings)
    access_payload = jwt_svc.decode_token(access_token)
    user_id = UUID(access_payload["sub"])
    tenant_id = UUID(access_payload["tenant_id"])

    refresh_resp = await real_auth_client.post(
        "/api/v1/auth/refresh",
        headers={"Cookie": f"refresh_token={first_refresh_token}"},
    )
    assert refresh_resp.status_code == 200, refresh_resp.text
    refreshed_access_token = refresh_resp.json()["access_token"]
    second_refresh_token = _refresh_cookie(real_auth_client)
    assert second_refresh_token != first_refresh_token

    logout_resp = await real_auth_client.post(
        "/api/v1/auth/logout",
        headers={
            "Authorization": f"Bearer {refreshed_access_token}",
            "Cookie": f"refresh_token={second_refresh_token}",
        },
    )
    assert logout_resp.status_code == 204, logout_resp.text
    assert logout_resp.content == b""

    audits = (
        await integration_db_session.execute(
            select(AuditEvent).where(
                AuditEvent.user_id == user_id,
                AuditEvent.action.in_(
                    ["auth.register", "auth.refresh", "auth.logout"]
                ),
            )
        )
    ).scalars().all()
    audits_by_action = {audit.action: audit for audit in audits}

    assert Counter(audit.action for audit in audits) == Counter(
        {
            "auth.register": 1,
            "auth.refresh": 1,
            "auth.logout": 1,
        }
    )
    register_audit = audits_by_action["auth.register"]
    refresh_audit = audits_by_action["auth.refresh"]
    logout_audit = audits_by_action["auth.logout"]

    assert register_audit.tenant_id == tenant_id
    assert register_audit.after_state == {"username": username, "email": email}
    assert refresh_audit.tenant_id == tenant_id
    assert refresh_audit.before_state is not None
    old_refresh_jti = refresh_audit.before_state.get("old_jti")
    assert refresh_audit.before_state == {"old_jti": old_refresh_jti}
    assert old_refresh_jti
    assert refresh_audit.after_state is not None
    new_refresh_jti = refresh_audit.after_state.get("new_jti")
    assert refresh_audit.after_state == {"new_jti": new_refresh_jti}
    assert new_refresh_jti
    assert new_refresh_jti != old_refresh_jti
    assert logout_audit.tenant_id == tenant_id
    assert logout_audit.after_state == {"had_access_token": True}

    serialized_audit = repr(
        [
            (
                audit.before_state,
                audit.after_state,
            )
            for audit in audits
        ]
    )
    for secret in [
        password,
        access_token,
        first_refresh_token,
        refreshed_access_token,
        second_refresh_token,
    ]:
        assert secret not in serialized_audit


@pytest.mark.asyncio
async def test_real_sse_ticket_writes_audit_without_storing_ticket(
    real_auth_client,
    integration_db_session,
):
    from qaplatform.infra.database.models import AuditEvent

    access_token = await _register_real_user(real_auth_client, prefix="sse_audit")

    resp = await real_auth_client.post(
        "/api/v1/auth/sse-ticket",
        headers={"Authorization": f"Bearer {access_token}"},
    )

    assert resp.status_code == 200, resp.text
    ticket = resp.json()["ticket"]
    assert ticket

    audit = (
        await integration_db_session.execute(
            select(AuditEvent)
            .where(AuditEvent.action == "auth.sse_ticket_create")
            .order_by(AuditEvent.created_at.desc())
            .limit(1)
        )
    ).scalar_one()
    assert audit.after_state == {"ttl_seconds": 90, "single_use": True}
    assert ticket not in str(audit.after_state)


@pytest.mark.asyncio
async def test_refresh_survives_refresh_token_revoke_outage(
    real_auth_app,
    real_auth_client,
    monkeypatch,
    caplog,
):
    """Refresh must issue a new token even if blacklist Redis has a blip."""
    from qaplatform.api.auth.jwt_service import JWTService

    access_token = await _register_real_user(real_auth_client, prefix="refresh_revoke")
    jwt_svc = JWTService(real_auth_app.state.container.settings)
    user_id = jwt_svc.decode_token(access_token)["sub"]
    refresh_token = jwt_svc.create_refresh_token(user_id)
    old_refresh_payload = jwt_svc.decode_token(refresh_token)
    old_jti = old_refresh_payload["jti"]
    real_auth_client.cookies.set(
        "refresh_token",
        refresh_token,
        path="/api/v1/auth",
    )
    redis = real_auth_app.state.container.redis_client

    revoke_spy = AsyncMock(side_effect=RuntimeError("redis revoke unavailable"))
    monkeypatch.setattr(redis, "set", revoke_spy)
    caplog.set_level(logging.WARNING, logger="qaplatform.api.auth.commands")

    resp = await real_auth_client.post("/api/v1/auth/refresh")

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["access_token"]
    assert body["token_type"] == "bearer"
    revoke_spy.assert_awaited_once()
    assert revoke_spy.await_args.args == (f"jwt:revoked:{old_jti}", "1")
    (revoke_expires_in,) = revoke_spy.await_args.kwargs.values()
    assert revoke_spy.await_args.kwargs == {"ex": revoke_expires_in}
    assert 1 <= revoke_expires_in <= (
        real_auth_app.state.container.settings.jwt_refresh_token_ttl
    )
    _assert_token_revoke_warning(caplog, old_jti)


@pytest.mark.asyncio
async def test_real_sse_logs_resume_after_last_event_id_uses_ticket_rbac_and_redis(
    real_auth_app,
    real_auth_client,
):
    from qaplatform.engine.events import publish_status_event
    from qaplatform.engine.log_stream import LogStream
    from qaplatform.infra.database.models import RunStatusEnum

    access_token = await _register_real_user(real_auth_client, prefix="sse_resume")
    stack = await _create_project_environment_and_pipeline(real_auth_client, access_token)

    trigger_resp = await real_auth_client.post(
        "/api/v1/runs",
        headers={"Authorization": f"Bearer {access_token}"},
        json={"pipeline_id": stack["pipeline_id"], "git_ref": "main"},
    )
    assert trigger_resp.status_code == 201, trigger_resp.text
    run_id = trigger_resp.json()["id"]

    redis = real_auth_app.state.container.redis_client
    stream = LogStream(redis)
    first_line = f"resume-before-{uuid4().hex}"
    second_line = f"resume-after-{uuid4().hex}"
    await stream.write_log(run_id, first_line, stream="stdout")
    await stream.write_log(run_id, second_line, stream="stderr")
    entries = await stream.read_logs(run_id, count=10)
    assert [entry["line"] for entry in entries] == [first_line, second_line]

    await publish_status_event(
        redis,
        run_id,
        RunStatusEnum.DONE.value,
        previous=RunStatusEnum.RUNNING.value,
    )

    run_read_token = await _create_real_api_token(
        real_auth_client,
        access_token,
        name="sse-run-read",
        scopes=["run.read"],
    )
    empty_scope_token = await _create_real_api_token(
        real_auth_client,
        access_token,
        name="sse-empty-scope",
        scopes=[],
    )

    missing_ticket_resp = await real_auth_client.get(f"/api/v1/runs/{run_id}/logs")
    assert missing_ticket_resp.status_code == 401, missing_ticket_resp.text
    assert missing_ticket_resp.json() == {"detail": "Invalid or expired SSE ticket"}

    ticket_resp = await real_auth_client.post(
        "/api/v1/auth/sse-ticket",
        headers={"Authorization": f"Bearer {access_token}"},
    )
    assert ticket_resp.status_code == 200, ticket_resp.text
    ticket = ticket_resp.json()["ticket"]

    resume_resp = await real_auth_client.get(
        f"/api/v1/runs/{run_id}/logs?ticket={ticket}",
        headers={"Last-Event-ID": entries[0]["id"]},
    )
    assert resume_resp.status_code == 200, resume_resp.text
    assert "text/event-stream" in resume_resp.headers.get("content-type", "")
    log_events = _parse_sse_events(resume_resp.text)
    expected_log_frames = [
        {
            "event": "log",
            "id": entries[1]["id"],
            "data": {"stream": "stderr", "line": second_line},
        },
        {"event": "done", "id": None, "data": {"status": "done"}},
    ]
    assert [
        {
            "event": event["event"],
            "id": event.get("id"),
            "data": json.loads(event["data"]),
        }
        for event in log_events
    ] == expected_log_frames

    reuse_resp = await real_auth_client.get(
        f"/api/v1/runs/{run_id}/logs?ticket={ticket}",
        headers={"Last-Event-ID": entries[0]["id"]},
    )
    assert reuse_resp.status_code == 401, reuse_resp.text
    assert reuse_resp.json() == {"detail": "Invalid or expired SSE ticket"}

    run_read_ticket_resp = await real_auth_client.post(
        "/api/v1/auth/sse-ticket",
        headers={"Authorization": f"Bearer {run_read_token}"},
    )
    assert run_read_ticket_resp.status_code == 200, run_read_ticket_resp.text
    run_read_resp = await real_auth_client.get(
        f"/api/v1/runs/{run_id}/logs?ticket={run_read_ticket_resp.json()['ticket']}",
        headers={"Last-Event-ID": entries[0]["id"]},
    )
    assert run_read_resp.status_code == 200, run_read_resp.text
    run_read_events = _parse_sse_events(run_read_resp.text)
    assert [
        {
            "event": event["event"],
            "id": event.get("id"),
            "data": json.loads(event["data"]),
        }
        for event in run_read_events
    ] == expected_log_frames

    empty_ticket_resp = await real_auth_client.post(
        "/api/v1/auth/sse-ticket",
        headers={"Authorization": f"Bearer {empty_scope_token}"},
    )
    assert empty_ticket_resp.status_code == 200, empty_ticket_resp.text
    empty_resp = await real_auth_client.get(
        f"/api/v1/runs/{run_id}/logs?ticket={empty_ticket_resp.json()['ticket']}",
        headers={"Last-Event-ID": entries[0]["id"]},
    )
    assert empty_resp.status_code == 403, empty_resp.text
    assert empty_resp.json() == {"detail": "Insufficient permissions"}


@pytest.mark.asyncio
async def test_real_sse_events_resume_after_last_event_id_uses_ticket_rbac_and_redis(
    real_auth_app,
    real_auth_client,
):
    from qaplatform.engine.events import EVENT_STREAM_KEY, publish_status_event

    access_token = await _register_real_user(real_auth_client, prefix="sse_events")
    stack = await _create_project_environment_and_pipeline(real_auth_client, access_token)

    trigger_resp = await real_auth_client.post(
        "/api/v1/runs",
        headers={"Authorization": f"Bearer {access_token}"},
        json={"pipeline_id": stack["pipeline_id"], "git_ref": "main"},
    )
    assert trigger_resp.status_code == 201, trigger_resp.text
    run_id = trigger_resp.json()["id"]

    redis = real_auth_app.state.container.redis_client
    await publish_status_event(redis, run_id, "running", previous="preparing")
    await publish_status_event(redis, run_id, "done", previous="running")
    events = await redis.xrange(EVENT_STREAM_KEY.format(run_id=run_id))
    event_payloads = [_decode_redis_entry(data) for _event_id, data in events]
    assert [
        {
            "run_id": payload["run_id"],
            "status": payload["status"],
            "previous": payload["previous"],
        }
        for payload in event_payloads
    ] == [
        {
            "run_id": run_id,
            "status": "running",
            "previous": "preparing",
        },
        {
            "run_id": run_id,
            "status": "done",
            "previous": "running",
        },
    ]
    assert [bool(payload["timestamp"]) for payload in event_payloads] == [True, True]
    first_event_id = events[0][0]
    second_event_id = events[1][0]

    ticket_resp = await real_auth_client.post(
        "/api/v1/auth/sse-ticket",
        headers={"Authorization": f"Bearer {access_token}"},
    )
    assert ticket_resp.status_code == 200, ticket_resp.text
    ticket = ticket_resp.json()["ticket"]

    resume_resp = await real_auth_client.get(
        f"/api/v1/runs/{run_id}/events?ticket={ticket}",
        headers={"Last-Event-ID": first_event_id},
    )
    assert resume_resp.status_code == 200, resume_resp.text
    assert "text/event-stream" in resume_resp.headers.get("content-type", "")
    sse_events = _parse_sse_events(resume_resp.text)
    expected_sse_frames = [
        {
            "event": "status_change",
            "id": second_event_id,
            "data": {
                "run_id": run_id,
                "status": "done",
                "previous": "running",
                "timestamp": event_payloads[1]["timestamp"],
            },
        },
        {"event": "done", "id": None, "data": {"status": "done"}},
    ]
    assert [
        {
            "event": event["event"],
            "id": event.get("id"),
            "data": json.loads(event["data"]),
        }
        for event in sse_events
    ] == expected_sse_frames

    reuse_resp = await real_auth_client.get(
        f"/api/v1/runs/{run_id}/events?ticket={ticket}",
        headers={"Last-Event-ID": first_event_id},
    )
    assert reuse_resp.status_code == 401, reuse_resp.text
    assert reuse_resp.json() == {"detail": "Invalid or expired SSE ticket"}


@pytest.mark.asyncio
async def test_archived_logs_api_replays_s3_jsonl_after_real_rbac(
    real_auth_app,
    real_auth_client,
):
    from qaplatform.engine.log_stream import LogStream

    access_token = await _register_real_user(real_auth_client, prefix="log_archive")
    stack = await _create_project_environment_and_pipeline(real_auth_client, access_token)

    trigger_resp = await real_auth_client.post(
        "/api/v1/runs",
        headers={"Authorization": f"Bearer {access_token}"},
        json={"pipeline_id": stack["pipeline_id"], "git_ref": "main"},
    )
    assert trigger_resp.status_code == 201, trigger_resp.text
    run_id = trigger_resp.json()["id"]

    s3 = _MemoryS3()
    real_auth_app.state.container.s3_client = s3
    stream = LogStream(real_auth_app.state.container.redis_client)
    for index in range(5):
        await stream.write_log(
            run_id,
            f"archived-line-{index}",
            stream="stderr" if index == 3 else "stdout",
        )

    archived = await stream.archive_logs(
        run_id,
        s3,
        real_auth_app.state.container.settings.s3_bucket,
    )
    assert archived is True

    replay_resp = await real_auth_client.get(
        f"/api/v1/runs/{run_id}/logs/archive",
        headers={"Authorization": f"Bearer {access_token}"},
    )

    assert replay_resp.status_code == 200, replay_resp.text
    body = replay_resp.json()
    assert body == {
        "data": [
            {"stream": "stdout", "line": "archived-line-0"},
            {"stream": "stdout", "line": "archived-line-1"},
            {"stream": "stdout", "line": "archived-line-2"},
            {"stream": "stderr", "line": "archived-line-3"},
            {"stream": "stdout", "line": "archived-line-4"},
        ],
        "page": 1,
        "per_page": 100,
        "total": 5,
    }

    page_resp = await real_auth_client.get(
        f"/api/v1/runs/{run_id}/logs/archive",
        headers={"Authorization": f"Bearer {access_token}"},
        params={"page": 2, "per_page": 2},
    )
    assert page_resp.status_code == 200, page_resp.text
    page_body = page_resp.json()
    assert page_body == {
        "data": [
            {"stream": "stdout", "line": "archived-line-2"},
            {"stream": "stderr", "line": "archived-line-3"},
        ],
        "page": 2,
        "per_page": 2,
        "total": 5,
    }


@pytest.mark.asyncio
async def test_archived_logs_api_replays_large_page_without_presign_after_real_rbac(
    real_auth_app,
    real_auth_client,
):
    access_token = await _register_real_user(real_auth_client, prefix="log_large_page")
    stack = await _create_project_environment_and_pipeline(real_auth_client, access_token)

    trigger_resp = await real_auth_client.post(
        "/api/v1/runs",
        headers={"Authorization": f"Bearer {access_token}"},
        json={"pipeline_id": stack["pipeline_id"], "git_ref": "main"},
    )
    assert trigger_resp.status_code == 201, trigger_resp.text
    run_id = trigger_resp.json()["id"]

    entries = [
        {
            "stream": "stderr" if index % 97 == 0 else "stdout",
            "line": f"archived-large-line-{index:04}",
        }
        for index in range(1500)
    ]
    archive_body = "\n".join(json.dumps(entry) for entry in entries).encode("utf-8")

    s3 = _MemoryS3()
    bucket = real_auth_app.state.container.settings.s3_bucket
    old_s3 = real_auth_app.state.container.s3_client
    real_auth_app.state.container.s3_client = s3
    try:
        await s3.put_object(
            Bucket=bucket,
            Key=f"logs/{run_id}.jsonl",
            Body=archive_body,
            ContentType="application/x-ndjson",
        )

        replay_resp = await real_auth_client.get(
            f"/api/v1/runs/{run_id}/logs/archive",
            headers={"Authorization": f"Bearer {access_token}"},
            params={"page": 15, "per_page": 100},
        )
    finally:
        real_auth_app.state.container.s3_client = old_s3

    assert replay_resp.status_code == 200, replay_resp.text
    body = replay_resp.json()
    assert body == {
        "data": entries[1400:1500],
        "page": 15,
        "per_page": 100,
        "total": 1500,
    }
    assert s3.get_calls == [{"bucket": bucket, "key": f"logs/{run_id}.jsonl"}]
    assert s3.presign_calls == []


@pytest.mark.asyncio
async def test_archived_logs_api_token_requires_run_read_scope(
    real_auth_app,
    real_auth_client,
):
    from qaplatform.engine.log_stream import LogStream

    access_token = await _register_real_user(
        real_auth_client,
        prefix="log_scope",
    )
    stack = await _create_project_environment_and_pipeline(real_auth_client, access_token)

    trigger_resp = await real_auth_client.post(
        "/api/v1/runs",
        headers={"Authorization": f"Bearer {access_token}"},
        json={"pipeline_id": stack["pipeline_id"], "git_ref": "main"},
    )
    assert trigger_resp.status_code == 201, trigger_resp.text
    run_id = trigger_resp.json()["id"]

    s3 = _MemoryS3()
    real_auth_app.state.container.s3_client = s3
    stream = LogStream(real_auth_app.state.container.redis_client)
    for index in range(3):
        await stream.write_log(run_id, f"scope-line-{index}", stream="stdout")

    archived = await stream.archive_logs(
        run_id,
        s3,
        real_auth_app.state.container.settings.s3_bucket,
    )
    assert archived is True

    project_read_token = await _create_real_api_token(
        real_auth_client,
        access_token,
        name="log-project-read-only",
        scopes=["project.read"],
    )
    empty_scope_token = await _create_real_api_token(
        real_auth_client,
        access_token,
        name="log-empty-scope",
        scopes=[],
    )
    denied_tokens = (
        ("project.read", project_read_token),
        ("empty scope", empty_scope_token),
    )
    for label, denied_token in denied_tokens:
        denied_resp = await real_auth_client.get(
            f"/api/v1/runs/{run_id}/logs/archive",
            headers={"Authorization": f"Bearer {denied_token}"},
        )
        assert denied_resp.status_code == 403, f"{label}: {denied_resp.text}"
        assert denied_resp.json() == {"detail": "Insufficient permissions"}
        assert f"logs/{run_id}.jsonl" not in denied_resp.text, label
        assert "scope-line-" not in denied_resp.text, label
    assert s3.get_calls == []
    assert s3.presign_calls == []

    run_read_token = await _create_real_api_token(
        real_auth_client,
        access_token,
        name="log-run-read",
        scopes=["run.read"],
    )
    allowed_resp = await real_auth_client.get(
        f"/api/v1/runs/{run_id}/logs/archive",
        headers={"Authorization": f"Bearer {run_read_token}"},
        params={"page": 1, "per_page": 2},
    )
    assert allowed_resp.status_code == 200, allowed_resp.text
    body = allowed_resp.json()
    assert body["total"] == 3
    assert body["per_page"] == 2
    assert body["data"] == [
        {"stream": "stdout", "line": "scope-line-0"},
        {"stream": "stdout", "line": "scope-line-1"},
    ]
    assert s3.get_calls == [
        {
            "bucket": real_auth_app.state.container.settings.s3_bucket,
            "key": f"logs/{run_id}.jsonl",
        }
    ]
    assert s3.presign_calls == []


@pytest.mark.asyncio
async def test_run_read_token_replays_logs_and_presigns_artifact_without_extra_s3_reads(
    real_auth_app,
    real_auth_client,
    integration_db_session,
):
    from qaplatform.engine.log_stream import LogStream
    from qaplatform.infra.database.repositories.run_repo import ArtifactRepository

    access_token = await _register_real_user(
        real_auth_client,
        prefix="run_read_bundle",
    )
    stack = await _create_project_environment_and_pipeline(real_auth_client, access_token)

    trigger_resp = await real_auth_client.post(
        "/api/v1/runs",
        headers={"Authorization": f"Bearer {access_token}"},
        json={"pipeline_id": stack["pipeline_id"], "git_ref": "main"},
    )
    assert trigger_resp.status_code == 201, trigger_resp.text
    run_id = trigger_resp.json()["id"]

    s3 = _MemoryS3()
    bucket = real_auth_app.state.container.settings.s3_bucket
    stream = LogStream(real_auth_app.state.container.redis_client)
    log_lines = [
        {"stream": "stdout", "line": f"bundle-log-{uuid4().hex}-0"},
        {"stream": "stderr", "line": f"bundle-log-{uuid4().hex}-1"},
    ]
    for entry in log_lines:
        await stream.write_log(run_id, entry["line"], stream=entry["stream"])
    assert await stream.archive_logs(run_id, s3, bucket) is True

    storage_path = f"reports/{run_id}/bundle-summary.html"
    artifact_repo = ArtifactRepository(integration_db_session)
    artifact = await artifact_repo.create(
        run_id=run_id,
        type="html",
        name="bundle-summary.html",
        storage_path=storage_path,
        size_bytes=512,
        mime_type="text/html",
    )
    await integration_db_session.commit()

    run_read_token = await _create_real_api_token(
        real_auth_client,
        access_token,
        name="run-read-log-artifact-bundle",
        scopes=["run.read"],
    )
    headers = {"Authorization": f"Bearer {run_read_token}"}

    old_s3 = real_auth_app.state.container.s3_client
    real_auth_app.state.container.s3_client = s3
    try:
        logs_resp = await real_auth_client.get(
            f"/api/v1/runs/{run_id}/logs/archive",
            headers=headers,
            params={"page": 1, "per_page": 10},
        )
        list_resp = await real_auth_client.get(
            f"/api/v1/runs/{run_id}/artifacts",
            headers=headers,
            params={"page": 1, "per_page": 10},
        )
        download_resp = await real_auth_client.get(
            f"/api/v1/artifacts/{artifact.id}/download",
            headers=headers,
        )
    finally:
        real_auth_app.state.container.s3_client = old_s3

    assert logs_resp.status_code == 200, logs_resp.text
    logs_body = logs_resp.json()
    assert logs_body["total"] == 2
    assert logs_body["data"] == log_lines

    assert list_resp.status_code == 200, list_resp.text
    artifacts_body = list_resp.json()
    assert artifacts_body == {
        "data": [
            {
                "id": str(artifact.id),
                "run_id": str(run_id),
                "type": "html",
                "name": "bundle-summary.html",
                "storage_path": storage_path,
                "size_bytes": 512,
                "mime_type": "text/html",
                "expires_at": None,
                "created_at": _json_datetime(artifact.created_at),
            }
        ],
        "page": 1,
        "per_page": 10,
        "total": 1,
    }

    assert download_resp.status_code == 200, download_resp.text
    ttl = real_auth_app.state.container.settings.s3_presigned_url_ttl
    assert download_resp.json() == {
        "download_url": f"http://s3.local/{storage_path}?expires={ttl}",
        "expires_in": ttl,
    }
    assert s3.get_calls == [{"bucket": bucket, "key": f"logs/{run_id}.jsonl"}]
    assert s3.presign_calls == [
        {
            "method": "get_object",
            "params": {
                "Bucket": bucket,
                "Key": storage_path,
            },
            "expires_in": ttl,
        }
    ]


@pytest.mark.asyncio
async def test_log_archive_retry_worker_uses_real_redis_marker(real_auth_app):
    from qaplatform.engine.log_stream import LogStream
    from qaplatform.worker.settings import retry_failed_archives

    retry_set = "run:logs:archive_failed"
    run_id = uuid4()
    redis = real_auth_app.state.container.redis_client
    stream = LogStream(redis)
    bucket = real_auth_app.state.container.settings.s3_bucket
    s3 = _FlakyOnceS3()
    stream_key = LogStream._stream_key(run_id)

    try:
        await stream.write_log(run_id, "retry-line-0", stream="stdout")
        await stream.write_log(run_id, "retry-line-1", stream="stderr")

        first_archive = await stream.archive_logs(run_id, s3, bucket)
        assert first_archive is False
        assert await redis.sismember(retry_set, str(run_id))
        failure_ttl = await redis.ttl(stream_key)
        assert 0 < failure_ttl <= 86400

        await retry_failed_archives(
            {
                "log_stream": stream,
                "s3_client": s3,
                "s3_bucket": bucket,
            }
        )

        assert s3.put_calls == [
            {"bucket": bucket, "key": f"logs/{run_id}.jsonl"},
            {"bucket": bucket, "key": f"logs/{run_id}.jsonl"},
        ]
        assert not await redis.sismember(retry_set, str(run_id))
        success_ttl = await redis.ttl(stream_key)
        assert 0 < success_ttl <= 3600
        assert await stream.read_archived_logs(run_id, s3, bucket) == [
            {"stream": "stdout", "line": "retry-line-0"},
            {"stream": "stderr", "line": "retry-line-1"},
        ]
    finally:
        await redis.srem(retry_set, str(run_id))
        await redis.delete(stream_key)


@pytest.mark.asyncio
async def test_archived_logs_api_returns_404_when_s3_object_missing(
    real_auth_app,
    real_auth_client,
):
    access_token = await _register_real_user(real_auth_client, prefix="log_missing")
    stack = await _create_project_environment_and_pipeline(real_auth_client, access_token)

    trigger_resp = await real_auth_client.post(
        "/api/v1/runs",
        headers={"Authorization": f"Bearer {access_token}"},
        json={"pipeline_id": stack["pipeline_id"], "git_ref": "main"},
    )
    assert trigger_resp.status_code == 201, trigger_resp.text
    run_id = trigger_resp.json()["id"]

    real_auth_app.state.container.s3_client = _MemoryS3()
    replay_resp = await real_auth_client.get(
        f"/api/v1/runs/{run_id}/logs/archive",
        headers={"Authorization": f"Bearer {access_token}"},
    )

    assert replay_resp.status_code == 404, replay_resp.text
    assert replay_resp.json() == {
        "error": {
            "code": "NOT_FOUND",
            "message": "Archived logs not found",
            "details": [],
        }
    }
    assert str(run_id) not in replay_resp.text


@pytest.mark.asyncio
async def test_archived_logs_api_returns_503_when_storage_unconfigured_after_rbac(
    real_auth_app,
    real_auth_client,
):
    access_token = await _register_real_user(real_auth_client, prefix="log_no_storage")
    stack = await _create_project_environment_and_pipeline(real_auth_client, access_token)

    trigger_resp = await real_auth_client.post(
        "/api/v1/runs",
        headers={"Authorization": f"Bearer {access_token}"},
        json={"pipeline_id": stack["pipeline_id"], "git_ref": "main"},
    )
    assert trigger_resp.status_code == 201, trigger_resp.text
    run_id = trigger_resp.json()["id"]

    old_s3 = real_auth_app.state.container.s3_client
    real_auth_app.state.container.s3_client = None
    try:
        replay_resp = await real_auth_client.get(
            f"/api/v1/runs/{run_id}/logs/archive",
            headers={"Authorization": f"Bearer {access_token}"},
        )
    finally:
        real_auth_app.state.container.s3_client = old_s3

    assert replay_resp.status_code == 503, replay_resp.text
    assert replay_resp.json() == {"detail": "Archived logs are not available"}


@pytest.mark.asyncio
async def test_artifact_download_url_uses_real_auth_rbac_and_db_row(
    real_auth_app,
    real_auth_client,
    integration_db_session,
):
    from qaplatform.infra.database.repositories.run_repo import ArtifactRepository

    access_token = await _register_real_user(real_auth_client, prefix="artifact_dl")
    stack = await _create_project_environment_and_pipeline(real_auth_client, access_token)

    trigger_resp = await real_auth_client.post(
        "/api/v1/runs",
        headers={"Authorization": f"Bearer {access_token}"},
        json={"pipeline_id": stack["pipeline_id"], "git_ref": "main"},
    )
    assert trigger_resp.status_code == 201, trigger_resp.text
    run_id = trigger_resp.json()["id"]

    storage_path = f"reports/{run_id}/summary.html"
    artifact_repo = ArtifactRepository(integration_db_session)
    artifact = await artifact_repo.create(
        run_id=run_id,
        type="html",
        name="summary.html",
        storage_path=storage_path,
        size_bytes=128,
        mime_type="text/html",
    )
    await integration_db_session.commit()

    headers = {"Authorization": f"Bearer {access_token}"}
    list_resp = await real_auth_client.get(
        f"/api/v1/runs/{run_id}/artifacts",
        headers=headers,
    )
    assert list_resp.status_code == 200, list_resp.text
    list_body = list_resp.json()
    assert list_body == {
        "data": [
            {
                "id": str(artifact.id),
                "run_id": str(run_id),
                "type": "html",
                "name": "summary.html",
                "storage_path": storage_path,
                "size_bytes": 128,
                "mime_type": "text/html",
                "expires_at": None,
                "created_at": _json_datetime(artifact.created_at),
            }
        ],
        "page": 1,
        "per_page": 20,
        "total": 1,
    }

    s3 = _MemoryS3()
    real_auth_app.state.container.s3_client = s3
    download_resp = await real_auth_client.get(
        f"/api/v1/artifacts/{artifact.id}/download",
        headers=headers,
    )
    assert download_resp.status_code == 200, download_resp.text
    download_body = download_resp.json()
    ttl = real_auth_app.state.container.settings.s3_presigned_url_ttl
    assert download_body == {
        "download_url": f"http://s3.local/{storage_path}?expires={ttl}",
        "expires_in": ttl,
    }
    assert s3.presign_calls == [
        {
            "method": "get_object",
            "params": {
                "Bucket": real_auth_app.state.container.settings.s3_bucket,
                "Key": storage_path,
            },
            "expires_in": ttl,
        }
    ]


@pytest.mark.asyncio
async def test_artifact_download_urls_presign_each_real_db_row_without_s3_reads(
    real_auth_app,
    real_auth_client,
    integration_db_session,
):
    from qaplatform.infra.database.repositories.run_repo import ArtifactRepository

    access_token = await _register_real_user(real_auth_client, prefix="artifact_burst")
    stack = await _create_project_environment_and_pipeline(real_auth_client, access_token)

    trigger_resp = await real_auth_client.post(
        "/api/v1/runs",
        headers={"Authorization": f"Bearer {access_token}"},
        json={"pipeline_id": stack["pipeline_id"], "git_ref": "main"},
    )
    assert trigger_resp.status_code == 201, trigger_resp.text
    run_id = trigger_resp.json()["id"]

    artifact_repo = ArtifactRepository(integration_db_session)
    artifacts = []
    for index, artifact_type in enumerate(("html", "junit", "log", "allure", "report")):
        artifact = await artifact_repo.create(
            run_id=run_id,
            type=artifact_type,
            name=f"download-{index}.{artifact_type}",
            storage_path=f"reports/{run_id}/download-{index}.{artifact_type}",
            size_bytes=1024 + index,
            mime_type="text/html" if artifact_type != "junit" else "application/xml",
        )
        artifacts.append(artifact)
    await integration_db_session.commit()

    run_read_token = await _create_real_api_token(
        real_auth_client,
        access_token,
        name="artifact-burst-run-read",
        scopes=["run.read"],
    )

    old_s3 = real_auth_app.state.container.s3_client
    s3 = _MemoryS3()
    real_auth_app.state.container.s3_client = s3
    responses = []
    try:
        for artifact in artifacts:
            response = await real_auth_client.get(
                f"/api/v1/artifacts/{artifact.id}/download",
                headers={"Authorization": f"Bearer {run_read_token}"},
            )
            assert response.status_code == 200, response.text
            responses.append(response.json())
    finally:
        real_auth_app.state.container.s3_client = old_s3

    ttl = real_auth_app.state.container.settings.s3_presigned_url_ttl
    assert responses == [
        {
            "download_url": f"http://s3.local/{artifact.storage_path}?expires={ttl}",
            "expires_in": ttl,
        }
        for artifact in artifacts
    ]
    assert s3.get_calls == []
    assert s3.presign_calls == [
        {
            "method": "get_object",
            "params": {
                "Bucket": real_auth_app.state.container.settings.s3_bucket,
                "Key": artifact.storage_path,
            },
            "expires_in": ttl,
        }
        for artifact in artifacts
    ]


@pytest.mark.asyncio
async def test_artifact_list_api_token_requires_run_read_scope(
    real_auth_app,
    real_auth_client,
    integration_db_session,
):
    from qaplatform.infra.database.repositories.run_repo import ArtifactRepository

    access_token = await _register_real_user(real_auth_client, prefix="artifact_list_scope")
    stack = await _create_project_environment_and_pipeline(real_auth_client, access_token)

    trigger_resp = await real_auth_client.post(
        "/api/v1/runs",
        headers={"Authorization": f"Bearer {access_token}"},
        json={"pipeline_id": stack["pipeline_id"], "git_ref": "main"},
    )
    assert trigger_resp.status_code == 201, trigger_resp.text
    run_id = trigger_resp.json()["id"]

    artifact_repo = ArtifactRepository(integration_db_session)
    artifact_created_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    first = await artifact_repo.create(
        run_id=run_id,
        type="html",
        name="summary.html",
        storage_path=f"reports/{run_id}/summary.html",
        size_bytes=128,
        mime_type="text/html",
        created_at=artifact_created_at,
    )
    second = await artifact_repo.create(
        run_id=run_id,
        type="junit",
        name="results.xml",
        storage_path=f"reports/{run_id}/results.xml",
        size_bytes=256,
        mime_type="application/xml",
        created_at=artifact_created_at + timedelta(seconds=1),
    )
    await integration_db_session.commit()

    project_read_token = await _create_real_api_token(
        real_auth_client,
        access_token,
        name="artifact-list-project-read",
        scopes=["project.read"],
    )
    empty_scope_token = await _create_real_api_token(
        real_auth_client,
        access_token,
        name="artifact-list-empty-scope",
        scopes=[],
    )
    old_s3 = real_auth_app.state.container.s3_client
    s3 = _MemoryS3()
    real_auth_app.state.container.s3_client = s3
    try:
        denied_responses = []
        denied_tokens = (
            ("project.read", project_read_token),
            ("empty scope", empty_scope_token),
        )
        for label, denied_token in denied_tokens:
            denied_responses.append(
                (
                    label,
                    await real_auth_client.get(
                        f"/api/v1/runs/{run_id}/artifacts",
                        headers={"Authorization": f"Bearer {denied_token}"},
                    ),
                )
            )
    finally:
        real_auth_app.state.container.s3_client = old_s3
    for label, denied_resp in denied_responses:
        assert denied_resp.status_code == 403, f"{label}: {denied_resp.text}"
        assert denied_resp.json() == {"detail": "Insufficient permissions"}
        assert "summary.html" not in denied_resp.text, label
        assert "results.xml" not in denied_resp.text, label
        assert f"reports/{run_id}/" not in denied_resp.text, label
    assert s3.presign_calls == []
    assert s3.get_calls == []

    run_read_token = await _create_real_api_token(
        real_auth_client,
        access_token,
        name="artifact-list-run-read",
        scopes=["run.read"],
    )
    allowed_resp = await real_auth_client.get(
        f"/api/v1/runs/{run_id}/artifacts",
        headers={"Authorization": f"Bearer {run_read_token}"},
        params={"page": 1, "per_page": 10},
    )
    assert allowed_resp.status_code == 200, allowed_resp.text
    body = allowed_resp.json()
    expected_body = {
        "data": [
            {
                "id": str(artifact.id),
                "run_id": run_id,
                "type": artifact.type,
                "name": artifact.name,
                "storage_path": artifact.storage_path,
                "size_bytes": artifact.size_bytes,
                "mime_type": artifact.mime_type,
                "expires_at": None,
                "created_at": _json_datetime(artifact.created_at),
            }
            for artifact in (second, first)
        ],
        "page": 1,
        "per_page": 10,
        "total": 2,
    }
    assert body == expected_body


@pytest.mark.asyncio
async def test_run_artifacts_list_paginates_real_db_without_s3_side_effects(
    real_auth_app,
    real_auth_client,
    integration_db_session,
):
    from qaplatform.infra.database.repositories.run_repo import ArtifactRepository

    access_token = await _register_real_user(real_auth_client, prefix="artifact_page")
    stack = await _create_project_environment_and_pipeline(real_auth_client, access_token)

    trigger_resp = await real_auth_client.post(
        "/api/v1/runs",
        headers={"Authorization": f"Bearer {access_token}"},
        json={"pipeline_id": stack["pipeline_id"], "git_ref": "main"},
    )
    assert trigger_resp.status_code == 201, trigger_resp.text
    run_id = trigger_resp.json()["id"]

    artifact_repo = ArtifactRepository(integration_db_session)
    created = []
    base_time = datetime(2026, 1, 1, tzinfo=timezone.utc)
    for index in range(5):
        artifact = await artifact_repo.create(
            run_id=run_id,
            type="report",
            name=f"report-{index}.html",
            storage_path=f"reports/{run_id}/report-{index}.html",
            size_bytes=1024 + index,
            mime_type="text/html",
            created_at=base_time + timedelta(seconds=index),
        )
        created.append(artifact)
    await integration_db_session.commit()

    expected_desc = list(reversed(created))
    old_s3 = real_auth_app.state.container.s3_client
    s3 = _MemoryS3()
    real_auth_app.state.container.s3_client = s3
    try:
        page_two_resp = await real_auth_client.get(
            f"/api/v1/runs/{run_id}/artifacts",
            headers={"Authorization": f"Bearer {access_token}"},
            params={"page": 2, "per_page": 2},
        )
        empty_page_resp = await real_auth_client.get(
            f"/api/v1/runs/{run_id}/artifacts",
            headers={"Authorization": f"Bearer {access_token}"},
            params={"page": 4, "per_page": 2},
        )
    finally:
        real_auth_app.state.container.s3_client = old_s3

    assert page_two_resp.status_code == 200, page_two_resp.text
    page_two = page_two_resp.json()
    assert page_two == {
        "data": [
            {
                "id": str(artifact.id),
                "run_id": run_id,
                "type": "report",
                "name": artifact.name,
                "storage_path": artifact.storage_path,
                "size_bytes": artifact.size_bytes,
                "mime_type": "text/html",
                "expires_at": None,
                "created_at": _json_datetime(artifact.created_at),
            }
            for artifact in expected_desc[2:4]
        ],
        "page": 2,
        "per_page": 2,
        "total": 5,
    }
    assert empty_page_resp.status_code == 200, empty_page_resp.text
    empty_page = empty_page_resp.json()
    assert empty_page == {
        "data": [],
        "page": 4,
        "per_page": 2,
        "total": 5,
    }

    assert s3.presign_calls == []
    assert s3.get_calls == []


@pytest.mark.asyncio
async def test_artifact_download_api_token_requires_run_read_scope(
    real_auth_app,
    real_auth_client,
    integration_db_session,
):
    from qaplatform.infra.database.repositories.run_repo import ArtifactRepository

    access_token = await _register_real_user(real_auth_client, prefix="artifact_scope")
    stack = await _create_project_environment_and_pipeline(real_auth_client, access_token)

    trigger_resp = await real_auth_client.post(
        "/api/v1/runs",
        headers={"Authorization": f"Bearer {access_token}"},
        json={"pipeline_id": stack["pipeline_id"], "git_ref": "main"},
    )
    assert trigger_resp.status_code == 201, trigger_resp.text
    run_id = trigger_resp.json()["id"]

    artifact_repo = ArtifactRepository(integration_db_session)
    artifact = await artifact_repo.create(
        run_id=run_id,
        type="junit",
        name="machine-readable.xml",
        storage_path=f"reports/{run_id}/machine-readable.xml",
        size_bytes=256,
        mime_type="application/xml",
    )
    await integration_db_session.commit()

    s3 = _MemoryS3()
    real_auth_app.state.container.s3_client = s3

    project_read_token = await _create_real_api_token(
        real_auth_client,
        access_token,
        name="project-read-only",
        scopes=["project.read"],
    )
    empty_scope_token = await _create_real_api_token(
        real_auth_client,
        access_token,
        name="artifact-download-empty-scope",
        scopes=[],
    )
    denied_tokens = (
        ("project.read", project_read_token),
        ("empty scope", empty_scope_token),
    )
    for label, denied_token in denied_tokens:
        denied_resp = await real_auth_client.get(
            f"/api/v1/artifacts/{artifact.id}/download",
            headers={"Authorization": f"Bearer {denied_token}"},
        )
        assert denied_resp.status_code == 403, f"{label}: {denied_resp.text}"
        assert denied_resp.json() == {"detail": "Insufficient permissions"}
        assert artifact.name not in denied_resp.text, label
        assert artifact.storage_path not in denied_resp.text, label
    assert s3.presign_calls == []
    assert s3.get_calls == []

    run_read_token = await _create_real_api_token(
        real_auth_client,
        access_token,
        name="run-read",
        scopes=["run.read"],
    )
    allowed_resp = await real_auth_client.get(
        f"/api/v1/artifacts/{artifact.id}/download",
        headers={"Authorization": f"Bearer {run_read_token}"},
    )
    assert allowed_resp.status_code == 200, allowed_resp.text
    ttl = real_auth_app.state.container.settings.s3_presigned_url_ttl
    assert allowed_resp.json() == {
        "download_url": f"http://s3.local/{artifact.storage_path}?expires={ttl}",
        "expires_in": ttl,
    }
    assert s3.presign_calls == [
        {
            "method": "get_object",
            "params": {
                "Bucket": real_auth_app.state.container.settings.s3_bucket,
                "Key": artifact.storage_path,
            },
            "expires_in": ttl,
        }
    ]


@pytest.mark.asyncio
async def test_artifact_download_returns_503_when_storage_unconfigured_after_rbac(
    real_auth_app,
    real_auth_client,
    integration_db_session,
):
    from qaplatform.infra.database.repositories.run_repo import ArtifactRepository

    access_token = await _register_real_user(real_auth_client, prefix="artifact_no_s3")
    stack = await _create_project_environment_and_pipeline(real_auth_client, access_token)

    trigger_resp = await real_auth_client.post(
        "/api/v1/runs",
        headers={"Authorization": f"Bearer {access_token}"},
        json={"pipeline_id": stack["pipeline_id"], "git_ref": "main"},
    )
    assert trigger_resp.status_code == 201, trigger_resp.text
    run_id = trigger_resp.json()["id"]

    artifact_repo = ArtifactRepository(integration_db_session)
    artifact = await artifact_repo.create(
        run_id=run_id,
        type="junit",
        name="machine-readable.xml",
        storage_path=f"reports/{run_id}/machine-readable.xml",
        size_bytes=256,
        mime_type="application/xml",
    )
    await integration_db_session.commit()

    old_s3 = real_auth_app.state.container.s3_client
    real_auth_app.state.container.s3_client = None
    try:
        download_resp = await real_auth_client.get(
            f"/api/v1/artifacts/{artifact.id}/download",
            headers={"Authorization": f"Bearer {access_token}"},
        )
    finally:
        real_auth_app.state.container.s3_client = old_s3

    assert download_resp.status_code == 503, download_resp.text
    assert download_resp.json() == {"detail": "Artifact download is not available"}


@pytest.mark.asyncio
async def test_artifact_download_soft_deleted_row_returns_404_without_presign(
    real_auth_app,
    real_auth_client,
    integration_db_session,
):
    from qaplatform.infra.database.models import Artifact as ArtifactModel
    from qaplatform.infra.database.repositories.run_repo import ArtifactRepository

    access_token = await _register_real_user(real_auth_client, prefix="artifact_deleted")
    stack = await _create_project_environment_and_pipeline(real_auth_client, access_token)

    trigger_resp = await real_auth_client.post(
        "/api/v1/runs",
        headers={"Authorization": f"Bearer {access_token}"},
        json={"pipeline_id": stack["pipeline_id"], "git_ref": "main"},
    )
    assert trigger_resp.status_code == 201, trigger_resp.text
    run_id = trigger_resp.json()["id"]

    artifact_repo = ArtifactRepository(integration_db_session)
    artifact = await artifact_repo.create(
        run_id=run_id,
        type="report",
        name="deleted-report.html",
        storage_path=f"reports/{run_id}/deleted-report.html",
        size_bytes=1024,
        mime_type="text/html",
    )
    await artifact_repo.delete(artifact)
    await integration_db_session.commit()
    soft_deleted_at = (
        await integration_db_session.execute(
            select(ArtifactModel.deleted_at).where(ArtifactModel.id == artifact.id)
        )
    ).scalar_one()
    assert soft_deleted_at is not None

    run_read_token = await _create_real_api_token(
        real_auth_client,
        access_token,
        name="deleted-artifact-run-read",
        scopes=["run.read"],
    )

    old_s3 = real_auth_app.state.container.s3_client
    s3 = _MemoryS3()
    real_auth_app.state.container.s3_client = s3
    try:
        random_resp = await real_auth_client.get(
            f"/api/v1/artifacts/{uuid4()}/download",
            headers={"Authorization": f"Bearer {run_read_token}"},
        )
        deleted_resp = await real_auth_client.get(
            f"/api/v1/artifacts/{artifact.id}/download",
            headers={"Authorization": f"Bearer {run_read_token}"},
        )
    finally:
        real_auth_app.state.container.s3_client = old_s3

    assert random_resp.status_code == 404, random_resp.text
    assert deleted_resp.status_code == 404, deleted_resp.text
    expected_404 = {
        "error": {
            "code": "NOT_FOUND",
            "message": "Artifact not found",
            "details": [],
        }
    }
    assert deleted_resp.json() == random_resp.json() == expected_404
    assert s3.presign_calls == []
    assert s3.get_calls == []


@pytest.mark.asyncio
async def test_artifact_download_api_token_cross_tenant_returns_same_404(
    real_auth_app,
    real_auth_client,
    integration_db_session,
):
    from qaplatform.infra.database.repositories.run_repo import ArtifactRepository

    access_token_a = await _register_real_user(real_auth_client, prefix="artifact_a")
    access_token_b = await _register_real_user(real_auth_client, prefix="artifact_b")
    stack_b = await _create_project_environment_and_pipeline(real_auth_client, access_token_b)

    trigger_resp = await real_auth_client.post(
        "/api/v1/runs",
        headers={"Authorization": f"Bearer {access_token_b}"},
        json={"pipeline_id": stack_b["pipeline_id"], "git_ref": "main"},
    )
    assert trigger_resp.status_code == 201, trigger_resp.text
    run_b_id = trigger_resp.json()["id"]

    artifact_repo = ArtifactRepository(integration_db_session)
    artifact_b = await artifact_repo.create(
        run_id=run_b_id,
        type="junit",
        name="tenant-b-report.xml",
        storage_path=f"reports/{run_b_id}/tenant-b-report.xml",
        size_bytes=512,
        mime_type="application/xml",
    )
    await integration_db_session.commit()

    s3 = _MemoryS3()
    real_auth_app.state.container.s3_client = s3
    run_read_token_a = await _create_real_api_token(
        real_auth_client,
        access_token_a,
        name="tenant-a-run-read",
        scopes=["run.read"],
    )
    headers_a = {"Authorization": f"Bearer {run_read_token_a}"}

    tenant_b_resp = await real_auth_client.get(
        f"/api/v1/artifacts/{artifact_b.id}/download",
        headers=headers_a,
    )
    random_resp = await real_auth_client.get(
        f"/api/v1/artifacts/{uuid4()}/download",
        headers=headers_a,
    )

    assert tenant_b_resp.status_code == random_resp.status_code == 404
    expected_404 = {
        "error": {
            "code": "NOT_FOUND",
            "message": "Artifact not found",
            "details": [],
        }
    }
    assert tenant_b_resp.json() == random_resp.json() == expected_404
    assert str(artifact_b.id) not in tenant_b_resp.text
    assert artifact_b.storage_path not in tenant_b_resp.text
    assert s3.presign_calls == []
    assert s3.get_calls == []


@pytest.mark.asyncio
async def test_artifact_upload_enforces_limits_before_real_db_rows(
    integration_db_session,
    seed_run,
    tmp_path,
):
    from qaplatform.engine.docker_backend import ResourceLimits
    from qaplatform.engine.executor import RunExecutor
    from qaplatform.infra.database.repositories.run_repo import ArtifactRepository

    run_id = seed_run["run"].id
    results_dir = tmp_path / "results"
    results_dir.mkdir()
    (results_dir / "a.txt").write_bytes(b"ok")
    (results_dir / "b.txt").write_bytes(b"too-large")
    (results_dir / "c.txt").write_bytes(b"ok")
    (results_dir / "d.txt").write_bytes(b"ok")

    s3 = _MemoryS3()
    log_stream = AsyncMock()
    artifact_repo = ArtifactRepository(integration_db_session)
    executor = RunExecutor(
        backend=AsyncMock(),
        log_stream=log_stream,
        run_repo=AsyncMock(),
        s3_client=s3,
        s3_bucket="qa-platform-test",
        artifact_repo=artifact_repo,
    )

    await executor._upload_artifacts(
        str(run_id),
        tmp_path,
        ResourceLimits(max_artifact_size_bytes=2, max_artifacts_count=2),
    )
    await integration_db_session.commit()

    rows, total = await artifact_repo.list_by_run(run_id, limit=10)
    artifact_rows = sorted(
        [
            {
                "run_id": str(row.run_id),
                "type": row.type,
                "name": row.name,
                "storage_path": row.storage_path,
                "size_bytes": row.size_bytes,
                "mime_type": row.mime_type,
            }
            for row in rows
        ],
        key=lambda row: row["name"],
    )
    assert {"total": total, "rows": artifact_rows} == {
        "total": 2,
        "rows": [
            {
                "run_id": str(run_id),
                "type": "log",
                "name": "a.txt",
                "storage_path": f"reports/{run_id}/a.txt",
                "size_bytes": 2,
                "mime_type": "text/plain",
            },
            {
                "run_id": str(run_id),
                "type": "log",
                "name": "c.txt",
                "storage_path": f"reports/{run_id}/c.txt",
                "size_bytes": 2,
                "mime_type": "text/plain",
            },
        ],
    }
    assert s3.objects == {
        ("qa-platform-test", f"reports/{run_id}/a.txt"): b"ok",
        ("qa-platform-test", f"reports/{run_id}/c.txt"): b"ok",
    }
    log_calls = [
        {
            "run_id": call.args[0],
            "line": call.args[1],
            "stream": call.kwargs.get("stream", "stdout"),
        }
        for call in log_stream.write_log.await_args_list
    ]
    assert log_calls == [
        {
            "run_id": str(run_id),
            "line": "Uploaded artifact: a.txt",
            "stream": "stdout",
        },
        {
            "run_id": str(run_id),
            "line": "Skipped artifact b.txt: size 9 exceeds limit 2 bytes",
            "stream": "stderr",
        },
        {
            "run_id": str(run_id),
            "line": "Uploaded artifact: c.txt",
            "stream": "stdout",
        },
        {
            "run_id": str(run_id),
            "line": "Skipped artifact d.txt: artifact count limit exceeded",
            "stream": "stderr",
        },
    ]


@pytest.mark.asyncio
async def test_artifact_upload_s3_failure_leaves_no_real_db_rows(
    integration_db_session,
    seed_run,
    tmp_path,
):
    from qaplatform.engine.docker_backend import ResourceLimits
    from qaplatform.engine.executor import RunExecutor
    from qaplatform.infra.database.repositories.run_repo import ArtifactRepository

    run_id = seed_run["run"].id
    results_dir = tmp_path / "results"
    results_dir.mkdir()
    (results_dir / "summary.html").write_text("<html>failed upload</html>")

    s3 = _FailingS3()
    artifact_repo = ArtifactRepository(integration_db_session)
    executor = RunExecutor(
        backend=AsyncMock(),
        log_stream=AsyncMock(),
        run_repo=AsyncMock(),
        s3_client=s3,
        s3_bucket="qa-platform-test",
        artifact_repo=artifact_repo,
    )

    await executor._upload_artifacts(
        str(run_id),
        tmp_path,
        ResourceLimits(max_artifact_size_bytes=1024, max_artifacts_count=10),
    )
    await integration_db_session.commit()

    rows, total = await artifact_repo.list_by_run(run_id, limit=10)
    assert rows == []
    assert total == 0
    assert s3.put_calls == [
        {
            "bucket": "qa-platform-test",
            "key": f"reports/{run_id}/summary.html",
        }
    ]


@pytest.mark.asyncio
async def test_artifact_upload_recurses_allure_report_with_real_db_rows(
    integration_db_session,
    seed_run,
    tmp_path,
):
    from qaplatform.engine.docker_backend import ResourceLimits
    from qaplatform.engine.executor import RunExecutor
    from qaplatform.infra.database.repositories.run_repo import ArtifactRepository

    run_id = seed_run["run"].id
    results_dir = tmp_path / "results"
    (results_dir / "allure-report" / "assets").mkdir(parents=True)
    (results_dir / "allure-report" / "index.html").write_text("<html/>")
    (results_dir / "allure-report" / "assets" / "app.js").write_text("ok")

    s3 = _MemoryS3()
    artifact_repo = ArtifactRepository(integration_db_session)
    executor = RunExecutor(
        backend=AsyncMock(),
        log_stream=AsyncMock(),
        run_repo=AsyncMock(),
        s3_client=s3,
        s3_bucket="qa-platform-test",
        artifact_repo=artifact_repo,
    )

    await executor._upload_artifacts(
        str(run_id),
        tmp_path,
        ResourceLimits(max_artifact_size_bytes=1024, max_artifacts_count=10),
    )
    await integration_db_session.commit()

    rows, total = await artifact_repo.list_by_run(run_id, limit=10)
    assert total == 2
    artifact_rows = sorted(
        [
            {
                "run_id": str(row.run_id),
                "type": row.type,
                "name": row.name,
                "storage_path": row.storage_path,
                "size_bytes": row.size_bytes,
                "mime_type": row.mime_type,
            }
            for row in rows
        ],
        key=lambda item: item["name"],
    )
    assert artifact_rows == [
        {
            "run_id": str(run_id),
            "type": "allure-report",
            "name": "allure-report/assets/app.js",
            "storage_path": f"reports/{run_id}/allure-report/assets/app.js",
            "size_bytes": len("ok"),
            "mime_type": "text/javascript",
        },
        {
            "run_id": str(run_id),
            "type": "allure-report",
            "name": "allure-report/index.html",
            "storage_path": f"reports/{run_id}/allure-report/index.html",
            "size_bytes": len("<html/>"),
            "mime_type": "text/html",
        },
    ]
    assert s3.objects == {
        (
            "qa-platform-test",
            f"reports/{run_id}/allure-report/assets/app.js",
        ): b"ok",
        (
            "qa-platform-test",
            f"reports/{run_id}/allure-report/index.html",
        ): b"<html/>",
    }


@pytest.mark.asyncio
async def test_api_token_scope_matrix_enforced_by_real_routes(
    real_auth_client,
    integration_db_session,
):
    from qaplatform.infra.database.models import Project, Run, RunStatusEnum, Schedule

    access_token = await _register_real_user(real_auth_client, prefix="scope_matrix")
    stack = await _create_project_environment_and_pipeline(real_auth_client, access_token)

    read_token = await _create_real_api_token(
        real_auth_client,
        access_token,
        name="read-only",
        scopes=["project.read"],
    )
    read_headers = {"Authorization": f"Bearer {read_token}"}
    read_resp = await real_auth_client.get("/api/v1/projects", headers=read_headers)
    assert read_resp.status_code == 200, read_resp.text
    read_body = read_resp.json()
    assert read_body["total"] == 1
    assert [item["id"] for item in read_body["data"]] == [stack["project_id"]]

    denied_slug = f"denied-{uuid4().hex[:8]}"
    denied_write = await real_auth_client.post(
        "/api/v1/projects",
        headers=read_headers,
        json={
            "name": "denied",
            "slug": denied_slug,
            "git_url": "https://example.com/denied.git",
        },
    )
    assert denied_write.status_code == 403, denied_write.text
    assert denied_write.json() == {"detail": "Insufficient permissions"}
    denied_project_count = await integration_db_session.scalar(
        select(func.count())
        .select_from(Project)
        .where(Project.slug == denied_slug)
    )
    assert denied_project_count == 0

    run_trigger_token = await _create_real_api_token(
        real_auth_client,
        access_token,
        name="run-trigger-only",
        scopes=["run.trigger"],
    )
    run_headers = {"Authorization": f"Bearer {run_trigger_token}"}
    trigger_resp = await real_auth_client.post(
        "/api/v1/runs",
        headers=run_headers,
        json={"pipeline_id": stack["pipeline_id"], "git_ref": "main"},
    )
    assert trigger_resp.status_code == 201, trigger_resp.text
    triggered = trigger_resp.json()
    assert triggered["project_id"] == stack["project_id"]
    assert triggered["pipeline_id"] == stack["pipeline_id"]
    assert triggered["environment_id"] == stack["environment_id"]
    assert triggered["status"] == "queued"
    assert triggered["trigger_type"] == "manual"
    assert triggered["git_ref"] == "main"
    run = await integration_db_session.get(Run, UUID(triggered["id"]))
    assert run is not None
    assert str(run.project_id) == stack["project_id"]
    assert str(run.pipeline_id) == stack["pipeline_id"]
    assert str(run.environment_id) == stack["environment_id"]
    assert run.status == RunStatusEnum.QUEUED
    assert run.trigger_type == "manual"

    schedule_count_before = await integration_db_session.scalar(
        select(func.count())
        .select_from(Schedule)
        .where(
            Schedule.project_id == UUID(stack["project_id"]),
            Schedule.pipeline_id == UUID(stack["pipeline_id"]),
        )
    )
    denied_schedule = await real_auth_client.post(
        f"/api/v1/projects/{stack['project_id']}/schedules",
        headers=run_headers,
        json={
            "pipeline_id": stack["pipeline_id"],
            "cron_expr": "*/15 * * * *",
            "timezone": "UTC",
            "missed_fire_policy": "skip",
            "quiet_windows": [],
            "enabled": True,
        },
    )
    assert denied_schedule.status_code == 403, denied_schedule.text
    assert denied_schedule.json() == {"detail": "Insufficient permissions"}
    schedule_count_after = await integration_db_session.scalar(
        select(func.count())
        .select_from(Schedule)
        .where(
            Schedule.project_id == UUID(stack["project_id"]),
            Schedule.pipeline_id == UUID(stack["pipeline_id"]),
        )
    )
    assert schedule_count_after == schedule_count_before

    wrong_scope_token = await _create_real_api_token(
        real_auth_client,
        access_token,
        name="wrong-scope",
        scopes=["run.read"],
    )
    wrong_scope_resp = await real_auth_client.get(
        "/api/v1/projects",
        headers={"Authorization": f"Bearer {wrong_scope_token}"},
    )
    assert wrong_scope_resp.status_code == 403, wrong_scope_resp.text
    assert wrong_scope_resp.json() == {"detail": "Insufficient permissions"}

    empty_scope_token = await _create_real_api_token(
        real_auth_client,
        access_token,
        name="empty-scope",
        scopes=[],
    )
    empty_scope_resp = await real_auth_client.post(
        "/api/v1/runs",
        headers={"Authorization": f"Bearer {empty_scope_token}"},
        json={"pipeline_id": stack["pipeline_id"], "git_ref": "main"},
    )
    assert empty_scope_resp.status_code == 403, empty_scope_resp.text
    assert empty_scope_resp.json() == {"detail": "Insufficient permissions"}


@pytest.mark.asyncio
async def test_run_results_api_filters_real_rows_and_recovers_after_duplicate(
    integration_client,
    integration_db_session,
    seed_run,
):
    from qaplatform.infra.database.models import TestResultStatusEnum
    from qaplatform.infra.database.repositories.run_repo import TestResultRepository

    run_id = seed_run["run"].id
    repo = TestResultRepository(integration_db_session)
    result_created_at = datetime(2026, 1, 1, tzinfo=timezone.utc)

    created_results = await repo.bulk_create(
        [
            {
                "run_id": run_id,
                "suite": "checkout",
                "name": "test_cart_total",
                "status": TestResultStatusEnum.PASSED,
                "duration_ms": 42,
                "tags": ["smoke"],
                "metadata_": {"node": "gw0"},
                "created_at": result_created_at,
            },
            {
                "run_id": run_id,
                "suite": "checkout",
                "name": "test_payment_decline",
                "status": TestResultStatusEnum.FAILED,
                "duration_ms": 87,
                "error_message": "AssertionError: card declined",
                "tags": ["payments"],
                "metadata_": {"node": "gw1"},
                "created_at": result_created_at + timedelta(seconds=1),
            },
        ]
    )
    await integration_db_session.commit()
    expected_results_by_name = {
        "test_cart_total": {
            "id": str(created_results[0].id),
            "run_id": str(run_id),
            "suite": "checkout",
            "name": "test_cart_total",
            "status": "passed",
            "duration_ms": 42,
            "error_message": None,
            "stack_trace": None,
            "tags": ["smoke"],
            "metadata": {"node": "gw0"},
        },
        "test_payment_decline": {
            "id": str(created_results[1].id),
            "run_id": str(run_id),
            "suite": "checkout",
            "name": "test_payment_decline",
            "status": "failed",
            "duration_ms": 87,
            "error_message": "AssertionError: card declined",
            "stack_trace": None,
            "tags": ["payments"],
            "metadata": {"node": "gw1"},
        },
    }

    resp = await integration_client.get(
        f"/api/v1/runs/{run_id}/results",
        params={"status": "failed", "suite": "checkout", "q": "card"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body == {
        "data": [expected_results_by_name["test_payment_decline"]],
        "page": 1,
        "per_page": 20,
        "total": 1,
    }
    with pytest.raises(IntegrityError) as exc_info:
        await repo.bulk_create(
            [
                {
                    "run_id": run_id,
                    "suite": "checkout",
                    "name": "test_payment_decline",
                    "status": TestResultStatusEnum.ERROR,
                    "duration_ms": 1,
                    "tags": [],
                    "metadata_": {},
                }
            ]
        )
        await integration_db_session.commit()
    _assert_integrity_constraint(exc_info.value, "uq_test_result_run_suite_name")

    await integration_db_session.rollback()

    after_rollback_resp = await integration_client.get(
        f"/api/v1/runs/{run_id}/results",
        params={"suite": "checkout", "per_page": 100},
    )
    assert after_rollback_resp.status_code == 200, after_rollback_resp.text
    after_rollback_body = after_rollback_resp.json()
    assert after_rollback_body == {
        "data": [
            expected_results_by_name["test_payment_decline"],
            expected_results_by_name["test_cart_total"],
        ],
        "page": 1,
        "per_page": 100,
        "total": 2,
    }


@pytest.mark.asyncio
async def test_run_artifacts_api_hides_soft_deleted_real_rows(
    integration_client,
    integration_db_session,
    seed_run,
):
    from qaplatform.infra.database.repositories.run_repo import ArtifactRepository

    run_id = seed_run["run"].id
    repo = ArtifactRepository(integration_db_session)

    visible = await repo.create(
        run_id=run_id,
        type="report",
        name="summary.html",
        storage_path=f"runs/{run_id}/summary.html",
        size_bytes=2048,
        mime_type="text/html",
    )
    deleted = await repo.create(
        run_id=run_id,
        type="trace",
        name="trace.zip",
        storage_path=f"runs/{run_id}/trace.zip",
        size_bytes=4096,
        mime_type="application/zip",
    )
    await repo.delete(deleted)
    await integration_db_session.commit()

    repo_items, repo_total = await repo.list_by_run(run_id, limit=100)
    assert repo_total == 1
    assert [item.id for item in repo_items] == [visible.id]

    resp = await integration_client.get(f"/api/v1/runs/{run_id}/artifacts")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body == {
        "data": [
            {
                "id": str(visible.id),
                "run_id": str(run_id),
                "type": "report",
                "name": "summary.html",
                "storage_path": f"runs/{run_id}/summary.html",
                "size_bytes": 2048,
                "mime_type": "text/html",
                "expires_at": None,
                "created_at": _json_datetime(visible.created_at),
            }
        ],
        "page": 1,
        "per_page": 20,
        "total": 1,
    }
