"""Public-API test data factory for black-box integration tests.

The helpers in this module only call documented HTTP endpoints. They create
the prerequisite resources API tests need and register cleanup calls that run
in reverse creation order.
"""
from __future__ import annotations

from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

import httpx
from httpx import AsyncClient, Response


Headers = Mapping[str, str]


@dataclass(frozen=True)
class ApiActor:
    username: str
    password: str
    access_token: str
    user: dict[str, Any]

    @property
    def headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.access_token}"}


@dataclass(frozen=True)
class ProjectStack:
    project: dict[str, Any]
    environment: dict[str, Any]
    pipeline: dict[str, Any]

    def as_dict(self) -> dict[str, dict[str, Any]]:
        return {
            "project": self.project,
            "environment": self.environment,
            "pipeline": self.pipeline,
        }


@dataclass(frozen=True)
class _Cleanup:
    method: str
    path: str
    headers: dict[str, str]
    expected_statuses: frozenset[int]
    label: str


def suffix(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex[:10]}"


def assert_status(response: Response, expected: int) -> dict[str, Any]:
    assert response.status_code == expected, response.text
    if expected == 204:
        assert response.content == b""
        return {}
    content_type = response.headers.get("content-type", "")
    assert "application/json" in content_type
    return response.json()


def project_payload(
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


def environment_payload(name: str) -> dict[str, Any]:
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


def pipeline_payload(name: str) -> dict[str, Any]:
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


def schedule_payload(pipeline_id: str) -> dict[str, Any]:
    return {
        "pipeline_id": pipeline_id,
        "cron_expr": "*/15 * * * *",
        "timezone": "UTC",
        "enabled": True,
    }


def notification_rule_payload(name: str) -> dict[str, Any]:
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


class ApiTestDataFactory:
    """Create and clean API test data through the public HTTP surface."""

    def __init__(self, client: AsyncClient) -> None:
        self.client = client
        self._cleanups: list[_Cleanup] = []

    async def register_actor(self, prefix: str = "api") -> ApiActor:
        """Register a test user.

        There is no public delete-user API, so actor cleanup is intentionally
        not attempted here.
        """
        username = suffix(prefix).replace("-", "_")[:32]
        password = f"TestPass-{uuid4().hex[:16]}"
        response = await self.client.post(
            "/api/v1/auth/register",
            json={
                "username": username,
                "email": f"{username}@qaplatform.dev",
                "password": password,
            },
        )
        body = assert_status(response, 201)
        assert body["token_type"] == "bearer"
        assert body["access_token"]
        assert body["user"]["username"] == username
        assert body["user"]["role"] == "owner"
        assert body["user"]["tenant_id"]
        return ApiActor(
            username=username,
            password=password,
            access_token=body["access_token"],
            user=body["user"],
        )

    async def create_project(
        self,
        *,
        headers: Headers,
        prefix: str = "project",
        git_url: str | None = None,
        settings: dict[str, Any] | None = None,
        payload_overrides: dict[str, Any] | None = None,
        track_cleanup: bool = True,
    ) -> dict[str, Any]:
        slug = suffix(prefix)
        payload = project_payload(slug, git_url=git_url, settings=settings)
        if payload_overrides:
            payload.update(payload_overrides)
        response = await self.client.post(
            "/api/v1/projects",
            headers=dict(headers),
            json=payload,
        )
        project = assert_status(response, 201)
        if track_cleanup:
            self._register_cleanup(
                "DELETE",
                f"/api/v1/projects/{project['id']}",
                headers,
                expected_statuses={204, 404},
                label=f"project {project['id']}",
            )
        return project

    async def create_environment(
        self,
        *,
        headers: Headers,
        project_id: str,
        name: str | None = None,
        payload_overrides: dict[str, Any] | None = None,
        track_cleanup: bool = True,
    ) -> dict[str, Any]:
        payload = environment_payload(name or suffix("env"))
        if payload_overrides:
            payload.update(payload_overrides)
        response = await self.client.post(
            f"/api/v1/projects/{project_id}/environments",
            headers=dict(headers),
            json=payload,
        )
        environment = assert_status(response, 201)
        if track_cleanup:
            self._register_cleanup(
                "DELETE",
                f"/api/v1/projects/{project_id}/environments/{environment['id']}",
                headers,
                expected_statuses={204, 404},
                label=f"environment {environment['id']}",
            )
        return environment

    async def create_pipeline(
        self,
        *,
        headers: Headers,
        project_id: str,
        name: str | None = None,
        payload_overrides: dict[str, Any] | None = None,
        track_cleanup: bool = True,
    ) -> dict[str, Any]:
        payload = pipeline_payload(name or suffix("pipeline"))
        if payload_overrides:
            payload.update(payload_overrides)
        response = await self.client.post(
            f"/api/v1/projects/{project_id}/pipelines",
            headers=dict(headers),
            json=payload,
        )
        pipeline = assert_status(response, 201)
        if track_cleanup:
            self._register_cleanup(
                "DELETE",
                f"/api/v1/projects/{project_id}/pipelines/{pipeline['id']}",
                headers,
                expected_statuses={204, 404},
                label=f"pipeline {pipeline['id']}",
            )
        return pipeline

    async def create_schedule(
        self,
        *,
        headers: Headers,
        project_id: str,
        pipeline_id: str,
        payload_overrides: dict[str, Any] | None = None,
        track_cleanup: bool = True,
    ) -> dict[str, Any]:
        payload = schedule_payload(pipeline_id)
        if payload_overrides:
            payload.update(payload_overrides)
        response = await self.client.post(
            f"/api/v1/projects/{project_id}/schedules",
            headers=dict(headers),
            json=payload,
        )
        schedule = assert_status(response, 201)
        if track_cleanup:
            self._register_cleanup(
                "DELETE",
                f"/api/v1/projects/{project_id}/schedules/{schedule['id']}",
                headers,
                expected_statuses={204, 404},
                label=f"schedule {schedule['id']}",
            )
        return schedule

    async def create_credential(
        self,
        *,
        headers: Headers,
        project_id: str,
        payload_overrides: dict[str, Any] | None = None,
        track_cleanup: bool = True,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "name": suffix("cred"),
            "type": "token",
            "value": "secret",
        }
        if payload_overrides:
            payload.update(payload_overrides)
        response = await self.client.post(
            f"/api/v1/projects/{project_id}/credentials",
            headers=dict(headers),
            json=payload,
        )
        credential = assert_status(response, 201)
        if track_cleanup:
            self._register_cleanup(
                "DELETE",
                f"/api/v1/projects/{project_id}/credentials/{credential['id']}",
                headers,
                expected_statuses={204, 404},
                label=f"credential {credential['id']}",
            )
        return credential

    async def create_notification_rule(
        self,
        *,
        headers: Headers,
        project_id: str,
        name: str | None = None,
        payload_overrides: dict[str, Any] | None = None,
        track_cleanup: bool = True,
    ) -> dict[str, Any]:
        payload = notification_rule_payload(name or suffix("notify"))
        if payload_overrides:
            payload.update(payload_overrides)
        response = await self.client.post(
            f"/api/v1/projects/{project_id}/notification-rules",
            headers=dict(headers),
            json=payload,
        )
        rule = assert_status(response, 201)
        if track_cleanup:
            self._register_cleanup(
                "DELETE",
                f"/api/v1/projects/{project_id}/notification-rules/{rule['id']}",
                headers,
                expected_statuses={204, 404},
                label=f"notification rule {rule['id']}",
            )
        return rule

    async def trigger_run(
        self,
        *,
        headers: Headers,
        pipeline_id: str,
        environment_id: str | None = None,
        payload_overrides: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "pipeline_id": pipeline_id,
            "git_ref": "main",
        }
        if environment_id is not None:
            payload["environment_id"] = environment_id
        if payload_overrides:
            payload.update(payload_overrides)
        response = await self.client.post(
            "/api/v1/runs",
            headers=dict(headers),
            json=payload,
        )
        return assert_status(response, 201)

    async def create_project_stack(
        self,
        *,
        headers: Headers,
        prefix: str = "stack",
        git_url: str | None = None,
        settings: dict[str, Any] | None = None,
        project_overrides: dict[str, Any] | None = None,
        environment_overrides: dict[str, Any] | None = None,
        pipeline_overrides: dict[str, Any] | None = None,
        track_cleanup: bool = True,
    ) -> ProjectStack:
        slug = suffix(prefix)
        project = await self.create_project(
            headers=headers,
            prefix=prefix,
            git_url=git_url,
            settings=settings,
            payload_overrides={
                **project_payload(slug, git_url=git_url, settings=settings),
                **(project_overrides or {}),
            },
            track_cleanup=track_cleanup,
        )
        environment = await self.create_environment(
            headers=headers,
            project_id=project["id"],
            name=f"{slug}-env",
            payload_overrides=environment_overrides,
            track_cleanup=track_cleanup,
        )
        default_env_response = await self.client.put(
            f"/api/v1/projects/{project['id']}",
            headers=dict(headers),
            json={"default_env_id": environment["id"]},
        )
        project = assert_status(default_env_response, 200)
        pipeline = await self.create_pipeline(
            headers=headers,
            project_id=project["id"],
            name=f"{slug}-pipeline",
            payload_overrides=pipeline_overrides,
            track_cleanup=track_cleanup,
        )
        return ProjectStack(
            project=project,
            environment=environment,
            pipeline=pipeline,
        )

    async def cleanup(self) -> list[str]:
        errors: list[str] = []
        while self._cleanups:
            cleanup = self._cleanups.pop()
            try:
                response = await self.client.request(
                    cleanup.method,
                    cleanup.path,
                    headers=cleanup.headers,
                )
            except httpx.HTTPError as exc:
                errors.append(f"{cleanup.label}: {exc!r}")
                continue
            if response.status_code not in cleanup.expected_statuses:
                errors.append(
                    f"{cleanup.label}: expected "
                    f"{sorted(cleanup.expected_statuses)}, got "
                    f"{response.status_code} {response.text[:300]}"
                )
        return errors

    def _register_cleanup(
        self,
        method: str,
        path: str,
        headers: Headers,
        *,
        expected_statuses: set[int],
        label: str,
    ) -> None:
        self._cleanups.append(
            _Cleanup(
                method=method,
                path=path,
                headers=dict(headers),
                expected_statuses=frozenset(expected_statuses),
                label=label,
            )
        )


@asynccontextmanager
async def api_data_factory(client: AsyncClient) -> AsyncIterator[ApiTestDataFactory]:
    factory = ApiTestDataFactory(client)
    cleanup_should_raise = True
    try:
        yield factory
    except BaseException:
        cleanup_should_raise = False
        raise
    finally:
        errors = await factory.cleanup()
        if errors and cleanup_should_raise:
            raise AssertionError("API test data cleanup failed: " + "; ".join(errors))
