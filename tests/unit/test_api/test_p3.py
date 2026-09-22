"""Tests for P3 endpoints: webhooks, analytics, batch operations."""

from __future__ import annotations

import json
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient
from sqlalchemy.exc import IntegrityError


@pytest.fixture
def tenant_id():
    return uuid.uuid4()


@pytest.fixture
def project_id():
    return uuid.uuid4()


@pytest.fixture
def mock_user(tenant_id):
    user = MagicMock()
    user.user_id = uuid.uuid4()
    user.tenant_id = tenant_id
    user.role = "owner"
    user.is_platform_admin = False
    return user


def _make_run(
    *,
    tenant_id,
    project_id,
    status,
    user_id=None,
    run_id=None,
    attempt=1,
):
    now = datetime.now(timezone.utc)
    return SimpleNamespace(
        id=run_id or uuid.uuid4(),
        tenant_id=tenant_id,
        project_id=project_id,
        pipeline_id=uuid.uuid4(),
        environment_id=uuid.uuid4(),
        status=status,
        trigger_type="manual",
        priority=1,
        triggered_by=user_id,
        git_ref="main",
        git_sha="abc123",
        attempt=attempt,
        started_at=None,
        finished_at=None,
        duration_ms=None,
        summary=None,
        error_message=None,
        created_at=now,
        updated_at=now,
        metadata_={},
        chain_depth=0,
        pipeline=SimpleNamespace(name="smoke"),
        environment=SimpleNamespace(name="default"),
    )


def _expected_run_response(run) -> dict:
    status = run.status.value if hasattr(run.status, "value") else run.status

    def _json_datetime(value):
        if value is None:
            return None
        return value.isoformat().replace("+00:00", "Z")

    return {
        "id": str(run.id),
        "tenant_id": str(run.tenant_id),
        "project_id": str(run.project_id),
        "pipeline_id": str(run.pipeline_id),
        "pipeline_name": run.pipeline.name,
        "environment_id": str(run.environment_id),
        "status": status,
        "trigger_type": run.trigger_type,
        "priority": run.priority,
        "triggered_by": str(run.triggered_by) if run.triggered_by else None,
        "git_ref": run.git_ref,
        "git_sha": run.git_sha,
        "attempt": run.attempt,
        "started_at": _json_datetime(run.started_at),
        "finished_at": _json_datetime(run.finished_at),
        "duration_ms": run.duration_ms,
        "summary": run.summary,
        "error_message": run.error_message,
        "created_at": _json_datetime(run.created_at),
        "updated_at": _json_datetime(run.updated_at),
    }


def _assert_cutoff_within_request_window(
    cutoff,
    *,
    days,
    started_at,
    finished_at,
):
    assert cutoff.tzinfo is timezone.utc
    assert started_at - timedelta(days=days) <= cutoff <= finished_at - timedelta(
        days=days,
    )


@pytest.fixture
def mock_project(project_id, tenant_id):
    obj = MagicMock()
    obj.id = project_id
    obj.tenant_id = tenant_id
    obj.status = "active"
    obj.git_url = "https://github.com/org/repo.git"
    obj.git_auth_method = "none"
    obj.credential_id = None
    obj.shallow_clone = False
    obj.default_branch = "main"
    obj.default_env_id = uuid.uuid4()
    obj.settings = {}
    return obj


@pytest.fixture
def mock_pipeline(project_id):
    obj = MagicMock()
    obj.id = uuid.uuid4()
    obj.project_id = project_id
    return obj


@pytest.fixture
def mock_repos(mock_project, mock_pipeline):
    repos = MagicMock()
    repos.project.get_for_tenant = AsyncMock(return_value=mock_project)
    repos.project.list_by_git_urls = AsyncMock(return_value=[mock_project])
    repos.pipeline.list_by_project = AsyncMock(return_value=([mock_pipeline], 1))
    repos.pipeline.get_latest_enabled = AsyncMock(return_value=mock_pipeline)
    repos.environment.list_by_project = AsyncMock(return_value=([MagicMock(id=uuid.uuid4())], 1))
    repos.run = AsyncMock()
    repos.run.create = AsyncMock()
    repos.run.get_for_tenant = AsyncMock()
    repos.run.get_active_by_dedup = AsyncMock(return_value=None)
    repos.test_result = AsyncMock()
    repos.run.cancel_if_current = AsyncMock(return_value=True)
    repos.audit = AsyncMock()
    repos.audit.create = AsyncMock()
    return repos


@pytest.fixture
def app(mock_repos, mock_user):
    from qaplatform.api.deps import _get_db_session, _get_repos, get_current_user
    from qaplatform.main import create_app

    container_mock = MagicMock()
    container_mock.redis_client = None
    app = create_app(container=container_mock)
    app.state.container = container_mock

    async def _override_repos():
        return mock_repos

    async def _override_user():
        return mock_user

    async def _override_session():
        yield AsyncMock()

    app.dependency_overrides[_get_repos] = _override_repos
    app.dependency_overrides[get_current_user] = _override_user
    app.dependency_overrides[_get_db_session] = _override_session
    return app


async def _make_client(app):
    transport = ASGITransport(app=app)
    return AsyncClient(transport=transport, base_url="http://test")


# --------------------------------------------------------------------------- #
# Webhook trigger
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("settings", "git_ref", "expected"),
    [
        ({}, "refs/heads/feature/foo", True),
        ({"allowed_branches": "main"}, "main", True),
        ({"allowed_branches": ["main"]}, "refs/heads/main", True),
        ({"allowed_branches": ["release/*"]}, "refs/heads/release/2026.05", True),
        ({"allowed_branches": ["main"]}, "refs/heads/feature/foo", False),
    ],
)
def test_webhook_allowed_branches(settings, git_ref, expected):
    from qaplatform.api.v1.webhooks import (
        _allowed_branch_patterns,
        _branch_allowed,
        _branch_name_from_ref,
    )

    branch_name = _branch_name_from_ref(git_ref)

    assert _branch_allowed(branch_name, _allowed_branch_patterns(settings)) is expected


def test_webhook_dedup_key_and_audit_state_defaults():
    from qaplatform.api.schemas import WebhookTriggerRequest
    from qaplatform.api.v1.webhooks import _dedup_key, _webhook_decision_audit_state

    project_id = uuid.uuid4()
    body = WebhookTriggerRequest(
        git_ref="main",
        git_sha="abc123",
        metadata={"delivery_id": "delivery-123"},
    )

    assert _dedup_key({}, "https://github.com/acme/widget.git", None, "main") is None
    assert (
        _dedup_key({}, "https://github.com/acme/widget.git", "abc123", "main")
        == "webhook:https://github.com/acme/widget.git:abc123:main"
    )
    assert _webhook_decision_audit_state(
        body,
        project_id=project_id,
        branch_name="main",
        status="duplicate",
        reason="dedup_key_conflict",
    ) == {
        "project_id": str(project_id),
        "status": "duplicate",
        "reason": "dedup_key_conflict",
        "git_ref": "main",
        "git_sha": "abc123",
        "branch_name": "main",
        "provider": "webhook",
        "delivery_id": "delivery-123",
    }


def test_signature_header_prefers_platform_header_then_github_alias():
    from qaplatform.api.v1.webhooks import _signature_header

    assert _signature_header(SimpleNamespace(headers={})) == ""
    assert _signature_header(
        SimpleNamespace(headers={"X-Hub-Signature-256": "sha256=github"})
    ) == "sha256=github"
    assert _signature_header(
        SimpleNamespace(
            headers={
                "X-Webhook-Signature": "sha256=platform",
                "X-Hub-Signature-256": "sha256=github",
            }
        )
    ) == "sha256=platform"


def test_webhook_route_module_reexports_pure_helper_functions():
    from qaplatform.api import webhook_helpers
    from qaplatform.api.v1 import webhooks

    assert webhooks._allowed_branch_patterns is webhook_helpers._allowed_branch_patterns
    assert webhooks._branch_allowed is webhook_helpers._branch_allowed
    assert webhooks._branch_name_from_ref is webhook_helpers._branch_name_from_ref
    assert webhooks._dedup_key is webhook_helpers._dedup_key
    assert (
        webhooks._github_payload_to_trigger_request
        is webhook_helpers._github_payload_to_trigger_request
    )
    assert webhooks._github_repo_url_candidates is webhook_helpers._github_repo_url_candidates
    assert webhooks._is_integrity_error is webhook_helpers._is_integrity_error
    assert (
        webhooks._webhook_decision_audit_state
        is webhook_helpers._webhook_decision_audit_state
    )


def test_github_repo_url_candidates_expand_common_clone_forms():
    from qaplatform.api.v1.webhooks import _github_repo_url_candidates

    candidates = _github_repo_url_candidates(
        {
            "clone_url": "https://github.com/acme/widget.git",
            "ssh_url": "git@github.com:acme/widget.git",
            "git_url": "git://github.com/acme/widget.git",
            "html_url": "https://github.com/acme/widget",
            "full_name": "acme/widget",
        }
    )

    assert candidates == {
        "https://github.com/acme/widget",
        "https://github.com/acme/widget.git",
        "git@github.com:acme/widget.git",
        "git://github.com/acme/widget.git",
    }


def test_github_push_payload_maps_to_webhook_trigger_request():
    from qaplatform.api.v1.webhooks import _github_payload_to_trigger_request

    body, repo_urls = _github_payload_to_trigger_request(
        {
            "ref": "refs/heads/main",
            "after": "a" * 40,
            "repository": {
                "full_name": "acme/widget",
                "html_url": "https://github.com/acme/widget",
            },
        },
        event="push",
        delivery_id="delivery-123",
    )

    assert body.git_ref == "refs/heads/main"
    assert body.git_sha == "a" * 40
    assert body.metadata == {
        "provider": "github",
        "event": "push",
        "delivery_id": "delivery-123",
        "repository": "acme/widget",
    }
    assert "https://github.com/acme/widget.git" in repo_urls


def test_github_pull_request_payload_uses_head_sha_and_base_repo_urls():
    from qaplatform.api.v1.webhooks import _github_payload_to_trigger_request

    body, repo_urls = _github_payload_to_trigger_request(
        {
            "pull_request": {
                "number": 42,
                "base": {
                    "repo": {
                        "full_name": "acme/widget",
                        "html_url": "https://github.com/acme/widget",
                    }
                },
                "head": {
                    "sha": "b" * 40,
                    "repo": {"full_name": "acme/widget"},
                },
            }
        },
        event="pull_request",
        delivery_id=None,
    )

    assert body.git_ref == "refs/pull/42/head"
    assert body.git_sha == "b" * 40
    assert body.metadata == {
        "provider": "github",
        "event": "pull_request",
        "repository": "acme/widget",
    }
    assert "https://github.com/acme/widget" in repo_urls


@pytest.mark.parametrize(
    ("payload", "event", "status_code", "detail"),
    [
        ({}, "push", 400, "Missing GitHub repository payload"),
        ({"repository": {}, "after": "a" * 40}, "push", 400, "Missing GitHub ref"),
        ({"repository": {}, "ref": "   ", "after": "a" * 40}, "push", 400, "Missing GitHub ref"),
        ({"repository": {}, "ref": "refs/heads/main"}, "push", 400, "Missing GitHub commit SHA"),
        (
            {"repository": {}, "ref": "refs/heads/main", "after": "not-a-sha"},
            "push",
            400,
            "Invalid GitHub commit SHA",
        ),
        ({}, "pull_request", 400, "Missing GitHub pull_request payload"),
        (
            {"pull_request": {"base": {}, "head": None}},
            "pull_request",
            400,
            "Missing GitHub pull_request refs",
        ),
        (
            {"pull_request": {"base": {"repo": {}}, "head": {"repo": None}}},
            "pull_request",
            400,
            "Missing GitHub pull_request repo",
        ),
        (
            {
                "pull_request": {
                    "number": "42",
                    "base": {"repo": {"full_name": "acme/widget"}},
                    "head": {"repo": {"full_name": "acme/widget"}, "sha": ""},
                }
            },
            "pull_request",
            400,
            "Missing GitHub pull_request number or SHA",
        ),
        (
            {
                "pull_request": {
                    "number": 42,
                    "base": {"repo": {"full_name": "acme/widget"}},
                    "head": {"repo": {"full_name": "acme/widget"}, "sha": "not-a-sha"},
                }
            },
            "pull_request",
            400,
            "Invalid GitHub pull_request SHA",
        ),
        (
            {
                "pull_request": {
                    "number": 1,
                    "base": {"repo": {"full_name": "acme/widget"}},
                    "head": {"repo": {"full_name": "fork/widget"}, "sha": "b" * 40},
                }
            },
            "pull_request",
            202,
            "Fork pull requests are ignored",
        ),
        ({}, "issues", 202, "Unsupported GitHub event: issues"),
    ],
)
def test_github_payload_validation_errors_are_explicit(payload, event, status_code, detail):
    from qaplatform.api.v1.webhooks import _github_payload_to_trigger_request

    with pytest.raises(HTTPException) as excinfo:
        _github_payload_to_trigger_request(payload, event=event, delivery_id=None)

    assert excinfo.value.status_code == status_code
    assert excinfo.value.detail == detail


def test_integrity_error_detection_follows_wrapped_driver_exceptions():
    from qaplatform.api.v1.webhooks import _is_integrity_error

    class UniqueViolationError(Exception):
        pass

    wrapped = RuntimeError("repository failed")
    wrapped.__cause__ = UniqueViolationError("duplicate key value violates unique constraint")

    assert _is_integrity_error(wrapped) is True
    assert _is_integrity_error(RuntimeError("connection reset")) is False


def _project_not_found_error() -> dict:
    return {
        "error": {
            "code": "NOT_FOUND",
            "message": "Project not found",
            "details": [],
        }
    }


def _assert_detail_openapi_response(response: dict) -> None:
    schema = response["content"]["application/json"]["schema"]
    assert schema["type"] == "object"
    assert schema["required"] == ["detail"]
    assert schema["properties"]["detail"]["type"] == "string"


def _assert_webhook_decision_openapi_response(response: dict) -> None:
    schema = response["content"]["application/json"]["schema"]
    assert schema["type"] == "object"
    assert schema["required"] == ["status"]
    assert schema["properties"]["status"]["type"] == "string"
    assert schema["properties"]["reason"]["type"] == "string"


def _assert_error_response_ref(response: dict) -> None:
    assert (
        response["content"]["application/json"]["schema"]["$ref"]
        == "#/components/schemas/ErrorResponse"
    )


def _assert_validation_error_response(
    resp,
    *,
    field: str,
    expected_type: str,
    expected_msg: str,
    expected_input: str,
) -> None:
    assert resp.status_code == 422
    assert _validation_error_projection(resp.json()["detail"]) == [
        {
            "type": expected_type,
            "loc": ["query", field],
            "msg": expected_msg,
            "input": expected_input,
        }
    ]


def _validation_error_projection(errors) -> list[dict]:
    return [
        {
            "type": error["type"],
            "loc": error["loc"],
            "msg": error["msg"],
            "input": error.get("input"),
        }
        for error in errors
    ]


def _assert_analytics_repositories_not_called(mock_repos) -> None:
    mock_repos.project.get_for_tenant.assert_not_awaited()
    mock_repos.run.list_trend_points.assert_not_awaited()
    mock_repos.test_result.list_flaky_tests.assert_not_awaited()
    mock_repos.test_result.list_test_history.assert_not_awaited()


_TOO_LONG_GIT_SHA = "a" * 101


def test_webhook_routes_document_actual_non_run_responses(app):
    openapi_paths = app.openapi()["paths"]

    project_responses = openapi_paths[
        "/api/v1/webhooks/{project_id}/trigger"
    ]["post"]["responses"]
    _assert_webhook_decision_openapi_response(project_responses["200"])
    _assert_detail_openapi_response(project_responses["401"])
    _assert_error_response_ref(project_responses["404"])
    _assert_detail_openapi_response(project_responses["409"])

    # Only check /api/v1/webhooks/{provider} as /webhooks/{provider} was removed
    provider_responses = openapi_paths["/api/v1/webhooks/{provider}"]["post"]["responses"]
    _assert_webhook_decision_openapi_response(provider_responses["200"])
    _assert_detail_openapi_response(provider_responses["202"])
    _assert_detail_openapi_response(provider_responses["400"])
    _assert_detail_openapi_response(provider_responses["401"])
    _assert_error_response_ref(provider_responses["404"])
    _assert_detail_openapi_response(provider_responses["409"])


class TestWebhookTrigger:
    @pytest.mark.asyncio
    async def test_webhook_trigger_missing_project_returns_404(
        self,
        app,
        mock_repos,
        mock_user,
        project_id,
    ):
        mock_repos.project.get_for_tenant = AsyncMock(return_value=None)

        async with await _make_client(app) as client:
            resp = await client.post(
                f"/api/v1/webhooks/{project_id}/trigger",
                json={"git_ref": "refs/heads/main", "git_sha": "abc123"},
            )

        assert resp.status_code == 404
        assert resp.json() == _project_not_found_error()
        mock_repos.project.get_for_tenant.assert_awaited_once_with(
            project_id,
            mock_user.tenant_id,
        )
        mock_repos.pipeline.get_latest_enabled.assert_not_awaited()
        mock_repos.environment.list_by_project.assert_not_awaited()
        mock_repos.run.get_active_by_dedup.assert_not_awaited()
        mock_repos.run.create.assert_not_awaited()
        mock_repos.audit.create.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_webhook_trigger_signed_project_requires_signature(
        self,
        app,
        mock_project,
        mock_repos,
        project_id,
    ):
        mock_project.settings = {"webhook_secret": "signed-webhook-secret"}

        async with await _make_client(app) as client:
            resp = await client.post(
                f"/api/v1/webhooks/{project_id}/trigger",
                json={"git_ref": "refs/heads/main", "git_sha": "abc123"},
            )

        assert resp.status_code == 401
        assert resp.json() == {"detail": "Missing X-Webhook-Signature header"}
        mock_repos.pipeline.get_latest_enabled.assert_not_awaited()
        mock_repos.environment.list_by_project.assert_not_awaited()
        mock_repos.run.get_active_by_dedup.assert_not_awaited()
        mock_repos.run.create.assert_not_awaited()
        mock_repos.audit.create.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_webhook_trigger_creates_run(
        self,
        app,
        mock_repos,
        project_id,
        mock_project,
        mock_pipeline,
        mock_user,
    ):
        run = MagicMock()
        run.id = uuid.uuid4()
        run.project_id = project_id
        run.pipeline_id = mock_pipeline.id
        run.pipeline = MagicMock()
        run.pipeline.name = "test-pipeline"
        run.status = "queued"
        run.trigger_type = "webhook"
        run.triggered_by = uuid.uuid4()
        run.git_ref = "main"
        run.git_sha = "abc123"
        run.attempt = 1
        run.started_at = None
        run.finished_at = None
        run.duration_ms = None
        run.summary = None
        run.error_message = None
        run.created_at = datetime.now(timezone.utc)
        run.updated_at = datetime.now(timezone.utc)
        run.tenant_id = uuid.uuid4()
        run.environment_id = uuid.uuid4()
        run.priority = 1
        mock_repos.run.create = AsyncMock(return_value=run)

        with patch(
            "qaplatform.worker.scheduler.enqueue_run",
            new_callable=AsyncMock,
        ) as enqueue_run:
            async with await _make_client(app) as client:
                resp = await client.post(
                    f"/api/v1/webhooks/{project_id}/trigger",
                    json={"git_ref": "refs/heads/main", "git_sha": "abc123"},
                )

        assert resp.status_code == 201
        assert resp.json() == _expected_run_response(run)
        mock_repos.pipeline.get_latest_enabled.assert_awaited_once_with(project_id)
        expected_dedup_key = "webhook:https://github.com/org/repo.git:abc123:main"
        mock_repos.run.get_active_by_dedup.assert_awaited_once_with(
            project_id=project_id,
            pipeline_id=mock_pipeline.id,
            dedup_key=expected_dedup_key,
        )
        mock_repos.run.create.assert_awaited_once()
        call_kwargs = mock_repos.run.create.await_args.kwargs
        assert call_kwargs == {
            "tenant_id": mock_project.tenant_id,
            "project_id": project_id,
            "pipeline_id": mock_pipeline.id,
            "environment_id": mock_project.default_env_id,
            "git_ref": "refs/heads/main",
            "git_sha": "abc123",
            "triggered_by": mock_user.user_id,
            "trigger_type": "webhook",
            "metadata_": {
                "git_url": "https://github.com/org/repo.git",
                "default_branch": "main",
            },
            "dedup_key": expected_dedup_key,
        }
        mock_repos.run.set_retry_group_id.assert_awaited_once_with(run.id, run.id)
        enqueue_run.assert_awaited_once()
        assert enqueue_run.await_args.args == (
            app.state.container.arq_pool,
            mock_repos.run,
            run,
            "webhook",
            app.state.container.settings,
        )
        assert enqueue_run.await_args.kwargs == {}

    @pytest.mark.asyncio
    async def test_webhook_trigger_queue_unavailable_returns_created_waiting_run(
        self,
        app,
        mock_repos,
        project_id,
        mock_project,
        mock_pipeline,
        mock_user,
    ):
        run = _make_run(
            tenant_id=mock_project.tenant_id,
            project_id=project_id,
            status="queued",
            user_id=mock_user.user_id,
        )
        run.pipeline_id = mock_pipeline.id
        run.trigger_type = "webhook"
        mock_repos.run.create = AsyncMock(return_value=run)
        mock_repos.run.count_active_or_enqueued = AsyncMock(return_value=0)
        mock_repos.run.count_active_or_enqueued_by_project = AsyncMock(return_value=0)
        mock_repos.run.mark_waiting = AsyncMock()
        mock_repos.run.mark_enqueued = AsyncMock()

        @asynccontextmanager
        async def _fake_lock():
            yield

        mock_repos.run.scheduler_lock = _fake_lock
        arq_pool = AsyncMock()
        arq_pool.enqueue_job = AsyncMock(
            side_effect=RuntimeError("redis://webhook-queue-secret@localhost/0")
        )
        app.state.container.arq_pool = arq_pool
        app.state.container.settings = SimpleNamespace(
            max_concurrent_runs=5,
            max_concurrent_per_project=3,
        )

        async with await _make_client(app) as client:
            resp = await client.post(
                f"/api/v1/webhooks/{project_id}/trigger",
                json={"git_ref": "refs/heads/main", "git_sha": "abc123"},
            )

        assert resp.status_code == 201, resp.text
        assert "webhook-queue-secret" not in resp.text
        assert resp.json() == _expected_run_response(run)
        arq_pool.enqueue_job.assert_awaited_once_with(
            "execute_run",
            str(run.id),
            _queue_name="queue:medium",
            _job_id=f"run:{run.id}",
            _defer_by=0,
        )
        mock_repos.run.mark_waiting.assert_awaited_once_with(
            run.id,
            reason="queue unavailable",
        )
        mock_repos.run.mark_enqueued.assert_not_awaited()
        mock_repos.audit.create.assert_awaited_once()
        assert mock_repos.audit.create.await_args.kwargs["after_state"] == resp.json()

    @pytest.mark.asyncio
    async def test_webhook_trigger_preserves_project_git_auth_metadata(
        self, app, mock_repos, project_id, mock_project, mock_pipeline, mock_user
    ):
        credential_id = uuid.uuid4()
        attacker_credential_id = uuid.uuid4()
        mock_project.git_auth_method = "token"
        mock_project.credential_id = credential_id
        mock_project.shallow_clone = True
        run = _make_run(
            tenant_id=mock_project.tenant_id,
            project_id=project_id,
            status="queued",
        )
        run.pipeline_id = mock_pipeline.id
        run.trigger_type = "webhook"
        mock_repos.run.create = AsyncMock(return_value=run)
        expected_dedup_key = "webhook:https://github.com/org/repo.git:abc123:main"
        expected_metadata = {
            "git_url": "https://github.com/org/repo.git",
            "git_auth_method": "token",
            "credential_id": str(credential_id),
            "shallow_clone": True,
            "default_branch": "main",
            "delivery_id": "delivery-1",
            "trace_id": "trace-123",
        }

        with patch("qaplatform.worker.scheduler.enqueue_run", new_callable=AsyncMock):
            async with await _make_client(app) as client:
                resp = await client.post(
                    f"/api/v1/webhooks/{project_id}/trigger",
                    json={
                        "git_ref": "refs/heads/main",
                        "git_sha": "abc123",
                        "metadata": {
                            "GIT_URL": "https://evil.example/repo.git",
                            "git_auth_method": "ssh_key",
                            "Credential_ID": str(attacker_credential_id),
                            "default_branch": "evil-main",
                            "shallow_clone": False,
                            "delivery_id": "delivery-1",
                            "trace_id": "trace-123",
                        },
                    },
                )

        assert resp.status_code == 201, resp.text
        assert resp.json() == _expected_run_response(run)
        mock_repos.run.get_active_by_dedup.assert_awaited_once_with(
            project_id=project_id,
            pipeline_id=mock_pipeline.id,
            dedup_key=expected_dedup_key,
        )
        mock_repos.run.create.assert_awaited_once()
        create_kwargs = mock_repos.run.create.await_args.kwargs
        assert create_kwargs == {
            "tenant_id": mock_project.tenant_id,
            "project_id": project_id,
            "pipeline_id": mock_pipeline.id,
            "environment_id": mock_project.default_env_id,
            "git_ref": "refs/heads/main",
            "git_sha": "abc123",
            "triggered_by": mock_user.user_id,
            "trigger_type": "webhook",
            "metadata_": expected_metadata,
            "dedup_key": expected_dedup_key,
        }
        rendered_create = repr(create_kwargs)
        assert str(attacker_credential_id) not in rendered_create
        assert "https://evil.example/repo.git" not in rendered_create
        assert "evil-main" not in rendered_create

    @pytest.mark.parametrize(
        ("payload", "expected_error"),
        [
            (
                {"git_ref": "   "},
                {
                    "type": "value_error",
                    "loc": ["body", "git_ref"],
                    "msg": "Value error, webhook git_ref must not be blank",
                    "input": "   ",
                },
            ),
            (
                {"git_sha": ""},
                {
                    "type": "string_too_short",
                    "loc": ["body", "git_sha"],
                    "msg": "String should have at least 1 character",
                    "input": "",
                },
            ),
            (
                {"git_sha": "   "},
                {
                    "type": "value_error",
                    "loc": ["body", "git_sha"],
                    "msg": "Value error, webhook git_sha must not be blank",
                    "input": "   ",
                },
            ),
            (
                {"git_sha": _TOO_LONG_GIT_SHA},
                {
                    "type": "string_too_long",
                    "loc": ["body", "git_sha"],
                    "msg": "String should have at most 100 characters",
                    "input": _TOO_LONG_GIT_SHA,
                },
            ),
        ],
    )
    @pytest.mark.asyncio
    async def test_webhook_trigger_rejects_invalid_git_inputs_without_side_effects(
        self,
        app,
        mock_repos,
        payload,
        expected_error,
        project_id,
    ):
        async with await _make_client(app) as client:
            resp = await client.post(
                f"/api/v1/webhooks/{project_id}/trigger",
                json={"git_ref": "refs/heads/main", **payload},
            )

        assert resp.status_code == 422, resp.text
        assert _validation_error_projection(resp.json()["detail"]) == [
            expected_error
        ]
        mock_repos.project.get_for_tenant.assert_not_awaited()
        mock_repos.pipeline.get_latest_enabled.assert_not_awaited()
        mock_repos.environment.list_by_project.assert_not_awaited()
        mock_repos.run.get_active_by_dedup.assert_not_awaited()
        mock_repos.run.create.assert_not_awaited()
        mock_repos.run.set_retry_group_id.assert_not_awaited()
        mock_repos.audit.create.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_webhook_trigger_archived_project_409(self, app, mock_repos, project_id):
        mock_repos.project.get_for_tenant = AsyncMock(
            return_value=SimpleNamespace(status="archived", id=project_id, settings={})
        )

        async with await _make_client(app) as client:
            resp = await client.post(
                f"/api/v1/webhooks/{project_id}/trigger",
                json={"git_ref": "main"},
        )

        assert resp.status_code == 409
        assert resp.json() == {
            "detail": "Project is archived; new runs cannot be triggered"
        }
        mock_repos.pipeline.get_latest_enabled.assert_not_awaited()
        mock_repos.environment.list_by_project.assert_not_awaited()
        mock_repos.run.get_active_by_dedup.assert_not_awaited()
        mock_repos.run.create.assert_not_awaited()
        mock_repos.audit.create.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_webhook_trigger_filtered_branch_returns_200_without_run(
        self,
        app,
        mock_project,
        mock_repos,
        project_id,
    ):
        mock_project.settings = {"allowed_branches": ["main"]}

        async with await _make_client(app) as client:
            resp = await client.post(
                f"/api/v1/webhooks/{project_id}/trigger",
                json={
                    "git_ref": "refs/heads/feature/foo",
                    "git_sha": "abc123",
                    "metadata": {
                        "provider": "github",
                        "delivery_id": "delivery-filtered-123",
                        "git_url": "https://attacker.example/repo.git",
                        "dedup_key": "should-not-leak",
                    },
                },
            )

        assert resp.status_code == 200
        assert resp.json() == {"status": "filtered", "reason": "branch_not_allowed"}
        mock_repos.pipeline.get_latest_enabled.assert_not_awaited()
        mock_repos.environment.list_by_project.assert_not_awaited()
        mock_repos.run.get_active_by_dedup.assert_not_awaited()
        mock_repos.run.create.assert_not_awaited()
        mock_repos.run.set_retry_group_id.assert_not_awaited()
        mock_repos.audit.create.assert_awaited_once()
        audit_kwargs = mock_repos.audit.create.await_args.kwargs
        assert audit_kwargs["action"] == "webhook.filtered"
        assert audit_kwargs["resource_type"] == "project"
        assert audit_kwargs["resource_id"] == mock_project.id
        assert audit_kwargs["after_state"] == {
            "project_id": str(mock_project.id),
            "status": "filtered",
            "reason": "branch_not_allowed",
            "git_ref": "refs/heads/feature/foo",
            "git_sha": "abc123",
            "branch_name": "feature/foo",
            "provider": "github",
            "delivery_id": "delivery-filtered-123",
        }
        assert mock_project.git_url not in repr(audit_kwargs["after_state"])
        assert "attacker.example" not in repr(audit_kwargs["after_state"])
        assert "should-not-leak" not in repr(audit_kwargs["after_state"])

    @pytest.mark.asyncio
    async def test_webhook_trigger_invalid_signature_stops_before_rbac_or_run_creation(
        self,
        app,
        mock_project,
        mock_repos,
        project_id,
    ):
        mock_project.settings = {"webhook_secret": "signed-webhook-secret"}

        with patch(
            "qaplatform.api.v1.webhooks.enforce_project_action",
            new_callable=AsyncMock,
        ) as enforce_action:
            async with await _make_client(app) as client:
                resp = await client.post(
                    f"/api/v1/webhooks/{project_id}/trigger",
                    json={"git_ref": "refs/heads/main", "git_sha": "abc123"},
                    headers={"X-Webhook-Signature": "sha256=bad"},
                )

        assert resp.status_code == 401
        assert resp.json() == {"detail": "Invalid webhook signature"}
        enforce_action.assert_not_awaited()
        mock_repos.pipeline.get_latest_enabled.assert_not_awaited()
        mock_repos.environment.list_by_project.assert_not_awaited()
        mock_repos.run.get_active_by_dedup.assert_not_awaited()
        mock_repos.run.create.assert_not_awaited()
        mock_repos.run.set_retry_group_id.assert_not_awaited()
        mock_repos.audit.create.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_webhook_trigger_existing_dedup_short_circuits_run_creation(
        self,
        app,
        mock_project,
        mock_repos,
        mock_pipeline,
        project_id,
    ):
        mock_repos.run.get_active_by_dedup = AsyncMock(return_value=MagicMock())

        async with await _make_client(app) as client:
            resp = await client.post(
                f"/api/v1/webhooks/{project_id}/trigger",
                json={
                    "git_ref": "refs/heads/main",
                    "git_sha": "abc123",
                    "metadata": {"provider": "github"},
                },
            )

        assert resp.status_code == 200
        assert resp.json() == {"status": "duplicate"}
        mock_repos.pipeline.get_latest_enabled.assert_awaited_once_with(project_id)
        mock_repos.run.get_active_by_dedup.assert_awaited_once_with(
            project_id=project_id,
            pipeline_id=mock_pipeline.id,
            dedup_key="github:https://github.com/org/repo.git:abc123:main",
        )
        mock_repos.run.create.assert_not_awaited()
        mock_repos.run.set_retry_group_id.assert_not_awaited()
        mock_repos.audit.create.assert_awaited_once()
        audit_kwargs = mock_repos.audit.create.await_args.kwargs
        assert audit_kwargs["action"] == "webhook.duplicate"
        assert audit_kwargs["resource_type"] == "project"
        assert audit_kwargs["resource_id"] == mock_project.id
        assert audit_kwargs["after_state"] == {
            "project_id": str(mock_project.id),
            "status": "duplicate",
            "reason": "dedup_key_conflict",
            "git_ref": "refs/heads/main",
            "git_sha": "abc123",
            "branch_name": "main",
            "provider": "github",
        }
        assert mock_project.git_url not in repr(audit_kwargs["after_state"])

    @pytest.mark.asyncio
    async def test_webhook_trigger_dedup_integrity_error_returns_duplicate(
        self,
        app,
        mock_repos,
        project_id,
    ):
        mock_repos.run.create = AsyncMock(
            side_effect=IntegrityError("insert run", {}, Exception("duplicate"))
        )

        async with await _make_client(app) as client:
            resp = await client.post(
                f"/api/v1/webhooks/{project_id}/trigger",
                json={"git_ref": "refs/heads/main", "git_sha": "abc123"},
            )

        assert resp.status_code == 200
        assert resp.json() == {"status": "duplicate"}
        mock_repos.audit.create.assert_awaited_once()
        audit_kwargs = mock_repos.audit.create.await_args.kwargs
        assert audit_kwargs["action"] == "webhook.duplicate"
        assert audit_kwargs["resource_type"] == "project"
        assert audit_kwargs["resource_id"] == project_id
        assert audit_kwargs["after_state"]["status"] == "duplicate"
        assert audit_kwargs["after_state"]["reason"] == "dedup_key_conflict"
        assert audit_kwargs["after_state"]["branch_name"] == "main"


class TestProviderWebhookTrigger:
    @pytest.mark.asyncio
    async def test_provider_webhook_invalid_json_short_circuits_repo_lookup(
        self,
        app,
        mock_repos,
    ):
        async with await _make_client(app) as client:
            resp = await client.post(
                "/api/v1/webhooks/github",
                content="{",
                headers={"Content-Type": "application/json"},
            )

        assert resp.status_code == 400
        assert resp.json() == {"detail": "Invalid webhook JSON"}
        mock_repos.project.list_by_git_urls.assert_not_awaited()
        mock_repos.pipeline.get_latest_enabled.assert_not_awaited()
        mock_repos.environment.list_by_project.assert_not_awaited()
        mock_repos.run.get_active_by_dedup.assert_not_awaited()
        mock_repos.run.create.assert_not_awaited()
        mock_repos.audit.create.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_provider_webhook_ignored_event_short_circuits_repo_lookup(
        self,
        app,
        mock_repos,
    ):
        async with await _make_client(app) as client:
            resp = await client.post(
                "/api/v1/webhooks/github",
                json={},
                headers={"X-GitHub-Event": "issues"},
            )

        assert resp.status_code == 202
        assert resp.json() == {"detail": "Unsupported GitHub event: issues"}
        mock_repos.project.list_by_git_urls.assert_not_awaited()
        mock_repos.pipeline.get_latest_enabled.assert_not_awaited()
        mock_repos.environment.list_by_project.assert_not_awaited()
        mock_repos.run.get_active_by_dedup.assert_not_awaited()
        mock_repos.run.create.assert_not_awaited()
        mock_repos.audit.create.assert_not_awaited()

    @pytest.mark.parametrize(
        ("payload", "detail"),
        [
            (
                {
                    "ref": "refs/heads/main",
                    "after": "not-a-sha",
                    "repository": {
                        "full_name": "acme/widget",
                        "html_url": "https://github.com/acme/widget",
                    },
                },
                "Invalid GitHub commit SHA",
            ),
            (
                {
                    "ref": "   ",
                    "after": "a" * 40,
                    "repository": {
                        "full_name": "acme/widget",
                        "html_url": "https://github.com/acme/widget",
                    },
                },
                "Missing GitHub ref",
            ),
        ],
    )
    @pytest.mark.asyncio
    async def test_provider_webhook_invalid_github_payload_short_circuits_repo_lookup(
        self,
        app,
        mock_repos,
        payload,
        detail,
    ):
        async with await _make_client(app) as client:
            resp = await client.post(
                "/api/v1/webhooks/github",
                json=payload,
                headers={"X-GitHub-Event": "push"},
            )

        assert resp.status_code == 400
        assert resp.json() == {"detail": detail}
        mock_repos.project.list_by_git_urls.assert_not_awaited()
        mock_repos.pipeline.get_latest_enabled.assert_not_awaited()
        mock_repos.environment.list_by_project.assert_not_awaited()
        mock_repos.run.get_active_by_dedup.assert_not_awaited()
        mock_repos.run.create.assert_not_awaited()
        mock_repos.audit.create.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_provider_webhook_invalid_signature_stops_before_run_creation(
        self,
        app,
        mock_project,
        mock_repos,
    ):
        mock_project.settings = {"webhook_secret": "github-provider-secret"}
        payload = {
            "ref": "refs/heads/main",
            "after": "a" * 40,
            "repository": {
                "full_name": "acme/widget",
                "html_url": "https://github.com/acme/widget",
            },
        }
        raw_body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()

        async with await _make_client(app) as client:
            resp = await client.post(
                "/api/v1/webhooks/github",
                content=raw_body,
                headers={
                    "Content-Type": "application/json",
                    "X-GitHub-Event": "push",
                    "X-Hub-Signature-256": "sha256=bad",
                },
            )

        assert resp.status_code == 401
        assert resp.json() == {"detail": "Invalid webhook signature"}
        mock_repos.project.list_by_git_urls.assert_awaited_once()
        mock_repos.pipeline.get_latest_enabled.assert_not_awaited()
        mock_repos.environment.list_by_project.assert_not_awaited()
        mock_repos.run.get_active_by_dedup.assert_not_awaited()
        mock_repos.run.create.assert_not_awaited()
        mock_repos.run.set_retry_group_id.assert_not_awaited()
        mock_repos.audit.create.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_provider_webhook_ambiguous_signed_projects_stop_before_run_creation(
        self,
        app,
        mock_project,
        mock_repos,
        tenant_id,
    ):
        from qaplatform.infra.webhook_signature import generate_webhook_signature

        secret = "github-provider-secret"
        mock_project.settings = {"webhook_secret": secret}
        other_project = MagicMock()
        other_project.id = uuid.uuid4()
        other_project.tenant_id = tenant_id
        other_project.settings = {"webhook_secret": secret}
        mock_repos.project.list_by_git_urls = AsyncMock(
            return_value=[mock_project, other_project]
        )
        payload = {
            "ref": "refs/heads/main",
            "after": "a" * 40,
            "repository": {
                "full_name": "acme/widget",
                "html_url": "https://github.com/acme/widget",
            },
        }
        raw_body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()

        async with await _make_client(app) as client:
            resp = await client.post(
                "/api/v1/webhooks/github",
                content=raw_body,
                headers={
                    "Content-Type": "application/json",
                    "X-GitHub-Event": "push",
                    "X-Hub-Signature-256": generate_webhook_signature(secret, raw_body),
                },
            )

        assert resp.status_code == 409
        assert resp.json() == {"detail": "Ambiguous webhook repository match"}
        mock_repos.pipeline.get_latest_enabled.assert_not_awaited()
        mock_repos.environment.list_by_project.assert_not_awaited()
        mock_repos.run.get_active_by_dedup.assert_not_awaited()
        mock_repos.run.create.assert_not_awaited()
        mock_repos.run.set_retry_group_id.assert_not_awaited()
        mock_repos.audit.create.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_provider_webhook_success_uses_system_identity_and_metadata(
        self,
        app,
        mock_project,
        mock_repos,
        mock_pipeline,
    ):
        from qaplatform.infra.webhook_signature import generate_webhook_signature

        secret = "github-provider-secret"
        mock_project.settings = {"webhook_secret": secret}
        run = _make_run(
            tenant_id=mock_project.tenant_id,
            project_id=mock_project.id,
            status="queued",
        )
        run.pipeline_id = mock_pipeline.id
        run.trigger_type = "webhook"
        run.triggered_by = None
        run.git_ref = "refs/heads/main"
        run.git_sha = "a" * 40
        mock_repos.run.create = AsyncMock(return_value=run)
        payload = {
            "ref": "refs/heads/main",
            "after": "a" * 40,
            "repository": {
                "full_name": "acme/widget",
                "html_url": "https://github.com/acme/widget",
            },
        }
        raw_body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()

        with patch("qaplatform.worker.scheduler.enqueue_run", new_callable=AsyncMock) as enqueue_run:
            async with await _make_client(app) as client:
                resp = await client.post(
                    "/api/v1/webhooks/github",
                    content=raw_body,
                    headers={
                        "Content-Type": "application/json",
                        "X-GitHub-Event": "push",
                        "X-GitHub-Delivery": "delivery-123",
                        "X-Hub-Signature-256": generate_webhook_signature(secret, raw_body),
                    },
                )

        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body == _expected_run_response(run)
        repo_urls = mock_repos.project.list_by_git_urls.await_args.args[0]
        assert repo_urls == {
            "https://github.com/acme/widget",
            "https://github.com/acme/widget.git",
            "git@github.com:acme/widget.git",
        }
        expected_dedup_key = f"github:{mock_project.git_url}:{'a' * 40}:main"
        mock_repos.run.get_active_by_dedup.assert_awaited_once_with(
            project_id=mock_project.id,
            pipeline_id=mock_pipeline.id,
            dedup_key=expected_dedup_key,
        )
        expected_metadata = {
            "git_url": mock_project.git_url,
            "default_branch": "main",
            "provider": "github",
            "event": "push",
            "delivery_id": "delivery-123",
            "repository": "acme/widget",
        }
        mock_repos.run.create.assert_awaited_once_with(
            tenant_id=mock_project.tenant_id,
            project_id=mock_project.id,
            pipeline_id=mock_pipeline.id,
            environment_id=mock_project.default_env_id,
            git_ref="refs/heads/main",
            git_sha="a" * 40,
            triggered_by=None,
            trigger_type="webhook",
            metadata_=expected_metadata,
            dedup_key=expected_dedup_key,
        )
        mock_repos.run.set_retry_group_id.assert_awaited_once_with(run.id, run.id)
        enqueue_run.assert_awaited_once()
        assert enqueue_run.await_args.args == (
            app.state.container.arq_pool,
            mock_repos.run,
            run,
            "webhook",
            app.state.container.settings,
        )
        assert enqueue_run.await_args.kwargs == {}
        assert mock_repos.audit.create.await_args.kwargs == {
            "tenant_id": mock_project.tenant_id,
            "user_id": None,
            "action": "run.trigger",
            "resource_type": "run",
            "resource_id": run.id,
            "before_state": None,
            "after_state": body,
        }

    @pytest.mark.asyncio
    async def test_provider_webhook_missing_signature_stops_before_run_creation(
        self,
        app,
        mock_repos,
    ):
        payload = {
            "ref": "refs/heads/main",
            "after": "a" * 40,
            "repository": {
                "full_name": "acme/widget",
                "html_url": "https://github.com/acme/widget",
            },
        }

        async with await _make_client(app) as client:
            resp = await client.post(
                "/api/v1/webhooks/github",
                json=payload,
                headers={"X-GitHub-Event": "push"},
            )

        assert resp.status_code == 401
        assert resp.json() == {"detail": "Missing webhook signature header"}
        mock_repos.project.list_by_git_urls.assert_awaited_once()
        repo_urls = mock_repos.project.list_by_git_urls.await_args.args[0]
        assert "https://github.com/acme/widget.git" in repo_urls
        mock_repos.pipeline.get_latest_enabled.assert_not_awaited()
        mock_repos.environment.list_by_project.assert_not_awaited()
        mock_repos.run.get_active_by_dedup.assert_not_awaited()
        mock_repos.run.create.assert_not_awaited()
        mock_repos.audit.create.assert_not_awaited()


# --------------------------------------------------------------------------- #
# Batch operations
# --------------------------------------------------------------------------- #


class TestBatchCancel:
    @pytest.mark.asyncio
    async def test_batch_cancel_success(self, app, mock_repos, tenant_id):
        from qaplatform.infra.database.models import RunStatusEnum

        run = _make_run(
            tenant_id=tenant_id,
            project_id=uuid.uuid4(),
            status=RunStatusEnum.RUNNING,
        )
        run_after = _make_run(
            tenant_id=tenant_id,
            project_id=run.project_id,
            status=RunStatusEnum.CANCELLED,
            run_id=run.id,
        )
        mock_repos.run.get_for_tenant = AsyncMock(side_effect=[run, run_after])
        mock_repos.run.cancel_if_current = AsyncMock(return_value=True)

        with patch("qaplatform.engine.cancel.publish_cancel", new_callable=AsyncMock), \
             patch("qaplatform.engine.events.publish_status_event", new_callable=AsyncMock):
            async with await _make_client(app) as client:
                resp = await client.post(
                    "/api/v1/runs/batch/cancel",
                    json={"run_ids": [str(run.id)]},
                )

        assert resp.status_code == 200
        assert resp.json() == {"processed": 1, "failed": 0, "errors": []}
        mock_repos.audit.create.assert_awaited_once()
        audit_kwargs = mock_repos.audit.create.await_args.kwargs
        assert audit_kwargs["action"] == "run.batch_cancel"
        assert audit_kwargs["resource_id"] == run.id
        assert audit_kwargs["before_state"]["status"] == "running"
        assert audit_kwargs["after_state"]["status"] == "cancelled"

    @pytest.mark.asyncio
    async def test_batch_cancel_not_found(self, app, mock_repos, mock_user):
        run_id = uuid.uuid4()
        mock_repos.run.get_for_tenant = AsyncMock(return_value=None)
        app.state.container.redis_client = MagicMock()

        with patch("qaplatform.engine.cancel.publish_cancel", new_callable=AsyncMock) as publish_cancel, \
             patch("qaplatform.engine.events.publish_status_event", new_callable=AsyncMock) as publish_status:
            async with await _make_client(app) as client:
                resp = await client.post(
                    "/api/v1/runs/batch/cancel",
                    json={"run_ids": [str(run_id)]},
                )

        assert resp.status_code == 200
        assert resp.json() == {
            "processed": 0,
            "failed": 1,
            "errors": [f"{run_id}: not found"],
        }
        mock_repos.run.get_for_tenant.assert_awaited_once_with(run_id, mock_user.tenant_id)
        mock_repos.run.cancel_if_current.assert_not_awaited()
        publish_cancel.assert_not_awaited()
        publish_status.assert_not_awaited()
        mock_repos.audit.create.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_batch_cancel_internal_failure_redacts_exception_without_side_effects(
        self,
        app,
        mock_repos,
        mock_user,
    ):
        run_id = uuid.uuid4()
        secret_error = "select * from runs where token='batch-cancel-secret'"
        mock_repos.run.get_for_tenant = AsyncMock(side_effect=ValueError(secret_error))
        app.state.container.redis_client = MagicMock()

        with patch("qaplatform.engine.cancel.publish_cancel", new_callable=AsyncMock) as publish_cancel, \
             patch("qaplatform.engine.events.publish_status_event", new_callable=AsyncMock) as publish_status:
            async with await _make_client(app) as client:
                resp = await client.post(
                    "/api/v1/runs/batch/cancel",
                    json={"run_ids": [str(run_id)]},
                )

        assert resp.status_code == 200
        assert resp.json() == {
            "processed": 0,
            "failed": 1,
            "errors": [f"{run_id}: operation failed"],
        }
        assert secret_error not in resp.text
        assert "batch-cancel-secret" not in resp.text
        mock_repos.run.get_for_tenant.assert_awaited_once_with(
            run_id,
            mock_user.tenant_id,
        )
        mock_repos.run.cancel_if_current.assert_not_awaited()
        publish_cancel.assert_not_awaited()
        publish_status.assert_not_awaited()
        mock_repos.audit.create.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_batch_cancel_rejects_duplicate_run_ids_without_side_effects(
        self,
        app,
        mock_repos,
    ):
        run_id = uuid.uuid4()
        duplicate_run_ids = [str(run_id), str(run_id)]

        with patch("qaplatform.engine.cancel.publish_cancel", new_callable=AsyncMock) as publish_cancel, \
             patch("qaplatform.engine.events.publish_status_event", new_callable=AsyncMock) as publish_status:
            async with await _make_client(app) as client:
                resp = await client.post(
                    "/api/v1/runs/batch/cancel",
                    json={"run_ids": duplicate_run_ids},
                )

        assert resp.status_code == 422, resp.text
        assert _validation_error_projection(resp.json()["detail"]) == [
            {
                "type": "value_error",
                "loc": ["body", "run_ids"],
                "msg": "Value error, duplicate run_ids are not allowed",
                "input": duplicate_run_ids,
            }
        ]
        mock_repos.run.get_for_tenant.assert_not_awaited()
        mock_repos.run.cancel_if_current.assert_not_awaited()
        publish_cancel.assert_not_awaited()
        publish_status.assert_not_awaited()
        mock_repos.audit.create.assert_not_awaited()


class TestBatchRetry:
    @pytest.mark.asyncio
    async def test_batch_retry_success(self, app, mock_repos, project_id, tenant_id):
        from qaplatform.infra.database.models import RunStatusEnum

        original = _make_run(
            tenant_id=tenant_id,
            project_id=project_id,
            status=RunStatusEnum.FAILED,
        )

        new_run = MagicMock()
        new_run.id = uuid.uuid4()
        new_run.retry_group_id = None
        new_run.attempt = 2

        mock_repos.run.get_for_tenant = AsyncMock(return_value=original)
        mock_repos.run.create = AsyncMock(return_value=new_run)

        with patch("qaplatform.worker.scheduler.enqueue_run", new_callable=AsyncMock):
            async with await _make_client(app) as client:
                resp = await client.post(
                    "/api/v1/runs/batch/retry",
                    json={"run_ids": [str(original.id)]},
                )

        assert resp.status_code == 200
        assert resp.json() == {"processed": 1, "failed": 0, "errors": []}
        mock_repos.run.set_retry_group_id.assert_awaited_once_with(
            new_run.id,
            new_run.id,
        )
        mock_repos.audit.create.assert_awaited_once()
        audit_kwargs = mock_repos.audit.create.await_args.kwargs
        assert audit_kwargs["action"] == "run.batch_retry"
        assert audit_kwargs["resource_id"] == original.id
        assert audit_kwargs["before_state"]["status"] == "failed"
        assert audit_kwargs["after_state"]["retry_run_id"] == str(new_run.id)

    @pytest.mark.asyncio
    async def test_batch_retry_not_terminal(self, app, mock_repos, mock_user, tenant_id):
        from qaplatform.infra.database.models import RunStatusEnum

        run = MagicMock()
        run.id = uuid.uuid4()
        run.tenant_id = tenant_id
        run.status = RunStatusEnum.RUNNING
        mock_repos.run.get_for_tenant = AsyncMock(return_value=run)
        app.state.container.arq_pool = MagicMock()

        with patch("qaplatform.worker.scheduler.enqueue_run", new_callable=AsyncMock) as enqueue_run:
            async with await _make_client(app) as client:
                resp = await client.post(
                    "/api/v1/runs/batch/retry",
                    json={"run_ids": [str(run.id)]},
                )

        assert resp.status_code == 200
        assert resp.json() == {
            "processed": 0,
            "failed": 1,
            "errors": [f"{run.id}: not terminal ({RunStatusEnum.RUNNING})"],
        }
        mock_repos.run.get_for_tenant.assert_awaited_once_with(run.id, mock_user.tenant_id)
        mock_repos.run.create.assert_not_awaited()
        mock_repos.run.set_retry_group_id.assert_not_awaited()
        enqueue_run.assert_not_awaited()
        mock_repos.audit.create.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_batch_retry_internal_failure_redacts_exception_without_side_effects(
        self,
        app,
        mock_repos,
        mock_user,
        project_id,
        tenant_id,
    ):
        from qaplatform.infra.database.models import RunStatusEnum

        original = _make_run(
            tenant_id=tenant_id,
            project_id=project_id,
            status=RunStatusEnum.FAILED,
        )
        secret_error = "retry insert failed with token=batch-retry-secret"
        mock_repos.run.get_for_tenant = AsyncMock(return_value=original)
        mock_repos.run.create = AsyncMock(side_effect=ValueError(secret_error))
        app.state.container.arq_pool = MagicMock()

        with patch("qaplatform.worker.scheduler.enqueue_run", new_callable=AsyncMock) as enqueue_run:
            async with await _make_client(app) as client:
                resp = await client.post(
                    "/api/v1/runs/batch/retry",
                    json={"run_ids": [str(original.id)]},
                )

        assert resp.status_code == 200
        assert resp.json() == {
            "processed": 0,
            "failed": 1,
            "errors": [f"{original.id}: operation failed"],
        }
        assert secret_error not in resp.text
        assert "batch-retry-secret" not in resp.text
        mock_repos.run.get_for_tenant.assert_awaited_once_with(
            original.id,
            mock_user.tenant_id,
        )
        mock_repos.run.create.assert_awaited_once()
        mock_repos.run.set_retry_group_id.assert_not_awaited()
        enqueue_run.assert_not_awaited()
        mock_repos.audit.create.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_batch_retry_rejects_duplicate_run_ids_without_side_effects(
        self,
        app,
        mock_repos,
    ):
        run_id = uuid.uuid4()
        duplicate_run_ids = [str(run_id), str(run_id)]
        app.state.container.arq_pool = MagicMock()

        with patch("qaplatform.worker.scheduler.enqueue_run", new_callable=AsyncMock) as enqueue_run:
            async with await _make_client(app) as client:
                resp = await client.post(
                    "/api/v1/runs/batch/retry",
                    json={"run_ids": duplicate_run_ids},
                )

        assert resp.status_code == 422, resp.text
        assert _validation_error_projection(resp.json()["detail"]) == [
            {
                "type": "value_error",
                "loc": ["body", "run_ids"],
                "msg": "Value error, duplicate run_ids are not allowed",
                "input": duplicate_run_ids,
            }
        ]
        mock_repos.run.get_for_tenant.assert_not_awaited()
        mock_repos.run.create.assert_not_awaited()
        mock_repos.run.set_retry_group_id.assert_not_awaited()
        enqueue_run.assert_not_awaited()
        mock_repos.audit.create.assert_not_awaited()


# --------------------------------------------------------------------------- #
# Analytics
# --------------------------------------------------------------------------- #


class TestAnalytics:
    """Tests for analytics endpoints with pagination support."""

    def _setup_session(self, app, mock_repos, mock_session):
        """Common session override setup for analytics tests."""
        from qaplatform.api.deps import _get_db_session, _get_repos, get_current_user

        app.dependency_overrides = {}

        async def _override_repos():
            return mock_repos

        async def _override_user():
            return MagicMock(user_id=uuid.uuid4(), tenant_id=uuid.uuid4(), role="owner", is_platform_admin=False)

        async def _override_session():
            yield mock_session

        app.dependency_overrides[_get_repos] = _override_repos
        app.dependency_overrides[get_current_user] = _override_user
        app.dependency_overrides[_get_db_session] = _override_session

    @pytest.mark.asyncio
    async def test_trends_returns_paginated_response(self, app, mock_repos, project_id):
        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(
            side_effect=AssertionError("analytics route must use repositories")
        )
        mock_repos.run.list_trend_points.return_value = (
            [SimpleNamespace(date="2026-05-19", total_runs=10, passed_runs=8, failed_runs=2)],
            1,
        )
        self._setup_session(app, mock_repos, mock_session)

        request_started = datetime.now(timezone.utc)
        async with await _make_client(app) as client:
            resp = await client.get(f"/api/v1/projects/{project_id}/analytics/trends")
        request_finished = datetime.now(timezone.utc)

        assert resp.status_code == 200
        assert resp.json() == {
            "data": [
                {
                    "date": "2026-05-19",
                    "total_runs": 10,
                    "passed_runs": 8,
                    "failed_runs": 2,
                    "pass_rate": 0.8,
                }
            ],
            "pagination": {"total": 1, "offset": 0, "limit": 365},
        }
        mock_repos.run.list_trend_points.assert_awaited_once()
        call_kwargs = mock_repos.run.list_trend_points.await_args.kwargs
        cutoff = call_kwargs["cutoff"]
        assert call_kwargs == {
            "project_id": project_id,
            "cutoff": cutoff,
            "offset": 0,
            "limit": 365,
        }
        _assert_cutoff_within_request_window(
            cutoff,
            days=30,
            started_at=request_started,
            finished_at=request_finished,
        )
        mock_session.execute.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_trends_with_custom_pagination(self, app, mock_repos, project_id):
        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(
            side_effect=AssertionError("analytics route must use repositories")
        )
        mock_repos.run.list_trend_points.return_value = ([], 10)
        self._setup_session(app, mock_repos, mock_session)

        request_started = datetime.now(timezone.utc)
        async with await _make_client(app) as client:
            resp = await client.get(
                f"/api/v1/projects/{project_id}/analytics/trends?offset=5&limit=3",
            )
        request_finished = datetime.now(timezone.utc)

        assert resp.status_code == 200
        assert resp.json() == {
            "data": [],
            "pagination": {"offset": 5, "limit": 3, "total": 10},
        }
        mock_repos.run.list_trend_points.assert_awaited_once()
        call_kwargs = dict(mock_repos.run.list_trend_points.await_args.kwargs)
        cutoff = call_kwargs.pop("cutoff")
        assert call_kwargs == {"project_id": project_id, "offset": 5, "limit": 3}
        _assert_cutoff_within_request_window(
            cutoff,
            days=30,
            started_at=request_started,
            finished_at=request_finished,
        )
        mock_session.execute.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_trends_rejects_invalid_pagination(self, app, mock_repos, project_id):
        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(
            side_effect=AssertionError("analytics validation errors must not query")
        )
        mock_repos.run.list_trend_points = AsyncMock()
        mock_repos.test_result.list_flaky_tests = AsyncMock()
        mock_repos.test_result.list_test_history = AsyncMock()
        self._setup_session(app, mock_repos, mock_session)

        async with await _make_client(app) as client:
            resp = await client.get(
                f"/api/v1/projects/{project_id}/analytics/trends?offset=-1",
            )
            _assert_validation_error_response(
                resp,
                field="offset",
                expected_type="greater_than_equal",
                expected_msg="Input should be greater than or equal to 0",
                expected_input="-1",
            )

            resp = await client.get(
                f"/api/v1/projects/{project_id}/analytics/trends?limit=366",
            )
            _assert_validation_error_response(
                resp,
                field="limit",
                expected_type="less_than_equal",
                expected_msg="Input should be less than or equal to 365",
                expected_input="366",
            )

        _assert_analytics_repositories_not_called(mock_repos)
        mock_session.execute.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_flaky_returns_paginated_response(self, app, mock_repos, project_id):
        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(
            side_effect=AssertionError("analytics route must use repositories")
        )
        mock_repos.test_result.list_flaky_tests.return_value = (
            [
                SimpleNamespace(
                    suite="test_auth",
                    name="test_login",
                    total_runs=10,
                    passed_count=7,
                    failed_count=3,
                )
            ],
            1,
        )
        self._setup_session(app, mock_repos, mock_session)

        request_started = datetime.now(timezone.utc)
        async with await _make_client(app) as client:
            resp = await client.get(f"/api/v1/projects/{project_id}/analytics/flaky")
        request_finished = datetime.now(timezone.utc)

        assert resp.status_code == 200
        assert resp.json() == {
            "data": [
                {
                    "suite": "test_auth",
                    "name": "test_login",
                    "total_runs": 10,
                    "failed_count": 3,
                    "passed_count": 7,
                    "flaky_rate": 0.3,
                    "observation_count": 10,
                    "window_days": 30,
                }
            ],
            "pagination": {"total": 1, "offset": 0, "limit": 50},
        }
        mock_repos.test_result.list_flaky_tests.assert_awaited_once()
        call_kwargs = mock_repos.test_result.list_flaky_tests.await_args.kwargs
        cutoff = call_kwargs["cutoff"]
        assert call_kwargs == {
            "project_id": project_id,
            "cutoff": cutoff,
            "min_runs": 3,
            "offset": 0,
            "limit": 50,
        }
        _assert_cutoff_within_request_window(
            cutoff,
            days=30,
            started_at=request_started,
            finished_at=request_finished,
        )
        mock_session.execute.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_flaky_with_offset(self, app, mock_repos, project_id):
        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(
            side_effect=AssertionError("analytics route must use repositories")
        )
        mock_repos.test_result.list_flaky_tests.return_value = ([], 100)
        self._setup_session(app, mock_repos, mock_session)

        request_started = datetime.now(timezone.utc)
        async with await _make_client(app) as client:
            resp = await client.get(
                f"/api/v1/projects/{project_id}/analytics/flaky?offset=10&limit=20",
            )
        request_finished = datetime.now(timezone.utc)

        assert resp.status_code == 200
        assert resp.json() == {
            "data": [],
            "pagination": {"offset": 10, "limit": 20, "total": 100},
        }
        mock_repos.test_result.list_flaky_tests.assert_awaited_once()
        call_kwargs = dict(mock_repos.test_result.list_flaky_tests.await_args.kwargs)
        cutoff = call_kwargs.pop("cutoff")
        assert call_kwargs == {
            "project_id": project_id,
            "min_runs": 3,
            "offset": 10,
            "limit": 20,
        }
        _assert_cutoff_within_request_window(
            cutoff,
            days=30,
            started_at=request_started,
            finished_at=request_finished,
        )
        mock_session.execute.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_flaky_rejects_invalid_pagination(self, app, mock_repos, project_id):
        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(
            side_effect=AssertionError("analytics validation errors must not query")
        )
        mock_repos.run.list_trend_points = AsyncMock()
        mock_repos.test_result.list_flaky_tests = AsyncMock()
        mock_repos.test_result.list_test_history = AsyncMock()
        self._setup_session(app, mock_repos, mock_session)

        async with await _make_client(app) as client:
            resp = await client.get(
                f"/api/v1/projects/{project_id}/analytics/flaky?offset=-1",
            )
            _assert_validation_error_response(
                resp,
                field="offset",
                expected_type="greater_than_equal",
                expected_msg="Input should be greater than or equal to 0",
                expected_input="-1",
            )

            resp = await client.get(
                f"/api/v1/projects/{project_id}/analytics/flaky?limit=201",
            )
            _assert_validation_error_response(
                resp,
                field="limit",
                expected_type="less_than_equal",
                expected_msg="Input should be less than or equal to 200",
                expected_input="201",
            )

        _assert_analytics_repositories_not_called(mock_repos)
        mock_session.execute.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_test_history_returns_repository_rows(self, app, mock_repos, project_id):
        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(
            side_effect=AssertionError("analytics route must use repositories")
        )
        run_id = uuid.uuid4()
        run_created_at = datetime(2026, 6, 1, 9, 10, tzinfo=timezone.utc)
        mock_repos.test_result.list_test_history.return_value = (
            [
                SimpleNamespace(
                    run_id=run_id,
                    run_created_at=run_created_at,
                    run_status="done",
                    status="failed",
                    duration_ms=123,
                    error_message="boom",
                    git_ref="main",
                )
            ],
            1,
        )
        self._setup_session(app, mock_repos, mock_session)

        request_started = datetime.now(timezone.utc)
        async with await _make_client(app) as client:
            resp = await client.get(
                f"/api/v1/projects/{project_id}/analytics/test-history",
                params={"suite": "checkout", "name": "test_login"},
            )
        request_finished = datetime.now(timezone.utc)

        assert resp.status_code == 200
        body = resp.json()
        assert body == {
            "data": [
                {
                    "run_id": str(run_id),
                    "run_created_at": run_created_at.isoformat().replace(
                        "+00:00",
                        "Z",
                    ),
                    "run_status": "done",
                    "status": "failed",
                    "duration_ms": 123,
                    "error_message": "boom",
                    "git_ref": "main",
                    "observation_count": 1,
                }
            ],
            "pagination": {"offset": 0, "limit": 50, "total": 1},
        }
        call_kwargs = mock_repos.test_result.list_test_history.await_args.kwargs
        cutoff = call_kwargs["cutoff"]
        assert call_kwargs == {
            "project_id": project_id,
            "suite": "checkout",
            "name": "test_login",
            "cutoff": cutoff,
            "offset": 0,
            "limit": 50,
        }
        _assert_cutoff_within_request_window(
            cutoff,
            days=30,
            started_at=request_started,
            finished_at=request_finished,
        )
        mock_session.execute.assert_not_awaited()
