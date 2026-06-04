"""Black-box API behavior tests driven by the public HTTP surface.

These tests intentionally create their setup data through documented API
endpoints: register a real user, use the returned bearer token, then create
projects and children through HTTP. They complement the OpenAPI contract smoke
test, which only proves declaration/runtime agreement for unauthenticated
failure paths.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

import jwt
import pytest
from httpx import ASGITransport, AsyncClient, Response

from qaplatform.config import Settings
from tests.support.api_data import ApiTestDataFactory
from tests.support.api_seed import LocalHttpsGitRepo, api_seed_state_factory


pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_INTEGRATION_TESTS") != "1",
    reason="set RUN_INTEGRATION_TESTS=1 to run integration tests",
)

FULL_SHA = "a" * 40
_API_DATA_FACTORIES: dict[int, ApiTestDataFactory] = {}


@dataclass(frozen=True)
class Actor:
    username: str
    password: str
    access_token: str
    user: dict[str, Any]

    @property
    def headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.access_token}"}


@dataclass(frozen=True)
class AuthSuccessCase:
    case_id: str
    run: Callable[[AsyncClient], Awaitable[None]]


@dataclass(frozen=True)
class ResourceSuccessCase:
    case_id: str
    run: Callable[[AsyncClient], Awaitable[None]]


@dataclass(frozen=True)
class SchemaNegativeCase:
    case_id: str
    method: str
    path_template: str
    kwargs_factory: Callable[[Actor, dict[str, str], str], dict[str, Any]]
    requires_stack: bool = False

    def path(self, ids: dict[str, str]) -> str:
        return self.path_template.format(**ids)


@dataclass(frozen=True)
class RbacTenantCase:
    case_id: str
    method: str
    path_template: str
    kwargs_factory: Callable[[dict[str, str]], dict[str, Any]]

    def path(self, ids: dict[str, str]) -> str:
        return self.path_template.format(**ids)


@asynccontextmanager
async def _api_client(app) -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport,
        base_url="http://localhost",
    ) as client:
        factory = ApiTestDataFactory(client)
        _API_DATA_FACTORIES[id(client)] = factory
        cleanup_should_raise = True
        try:
            yield client
        except BaseException:
            cleanup_should_raise = False
            raise
        finally:
            _API_DATA_FACTORIES.pop(id(client), None)
            cleanup_errors = await factory.cleanup()
            if cleanup_errors and cleanup_should_raise:
                raise AssertionError(
                    "API test data cleanup failed: " + "; ".join(cleanup_errors)
                )


def _test_data_factory(client: AsyncClient) -> ApiTestDataFactory | None:
    return _API_DATA_FACTORIES.get(id(client))


def _suffix(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex[:10]}"


def _assert_status(response: Response, expected: int) -> dict[str, Any]:
    assert response.status_code == expected, response.text
    if expected == 204:
        assert response.content == b""
        return {}
    content_type = response.headers.get("content-type", "")
    assert "application/json" in content_type
    return response.json()


def _assert_error_body(response: Response) -> dict[str, Any]:
    body = response.json()
    assert response.status_code >= 400, body
    assert "detail" in body or "error" in body
    return body


async def _register_actor(client: AsyncClient, prefix: str = "bb") -> Actor:
    username = _suffix(prefix).replace("-", "_")[:32]
    password = f"TestPass-{uuid4().hex[:16]}"
    response = await client.post(
        "/api/v1/auth/register",
        json={
            "username": username,
            "email": f"{username}@qaplatform.dev",
            "password": password,
        },
    )
    body = _assert_status(response, 201)
    assert body["token_type"] == "bearer"
    assert body["access_token"]
    assert body["user"]["username"] == username
    assert body["user"]["role"] == "owner"
    assert body["user"]["tenant_id"]
    return Actor(
        username=username,
        password=password,
        access_token=body["access_token"],
        user=body["user"],
    )


def _project_payload(
    slug: str,
    *,
    git_url: str | None = None,
    settings: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "name": slug,
        "slug": slug,
        "git_url": git_url or f"https://github.com/example/{slug}.git",
        "default_branch": "main",
    }
    if settings is not None:
        payload["settings"] = settings
    return payload


def _environment_payload(name: str) -> dict[str, Any]:
    return {
        "name": name,
        "base_image": "python:3.12-alpine",
        "memory_mb": 256,
        "cpu_cores": 0.5,
        "disk_mb": 1024,
        "max_artifact_size_mb": 10,
        "max_artifacts_count": 5,
        "network_policy": "restricted",
        "env_vars": {"API_TOKEN": f"env-{uuid4().hex}"},
        "cache_key": "deps-v1",
    }


def _pipeline_payload(name: str) -> dict[str, Any]:
    return {
        "name": name,
        "stages": [
            {
                "name": "run-tests",
                "plugin": "pytest",
                "phase": "execute",
                "config": {"args": ["tests/api"]},
            }
        ],
        "selector": {"include_paths": ["tests/api"], "on_empty": "warn"},
        "trigger_config": {"type": "manual", "source": {"branch": "main"}},
        "collectors": [
            {
                "plugin": "junit",
                "config": {"path": "results/junit.xml"},
                "enabled": True,
            }
        ],
        "timeout_seconds": 300,
        "retry_policy": {
            "max_attempts": 2,
            "retry_on": ["timeout"],
            "backoff_seconds": 1,
            "scope": "pipeline",
        },
        "enabled": True,
    }


def _schedule_payload(pipeline_id: str) -> dict[str, Any]:
    return {
        "pipeline_id": pipeline_id,
        "cron_expr": "*/15 * * * *",
        "timezone": "UTC",
        "enabled": True,
    }


def _notification_rule_payload(name: str) -> dict[str, Any]:
    return {
        "name": name,
        "conditions": [{"field": "status", "operator": "eq", "value": "failed"}],
        "channels": [
            {
                "type": "webhook",
                "config": {"url": "https://hooks.example.test/run"},
            }
        ],
    }


async def _create_project_stack(
    client: AsyncClient,
    actor: Actor,
    *,
    prefix: str = "stack",
    git_url: str | None = None,
    settings: dict[str, Any] | None = None,
) -> dict[str, dict[str, Any]]:
    factory = _test_data_factory(client)
    if factory is not None:
        return (
            await factory.create_project_stack(
                headers=actor.headers,
                prefix=prefix,
                git_url=git_url,
                settings=settings,
            )
        ).as_dict()

    slug = _suffix(prefix)
    project_response = await client.post(
        "/api/v1/projects",
        headers=actor.headers,
        json=_project_payload(slug, git_url=git_url, settings=settings),
    )
    project = _assert_status(project_response, 201)

    env_response = await client.post(
        f"/api/v1/projects/{project['id']}/environments",
        headers=actor.headers,
        json=_environment_payload(f"{slug}-env"),
    )
    environment = _assert_status(env_response, 201)

    default_env_response = await client.put(
        f"/api/v1/projects/{project['id']}",
        headers=actor.headers,
        json={"default_env_id": environment["id"]},
    )
    project = _assert_status(default_env_response, 200)

    pipeline_response = await client.post(
        f"/api/v1/projects/{project['id']}/pipelines",
        headers=actor.headers,
        json=_pipeline_payload(f"{slug}-pipeline"),
    )
    pipeline = _assert_status(pipeline_response, 201)
    return {"project": project, "environment": environment, "pipeline": pipeline}


async def _create_project(
    client: AsyncClient,
    actor: Actor,
    *,
    prefix: str = "project",
) -> dict[str, Any]:
    factory = _test_data_factory(client)
    if factory is not None:
        return await factory.create_project(headers=actor.headers, prefix=prefix)

    slug = _suffix(prefix)
    response = await client.post(
        "/api/v1/projects",
        headers=actor.headers,
        json=_project_payload(slug),
    )
    return _assert_status(response, 201)


async def _create_cross_tenant_resource_ids(
    client: AsyncClient,
) -> tuple[Actor, Actor, dict[str, str]]:
    actor_a = await _register_actor(client, "tenant_a")
    stack_a = await _create_project_stack(client, actor_a, prefix="tenant-a")
    project_a = stack_a["project"]
    pipeline_a = stack_a["pipeline"]
    environment_a = stack_a["environment"]

    credential_a = await _create_credential(client, actor_a, project_a["id"])
    schedule_a = await _create_schedule(
        client,
        actor_a,
        project_a["id"],
        pipeline_a["id"],
    )
    rule_a = await _create_notification_rule(client, actor_a, project_a["id"])
    factory = _test_data_factory(client)
    if factory is not None:
        run_a = await factory.trigger_run(
            headers=actor_a.headers,
            pipeline_id=pipeline_a["id"],
            environment_id=environment_a["id"],
        )
    else:
        run_response = await client.post(
            "/api/v1/runs",
            headers=actor_a.headers,
            json={
                "pipeline_id": pipeline_a["id"],
                "environment_id": environment_a["id"],
            },
        )
        run_a = _assert_status(run_response, 201)

    actor_b = await _register_actor(client, "tenant_b")
    ids = {
        "project_id": project_a["id"],
        "pipeline_id": pipeline_a["id"],
        "environment_id": environment_a["id"],
        "credential_id": credential_a["id"],
        "schedule_id": schedule_a["id"],
        "rule_id": rule_a["id"],
        "run_id": run_a["id"],
    }
    return actor_a, actor_b, ids


def _canonical_json_bytes(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()


def _webhook_signature(secret: str, payload: bytes) -> str:
    digest = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def _github_push_payload(repo_full_name: str, *, git_sha: str = FULL_SHA) -> dict[str, Any]:
    return {
        "ref": "refs/heads/main",
        "after": git_sha,
        "repository": {
            "full_name": repo_full_name,
            "clone_url": f"https://github.com/{repo_full_name}.git",
            "html_url": f"https://github.com/{repo_full_name}",
            "ssh_url": f"git@github.com:{repo_full_name}.git",
        },
    }


def _expired_access_token(actor: Actor, settings: Settings) -> str:
    payload = {
        "sub": actor.user["id"],
        "tenant_id": actor.user["tenant_id"],
        "role": actor.user["role"],
        "type": "access",
        "is_platform_admin": False,
        "exp": datetime.now(timezone.utc) - timedelta(seconds=1),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


async def _auth_success_register(client: AsyncClient) -> None:
    actor = await _register_actor(client, "auth_register")
    assert actor.access_token
    assert actor.user["role"] == "owner"


async def _auth_success_login(client: AsyncClient) -> None:
    actor = await _register_actor(client, "auth_login")
    login_response = await client.post(
        "/api/v1/auth/login",
        json={
            "username": actor.username,
            "password": actor.password,
            "tenant_id": actor.user["tenant_id"],
        },
    )
    login_body = _assert_status(login_response, 200)
    assert login_body["token_type"] == "bearer"
    assert login_body["user"]["id"] == actor.user["id"]


async def _auth_success_refresh(client: AsyncClient) -> None:
    actor = await _register_actor(client, "auth_refresh")
    await client.post(
        "/api/v1/auth/login",
        json={
            "username": actor.username,
            "password": actor.password,
            "tenant_id": actor.user["tenant_id"],
        },
    )
    refresh_response = await client.post("/api/v1/auth/refresh")
    refresh_body = _assert_status(refresh_response, 200)
    assert refresh_body["token_type"] == "bearer"
    assert refresh_body["access_token"]


async def _auth_success_logout(client: AsyncClient) -> None:
    actor = await _register_actor(client, "auth_logout")
    logout_response = await client.post(
        "/api/v1/auth/logout",
        headers=actor.headers,
    )
    _assert_status(logout_response, 204)


async def _auth_success_sse_ticket(client: AsyncClient) -> None:
    actor = await _register_actor(client, "auth_sse")
    ticket_response = await client.post(
        "/api/v1/auth/sse-ticket",
        headers=actor.headers,
    )
    ticket_body = _assert_status(ticket_response, 200)
    assert ticket_body["ticket"]


async def _auth_success_api_token_create(client: AsyncClient) -> None:
    actor = await _register_actor(client, "auth_token_create")
    token_response = await client.post(
        "/api/v1/auth/tokens",
        headers=actor.headers,
        json={"name": _suffix("api-token"), "scopes": ["project.read"]},
    )
    token_body = _assert_status(token_response, 201)
    assert token_body["token"].startswith("qap_")
    assert token_body["scopes"] == ["project.read"]


async def _auth_success_api_token_list(client: AsyncClient) -> None:
    actor = await _register_actor(client, "auth_token_list")
    token_response = await client.post(
        "/api/v1/auth/tokens",
        headers=actor.headers,
        json={"name": _suffix("api-token"), "scopes": ["project.read"]},
    )
    token_body = _assert_status(token_response, 201)
    list_response = await client.get("/api/v1/auth/tokens", headers=actor.headers)
    list_body = _assert_status(list_response, 200)
    assert any(item["token_id"] == token_body["token_id"] for item in list_body["data"])


async def _auth_success_api_token_delete(client: AsyncClient) -> None:
    actor = await _register_actor(client, "auth_token_delete")
    token_response = await client.post(
        "/api/v1/auth/tokens",
        headers=actor.headers,
        json={"name": _suffix("api-token"), "scopes": ["project.read"]},
    )
    token_body = _assert_status(token_response, 201)
    delete_response = await client.delete(
        f"/api/v1/auth/tokens/{token_body['token_id']}",
        headers=actor.headers,
    )
    _assert_status(delete_response, 204)


AUTH_SUCCESS_CASES: tuple[AuthSuccessCase, ...] = (
    AuthSuccessCase("post_api_v1_auth_register::success", _auth_success_register),
    AuthSuccessCase("post_api_v1_auth_login::success", _auth_success_login),
    AuthSuccessCase("post_api_v1_auth_refresh::success", _auth_success_refresh),
    AuthSuccessCase("post_api_v1_auth_logout::success", _auth_success_logout),
    AuthSuccessCase("post_api_v1_auth_sse_ticket::success", _auth_success_sse_ticket),
    AuthSuccessCase("post_api_v1_auth_tokens::success", _auth_success_api_token_create),
    AuthSuccessCase("get_api_v1_auth_tokens::success", _auth_success_api_token_list),
    AuthSuccessCase(
        "delete_api_v1_auth_tokens_token_id::success",
        _auth_success_api_token_delete,
    ),
)


def _auth_success_case_id(case: AuthSuccessCase) -> str:
    return case.case_id


async def _resource_success_project_list(client: AsyncClient) -> None:
    actor = await _register_actor(client, "success_project_list")
    project = await _create_project(client, actor, prefix="success-list")
    response = await client.get(
        "/api/v1/projects",
        headers=actor.headers,
        params={"q": project["slug"], "page": 1, "per_page": 5},
    )
    body = _assert_status(response, 200)
    assert any(item["id"] == project["id"] for item in body["data"])


async def _resource_success_project_create(client: AsyncClient) -> None:
    actor = await _register_actor(client, "success_project_create")
    project = await _create_project(client, actor, prefix="success-create")
    assert project["slug"].startswith("success-create-")
    assert project["status"] == "active"


async def _resource_success_project_get(client: AsyncClient) -> None:
    actor = await _register_actor(client, "success_project_get")
    project = await _create_project(client, actor, prefix="success-get")
    response = await client.get(
        f"/api/v1/projects/{project['id']}",
        headers=actor.headers,
    )
    assert _assert_status(response, 200)["id"] == project["id"]


async def _resource_success_project_update(client: AsyncClient) -> None:
    actor = await _register_actor(client, "success_project_update")
    project = await _create_project(client, actor, prefix="success-update")
    response = await client.put(
        f"/api/v1/projects/{project['id']}",
        headers=actor.headers,
        json={"description": "atomic success update"},
    )
    updated = _assert_status(response, 200)
    assert updated["description"] == "atomic success update"


async def _resource_success_project_delete(client: AsyncClient) -> None:
    actor = await _register_actor(client, "success_project_delete")
    project = await _create_project(client, actor, prefix="success-delete")
    response = await client.delete(
        f"/api/v1/projects/{project['id']}",
        headers=actor.headers,
    )
    _assert_status(response, 204)


async def _resource_success_project_members_list(client: AsyncClient) -> None:
    actor = await _register_actor(client, "success_members")
    project = await _create_project(client, actor, prefix="success-members")
    response = await client.get(
        f"/api/v1/projects/{project['id']}/members",
        headers=actor.headers,
    )
    body = _assert_status(response, 200)
    assert any(item["user_id"] == actor.user["id"] for item in body["data"])


async def _create_credential(
    client: AsyncClient,
    actor: Actor,
    project_id: str,
) -> dict[str, Any]:
    factory = _test_data_factory(client)
    if factory is not None:
        return await factory.create_credential(
            headers=actor.headers,
            project_id=project_id,
        )

    response = await client.post(
        f"/api/v1/projects/{project_id}/credentials",
        headers=actor.headers,
        json={"name": _suffix("cred"), "type": "token", "value": "secret"},
    )
    return _assert_status(response, 201)


async def _resource_success_credential_create(client: AsyncClient) -> None:
    actor = await _register_actor(client, "success_cred_create")
    project = await _create_project(client, actor, prefix="success-cred-create")
    credential = await _create_credential(client, actor, project["id"])
    assert credential["type"] == "token"
    assert "secret" not in credential


async def _resource_success_credential_list(client: AsyncClient) -> None:
    actor = await _register_actor(client, "success_cred_list")
    project = await _create_project(client, actor, prefix="success-cred-list")
    credential = await _create_credential(client, actor, project["id"])
    response = await client.get(
        f"/api/v1/projects/{project['id']}/credentials",
        headers=actor.headers,
    )
    body = _assert_status(response, 200)
    assert any(item["id"] == credential["id"] for item in body["data"])


async def _resource_success_credential_get(client: AsyncClient) -> None:
    actor = await _register_actor(client, "success_cred_get")
    project = await _create_project(client, actor, prefix="success-cred-get")
    credential = await _create_credential(client, actor, project["id"])
    response = await client.get(
        f"/api/v1/projects/{project['id']}/credentials/{credential['id']}",
        headers=actor.headers,
    )
    assert _assert_status(response, 200)["id"] == credential["id"]


async def _resource_success_credential_update(client: AsyncClient) -> None:
    actor = await _register_actor(client, "success_cred_update")
    project = await _create_project(client, actor, prefix="success-cred-update")
    credential = await _create_credential(client, actor, project["id"])
    response = await client.put(
        f"/api/v1/projects/{project['id']}/credentials/{credential['id']}",
        headers=actor.headers,
        json={"value": "rotated"},
    )
    assert _assert_status(response, 200)["id"] == credential["id"]


async def _resource_success_credential_delete(client: AsyncClient) -> None:
    actor = await _register_actor(client, "success_cred_delete")
    project = await _create_project(client, actor, prefix="success-cred-delete")
    credential = await _create_credential(client, actor, project["id"])
    response = await client.delete(
        f"/api/v1/projects/{project['id']}/credentials/{credential['id']}",
        headers=actor.headers,
    )
    _assert_status(response, 204)


async def _create_environment(
    client: AsyncClient,
    actor: Actor,
    project_id: str,
) -> dict[str, Any]:
    factory = _test_data_factory(client)
    if factory is not None:
        return await factory.create_environment(
            headers=actor.headers,
            project_id=project_id,
        )

    response = await client.post(
        f"/api/v1/projects/{project_id}/environments",
        headers=actor.headers,
        json=_environment_payload(_suffix("env")),
    )
    return _assert_status(response, 201)


async def _resource_success_environment_create(client: AsyncClient) -> None:
    actor = await _register_actor(client, "success_env_create")
    project = await _create_project(client, actor, prefix="success-env-create")
    environment = await _create_environment(client, actor, project["id"])
    assert environment["memory_mb"] == 256


async def _resource_success_environment_list(client: AsyncClient) -> None:
    actor = await _register_actor(client, "success_env_list")
    project = await _create_project(client, actor, prefix="success-env-list")
    environment = await _create_environment(client, actor, project["id"])
    response = await client.get(
        f"/api/v1/projects/{project['id']}/environments",
        headers=actor.headers,
    )
    body = _assert_status(response, 200)
    assert any(item["id"] == environment["id"] for item in body["data"])


async def _resource_success_environment_get(client: AsyncClient) -> None:
    actor = await _register_actor(client, "success_env_get")
    project = await _create_project(client, actor, prefix="success-env-get")
    environment = await _create_environment(client, actor, project["id"])
    response = await client.get(
        f"/api/v1/projects/{project['id']}/environments/{environment['id']}",
        headers=actor.headers,
    )
    assert _assert_status(response, 200)["id"] == environment["id"]


async def _resource_success_environment_update(client: AsyncClient) -> None:
    actor = await _register_actor(client, "success_env_update")
    project = await _create_project(client, actor, prefix="success-env-update")
    environment = await _create_environment(client, actor, project["id"])
    response = await client.put(
        f"/api/v1/projects/{project['id']}/environments/{environment['id']}",
        headers=actor.headers,
        json={"memory_mb": 384},
    )
    assert _assert_status(response, 200)["memory_mb"] == 384


async def _resource_success_environment_delete(client: AsyncClient) -> None:
    actor = await _register_actor(client, "success_env_delete")
    project = await _create_project(client, actor, prefix="success-env-delete")
    environment = await _create_environment(client, actor, project["id"])
    response = await client.delete(
        f"/api/v1/projects/{project['id']}/environments/{environment['id']}",
        headers=actor.headers,
    )
    _assert_status(response, 204)


async def _resource_success_audit_events_list(client: AsyncClient) -> None:
    actor = await _register_actor(client, "success_audit")
    project = await _create_project(client, actor, prefix="success-audit")
    response = await client.get(
        "/api/v1/audit-events",
        headers=actor.headers,
        params={
            "action": "project.create",
            "resource_type": "project",
            "resource_id": project["id"],
        },
    )
    body = _assert_status(response, 200)
    assert any(item["resource_id"] == project["id"] for item in body["data"])


async def _create_pipeline(
    client: AsyncClient,
    actor: Actor,
    project_id: str,
) -> dict[str, Any]:
    factory = _test_data_factory(client)
    if factory is not None:
        return await factory.create_pipeline(
            headers=actor.headers,
            project_id=project_id,
        )

    response = await client.post(
        f"/api/v1/projects/{project_id}/pipelines",
        headers=actor.headers,
        json=_pipeline_payload(_suffix("pipeline")),
    )
    return _assert_status(response, 201)


async def _resource_success_pipeline_create(client: AsyncClient) -> None:
    actor = await _register_actor(client, "success_pipe_create")
    project = await _create_project(client, actor, prefix="success-pipe-create")
    pipeline = await _create_pipeline(client, actor, project["id"])
    assert pipeline["enabled"] is True


async def _resource_success_pipeline_list(client: AsyncClient) -> None:
    actor = await _register_actor(client, "success_pipe_list")
    project = await _create_project(client, actor, prefix="success-pipe-list")
    pipeline = await _create_pipeline(client, actor, project["id"])
    response = await client.get(
        f"/api/v1/projects/{project['id']}/pipelines",
        headers=actor.headers,
    )
    body = _assert_status(response, 200)
    assert any(item["id"] == pipeline["id"] for item in body["data"])


async def _resource_success_pipeline_get(client: AsyncClient) -> None:
    actor = await _register_actor(client, "success_pipe_get")
    project = await _create_project(client, actor, prefix="success-pipe-get")
    pipeline = await _create_pipeline(client, actor, project["id"])
    response = await client.get(
        f"/api/v1/projects/{project['id']}/pipelines/{pipeline['id']}",
        headers=actor.headers,
    )
    assert _assert_status(response, 200)["id"] == pipeline["id"]


async def _resource_success_pipeline_update(client: AsyncClient) -> None:
    actor = await _register_actor(client, "success_pipe_update")
    project = await _create_project(client, actor, prefix="success-pipe-update")
    pipeline = await _create_pipeline(client, actor, project["id"])
    response = await client.put(
        f"/api/v1/projects/{project['id']}/pipelines/{pipeline['id']}",
        headers=actor.headers,
        json={"enabled": False},
    )
    assert _assert_status(response, 200)["enabled"] is False


async def _resource_success_pipeline_delete(client: AsyncClient) -> None:
    actor = await _register_actor(client, "success_pipe_delete")
    project = await _create_project(client, actor, prefix="success-pipe-delete")
    pipeline = await _create_pipeline(client, actor, project["id"])
    response = await client.delete(
        f"/api/v1/projects/{project['id']}/pipelines/{pipeline['id']}",
        headers=actor.headers,
    )
    _assert_status(response, 204)


async def _create_schedule(
    client: AsyncClient,
    actor: Actor,
    project_id: str,
    pipeline_id: str,
) -> dict[str, Any]:
    factory = _test_data_factory(client)
    if factory is not None:
        return await factory.create_schedule(
            headers=actor.headers,
            project_id=project_id,
            pipeline_id=pipeline_id,
        )

    response = await client.post(
        f"/api/v1/projects/{project_id}/schedules",
        headers=actor.headers,
        json=_schedule_payload(pipeline_id),
    )
    return _assert_status(response, 201)


async def _resource_success_schedule_create(client: AsyncClient) -> None:
    actor = await _register_actor(client, "success_sched_create")
    stack = await _create_project_stack(client, actor, prefix="success-sched-create")
    schedule = await _create_schedule(
        client,
        actor,
        stack["project"]["id"],
        stack["pipeline"]["id"],
    )
    assert schedule["enabled"] is True


async def _resource_success_schedule_list(client: AsyncClient) -> None:
    actor = await _register_actor(client, "success_sched_list")
    stack = await _create_project_stack(client, actor, prefix="success-sched-list")
    schedule = await _create_schedule(
        client,
        actor,
        stack["project"]["id"],
        stack["pipeline"]["id"],
    )
    response = await client.get(
        f"/api/v1/projects/{stack['project']['id']}/schedules",
        headers=actor.headers,
    )
    body = _assert_status(response, 200)
    assert any(item["id"] == schedule["id"] for item in body["data"])


async def _resource_success_schedule_get(client: AsyncClient) -> None:
    actor = await _register_actor(client, "success_sched_get")
    stack = await _create_project_stack(client, actor, prefix="success-sched-get")
    schedule = await _create_schedule(
        client,
        actor,
        stack["project"]["id"],
        stack["pipeline"]["id"],
    )
    response = await client.get(
        f"/api/v1/projects/{stack['project']['id']}/schedules/{schedule['id']}",
        headers=actor.headers,
    )
    assert _assert_status(response, 200)["id"] == schedule["id"]


async def _resource_success_schedule_update(client: AsyncClient) -> None:
    actor = await _register_actor(client, "success_sched_update")
    stack = await _create_project_stack(client, actor, prefix="success-sched-update")
    schedule = await _create_schedule(
        client,
        actor,
        stack["project"]["id"],
        stack["pipeline"]["id"],
    )
    response = await client.put(
        f"/api/v1/projects/{stack['project']['id']}/schedules/{schedule['id']}",
        headers=actor.headers,
        json={"enabled": False},
    )
    assert _assert_status(response, 200)["enabled"] is False


async def _resource_success_schedule_delete(client: AsyncClient) -> None:
    actor = await _register_actor(client, "success_sched_delete")
    stack = await _create_project_stack(client, actor, prefix="success-sched-delete")
    schedule = await _create_schedule(
        client,
        actor,
        stack["project"]["id"],
        stack["pipeline"]["id"],
    )
    response = await client.delete(
        f"/api/v1/projects/{stack['project']['id']}/schedules/{schedule['id']}",
        headers=actor.headers,
    )
    _assert_status(response, 204)


async def _create_notification_rule(
    client: AsyncClient,
    actor: Actor,
    project_id: str,
) -> dict[str, Any]:
    factory = _test_data_factory(client)
    if factory is not None:
        return await factory.create_notification_rule(
            headers=actor.headers,
            project_id=project_id,
        )

    response = await client.post(
        f"/api/v1/projects/{project_id}/notification-rules",
        headers=actor.headers,
        json=_notification_rule_payload(_suffix("notify")),
    )
    return _assert_status(response, 201)


async def _resource_success_notification_create(client: AsyncClient) -> None:
    actor = await _register_actor(client, "success_notify_create")
    project = await _create_project(client, actor, prefix="success-notify-create")
    rule = await _create_notification_rule(client, actor, project["id"])
    assert rule["enabled"] is True


async def _resource_success_notification_list(client: AsyncClient) -> None:
    actor = await _register_actor(client, "success_notify_list")
    project = await _create_project(client, actor, prefix="success-notify-list")
    rule = await _create_notification_rule(client, actor, project["id"])
    response = await client.get(
        f"/api/v1/projects/{project['id']}/notification-rules",
        headers=actor.headers,
    )
    body = _assert_status(response, 200)
    assert any(item["id"] == rule["id"] for item in body["data"])


async def _resource_success_notification_get(client: AsyncClient) -> None:
    actor = await _register_actor(client, "success_notify_get")
    project = await _create_project(client, actor, prefix="success-notify-get")
    rule = await _create_notification_rule(client, actor, project["id"])
    response = await client.get(
        f"/api/v1/projects/{project['id']}/notification-rules/{rule['id']}",
        headers=actor.headers,
    )
    assert _assert_status(response, 200)["id"] == rule["id"]


async def _resource_success_notification_update(client: AsyncClient) -> None:
    actor = await _register_actor(client, "success_notify_update")
    project = await _create_project(client, actor, prefix="success-notify-update")
    rule = await _create_notification_rule(client, actor, project["id"])
    response = await client.put(
        f"/api/v1/projects/{project['id']}/notification-rules/{rule['id']}",
        headers=actor.headers,
        json={"enabled": False},
    )
    assert _assert_status(response, 200)["enabled"] is False


async def _resource_success_notification_delete(client: AsyncClient) -> None:
    actor = await _register_actor(client, "success_notify_delete")
    project = await _create_project(client, actor, prefix="success-notify-delete")
    rule = await _create_notification_rule(client, actor, project["id"])
    response = await client.delete(
        f"/api/v1/projects/{project['id']}/notification-rules/{rule['id']}",
        headers=actor.headers,
    )
    _assert_status(response, 204)


async def _trigger_run(
    client: AsyncClient,
    actor: Actor,
    *,
    prefix: str,
) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    stack = await _create_project_stack(client, actor, prefix=prefix)
    factory = _test_data_factory(client)
    if factory is not None:
        run = await factory.trigger_run(
            headers=actor.headers,
            pipeline_id=stack["pipeline"]["id"],
            environment_id=stack["environment"]["id"],
            payload_overrides={"git_sha": FULL_SHA},
        )
    else:
        response = await client.post(
            "/api/v1/runs",
            headers=actor.headers,
            json={
                "pipeline_id": stack["pipeline"]["id"],
                "environment_id": stack["environment"]["id"],
                "git_ref": "main",
                "git_sha": FULL_SHA,
            },
        )
        run = _assert_status(response, 201)
    return stack, run


async def _resource_success_run_trigger(client: AsyncClient) -> None:
    actor = await _register_actor(client, "success_run_trigger")
    stack, run = await _trigger_run(client, actor, prefix="success-run-trigger")
    assert run["project_id"] == stack["project"]["id"]
    assert run["pipeline_id"] == stack["pipeline"]["id"]


async def _resource_success_run_get(client: AsyncClient) -> None:
    actor = await _register_actor(client, "success_run_get")
    _stack, run = await _trigger_run(client, actor, prefix="success-run-get")
    response = await client.get(f"/api/v1/runs/{run['id']}", headers=actor.headers)
    assert _assert_status(response, 200)["id"] == run["id"]


async def _resource_success_runs_list(client: AsyncClient) -> None:
    actor = await _register_actor(client, "success_runs_list")
    stack, run = await _trigger_run(client, actor, prefix="success-runs-list")
    response = await client.get(
        "/api/v1/runs",
        headers=actor.headers,
        params={
            "project_id": stack["project"]["id"],
            "pipeline_id": stack["pipeline"]["id"],
            "status": run["status"],
        },
    )
    body = _assert_status(response, 200)
    assert any(item["id"] == run["id"] for item in body["data"])


async def _resource_success_run_results_list(client: AsyncClient) -> None:
    actor = await _register_actor(client, "success_run_results")
    _stack, run = await _trigger_run(client, actor, prefix="success-run-results")
    response = await client.get(
        f"/api/v1/runs/{run['id']}/results",
        headers=actor.headers,
    )
    assert _assert_status(response, 200)["data"] == []


async def _resource_success_run_artifacts_list(client: AsyncClient) -> None:
    actor = await _register_actor(client, "success_run_artifacts")
    _stack, run = await _trigger_run(client, actor, prefix="success-run-artifacts")
    response = await client.get(
        f"/api/v1/runs/{run['id']}/artifacts",
        headers=actor.headers,
    )
    assert _assert_status(response, 200)["data"] == []


async def _resource_success_run_notifications_list(client: AsyncClient) -> None:
    actor = await _register_actor(client, "success_run_notifications")
    _stack, run = await _trigger_run(client, actor, prefix="success-run-notifications")
    response = await client.get(
        f"/api/v1/runs/{run['id']}/notifications",
        headers=actor.headers,
    )
    assert _assert_status(response, 200)["data"] == []


async def _resource_success_run_cancel(client: AsyncClient) -> None:
    actor = await _register_actor(client, "success_run_cancel")
    _stack, run = await _trigger_run(client, actor, prefix="success-run-cancel")
    response = await client.post(
        f"/api/v1/runs/{run['id']}/cancel",
        headers=actor.headers,
        json={"reason": "atomic success cancel"},
    )
    assert _assert_status(response, 200)["id"] == run["id"]


async def _resource_success_run_batch_cancel(client: AsyncClient) -> None:
    actor = await _register_actor(client, "success_batch_cancel")
    _stack, run = await _trigger_run(client, actor, prefix="success-batch-cancel")
    response = await client.post(
        "/api/v1/runs/batch/cancel",
        headers=actor.headers,
        json={"run_ids": [run["id"]]},
    )
    body = _assert_status(response, 200)
    assert body == {"processed": 1, "failed": 0, "errors": []}


async def _resource_success_run_batch_retry(client: AsyncClient) -> None:
    actor = await _register_actor(client, "success_batch_retry")
    _stack, run = await _trigger_run(client, actor, prefix="success-batch-retry")
    cancel_response = await client.post(
        f"/api/v1/runs/{run['id']}/cancel",
        headers=actor.headers,
        json={"reason": "prepare retry"},
    )
    _assert_status(cancel_response, 200)
    response = await client.post(
        "/api/v1/runs/batch/retry",
        headers=actor.headers,
        json={"run_ids": [run["id"]]},
    )
    body = _assert_status(response, 200)
    assert body == {"processed": 1, "failed": 0, "errors": []}


async def _resource_success_run_events_stream(client: AsyncClient) -> None:
    actor = await _register_actor(client, "success_run_events")
    _stack, run = await _trigger_run(client, actor, prefix="success-run-events")
    ticket_response = await client.post(
        "/api/v1/auth/sse-ticket",
        headers=actor.headers,
    )
    ticket = _assert_status(ticket_response, 200)["ticket"]
    cancel_response = await client.post(
        f"/api/v1/runs/{run['id']}/cancel",
        headers=actor.headers,
        json={"reason": "emit event"},
    )
    _assert_status(cancel_response, 200)
    response = await client.get(
        f"/api/v1/runs/{run['id']}/events",
        params={"ticket": ticket},
        timeout=10,
    )
    assert response.status_code == 200, response.text
    assert "text/event-stream" in response.headers.get("content-type", "")
    assert "status_change" in response.text


async def _resource_success_run_logs_stream(client: AsyncClient) -> None:
    actor = await _register_actor(client, "success_run_logs")
    _stack, run = await _trigger_run(client, actor, prefix="success-run-logs")
    cancel_response = await client.post(
        f"/api/v1/runs/{run['id']}/cancel",
        headers=actor.headers,
        json={"reason": "emit log completion"},
    )
    _assert_status(cancel_response, 200)
    ticket_response = await client.post(
        "/api/v1/auth/sse-ticket",
        headers=actor.headers,
    )
    ticket = _assert_status(ticket_response, 200)["ticket"]
    response = await client.get(
        f"/api/v1/runs/{run['id']}/logs",
        params={"ticket": ticket},
        timeout=10,
    )
    assert response.status_code == 200, response.text
    assert "text/event-stream" in response.headers.get("content-type", "")
    assert "done" in response.text


async def _signed_webhook_setup(
    client: AsyncClient,
    actor: Actor,
    *,
    prefix: str,
) -> tuple[dict[str, Any], bytes, dict[str, str], str]:
    secret = _suffix("secret")
    repo_name = f"acme/{_suffix(prefix)}"
    repo_url = f"https://github.com/{repo_name}.git"
    stack = await _create_project_stack(
        client,
        actor,
        prefix=prefix,
        git_url=repo_url,
        settings={"webhook_secret": secret, "allowed_branches": ["main"]},
    )
    payload = _github_push_payload(repo_name)
    raw_body = _canonical_json_bytes(payload)
    headers = {
        "content-type": "application/json",
        "X-GitHub-Event": "push",
        "X-GitHub-Delivery": _suffix("delivery"),
        "X-Hub-Signature-256": _webhook_signature(secret, raw_body),
    }
    return stack["project"], raw_body, headers, secret


async def _resource_success_provider_webhook(client: AsyncClient) -> None:
    actor = await _register_actor(client, "success_provider_hook")
    _project, raw_body, headers, _secret = await _signed_webhook_setup(
        client,
        actor,
        prefix="success-provider-hook",
    )
    response = await client.post("/webhooks/github", content=raw_body, headers=headers)
    run = _assert_status(response, 201)
    assert run["trigger_type"] == "webhook"
    assert run["git_sha"] == FULL_SHA


async def _resource_success_provider_webhook_duplicate(client: AsyncClient) -> None:
    actor = await _register_actor(client, "success_provider_dup")
    _project, raw_body, headers, _secret = await _signed_webhook_setup(
        client,
        actor,
        prefix="success-provider-dup",
    )
    first_response = await client.post("/webhooks/github", content=raw_body, headers=headers)
    _assert_status(first_response, 201)
    response = await client.post("/webhooks/github", content=raw_body, headers=headers)
    assert _assert_status(response, 200)["status"] == "duplicate"


async def _resource_success_api_v1_provider_webhook(client: AsyncClient) -> None:
    actor = await _register_actor(client, "success_api_provider")
    _project, raw_body, headers, _secret = await _signed_webhook_setup(
        client,
        actor,
        prefix="success-api-provider",
    )
    response = await client.post(
        "/api/v1/webhooks/github",
        content=raw_body,
        headers=headers,
    )
    run = _assert_status(response, 201)
    assert run["trigger_type"] == "webhook"


async def _resource_success_project_webhook(client: AsyncClient) -> None:
    actor = await _register_actor(client, "success_project_hook")
    project, _raw_body, _headers, secret = await _signed_webhook_setup(
        client,
        actor,
        prefix="success-project-hook",
    )
    payload = {
        "git_ref": "refs/heads/main",
        "git_sha": "d" * 40,
        "metadata": {"provider": "github", "delivery_id": _suffix("delivery")},
    }
    raw_body = _canonical_json_bytes(payload)
    response = await client.post(
        f"/api/v1/webhooks/{project['id']}/trigger",
        headers={
            **actor.headers,
            "content-type": "application/json",
            "X-Webhook-Signature": _webhook_signature(secret, raw_body),
        },
        content=raw_body,
    )
    run = _assert_status(response, 201)
    assert run["trigger_type"] == "webhook"
    assert run["git_sha"] == "d" * 40


async def _resource_success_project_webhook_duplicate(client: AsyncClient) -> None:
    actor = await _register_actor(client, "success_project_dup")
    stack = await _create_project_stack(client, actor, prefix="success-project-dup")
    project = stack["project"]
    payload = {
        "git_ref": "refs/heads/main",
        "git_sha": "e" * 40,
        "metadata": {"provider": "github", "delivery_id": _suffix("delivery")},
    }
    first_response = await client.post(
        f"/api/v1/webhooks/{project['id']}/trigger",
        headers=actor.headers,
        json=payload,
    )
    _assert_status(first_response, 201)
    response = await client.post(
        f"/api/v1/webhooks/{project['id']}/trigger",
        headers=actor.headers,
        json=payload,
    )
    assert _assert_status(response, 200)["status"] == "duplicate"


RESOURCE_SUCCESS_CASES: tuple[ResourceSuccessCase, ...] = (
    ResourceSuccessCase("get_api_v1_projects::success", _resource_success_project_list),
    ResourceSuccessCase("post_api_v1_projects::success", _resource_success_project_create),
    ResourceSuccessCase(
        "get_api_v1_projects_project_id::success",
        _resource_success_project_get,
    ),
    ResourceSuccessCase(
        "put_api_v1_projects_project_id::success",
        _resource_success_project_update,
    ),
    ResourceSuccessCase(
        "delete_api_v1_projects_project_id::success",
        _resource_success_project_delete,
    ),
    ResourceSuccessCase(
        "get_api_v1_projects_project_id_members::success",
        _resource_success_project_members_list,
    ),
    ResourceSuccessCase(
        "post_api_v1_projects_project_id_credentials::success",
        _resource_success_credential_create,
    ),
    ResourceSuccessCase(
        "get_api_v1_projects_project_id_credentials::success",
        _resource_success_credential_list,
    ),
    ResourceSuccessCase(
        "get_api_v1_projects_project_id_credentials_credential_id::success",
        _resource_success_credential_get,
    ),
    ResourceSuccessCase(
        "put_api_v1_projects_project_id_credentials_credential_id::success",
        _resource_success_credential_update,
    ),
    ResourceSuccessCase(
        "delete_api_v1_projects_project_id_credentials_credential_id::success",
        _resource_success_credential_delete,
    ),
    ResourceSuccessCase(
        "post_api_v1_projects_project_id_environments::success",
        _resource_success_environment_create,
    ),
    ResourceSuccessCase(
        "get_api_v1_projects_project_id_environments::success",
        _resource_success_environment_list,
    ),
    ResourceSuccessCase(
        "get_api_v1_projects_project_id_environments_env_id::success",
        _resource_success_environment_get,
    ),
    ResourceSuccessCase(
        "put_api_v1_projects_project_id_environments_env_id::success",
        _resource_success_environment_update,
    ),
    ResourceSuccessCase(
        "delete_api_v1_projects_project_id_environments_env_id::success",
        _resource_success_environment_delete,
    ),
    ResourceSuccessCase(
        "post_api_v1_projects_project_id_pipelines::success",
        _resource_success_pipeline_create,
    ),
    ResourceSuccessCase(
        "get_api_v1_projects_project_id_pipelines::success",
        _resource_success_pipeline_list,
    ),
    ResourceSuccessCase(
        "get_api_v1_projects_project_id_pipelines_pipeline_id::success",
        _resource_success_pipeline_get,
    ),
    ResourceSuccessCase(
        "put_api_v1_projects_project_id_pipelines_pipeline_id::success",
        _resource_success_pipeline_update,
    ),
    ResourceSuccessCase(
        "delete_api_v1_projects_project_id_pipelines_pipeline_id::success",
        _resource_success_pipeline_delete,
    ),
    ResourceSuccessCase(
        "post_api_v1_projects_project_id_schedules::success",
        _resource_success_schedule_create,
    ),
    ResourceSuccessCase(
        "get_api_v1_projects_project_id_schedules::success",
        _resource_success_schedule_list,
    ),
    ResourceSuccessCase(
        "get_api_v1_projects_project_id_schedules_schedule_id::success",
        _resource_success_schedule_get,
    ),
    ResourceSuccessCase(
        "put_api_v1_projects_project_id_schedules_schedule_id::success",
        _resource_success_schedule_update,
    ),
    ResourceSuccessCase(
        "delete_api_v1_projects_project_id_schedules_schedule_id::success",
        _resource_success_schedule_delete,
    ),
    ResourceSuccessCase(
        "post_api_v1_projects_project_id_notification_rules::success",
        _resource_success_notification_create,
    ),
    ResourceSuccessCase(
        "get_api_v1_projects_project_id_notification_rules::success",
        _resource_success_notification_list,
    ),
    ResourceSuccessCase(
        "get_api_v1_projects_project_id_notification_rules_rule_id::success",
        _resource_success_notification_get,
    ),
    ResourceSuccessCase(
        "put_api_v1_projects_project_id_notification_rules_rule_id::success",
        _resource_success_notification_update,
    ),
    ResourceSuccessCase(
        "delete_api_v1_projects_project_id_notification_rules_rule_id::success",
        _resource_success_notification_delete,
    ),
    ResourceSuccessCase("post_api_v1_runs::success", _resource_success_run_trigger),
    ResourceSuccessCase("get_api_v1_runs_run_id::success", _resource_success_run_get),
    ResourceSuccessCase("get_api_v1_runs::success", _resource_success_runs_list),
    ResourceSuccessCase(
        "get_api_v1_runs_run_id_results::success",
        _resource_success_run_results_list,
    ),
    ResourceSuccessCase(
        "get_api_v1_runs_run_id_artifacts::success",
        _resource_success_run_artifacts_list,
    ),
    ResourceSuccessCase(
        "get_api_v1_runs_run_id_notifications::success",
        _resource_success_run_notifications_list,
    ),
    ResourceSuccessCase(
        "post_api_v1_runs_run_id_cancel::success",
        _resource_success_run_cancel,
    ),
    ResourceSuccessCase(
        "post_api_v1_runs_batch_cancel::success",
        _resource_success_run_batch_cancel,
    ),
    ResourceSuccessCase(
        "post_api_v1_runs_batch_retry::success",
        _resource_success_run_batch_retry,
    ),
    ResourceSuccessCase(
        "get_api_v1_runs_run_id_events::success",
        _resource_success_run_events_stream,
    ),
    ResourceSuccessCase(
        "get_api_v1_runs_run_id_logs::success",
        _resource_success_run_logs_stream,
    ),
    ResourceSuccessCase(
        "post_webhooks_provider::success::signed_push",
        _resource_success_provider_webhook,
    ),
    ResourceSuccessCase(
        "post_webhooks_provider::success::duplicate_delivery",
        _resource_success_provider_webhook_duplicate,
    ),
    ResourceSuccessCase(
        "post_api_v1_webhooks_provider::success::signed_push",
        _resource_success_api_v1_provider_webhook,
    ),
    ResourceSuccessCase(
        "post_api_v1_webhooks_project_id_trigger::success::signed_delivery",
        _resource_success_project_webhook,
    ),
    ResourceSuccessCase(
        "post_api_v1_webhooks_project_id_trigger::success::duplicate_delivery",
        _resource_success_project_webhook_duplicate,
    ),
    ResourceSuccessCase("get_api_v1_audit_events::success", _resource_success_audit_events_list),
)


def _resource_success_case_id(case: ResourceSuccessCase) -> str:
    return case.case_id


SCHEMA_NEGATIVE_CASES: tuple[SchemaNegativeCase, ...] = (
    SchemaNegativeCase(
        "post_api_v1_auth_register::schema_negative::missing_password",
        "POST",
        "/api/v1/auth/register",
        lambda _actor, _ids, _duplicate_run_id: {
            "json": {
                "username": _suffix("missing").replace("-", "_")[:32],
                "email": "missing@qaplatform.dev",
            }
        },
    ),
    SchemaNegativeCase(
        "post_api_v1_auth_register::schema_negative::invalid_username",
        "POST",
        "/api/v1/auth/register",
        lambda _actor, _ids, _duplicate_run_id: {
            "json": {
                "username": "bad-name",
                "email": "bad-name@qaplatform.dev",
                "password": "ValidPass123",
            }
        },
    ),
    SchemaNegativeCase(
        "post_api_v1_projects::schema_negative::invalid_git_auth_method",
        "POST",
        "/api/v1/projects",
        lambda actor, _ids, _duplicate_run_id: {
            "headers": actor.headers,
            "json": {
                **_project_payload(_suffix("bad-enum")),
                "git_auth_method": "oauth",
            },
        },
    ),
    SchemaNegativeCase(
        "post_api_v1_projects::schema_negative::name_too_long",
        "POST",
        "/api/v1/projects",
        lambda actor, _ids, _duplicate_run_id: {
            "headers": actor.headers,
            "json": {
                **_project_payload(_suffix("long-name")),
                "name": "x" * 101,
            },
        },
    ),
    SchemaNegativeCase(
        "post_api_v1_projects_branches::schema_negative::missing_body",
        "POST",
        "/api/v1/projects/branches",
        lambda actor, _ids, _duplicate_run_id: {
            "headers": actor.headers,
            "json": {},
        },
    ),
    SchemaNegativeCase(
        "post_api_v1_projects_branches::schema_negative::token_auth_rejected",
        "POST",
        "/api/v1/projects/branches",
        lambda actor, _ids, _duplicate_run_id: {
            "headers": actor.headers,
            "json": {
                "git_url": "https://github.com/example/repo.git",
                "git_auth_method": "token",
            },
        },
    ),
    SchemaNegativeCase(
        "post_api_v1_projects_branches::schema_negative::file_url_rejected",
        "POST",
        "/api/v1/projects/branches",
        lambda actor, _ids, _duplicate_run_id: {
            "headers": actor.headers,
            "json": {
                "git_url": "file:///tmp/repo.git",
                "git_auth_method": "none",
            },
        },
    ),
    SchemaNegativeCase(
        "get_api_v1_projects_project_id::schema_negative::invalid_uuid",
        "GET",
        "/api/v1/projects/not-a-uuid",
        lambda actor, _ids, _duplicate_run_id: {"headers": actor.headers},
    ),
    SchemaNegativeCase(
        "get_api_v1_projects::schema_negative::page_below_minimum",
        "GET",
        "/api/v1/projects",
        lambda actor, _ids, _duplicate_run_id: {
            "headers": actor.headers,
            "params": {"page": 0},
        },
    ),
    SchemaNegativeCase(
        "get_api_v1_projects::schema_negative::page_not_integer",
        "GET",
        "/api/v1/projects",
        lambda actor, _ids, _duplicate_run_id: {
            "headers": actor.headers,
            "params": {"page": "not-a-number"},
        },
    ),
    SchemaNegativeCase(
        "get_api_v1_projects::schema_negative::per_page_above_maximum",
        "GET",
        "/api/v1/projects",
        lambda actor, _ids, _duplicate_run_id: {
            "headers": actor.headers,
            "params": {"per_page": 101},
        },
    ),
    SchemaNegativeCase(
        "get_api_v1_projects::schema_negative::invalid_status",
        "GET",
        "/api/v1/projects",
        lambda actor, _ids, _duplicate_run_id: {
            "headers": actor.headers,
            "params": {"status": "paused"},
        },
    ),
    SchemaNegativeCase(
        "get_api_v1_runs::schema_negative::invalid_status",
        "GET",
        "/api/v1/runs",
        lambda actor, _ids, _duplicate_run_id: {
            "headers": actor.headers,
            "params": {"status": "bogus"},
        },
    ),
    SchemaNegativeCase(
        "get_api_v1_runs::schema_negative::invalid_sort",
        "GET",
        "/api/v1/runs",
        lambda actor, _ids, _duplicate_run_id: {
            "headers": actor.headers,
            "params": {"sort": "updated_at"},
        },
    ),
    SchemaNegativeCase(
        "get_api_v1_runs::schema_negative::invalid_created_range",
        "GET",
        "/api/v1/runs",
        lambda actor, _ids, _duplicate_run_id: {
            "headers": actor.headers,
            "params": {
                "created_from": "2026-06-02T00:00:00Z",
                "created_to": "2026-06-01T00:00:00Z",
            },
        },
    ),
    SchemaNegativeCase(
        "get_api_v1_audit_events::schema_negative::blank_action",
        "GET",
        "/api/v1/audit-events",
        lambda actor, _ids, _duplicate_run_id: {
            "headers": actor.headers,
            "params": {"action": "   "},
        },
    ),
    SchemaNegativeCase(
        "get_api_v1_audit_events::schema_negative::resource_type_too_long",
        "GET",
        "/api/v1/audit-events",
        lambda actor, _ids, _duplicate_run_id: {
            "headers": actor.headers,
            "params": {"resource_type": "x" * 201},
        },
    ),
    SchemaNegativeCase(
        "get_api_v1_audit_events::schema_negative::invalid_time_range",
        "GET",
        "/api/v1/audit-events",
        lambda actor, _ids, _duplicate_run_id: {
            "headers": actor.headers,
            "params": {
                "start_at": "2026-06-02T00:00:00Z",
                "end_at": "2026-06-01T00:00:00Z",
            },
        },
    ),
    SchemaNegativeCase(
        "get_api_v1_audit_events::schema_negative::per_page_above_maximum",
        "GET",
        "/api/v1/audit-events",
        lambda actor, _ids, _duplicate_run_id: {
            "headers": actor.headers,
            "params": {"per_page": 101},
        },
    ),
    SchemaNegativeCase(
        "get_api_v1_projects_project_id_analytics_trends::schema_negative::days_low",
        "GET",
        "/api/v1/projects/{project_id}/analytics/trends",
        lambda actor, _ids, _duplicate_run_id: {
            "headers": actor.headers,
            "params": {"days": 0},
        },
        requires_stack=True,
    ),
    SchemaNegativeCase(
        "get_api_v1_projects_project_id_analytics_flaky::schema_negative::min_runs_low",
        "GET",
        "/api/v1/projects/{project_id}/analytics/flaky",
        lambda actor, _ids, _duplicate_run_id: {
            "headers": actor.headers,
            "params": {"min_runs": 1},
        },
        requires_stack=True,
    ),
    SchemaNegativeCase(
        "get_api_v1_projects_project_id_analytics_test_history::"
        "schema_negative::blank_suite",
        "GET",
        "/api/v1/projects/{project_id}/analytics/test-history",
        lambda actor, _ids, _duplicate_run_id: {
            "headers": actor.headers,
            "params": {"suite": "   ", "name": "test_blackbox"},
        },
        requires_stack=True,
    ),
    SchemaNegativeCase(
        "post_api_v1_runs_batch_cancel::schema_negative::duplicate_run_ids",
        "POST",
        "/api/v1/runs/batch/cancel",
        lambda actor, _ids, duplicate_run_id: {
            "headers": actor.headers,
            "json": {"run_ids": [duplicate_run_id, duplicate_run_id]},
        },
    ),
    SchemaNegativeCase(
        "post_api_v1_projects_project_id_environments::schema_negative::"
        "memory_below_minimum",
        "POST",
        "/api/v1/projects/{project_id}/environments",
        lambda actor, _ids, _duplicate_run_id: {
            "headers": actor.headers,
            "json": {
                "name": _suffix("bad-env"),
                "base_image": "python:3.12-alpine",
                "memory_mb": 0,
            },
        },
        requires_stack=True,
    ),
    SchemaNegativeCase(
        "post_api_v1_projects_project_id_pipelines::schema_negative::"
        "empty_collectors",
        "POST",
        "/api/v1/projects/{project_id}/pipelines",
        lambda actor, _ids, _duplicate_run_id: {
            "headers": actor.headers,
            "json": {"name": _suffix("bad-pipe"), "collectors": []},
        },
        requires_stack=True,
    ),
    SchemaNegativeCase(
        "post_api_v1_projects_project_id_schedules::schema_negative::blank_cron",
        "POST",
        "/api/v1/projects/{project_id}/schedules",
        lambda actor, ids, _duplicate_run_id: {
            "headers": actor.headers,
            "json": {
                "pipeline_id": ids["pipeline_id"],
                "cron_expr": "",
            },
        },
        requires_stack=True,
    ),
    SchemaNegativeCase(
        "post_api_v1_projects_project_id_credentials::schema_negative::invalid_type",
        "POST",
        "/api/v1/projects/{project_id}/credentials",
        lambda actor, _ids, _duplicate_run_id: {
            "headers": actor.headers,
            "json": {
                "name": _suffix("bad-cred"),
                "type": "oauth",
                "value": "secret",
            },
        },
        requires_stack=True,
    ),
    SchemaNegativeCase(
        "post_api_v1_projects_project_id_notification_rules::schema_negative::"
        "invalid_channel",
        "POST",
        "/api/v1/projects/{project_id}/notification-rules",
        lambda actor, _ids, _duplicate_run_id: {
            "headers": actor.headers,
            "json": {
                "name": _suffix("bad-notify"),
                "channels": [{"type": "sms", "config": {}}],
                "conditions": [],
            },
        },
        requires_stack=True,
    ),
    SchemaNegativeCase(
        "get_api_v1_projects_project_id_members::schema_negative::invalid_uuid",
        "GET",
        "/api/v1/projects/not-a-uuid/members",
        lambda actor, _ids, _duplicate_run_id: {"headers": actor.headers},
    ),
    SchemaNegativeCase(
        "post_api_v1_webhooks_project_id_trigger::schema_negative::invalid_json",
        "POST",
        "/api/v1/webhooks/{project_id}/trigger",
        lambda actor, _ids, _duplicate_run_id: {
            "headers": {
                **actor.headers,
                "content-type": "application/json",
            },
            "content": b"{",
        },
        requires_stack=True,
    ),
)


def _schema_negative_case_id(case: SchemaNegativeCase) -> str:
    return case.case_id


RBAC_TENANT_CASES: tuple[RbacTenantCase, ...] = (
    RbacTenantCase(
        "get_api_v1_projects_project_id::rbac_tenant::cross_tenant_read_denied",
        "GET",
        "/api/v1/projects/{project_id}",
        lambda _ids: {},
    ),
    RbacTenantCase(
        "put_api_v1_projects_project_id::rbac_tenant::cross_tenant_update_denied",
        "PUT",
        "/api/v1/projects/{project_id}",
        lambda _ids: {"json": {"name": "cross-tenant-update"}},
    ),
    RbacTenantCase(
        "delete_api_v1_projects_project_id::rbac_tenant::cross_tenant_delete_denied",
        "DELETE",
        "/api/v1/projects/{project_id}",
        lambda _ids: {},
    ),
    RbacTenantCase(
        "get_api_v1_runs_run_id::rbac_tenant::cross_tenant_read_denied",
        "GET",
        "/api/v1/runs/{run_id}",
        lambda _ids: {},
    ),
    RbacTenantCase(
        "get_api_v1_runs_run_id_results::rbac_tenant::cross_tenant_read_denied",
        "GET",
        "/api/v1/runs/{run_id}/results",
        lambda _ids: {},
    ),
    RbacTenantCase(
        "get_api_v1_runs_run_id_artifacts::rbac_tenant::cross_tenant_read_denied",
        "GET",
        "/api/v1/runs/{run_id}/artifacts",
        lambda _ids: {},
    ),
    RbacTenantCase(
        "get_api_v1_runs_run_id_artifacts_allure_report::"
        "rbac_tenant::cross_tenant_read_denied",
        "GET",
        "/api/v1/runs/{run_id}/artifacts/allure-report",
        lambda _ids: {},
    ),
    RbacTenantCase(
        "get_api_v1_runs_run_id_logs_archive::rbac_tenant::cross_tenant_read_denied",
        "GET",
        "/api/v1/runs/{run_id}/logs/archive",
        lambda _ids: {},
    ),
    RbacTenantCase(
        "get_api_v1_runs_run_id_notifications::rbac_tenant::cross_tenant_read_denied",
        "GET",
        "/api/v1/runs/{run_id}/notifications",
        lambda _ids: {},
    ),
    RbacTenantCase(
        "get_api_v1_projects_project_id_analytics_trends::"
        "rbac_tenant::cross_tenant_read_denied",
        "GET",
        "/api/v1/projects/{project_id}/analytics/trends",
        lambda _ids: {"params": {"days": 7, "offset": 0, "limit": 5}},
    ),
    RbacTenantCase(
        "get_api_v1_projects_project_id_analytics_flaky::"
        "rbac_tenant::cross_tenant_read_denied",
        "GET",
        "/api/v1/projects/{project_id}/analytics/flaky",
        lambda _ids: {
            "params": {"days": 7, "min_runs": 2, "offset": 0, "limit": 5},
        },
    ),
    RbacTenantCase(
        "get_api_v1_projects_project_id_analytics_test_history::"
        "rbac_tenant::cross_tenant_read_denied",
        "GET",
        "/api/v1/projects/{project_id}/analytics/test-history",
        lambda _ids: {
            "params": {
                "suite": "api",
                "name": "test_blackbox",
                "days": 7,
                "offset": 0,
                "limit": 5,
            }
        },
    ),
    RbacTenantCase(
        "post_api_v1_runs_run_id_cancel::rbac_tenant::cross_tenant_write_denied",
        "POST",
        "/api/v1/runs/{run_id}/cancel",
        lambda _ids: {"json": {"reason": "cross tenant denied"}},
    ),
    RbacTenantCase(
        "get_api_v1_projects_project_id_members::rbac_tenant::"
        "cross_tenant_read_denied",
        "GET",
        "/api/v1/projects/{project_id}/members",
        lambda _ids: {},
    ),
    RbacTenantCase(
        "get_api_v1_projects_project_id_credentials::rbac_tenant::"
        "cross_tenant_list_denied",
        "GET",
        "/api/v1/projects/{project_id}/credentials",
        lambda _ids: {},
    ),
    RbacTenantCase(
        "post_api_v1_projects_project_id_credentials::rbac_tenant::"
        "cross_tenant_create_denied",
        "POST",
        "/api/v1/projects/{project_id}/credentials",
        lambda _ids: {
            "json": {"name": _suffix("tenant-cred"), "type": "token", "value": "x"},
        },
    ),
    RbacTenantCase(
        "get_api_v1_projects_project_id_credentials_credential_id::"
        "rbac_tenant::cross_tenant_read_denied",
        "GET",
        "/api/v1/projects/{project_id}/credentials/{credential_id}",
        lambda _ids: {},
    ),
    RbacTenantCase(
        "put_api_v1_projects_project_id_credentials_credential_id::"
        "rbac_tenant::cross_tenant_update_denied",
        "PUT",
        "/api/v1/projects/{project_id}/credentials/{credential_id}",
        lambda _ids: {"json": {"value": "rotated"}},
    ),
    RbacTenantCase(
        "delete_api_v1_projects_project_id_credentials_credential_id::"
        "rbac_tenant::cross_tenant_delete_denied",
        "DELETE",
        "/api/v1/projects/{project_id}/credentials/{credential_id}",
        lambda _ids: {},
    ),
    RbacTenantCase(
        "get_api_v1_projects_project_id_environments::rbac_tenant::"
        "cross_tenant_list_denied",
        "GET",
        "/api/v1/projects/{project_id}/environments",
        lambda _ids: {},
    ),
    RbacTenantCase(
        "post_api_v1_projects_project_id_environments::rbac_tenant::"
        "cross_tenant_create_denied",
        "POST",
        "/api/v1/projects/{project_id}/environments",
        lambda _ids: {"json": _environment_payload(_suffix("tenant-env"))},
    ),
    RbacTenantCase(
        "get_api_v1_projects_project_id_environments_env_id::"
        "rbac_tenant::cross_tenant_read_denied",
        "GET",
        "/api/v1/projects/{project_id}/environments/{environment_id}",
        lambda _ids: {},
    ),
    RbacTenantCase(
        "put_api_v1_projects_project_id_environments_env_id::"
        "rbac_tenant::cross_tenant_update_denied",
        "PUT",
        "/api/v1/projects/{project_id}/environments/{environment_id}",
        lambda _ids: {"json": {"memory_mb": 512}},
    ),
    RbacTenantCase(
        "delete_api_v1_projects_project_id_environments_env_id::"
        "rbac_tenant::cross_tenant_delete_denied",
        "DELETE",
        "/api/v1/projects/{project_id}/environments/{environment_id}",
        lambda _ids: {},
    ),
    RbacTenantCase(
        "get_api_v1_projects_project_id_pipelines::rbac_tenant::"
        "cross_tenant_list_denied",
        "GET",
        "/api/v1/projects/{project_id}/pipelines",
        lambda _ids: {},
    ),
    RbacTenantCase(
        "post_api_v1_projects_project_id_pipelines::rbac_tenant::"
        "cross_tenant_create_denied",
        "POST",
        "/api/v1/projects/{project_id}/pipelines",
        lambda _ids: {"json": _pipeline_payload(_suffix("tenant-pipe"))},
    ),
    RbacTenantCase(
        "get_api_v1_projects_project_id_pipelines_pipeline_id::"
        "rbac_tenant::cross_tenant_read_denied",
        "GET",
        "/api/v1/projects/{project_id}/pipelines/{pipeline_id}",
        lambda _ids: {},
    ),
    RbacTenantCase(
        "put_api_v1_projects_project_id_pipelines_pipeline_id::"
        "rbac_tenant::cross_tenant_update_denied",
        "PUT",
        "/api/v1/projects/{project_id}/pipelines/{pipeline_id}",
        lambda _ids: {"json": {"enabled": False}},
    ),
    RbacTenantCase(
        "delete_api_v1_projects_project_id_pipelines_pipeline_id::"
        "rbac_tenant::cross_tenant_delete_denied",
        "DELETE",
        "/api/v1/projects/{project_id}/pipelines/{pipeline_id}",
        lambda _ids: {},
    ),
    RbacTenantCase(
        "get_api_v1_projects_project_id_schedules::rbac_tenant::"
        "cross_tenant_list_denied",
        "GET",
        "/api/v1/projects/{project_id}/schedules",
        lambda _ids: {},
    ),
    RbacTenantCase(
        "post_api_v1_projects_project_id_schedules::rbac_tenant::"
        "cross_tenant_create_denied",
        "POST",
        "/api/v1/projects/{project_id}/schedules",
        lambda ids: {"json": _schedule_payload(ids["pipeline_id"])},
    ),
    RbacTenantCase(
        "get_api_v1_projects_project_id_schedules_schedule_id::"
        "rbac_tenant::cross_tenant_read_denied",
        "GET",
        "/api/v1/projects/{project_id}/schedules/{schedule_id}",
        lambda _ids: {},
    ),
    RbacTenantCase(
        "put_api_v1_projects_project_id_schedules_schedule_id::"
        "rbac_tenant::cross_tenant_update_denied",
        "PUT",
        "/api/v1/projects/{project_id}/schedules/{schedule_id}",
        lambda _ids: {"json": {"enabled": False}},
    ),
    RbacTenantCase(
        "delete_api_v1_projects_project_id_schedules_schedule_id::"
        "rbac_tenant::cross_tenant_delete_denied",
        "DELETE",
        "/api/v1/projects/{project_id}/schedules/{schedule_id}",
        lambda _ids: {},
    ),
    RbacTenantCase(
        "get_api_v1_projects_project_id_notification_rules::rbac_tenant::"
        "cross_tenant_list_denied",
        "GET",
        "/api/v1/projects/{project_id}/notification-rules",
        lambda _ids: {},
    ),
    RbacTenantCase(
        "post_api_v1_projects_project_id_notification_rules::rbac_tenant::"
        "cross_tenant_create_denied",
        "POST",
        "/api/v1/projects/{project_id}/notification-rules",
        lambda _ids: {"json": _notification_rule_payload(_suffix("tenant-rule"))},
    ),
    RbacTenantCase(
        "get_api_v1_projects_project_id_notification_rules_rule_id::"
        "rbac_tenant::cross_tenant_read_denied",
        "GET",
        "/api/v1/projects/{project_id}/notification-rules/{rule_id}",
        lambda _ids: {},
    ),
    RbacTenantCase(
        "put_api_v1_projects_project_id_notification_rules_rule_id::"
        "rbac_tenant::cross_tenant_update_denied",
        "PUT",
        "/api/v1/projects/{project_id}/notification-rules/{rule_id}",
        lambda _ids: {"json": {"enabled": False}},
    ),
    RbacTenantCase(
        "delete_api_v1_projects_project_id_notification_rules_rule_id::"
        "rbac_tenant::cross_tenant_delete_denied",
        "DELETE",
        "/api/v1/projects/{project_id}/notification-rules/{rule_id}",
        lambda _ids: {},
    ),
)


def _rbac_tenant_case_id(case: RbacTenantCase) -> str:
    return case.case_id


@pytest.mark.parametrize(
    "case",
    AUTH_SUCCESS_CASES,
    ids=_auth_success_case_id,
)
async def test_openapi_atomic_auth_success_case(
    no_auth_integration_app,
    case: AuthSuccessCase,
) -> None:
    async with _api_client(no_auth_integration_app) as client:
        await case.run(client)


@pytest.mark.parametrize(
    "case",
    RESOURCE_SUCCESS_CASES,
    ids=_resource_success_case_id,
)
async def test_openapi_atomic_resource_success_case(
    no_auth_integration_app,
    case: ResourceSuccessCase,
) -> None:
    async with _api_client(no_auth_integration_app) as client:
        await case.run(client)


async def test_auth_blackbox_register_login_refresh_logout_and_token_rejections(
    no_auth_integration_app,
    test_settings: Settings,
) -> None:
    async with _api_client(no_auth_integration_app) as client:
        actor = await _register_actor(client, "auth")

        bad_login = await client.post(
            "/api/v1/auth/login",
            json={
                "username": actor.username,
                "password": "wrong-password",
                "tenant_id": actor.user["tenant_id"],
            },
        )
        assert bad_login.status_code == 401
        _assert_error_body(bad_login)

        login_response = await client.post(
            "/api/v1/auth/login",
            json={
                "username": actor.username,
                "password": actor.password,
                "tenant_id": actor.user["tenant_id"],
            },
        )
        login_body = _assert_status(login_response, 200)
        login_token = login_body["access_token"]
        assert login_body["user"]["id"] == actor.user["id"]

        refresh_response = await client.post("/api/v1/auth/refresh")
        refresh_body = _assert_status(refresh_response, 200)
        assert refresh_body["token_type"] == "bearer"
        assert refresh_body["access_token"]

        token_response = await client.post(
            "/api/v1/auth/tokens",
            headers={"Authorization": f"Bearer {refresh_body['access_token']}"},
            json={"name": _suffix("api-token"), "scopes": ["project.read"]},
        )
        token_body = _assert_status(token_response, 201)
        assert token_body["token"].startswith("qap_")
        assert token_body["scopes"] == ["project.read"]

        list_token_response = await client.get(
            "/api/v1/auth/tokens",
            headers={"Authorization": f"Bearer {refresh_body['access_token']}"},
        )
        list_token_body = _assert_status(list_token_response, 200)
        assert any(
            item["token_id"] == token_body["token_id"]
            for item in list_token_body["data"]
        )

        api_token_auth_response = await client.get(
            "/api/v1/projects",
            headers={"Authorization": f"Bearer {token_body['token']}"},
        )
        _assert_status(api_token_auth_response, 200)

        api_token_write_response = await client.post(
            "/api/v1/projects",
            headers={"Authorization": f"Bearer {token_body['token']}"},
            json=_project_payload(_suffix("read-only-token-denied")),
        )
        assert api_token_write_response.status_code == 403
        _assert_error_body(api_token_write_response)

        revoke_response = await client.delete(
            f"/api/v1/auth/tokens/{token_body['token_id']}",
            headers={"Authorization": f"Bearer {refresh_body['access_token']}"},
        )
        _assert_status(revoke_response, 204)

        revoked_api_token_response = await client.get(
            "/api/v1/projects",
            headers={"Authorization": f"Bearer {token_body['token']}"},
        )
        assert revoked_api_token_response.status_code == 401
        _assert_error_body(revoked_api_token_response)

        invalid_token_response = await client.get(
            "/api/v1/projects",
            headers={"Authorization": "Bearer invalid-token"},
        )
        assert invalid_token_response.status_code == 401
        _assert_error_body(invalid_token_response)

        expired_token_response = await client.get(
            "/api/v1/projects",
            headers={
                "Authorization": (
                    f"Bearer {_expired_access_token(actor, test_settings)}"
                )
            },
        )
        assert expired_token_response.status_code == 401
        _assert_error_body(expired_token_response)

        admin_response = await client.get(
            "/api/v1/admin/status",
            headers={"Authorization": f"Bearer {refresh_body['access_token']}"},
        )
        assert admin_response.status_code == 403
        _assert_error_body(admin_response)

        logout_response = await client.post(
            "/api/v1/auth/logout",
            headers={"Authorization": f"Bearer {login_token}"},
        )
        _assert_status(logout_response, 204)

        revoked_jwt_response = await client.get(
            "/api/v1/projects",
            headers={"Authorization": f"Bearer {login_token}"},
        )
        assert revoked_jwt_response.status_code == 401
        _assert_error_body(revoked_jwt_response)


async def test_resource_lifecycle_blackbox_crud_and_listing(
    no_auth_integration_app,
) -> None:
    async with _api_client(no_auth_integration_app) as client:
        actor = await _register_actor(client, "life")

        stack = await _create_project_stack(client, actor, prefix="life")
        project = stack["project"]
        environment = stack["environment"]
        pipeline = stack["pipeline"]

        duplicate_project = await client.post(
            "/api/v1/projects",
            headers=actor.headers,
            json=_project_payload(project["slug"]),
        )
        assert duplicate_project.status_code == 409
        _assert_error_body(duplicate_project)

        project_get = await client.get(
            f"/api/v1/projects/{project['id']}",
            headers=actor.headers,
        )
        assert _assert_status(project_get, 200)["id"] == project["id"]

        project_list = await client.get(
            "/api/v1/projects",
            headers=actor.headers,
            params={"q": project["slug"], "status": "active", "page": 1, "per_page": 5},
        )
        project_list_body = _assert_status(project_list, 200)
        assert [item["id"] for item in project_list_body["data"]] == [project["id"]]

        project_update = await client.put(
            f"/api/v1/projects/{project['id']}",
            headers=actor.headers,
            json={
                "name": f"{project['name']}-updated",
                "description": "black-box lifecycle coverage",
            },
        )
        project = _assert_status(project_update, 200)
        assert project["description"] == "black-box lifecycle coverage"

        credential_create = await client.post(
            f"/api/v1/projects/{project['id']}/credentials",
            headers=actor.headers,
            json={"name": _suffix("cred"), "type": "token", "value": "secret-v1"},
        )
        credential = _assert_status(credential_create, 201)
        assert "secret-v1" not in credential

        credential_get = await client.get(
            f"/api/v1/projects/{project['id']}/credentials/{credential['id']}",
            headers=actor.headers,
        )
        assert _assert_status(credential_get, 200)["id"] == credential["id"]

        credential_list = await client.get(
            f"/api/v1/projects/{project['id']}/credentials",
            headers=actor.headers,
        )
        credential_list_body = _assert_status(credential_list, 200)
        assert any(item["id"] == credential["id"] for item in credential_list_body["data"])

        credential_update = await client.put(
            f"/api/v1/projects/{project['id']}/credentials/{credential['id']}",
            headers=actor.headers,
            json={"value": "secret-v2"},
        )
        _assert_status(credential_update, 200)

        env_get = await client.get(
            f"/api/v1/projects/{project['id']}/environments/{environment['id']}",
            headers=actor.headers,
        )
        assert _assert_status(env_get, 200)["id"] == environment["id"]

        env_list = await client.get(
            f"/api/v1/projects/{project['id']}/environments",
            headers=actor.headers,
            params={"page": 1, "per_page": 10},
        )
        env_list_body = _assert_status(env_list, 200)
        assert any(item["id"] == environment["id"] for item in env_list_body["data"])

        env_update = await client.put(
            f"/api/v1/projects/{project['id']}/environments/{environment['id']}",
            headers=actor.headers,
            json={"memory_mb": 384, "env_vars": {"API_TOKEN": "rotated"}},
        )
        environment = _assert_status(env_update, 200)
        assert environment["memory_mb"] == 384
        assert environment["env_vars"] == {"API_TOKEN": "rotated"}

        pipeline_get = await client.get(
            f"/api/v1/projects/{project['id']}/pipelines/{pipeline['id']}",
            headers=actor.headers,
        )
        assert _assert_status(pipeline_get, 200)["id"] == pipeline["id"]

        pipeline_list = await client.get(
            f"/api/v1/projects/{project['id']}/pipelines",
            headers=actor.headers,
        )
        pipeline_list_body = _assert_status(pipeline_list, 200)
        assert any(item["id"] == pipeline["id"] for item in pipeline_list_body["data"])

        pipeline_update = await client.put(
            f"/api/v1/projects/{project['id']}/pipelines/{pipeline['id']}",
            headers=actor.headers,
            json={"name": f"{pipeline['name']}-updated", "enabled": False},
        )
        pipeline = _assert_status(pipeline_update, 200)
        assert pipeline["enabled"] is False

        schedule_create = await client.post(
            f"/api/v1/projects/{project['id']}/schedules",
            headers=actor.headers,
            json=_schedule_payload(pipeline["id"]),
        )
        schedule = _assert_status(schedule_create, 201)

        schedule_get = await client.get(
            f"/api/v1/projects/{project['id']}/schedules/{schedule['id']}",
            headers=actor.headers,
        )
        assert _assert_status(schedule_get, 200)["id"] == schedule["id"]

        schedule_list = await client.get(
            f"/api/v1/projects/{project['id']}/schedules",
            headers=actor.headers,
        )
        schedule_list_body = _assert_status(schedule_list, 200)
        assert any(item["id"] == schedule["id"] for item in schedule_list_body["data"])

        schedule_update = await client.put(
            f"/api/v1/projects/{project['id']}/schedules/{schedule['id']}",
            headers=actor.headers,
            json={"enabled": False, "missed_fire_policy": "run_once"},
        )
        schedule = _assert_status(schedule_update, 200)
        assert schedule["enabled"] is False

        rule_create = await client.post(
            f"/api/v1/projects/{project['id']}/notification-rules",
            headers=actor.headers,
            json=_notification_rule_payload(_suffix("notify")),
        )
        rule = _assert_status(rule_create, 201)

        rule_get = await client.get(
            f"/api/v1/projects/{project['id']}/notification-rules/{rule['id']}",
            headers=actor.headers,
        )
        assert _assert_status(rule_get, 200)["id"] == rule["id"]

        rule_list = await client.get(
            f"/api/v1/projects/{project['id']}/notification-rules",
            headers=actor.headers,
        )
        rule_list_body = _assert_status(rule_list, 200)
        assert any(item["id"] == rule["id"] for item in rule_list_body["data"])

        rule_update = await client.put(
            f"/api/v1/projects/{project['id']}/notification-rules/{rule['id']}",
            headers=actor.headers,
            json={"enabled": False, "template": "Run {{ status }}"},
        )
        rule = _assert_status(rule_update, 200)
        assert rule["enabled"] is False

        member_list = await client.get(
            f"/api/v1/projects/{project['id']}/members",
            headers=actor.headers,
        )
        member_list_body = _assert_status(member_list, 200)
        assert any(item["user_id"] == actor.user["id"] for item in member_list_body["data"])

        audit_response = await client.get(
            "/api/v1/audit-events",
            headers=actor.headers,
            params={
                "actor_id": actor.user["id"],
                "action": "project.create",
                "resource_type": "project",
                "resource_id": project["id"],
                "start_at": "2000-01-01T00:00:00Z",
                "end_at": "2999-01-01T00:00:00Z",
                "page": 1,
                "per_page": 10,
            },
        )
        audit_body = _assert_status(audit_response, 200)
        assert audit_body["page"] == 1
        assert audit_body["per_page"] == 10
        assert audit_body["total"] >= 1
        assert all(
            item["user_id"] == actor.user["id"]
            and item["resource_id"] == project["id"]
            and item["resource_type"] == "project"
            and item["action"] == "project.create"
            for item in audit_body["data"]
        )

        analytics_requests = (
            (
                f"/api/v1/projects/{project['id']}/analytics/trends",
                {"days": 7, "offset": 0, "limit": 5},
            ),
            (
                f"/api/v1/projects/{project['id']}/analytics/flaky",
                {"days": 7, "min_runs": 2, "offset": 0, "limit": 5},
            ),
            (
                f"/api/v1/projects/{project['id']}/analytics/test-history",
                {
                    "suite": "api",
                    "name": "test_blackbox",
                    "days": 7,
                    "offset": 0,
                    "limit": 5,
                },
            ),
        )
        for path, params in analytics_requests:
            analytics_response = await client.get(
                path,
                headers=actor.headers,
                params=params,
            )
            analytics_body = _assert_status(analytics_response, 200)
            assert analytics_body["data"] == []
            assert analytics_body["pagination"]["offset"] == 0
            assert analytics_body["pagination"]["limit"] == 5

        for path in (
            f"/api/v1/projects/{project['id']}/notification-rules/{rule['id']}",
            f"/api/v1/projects/{project['id']}/schedules/{schedule['id']}",
            f"/api/v1/projects/{project['id']}/pipelines/{pipeline['id']}",
            f"/api/v1/projects/{project['id']}/credentials/{credential['id']}",
            f"/api/v1/projects/{project['id']}/environments/{environment['id']}",
            f"/api/v1/projects/{project['id']}",
        ):
            delete_response = await client.delete(path, headers=actor.headers)
            _assert_status(delete_response, 204)

        deleted_project_get = await client.get(
            f"/api/v1/projects/{project['id']}",
            headers=actor.headers,
        )
        assert deleted_project_get.status_code == 404
        _assert_error_body(deleted_project_get)


async def test_runs_logs_and_artifacts_blackbox_paths(
    no_auth_integration_app,
) -> None:
    async with _api_client(no_auth_integration_app) as client:
        actor = await _register_actor(client, "run")
        stack = await _create_project_stack(client, actor, prefix="run")
        project = stack["project"]
        environment = stack["environment"]
        pipeline = stack["pipeline"]

        missing_pipeline_response = await client.post(
            "/api/v1/runs",
            headers=actor.headers,
            json={"pipeline_id": str(uuid4())},
        )
        assert missing_pipeline_response.status_code == 404
        _assert_error_body(missing_pipeline_response)

        invalid_trigger_response = await client.post(
            "/api/v1/runs",
            headers=actor.headers,
            json={"pipeline_id": pipeline["id"], "priority": 3},
        )
        assert invalid_trigger_response.status_code == 422
        _assert_error_body(invalid_trigger_response)

        no_env_project = await _create_project(client, actor, prefix="run-no-env")
        no_env_pipeline = await _create_pipeline(
            client,
            actor,
            no_env_project["id"],
        )
        no_environment_response = await client.post(
            "/api/v1/runs",
            headers=actor.headers,
            json={"pipeline_id": no_env_pipeline["id"]},
        )
        assert no_environment_response.status_code == 409
        _assert_error_body(no_environment_response)

        trigger_response = await client.post(
            "/api/v1/runs",
            headers=actor.headers,
            json={
                "pipeline_id": pipeline["id"],
                "environment_id": environment["id"],
                "git_ref": "main",
                "git_sha": FULL_SHA,
                "priority": 1,
            },
        )
        run = _assert_status(trigger_response, 201)
        assert run["project_id"] == project["id"]
        assert run["pipeline_id"] == pipeline["id"]
        assert run["environment_id"] == environment["id"]

        get_response = await client.get(f"/api/v1/runs/{run['id']}", headers=actor.headers)
        assert _assert_status(get_response, 200)["id"] == run["id"]

        list_response = await client.get(
            "/api/v1/runs",
            headers=actor.headers,
            params={
                "project_id": project["id"],
                "pipeline_id": pipeline["id"],
                "status": run["status"],
                "sort": "-created_at",
            },
        )
        list_body = _assert_status(list_response, 200)
        assert any(item["id"] == run["id"] for item in list_body["data"])

        for child_path in (
            "results",
            "artifacts",
            "notifications",
        ):
            child_response = await client.get(
                f"/api/v1/runs/{run['id']}/{child_path}",
                headers=actor.headers,
            )
            child_body = _assert_status(child_response, 200)
            assert child_body["data"] == []

        allure_response = await client.get(
            f"/api/v1/runs/{run['id']}/artifacts/allure-report",
            headers=actor.headers,
        )
        assert allure_response.status_code == 404
        _assert_error_body(allure_response)

        archive_response = await client.get(
            f"/api/v1/runs/{run['id']}/logs/archive",
            headers=actor.headers,
        )
        assert archive_response.status_code in {404, 503}
        _assert_error_body(archive_response)

        missing_artifact_id = uuid4()
        for artifact_path in (
            f"/api/v1/artifacts/{missing_artifact_id}/download",
            f"/api/v1/artifacts/{missing_artifact_id}/preview-url",
        ):
            artifact_response = await client.get(artifact_path, headers=actor.headers)
            assert artifact_response.status_code == 404
            _assert_error_body(artifact_response)

        ticket_response = await client.post(
            "/api/v1/auth/sse-ticket",
            headers=actor.headers,
        )
        ticket_body = _assert_status(ticket_response, 200)
        assert ticket_body["ticket"]

        missing_ticket_response = await client.get(f"/api/v1/runs/{run['id']}/logs")
        assert missing_ticket_response.status_code == 401
        _assert_error_body(missing_ticket_response)

        invalid_ticket_response = await client.get(
            f"/api/v1/runs/{run['id']}/events",
            params={"ticket": "invalid-ticket"},
        )
        assert invalid_ticket_response.status_code == 401
        _assert_error_body(invalid_ticket_response)

        cancel_response = await client.post(
            f"/api/v1/runs/{run['id']}/cancel",
            headers=actor.headers,
            json={"reason": "black-box cancel"},
        )
        canceled = _assert_status(cancel_response, 200)
        assert canceled["id"] == run["id"]

        events_response = await client.get(
            f"/api/v1/runs/{run['id']}/events",
            params={"ticket": ticket_body["ticket"]},
            timeout=10,
        )
        assert events_response.status_code == 200, events_response.text
        assert "text/event-stream" in events_response.headers.get("content-type", "")
        assert "status_change" in events_response.text
        assert "cancelled" in events_response.text

        logs_ticket_response = await client.post(
            "/api/v1/auth/sse-ticket",
            headers=actor.headers,
        )
        logs_ticket_body = _assert_status(logs_ticket_response, 200)
        logs_response = await client.get(
            f"/api/v1/runs/{run['id']}/logs",
            params={"ticket": logs_ticket_body["ticket"]},
            timeout=10,
        )
        assert logs_response.status_code == 200, logs_response.text
        assert "text/event-stream" in logs_response.headers.get("content-type", "")
        assert "done" in logs_response.text

        terminal_cancel_response = await client.post(
            f"/api/v1/runs/{run['id']}/cancel",
            headers=actor.headers,
            json={"reason": "already terminal"},
        )
        assert terminal_cancel_response.status_code == 409
        _assert_error_body(terminal_cancel_response)

        batch_cancel_response = await client.post(
            "/api/v1/runs/batch/cancel",
            headers=actor.headers,
            json={"run_ids": [run["id"]]},
        )
        batch_cancel_body = _assert_status(batch_cancel_response, 200)
        assert batch_cancel_body["processed"] == 0
        assert batch_cancel_body["failed"] == 1
        assert "already terminal" in batch_cancel_body["errors"][0]

        batch_retry_response = await client.post(
            "/api/v1/runs/batch/retry",
            headers=actor.headers,
            json={"run_ids": [run["id"]]},
        )
        batch_retry_body = _assert_status(batch_retry_response, 200)
        assert batch_retry_body == {"processed": 1, "failed": 0, "errors": []}


async def test_webhooks_blackbox_security_failures_and_duplicate_delivery(
    no_auth_integration_app,
) -> None:
    async with _api_client(no_auth_integration_app) as client:
        actor = await _register_actor(client, "hook")

        invalid_provider = await client.post("/api/v1/webhooks/not-supported")
        assert invalid_provider.status_code == 404
        _assert_error_body(invalid_provider)

        invalid_json = await client.post(
            "/api/v1/webhooks/github",
            content=b"{",
            headers={"content-type": "application/json"},
        )
        assert invalid_json.status_code == 400
        _assert_error_body(invalid_json)

        empty_body = await client.post("/api/v1/webhooks/github", content=b"")
        assert empty_body.status_code == 400
        _assert_error_body(empty_body)

        secret = _suffix("secret")
        repo_name = f"acme/{_suffix('repo')}"
        repo_url = f"https://github.com/{repo_name}.git"
        signed_stack = await _create_project_stack(
            client,
            actor,
            prefix="signed-hook",
            git_url=repo_url,
            settings={"webhook_secret": secret, "allowed_branches": ["main"]},
        )
        signed_project = signed_stack["project"]
        github_payload = _github_push_payload(repo_name)
        raw_body = _canonical_json_bytes(github_payload)
        provider_headers = {
            "content-type": "application/json",
            "X-GitHub-Event": "push",
            "X-GitHub-Delivery": _suffix("delivery"),
        }

        missing_signature = await client.post(
            "/webhooks/github",
            content=raw_body,
            headers=provider_headers,
        )
        assert missing_signature.status_code == 401
        _assert_error_body(missing_signature)

        wrong_signature = await client.post(
            "/webhooks/github",
            content=raw_body,
            headers={**provider_headers, "X-Hub-Signature-256": "sha256=bad"},
        )
        assert wrong_signature.status_code == 401
        _assert_error_body(wrong_signature)

        signed_delivery = await client.post(
            "/webhooks/github",
            content=raw_body,
            headers={
                **provider_headers,
                "X-Hub-Signature-256": _webhook_signature(secret, raw_body),
            },
        )
        signed_run = _assert_status(signed_delivery, 201)
        assert signed_run["trigger_type"] == "webhook"
        assert signed_run["git_sha"] == FULL_SHA

        duplicate_delivery = await client.post(
            "/webhooks/github",
            content=raw_body,
            headers={
                **provider_headers,
                "X-Hub-Signature-256": _webhook_signature(secret, raw_body),
            },
        )
        duplicate_body = _assert_status(duplicate_delivery, 200)
        assert duplicate_body["status"] == "duplicate"

        api_v1_duplicate_delivery = await client.post(
            "/api/v1/webhooks/github",
            content=raw_body,
            headers={
                **provider_headers,
                "X-Hub-Signature-256": _webhook_signature(secret, raw_body),
            },
        )
        api_v1_duplicate_body = _assert_status(api_v1_duplicate_delivery, 200)
        assert api_v1_duplicate_body["status"] == "duplicate"

        filtered_payload = _github_push_payload(repo_name, git_sha="c" * 40)
        filtered_payload["ref"] = "refs/heads/feature/ignored"
        filtered_raw_body = _canonical_json_bytes(filtered_payload)
        filtered_delivery = await client.post(
            "/webhooks/github",
            content=filtered_raw_body,
            headers={
                **provider_headers,
                "X-GitHub-Delivery": _suffix("filtered-delivery"),
                "X-Hub-Signature-256": _webhook_signature(secret, filtered_raw_body),
            },
        )
        filtered_body = _assert_status(filtered_delivery, 200)
        assert filtered_body == {
            "status": "filtered",
            "reason": "branch_not_allowed",
        }

        ignored_event = await client.post(
            "/webhooks/github",
            json={"zen": "keep it logically precise"},
            headers={"X-GitHub-Event": "ping"},
        )
        assert ignored_event.status_code == 202
        assert ignored_event.json()["detail"] == "Unsupported GitHub event: ping"

        signed_project_payload = {
            "git_ref": "refs/heads/main",
            "git_sha": "d" * 40,
            "metadata": {
                "provider": "github",
                "delivery_id": _suffix("signed-project-delivery"),
            },
        }
        signed_project_raw_body = _canonical_json_bytes(signed_project_payload)
        missing_project_signature = await client.post(
            f"/api/v1/webhooks/{signed_project['id']}/trigger",
            headers={
                **actor.headers,
                "content-type": "application/json",
            },
            content=signed_project_raw_body,
        )
        assert missing_project_signature.status_code == 401
        _assert_error_body(missing_project_signature)

        signed_project_delivery = await client.post(
            f"/api/v1/webhooks/{signed_project['id']}/trigger",
            headers={
                **actor.headers,
                "content-type": "application/json",
                "X-Webhook-Signature": _webhook_signature(
                    secret,
                    signed_project_raw_body,
                ),
            },
            content=signed_project_raw_body,
        )
        signed_project_run = _assert_status(signed_project_delivery, 201)
        assert signed_project_run["trigger_type"] == "webhook"
        assert signed_project_run["git_sha"] == "d" * 40

        unsigned_stack = await _create_project_stack(
            client,
            actor,
            prefix="project-hook",
        )
        project_payload = {
            "git_ref": "refs/heads/main",
            "git_sha": "b" * 40,
            "metadata": {
                "provider": "github",
                "delivery_id": _suffix("project-delivery"),
            },
        }
        first_project_webhook = await client.post(
            f"/api/v1/webhooks/{unsigned_stack['project']['id']}/trigger",
            headers=actor.headers,
            json=project_payload,
        )
        _assert_status(first_project_webhook, 201)
        duplicate_project_webhook = await client.post(
            f"/api/v1/webhooks/{unsigned_stack['project']['id']}/trigger",
            headers=actor.headers,
            json=project_payload,
        )
        duplicate_project_body = _assert_status(duplicate_project_webhook, 200)
        assert duplicate_project_body["status"] == "duplicate"


@pytest.mark.parametrize(
    "case",
    RBAC_TENANT_CASES,
    ids=_rbac_tenant_case_id,
)
async def test_openapi_atomic_rbac_tenant_case(
    no_auth_integration_app,
    case: RbacTenantCase,
) -> None:
    async with _api_client(no_auth_integration_app) as client:
        _actor_a, actor_b, ids = await _create_cross_tenant_resource_ids(client)
        response = await client.request(
            case.method,
            case.path(ids),
            headers=actor_b.headers,
            **case.kwargs_factory(ids),
        )
        assert response.status_code == 404, response.text
        _assert_error_body(response)


async def test_multi_tenant_blackbox_special_flows_do_not_leak(
    no_auth_integration_app,
) -> None:
    async with _api_client(no_auth_integration_app) as client:
        actor_a, actor_b, ids = await _create_cross_tenant_resource_ids(client)
        list_b = await client.get("/api/v1/projects", headers=actor_b.headers)
        list_b_body = _assert_status(list_b, 200)
        assert all(item["id"] != ids["project_id"] for item in list_b_body["data"])

        cross_tenant_audit = await client.get(
            "/api/v1/audit-events",
            headers=actor_b.headers,
            params={"resource_type": "project", "resource_id": ids["project_id"]},
        )
        assert cross_tenant_audit.status_code == 404
        _assert_error_body(cross_tenant_audit)

        cross_tenant_trigger = await client.post(
            "/api/v1/runs",
            headers=actor_b.headers,
            json={"pipeline_id": ids["pipeline_id"]},
        )
        assert cross_tenant_trigger.status_code == 404
        _assert_error_body(cross_tenant_trigger)

        for batch_path in ("/api/v1/runs/batch/cancel", "/api/v1/runs/batch/retry"):
            cross_tenant_batch = await client.post(
                batch_path,
                headers=actor_b.headers,
                json={"run_ids": [ids["run_id"]]},
            )
            cross_tenant_batch_body = _assert_status(cross_tenant_batch, 200)
            assert cross_tenant_batch_body["processed"] == 0
            assert cross_tenant_batch_body["failed"] == 1
            assert "not found" in cross_tenant_batch_body["errors"][0]

        for stream_path in ("logs", "events"):
            ticket_response = await client.post(
                "/api/v1/auth/sse-ticket",
                headers=actor_b.headers,
            )
            ticket_body = _assert_status(ticket_response, 200)
            cross_tenant_stream = await client.get(
                f"/api/v1/runs/{ids['run_id']}/{stream_path}",
                params={"ticket": ticket_body["ticket"]},
            )
            assert cross_tenant_stream.status_code == 404
            _assert_error_body(cross_tenant_stream)

        add_cross_tenant_member = await client.post(
            f"/api/v1/projects/{ids['project_id']}/members",
            headers=actor_a.headers,
            json={"user_id": actor_b.user["id"], "role": "viewer"},
        )
        assert add_cross_tenant_member.status_code in {404, 422}
        _assert_error_body(add_cross_tenant_member)


async def test_seeded_setup_covers_remaining_success_paths(
    no_auth_integration_app,
    monkeypatch,
) -> None:
    settings = no_auth_integration_app.state.container.settings
    original_private_hosts = list(settings.git_allowed_private_hosts)
    settings.git_allowed_private_hosts = ["127.0.0.1"]
    monkeypatch.setenv("GIT_SSL_NO_VERIFY", "true")
    try:
        async with (
            api_seed_state_factory(no_auth_integration_app) as seed,
            _api_client(no_auth_integration_app) as client,
        ):
            actor = await _register_actor(client, "seeded_success")
            await seed.promote_platform_admin(actor.user["id"])
            admin_login_response = await client.post(
                "/api/v1/auth/login",
                json={
                    "username": actor.username,
                    "password": actor.password,
                    "tenant_id": actor.user["tenant_id"],
                },
            )
            admin_login = _assert_status(admin_login_response, 200)
            admin_headers = {
                "Authorization": f"Bearer {admin_login['access_token']}",
            }

            admin_status_response = await client.get(
                "/api/v1/admin/status",
                headers=admin_headers,
            )
            admin_status = _assert_status(admin_status_response, 200)
            assert set(admin_status) == {
                "queue_depth",
                "in_flight",
                "success_rate_1h",
                "total_runs_1h",
            }
            assert admin_status["success_rate_1h"] >= 0

            with LocalHttpsGitRepo() as git_repo:
                branches_response = await client.post(
                    "/api/v1/projects/branches",
                    headers=actor.headers,
                    json={"git_url": git_repo.url},
                )
            branches = _assert_status(branches_response, 200)
            assert branches["default_branch"] == "main"
            assert branches["branches"] == ["feature/seed", "main", "release/api"]

            project = await _create_project(client, actor, prefix="seeded-members")
            seeded_member = await seed.create_same_tenant_user(
                tenant_id=actor.user["tenant_id"],
            )
            add_member_response = await client.post(
                f"/api/v1/projects/{project['id']}/members",
                headers=actor.headers,
                json={"user_id": seeded_member.id, "role": "viewer"},
            )
            added_member = _assert_status(add_member_response, 201)
            assert added_member["user_id"] == seeded_member.id
            assert added_member["username"] == seeded_member.username
            assert added_member["email"] == seeded_member.email
            assert added_member["role"] == "viewer"

            update_member_response = await client.put(
                f"/api/v1/projects/{project['id']}/members/{seeded_member.id}",
                headers=actor.headers,
                json={"role": "developer"},
            )
            updated_member = _assert_status(update_member_response, 200)
            assert updated_member["role"] == "developer"

            delete_member_response = await client.delete(
                f"/api/v1/projects/{project['id']}/members/{seeded_member.id}",
                headers=actor.headers,
            )
            _assert_status(delete_member_response, 204)

            list_members_response = await client.get(
                f"/api/v1/projects/{project['id']}/members",
                headers=actor.headers,
            )
            list_members = _assert_status(list_members_response, 200)
            assert all(
                item["user_id"] != seeded_member.id
                for item in list_members["data"]
            )
    finally:
        settings.git_allowed_private_hosts = original_private_hosts


@pytest.mark.parametrize(
    "case",
    SCHEMA_NEGATIVE_CASES,
    ids=_schema_negative_case_id,
)
async def test_openapi_atomic_schema_negative_case(
    no_auth_integration_app,
    case: SchemaNegativeCase,
) -> None:
    async with _api_client(no_auth_integration_app) as client:
        actor = await _register_actor(client, "schema")
        ids: dict[str, str] = {}
        if case.requires_stack:
            stack = await _create_project_stack(client, actor, prefix="schema")
            ids = {
                "project_id": stack["project"]["id"],
                "pipeline_id": stack["pipeline"]["id"],
            }

        duplicate_run_id = str(uuid4())
        response = await client.request(
            case.method,
            case.path(ids),
            **case.kwargs_factory(actor, ids, duplicate_run_id),
        )
        assert response.status_code == 422, (
            case.method,
            case.path(ids),
            response.status_code,
            response.text,
        )
        _assert_error_body(response)
