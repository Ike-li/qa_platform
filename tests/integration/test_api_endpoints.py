"""Integration tests: core API endpoints end-to-end.

Covers Projects CRUD, Runs, Pipelines, Notification Rules, Analytics,
and cross-tenant isolation. Each test is independent and uses real DB
(no mocking).
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from qaplatform.infra.database.models import (
    AuditEvent,
    NotificationRule,
    Pipeline,
    Project,
    Run,
    RunStatusEnum,
)
from qaplatform.infra.database.models import (
    TestResult as DbTestResult,
)
from qaplatform.infra.database.models import (
    TestResultStatusEnum as DbTestResultStatusEnum,
)

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_INTEGRATION_TESTS") != "1",
    reason="set RUN_INTEGRATION_TESTS=1 to run integration tests",
)


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _unique_slug(prefix: str = "proj") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def _json_datetime(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def _validation_error_projection(errors: list[dict]) -> list[dict]:
    return [
        {
            "type": error["type"],
            "loc": error["loc"],
            "msg": error["msg"],
            "input": error.get("input"),
        }
        for error in errors
    ]


def _not_found_body(message: str) -> dict:
    return {"error": {"code": "NOT_FOUND", "message": message, "details": []}}


def _expected_run_response(run: Run, *, pipeline_name: str) -> dict:
    return {
        "id": str(run.id),
        "tenant_id": str(run.tenant_id),
        "project_id": str(run.project_id),
        "pipeline_id": str(run.pipeline_id),
        "pipeline_name": pipeline_name,
        "environment_id": str(run.environment_id),
        "status": run.status.value if hasattr(run.status, "value") else run.status,
        "trigger_type": run.trigger_type,
        "priority": run.priority,
        "triggered_by": str(run.triggered_by) if run.triggered_by else None,
        "git_ref": run.git_ref,
        "git_sha": run.git_sha,
        "attempt": run.attempt,
        "started_at": _json_datetime(run.started_at) if run.started_at else None,
        "finished_at": _json_datetime(run.finished_at) if run.finished_at else None,
        "duration_ms": run.duration_ms,
        "summary": run.summary,
        "error_message": run.error_message,
        "created_at": _json_datetime(run.created_at),
        "updated_at": _json_datetime(run.updated_at),
    }


def _expected_seed_project_response(
    seed_run: dict,
    *,
    name: str | None = None,
    updated_at: str | None = None,
) -> dict:
    project = seed_run["project"]
    return {
        "id": str(project.id),
        "tenant_id": str(seed_run["tenant"].id),
        "name": name or project.name,
        "slug": project.slug,
        "description": None,
        "git_url": "file:///tmp/none",
        "git_auth_method": "none",
        "credential_id": None,
        "default_branch": "main",
        "root_path": ".",
        "shallow_clone": True,
        "default_env_id": None,
        "settings": {},
        "silent_windows": [],
        "status": "active",
        "created_by": str(seed_run["user"].id),
        "created_at": _json_datetime(project.created_at),
        "updated_at": updated_at or _json_datetime(project.updated_at),
    }


def _pipeline_contract_payload(name: str) -> dict:
    return {
        "name": name,
        "stages": [
            {
                "name": "prepare",
                "plugin": "shell",
                "phase": "prepare",
                "config": {"command": "python -m pip install -r requirements.txt"},
            },
            {
                "name": "run-tests",
                "plugin": "pytest",
                "phase": "execute",
                "config": {"args": ["tests/api"], "report": "junit"},
            },
        ],
        "selector": {"include_paths": ["tests/api"], "on_empty": "warn"},
        "trigger_config": {
            "type": "manual",
            "source": {"branch": "main"},
            "conditions": {"changed_paths": ["tests/api/**"]},
            "target": {"environment": "staging"},
        },
        "collectors": [
            {
                "plugin": "junit",
                "config": {"path": "results/junit.xml"},
                "enabled": True,
            }
        ],
        "retry_policy": {
            "max_attempts": 3,
            "retry_on": ["infra", "timeout"],
            "backoff_seconds": 30,
            "scope": "stage",
        },
        "timeout_seconds": 600,
    }


def _notification_rule_audit_state(body: dict) -> dict:
    return {
        "id": body["id"],
        "project_id": body["project_id"],
        "name": body["name"],
        "enabled": body["enabled"],
        "conditions": body["conditions"],
        "channels": {
            "redacted": True,
            "count": len(body["channels"]),
            "types": [channel["type"] for channel in body["channels"]],
        },
        "template": {
            "redacted": True,
            "present": body["template"] is not None,
            "length": len(body["template"] or ""),
        },
        "created_at": body["created_at"],
    }


# --------------------------------------------------------------------------- #
# Projects CRUD
# --------------------------------------------------------------------------- #


class TestProjectsCRUD:
    """Tests 1-5: Projects create / list / get / update / delete."""

    async def test_create_project(self, integration_client, seed_run):
        """POST /api/v1/projects -> 201 + returned fields match."""
        slug = _unique_slug()
        payload = {
            "name": "new-project",
            "slug": slug,
            "git_url": "https://github.com/example/repo.git",
            "default_branch": "main",
        }
        resp = await integration_client.post("/api/v1/projects", json=payload)
        assert resp.status_code == 201, resp.text
        body = resp.json()
        created_id = uuid.UUID(body["id"])
        created_at = datetime.fromisoformat(body["created_at"].replace("Z", "+00:00"))
        updated_at = datetime.fromisoformat(body["updated_at"].replace("Z", "+00:00"))
        assert created_at.tzinfo is not None
        assert updated_at >= created_at
        assert {
            key: value
            for key, value in body.items()
            if key not in {"id", "created_at", "updated_at"}
        } == {
            "tenant_id": str(seed_run["tenant"].id),
            "name": "new-project",
            "slug": slug,
            "description": None,
            "git_url": payload["git_url"],
            "git_auth_method": "none",
            "credential_id": None,
            "default_branch": "main",
            "root_path": ".",
            "shallow_clone": True,
            "default_env_id": None,
            "settings": {},
            "silent_windows": [],
            "status": "active",
            "created_by": str(seed_run["user"].id),
        }
        assert body["id"] == str(created_id)

    async def test_list_projects(self, integration_client, seed_run):
        """GET /api/v1/projects -> paginated list scoped to the current tenant."""
        # Create a second project to ensure listing works
        slug = _unique_slug()
        create_resp = await integration_client.post(
            "/api/v1/projects",
            json={"name": "list-test", "slug": slug, "git_url": "https://example.com/r.git"},
        )
        assert create_resp.status_code == 201, create_resp.text
        created = create_resp.json()

        resp = await integration_client.get("/api/v1/projects")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body == {
            "data": [
                {
                    "id": str(seed_run["project"].id),
                    "tenant_id": str(seed_run["tenant"].id),
                    "name": "integration-project",
                    "slug": seed_run["project"].slug,
                    "description": None,
                    "git_url": "file:///tmp/none",
                    "git_auth_method": "none",
                    "credential_id": None,
                    "default_branch": "main",
                    "root_path": ".",
                    "shallow_clone": True,
                    "default_env_id": None,
                    "settings": {},
                    "silent_windows": [],
                    "status": "active",
                    "created_by": str(seed_run["user"].id),
                    "created_at": _json_datetime(seed_run["project"].created_at),
                    "updated_at": _json_datetime(seed_run["project"].updated_at),
                },
                created,
            ],
            "page": 1,
            "per_page": 20,
            "total": 2,
        }
    async def test_list_projects_search_orders_results_by_name(
        self,
        integration_client,
    ):
        """F-LS-03: search results are sorted alphabetically by project name."""
        token = uuid.uuid4().hex[:8]
        names = [
            f"Search Sort Alpha {token}",
            f"Search Sort Zulu {token}",
            f"Search Sort Beta {token}",
        ]
        created_projects = []
        for name in names:
            slug = _unique_slug("search-sort")
            create_resp = await integration_client.post(
                "/api/v1/projects",
                json={
                    "name": name,
                    "slug": slug,
                    "git_url": f"https://example.com/{slug}.git",
                },
            )
            assert create_resp.status_code == 201, create_resp.text
            created_projects.append(create_resp.json())

        resp = await integration_client.get(
            "/api/v1/projects",
            params={"q": token, "per_page": 10},
        )

        assert resp.status_code == 200, resp.text
        assert resp.json() == {
            "data": sorted(created_projects, key=lambda item: item["name"]),
            "page": 1,
            "per_page": 10,
            "total": 3,
        }

    async def test_get_project(self, integration_client, seed_run):
        """GET /api/v1/projects/{id} -> 200 with correct fields."""
        project_id = str(seed_run["project"].id)
        resp = await integration_client.get(f"/api/v1/projects/{project_id}")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body == _expected_seed_project_response(seed_run)

    async def test_update_project(
        self, integration_client, integration_db_session, seed_run
    ):
        """PUT /api/v1/projects/{id} -> 200 with updated name."""
        project_id = str(seed_run["project"].id)
        before_body = _expected_seed_project_response(seed_run)
        resp = await integration_client.put(
            f"/api/v1/projects/{project_id}",
            json={"name": "renamed-project"},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        expected_body = _expected_seed_project_response(
            seed_run,
            name="renamed-project",
            updated_at=body["updated_at"],
        )
        assert body == expected_body
        created_at = datetime.fromisoformat(body["created_at"].replace("Z", "+00:00"))
        updated_at = datetime.fromisoformat(body["updated_at"].replace("Z", "+00:00"))
        assert updated_at >= created_at

        await integration_db_session.refresh(seed_run["project"])
        assert seed_run["project"].name == "renamed-project"
        audit = (
            await integration_db_session.execute(
                select(AuditEvent).where(
                    AuditEvent.action == "project.update",
                    AuditEvent.resource_id == seed_run["project"].id,
                )
            )
        ).scalar_one()
        assert audit.tenant_id == seed_run["tenant"].id
        assert audit.user_id == seed_run["user"].id
        assert audit.resource_type == "project"
        assert audit.resource_id == seed_run["project"].id
        assert audit.before_state == before_body
        assert audit.after_state == expected_body

    async def test_delete_project(
        self, integration_client, integration_db_session, seed_run
    ):
        """DELETE /api/v1/projects/{id} -> 204, subsequent GET -> 404."""
        # Create a throwaway project so we don't break other tests
        slug = _unique_slug()
        payload = {
            "name": "to-delete",
            "slug": slug,
            "git_url": "https://git-user:git-pass@example.com/r.git",
        }
        create_resp = await integration_client.post(
            "/api/v1/projects",
            json=payload,
        )
        assert create_resp.status_code == 201, create_resp.text
        created = create_resp.json()
        assert created["git_url"] == payload["git_url"]
        pid = created["id"]

        del_resp = await integration_client.delete(f"/api/v1/projects/{pid}")
        assert del_resp.status_code == 204
        assert del_resp.content == b""

        get_resp = await integration_client.get(f"/api/v1/projects/{pid}")
        assert get_resp.status_code == 404, get_resp.text
        assert get_resp.json() == _not_found_body("Project not found")
        for forbidden in [pid, payload["git_url"], "git-user", "git-pass"]:
            assert forbidden not in get_resp.text
        deleted_project = await integration_db_session.get(Project, uuid.UUID(pid))
        assert deleted_project is not None
        assert deleted_project.deleted_at is not None

        audit = (
            await integration_db_session.execute(
                select(AuditEvent).where(
                    AuditEvent.action == "project.delete",
                    AuditEvent.resource_id == deleted_project.id,
                )
            )
        ).scalar_one()
        assert audit.tenant_id == seed_run["tenant"].id
        assert audit.user_id == seed_run["user"].id
        assert audit.resource_type == "project"
        assert audit.resource_id == deleted_project.id
        expected_before_state = {**created, "git_url": "https://***@example.com/r.git"}
        assert audit.before_state == expected_before_state
        assert audit.after_state is None
        serialized_audit = repr([audit.before_state, audit.after_state])
        for forbidden in ["git-user", "git-pass", payload["git_url"]]:
            assert forbidden not in serialized_audit


# --------------------------------------------------------------------------- #
# Runs
# --------------------------------------------------------------------------- #


class TestRuns:
    """Tests 6-8: trigger run / get run / list runs."""

    async def test_trigger_run(self, integration_client, integration_db_session, seed_run):
        """POST /api/v1/runs -> 201 with explicit pipeline/env/git fields."""
        pipeline_id = str(seed_run["pipeline"].id)
        environment_id = str(seed_run["environment"].id)
        git_sha = "0123456789abcdef0123456789abcdef01234567"
        payload = {
            "pipeline_id": pipeline_id,
            "environment_id": environment_id,
            "git_ref": "main",
            "git_sha": git_sha,
            "priority": 0,
        }
        resp = await integration_client.post("/api/v1/runs", json=payload)
        assert resp.status_code == 201, resp.text
        body = resp.json()

        run = await integration_db_session.get(Run, body["id"])
        assert run is not None
        assert body == _expected_run_response(run, pipeline_name=seed_run["pipeline"].name)
        assert str(run.pipeline_id) == pipeline_id
        assert str(run.environment_id) == environment_id
        assert run.status == RunStatusEnum.QUEUED
        assert run.trigger_type == "manual"
        assert run.priority == 0
        assert run.triggered_by == seed_run["user"].id
        assert run.git_ref == "main"
        assert run.git_sha == git_sha
        assert run.retry_group_id == run.id

        audit = (
            await integration_db_session.execute(
                select(AuditEvent).where(
                    AuditEvent.action == "run.trigger",
                    AuditEvent.resource_id == run.id,
                )
            )
        ).scalar_one()
        assert audit.tenant_id == seed_run["tenant"].id
        assert audit.user_id == seed_run["user"].id
        assert audit.resource_type == "run"
        assert audit.resource_id == run.id
        assert audit.before_state is None
        assert audit.after_state == body

    async def test_get_run(self, integration_client, seed_run):
        """GET /api/v1/runs/{id} -> 200 with correct fields."""
        run_id = str(seed_run["run"].id)
        resp = await integration_client.get(f"/api/v1/runs/{run_id}")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body == _expected_run_response(
            seed_run["run"], pipeline_name=seed_run["pipeline"].name
        )

    async def test_list_runs(self, integration_client, seed_run):
        """GET /api/v1/runs -> paginated list with seeded run."""
        resp = await integration_client.get("/api/v1/runs")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body == {
            "data": [
                {
                    "id": str(seed_run["run"].id),
                    "tenant_id": str(seed_run["tenant"].id),
                    "project_id": str(seed_run["project"].id),
                    "pipeline_id": str(seed_run["pipeline"].id),
                    "pipeline_name": "smoke",
                    "environment_id": str(seed_run["environment"].id),
                    "status": "queued",
                    "trigger_type": "manual",
                    "priority": 1,
                    "triggered_by": str(seed_run["user"].id),
                    "git_ref": "main",
                    "git_sha": None,
                    "attempt": 1,
                    "started_at": None,
                    "finished_at": None,
                    "duration_ms": None,
                    "summary": None,
                    "error_message": None,
                    "created_at": _json_datetime(seed_run["run"].created_at),
                    "updated_at": _json_datetime(seed_run["run"].updated_at),
                }
            ],
            "page": 1,
            "per_page": 20,
            "total": 1,
        }
    async def test_list_runs_filters_pipeline_git_ref_and_created_range(
        self, integration_client, integration_db_session, seed_run
    ):
        """GET /api/v1/runs filters by pipeline_id, git_ref, and created_at range."""
        base_time = datetime(2026, 1, 2, 12, 0, tzinfo=timezone.utc)
        project = seed_run["project"]
        environment = seed_run["environment"]
        user = seed_run["user"]

        second_pipeline = Pipeline(
            project_id=project.id,
            name=f"filter-pipeline-{uuid.uuid4().hex[:8]}",
            stages=[{"name": "exec", "plugin": "pytest", "phase": "execute", "config": {}}],
            selector={},
            trigger_config={"type": "manual"},
            timeout_seconds=120,
            enabled=True,
        )
        integration_db_session.add(second_pipeline)
        await integration_db_session.flush()

        first_pipeline_run = Run(
            tenant_id=project.tenant_id,
            project_id=project.id,
            pipeline_id=seed_run["pipeline"].id,
            environment_id=environment.id,
            status=RunStatusEnum.QUEUED,
            trigger_type="manual",
            priority=1,
            triggered_by=user.id,
            git_ref=f"filter-main-{uuid.uuid4().hex[:8]}",
            attempt=1,
            chain_depth=0,
            metadata_={},
            created_at=base_time,
        )
        target_run = Run(
            tenant_id=project.tenant_id,
            project_id=project.id,
            pipeline_id=second_pipeline.id,
            environment_id=environment.id,
            status=RunStatusEnum.QUEUED,
            trigger_type="manual",
            priority=1,
            triggered_by=user.id,
            git_ref=f"filter-feature-{uuid.uuid4().hex[:8]}",
            attempt=1,
            chain_depth=0,
            metadata_={},
            created_at=base_time + timedelta(hours=1),
        )
        later_run = Run(
            tenant_id=project.tenant_id,
            project_id=project.id,
            pipeline_id=second_pipeline.id,
            environment_id=environment.id,
            status=RunStatusEnum.QUEUED,
            trigger_type="manual",
            priority=1,
            triggered_by=user.id,
            git_ref=f"filter-later-{uuid.uuid4().hex[:8]}",
            attempt=1,
            chain_depth=0,
            metadata_={},
            created_at=base_time + timedelta(hours=2),
        )
        integration_db_session.add_all([first_pipeline_run, target_run, later_run])
        await integration_db_session.commit()

        pipeline_resp = await integration_client.get(
            "/api/v1/runs",
            params={"pipeline_id": str(second_pipeline.id), "per_page": 100},
        )
        assert pipeline_resp.status_code == 200, pipeline_resp.text
        pipeline_body = pipeline_resp.json()
        assert pipeline_body == {
            "data": [
                _expected_run_response(later_run, pipeline_name=second_pipeline.name),
                _expected_run_response(target_run, pipeline_name=second_pipeline.name),
            ],
            "page": 1,
            "per_page": 100,
            "total": 2,
        }

        git_ref_resp = await integration_client.get(
            "/api/v1/runs",
            params={"git_ref": target_run.git_ref, "per_page": 100},
        )
        assert git_ref_resp.status_code == 200, git_ref_resp.text
        git_ref_body = git_ref_resp.json()
        expected_target_page = {
            "data": [_expected_run_response(target_run, pipeline_name=second_pipeline.name)],
            "page": 1,
            "per_page": 100,
            "total": 1,
        }
        assert git_ref_body == expected_target_page

        range_resp = await integration_client.get(
            "/api/v1/runs",
            params={
                "created_from": (base_time + timedelta(minutes=30)).isoformat(),
                "created_to": (base_time + timedelta(minutes=90)).isoformat(),
                "per_page": 100,
            },
        )
        assert range_resp.status_code == 200, range_resp.text
        range_body = range_resp.json()
        assert range_body == expected_target_page


# --------------------------------------------------------------------------- #
# Pipelines
# --------------------------------------------------------------------------- #


class TestPipelines:
    """Tests 9-10: create / list pipelines."""

    async def test_create_pipeline(self, integration_client, seed_run):
        """POST /api/v1/projects/{id}/pipelines -> 201."""
        project_id = str(seed_run["project"].id)
        payload = _pipeline_contract_payload("e2e-pipeline")
        resp = await integration_client.post(
            f"/api/v1/projects/{project_id}/pipelines", json=payload
        )
        assert resp.status_code == 201, resp.text
        body = resp.json()
        expected_body = {
            "id": body["id"],
            "project_id": project_id,
            "name": "e2e-pipeline",
            "stages": [
                {**stage, "continue_on_error": False} for stage in payload["stages"]
            ],
            "selector": {
                "include_paths": ["tests/api"],
                "exclude_paths": [],
                "tags": [],
                "expression": None,
                "regex": None,
                "on_empty": "warn",
            },
            "trigger_config": {
                "type": "manual",
                "dedup_window_seconds": None,
                "source": {"branch": "main"},
                "conditions": {"changed_paths": ["tests/api/**"]},
                "target": {"environment": "staging"},
            },
            "collectors": payload["collectors"],
            "timeout_seconds": payload["timeout_seconds"],
            "retry_policy": payload["retry_policy"],
            "enabled": True,
            "created_at": body["created_at"],
            "updated_at": body["updated_at"],
        }
        assert body == expected_body

    async def test_update_pipeline_accepts_current_contract(
        self, integration_client, seed_run
    ):
        """PUT /api/v1/projects/{id}/pipelines/{id} -> 200 with current schema."""
        project_id = str(seed_run["project"].id)
        create_resp = await integration_client.post(
            f"/api/v1/projects/{project_id}/pipelines",
            json=_pipeline_contract_payload("before-update"),
        )
        assert create_resp.status_code == 201, create_resp.text
        created = create_resp.json()
        pipeline_id = created["id"]

        payload = _pipeline_contract_payload("after-update")
        payload["stages"] = [
            {
                "name": "notify",
                "plugin": "webhook",
                "phase": "notify",
                "config": {"url": "https://deploy.example/hooks/qa"},
            }
        ]
        payload["selector"] = {"include_paths": ["tests/e2e"], "on_empty": "skip"}
        payload["trigger_config"] = {
            "type": "webhook",
            "source": {"provider": "github"},
            "conditions": {"event": "push"},
            "target": {"environment": "prod"},
        }
        payload["retry_policy"] = {
            "max_attempts": 2,
            "retry_on": ["timeout"],
            "backoff_seconds": 10,
            "scope": "pipeline",
        }
        payload["collectors"] = [
            {
                "plugin": "junit",
                "config": {"path": "custom/junit.xml"},
                "enabled": True,
            }
        ]
        payload["enabled"] = False

        resp = await integration_client.put(
            f"/api/v1/projects/{project_id}/pipelines/{pipeline_id}",
            json=payload,
        )

        assert resp.status_code == 200, resp.text
        body = resp.json()
        expected_body = {
            "id": pipeline_id,
            "project_id": project_id,
            "name": "after-update",
            "stages": [
                {**stage, "continue_on_error": False} for stage in payload["stages"]
            ],
            "selector": {
                "include_paths": ["tests/e2e"],
                "exclude_paths": [],
                "tags": [],
                "expression": None,
                "regex": None,
                "on_empty": "skip",
            },
            "trigger_config": {
                "type": "webhook",
                "dedup_window_seconds": None,
                "source": {"provider": "github"},
                "conditions": {"event": "push"},
                "target": {"environment": "prod"},
            },
            "collectors": payload["collectors"],
            "timeout_seconds": payload["timeout_seconds"],
            "retry_policy": payload["retry_policy"],
            "enabled": False,
            "created_at": created["created_at"],
            "updated_at": body["updated_at"],
        }
        assert body == expected_body

    async def test_list_pipelines(self, integration_client, seed_run):
        """GET /api/v1/projects/{id}/pipelines -> returns newly created pipelines."""
        project_id = str(seed_run["project"].id)
        payload = _pipeline_contract_payload("list-pipeline")
        create_resp = await integration_client.post(
            f"/api/v1/projects/{project_id}/pipelines", json=payload
        )
        assert create_resp.status_code == 201, create_resp.text
        created = create_resp.json()

        resp = await integration_client.get(
            f"/api/v1/projects/{project_id}/pipelines"
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body == {
            "data": [
                created,
                {
                    "id": str(seed_run["pipeline"].id),
                    "project_id": project_id,
                    "name": "smoke",
                    "stages": [
                        {
                            "name": "exec",
                            "plugin": "pytest",
                            "config": {},
                            "continue_on_error": False,
                            "phase": "execute",
                        }
                    ],
                    "selector": {
                        "include_paths": [],
                        "exclude_paths": [],
                        "tags": [],
                        "expression": None,
                        "regex": None,
                        "on_empty": "fail",
                    },
                    "trigger_config": {
                        "type": "manual",
                        "dedup_window_seconds": None,
                        "source": {},
                        "conditions": {},
                        "target": {},
                    },
                    "collectors": [{"plugin": "junit", "config": {}, "enabled": True}],
                    "timeout_seconds": 120,
                    "retry_policy": None,
                    "enabled": True,
                    "created_at": _json_datetime(seed_run["pipeline"].created_at),
                    "updated_at": _json_datetime(seed_run["pipeline"].updated_at),
                },
            ],
            "page": 1,
            "per_page": 20,
            "total": 2,
        }

# --------------------------------------------------------------------------- #
# Notification Rules
# --------------------------------------------------------------------------- #


class TestNotificationRules:
    """Tests 11-14: create / list / update / delete notification rules."""

    async def test_create_notification_rule(
        self, integration_client, integration_db_session, seed_run
    ):
        """POST /api/v1/projects/{id}/notification-rules -> 201."""
        project_id = str(seed_run["project"].id)
        payload = {
            "name": "slack-alert",
            "enabled": True,
            "conditions": [{"field": "status", "operator": "eq", "value": "failed"}],
            "channels": [{"type": "webhook", "webhook_url": "https://hooks.example.com/test"}],
        }
        resp = await integration_client.post(
            f"/api/v1/projects/{project_id}/notification-rules", json=payload
        )
        assert resp.status_code == 201, resp.text
        body = resp.json()
        expected_body = {
            "id": body["id"],
            "project_id": project_id,
            "name": "slack-alert",
            "enabled": True,
            "conditions": payload["conditions"],
            "channels": [
                {
                    "type": "webhook",
                    "config": {"url": "https://hooks.example.com/test"},
                    "template": None,
                }
            ],
            "template": None,
            "created_at": body["created_at"],
        }
        assert body == expected_body

        rule = await integration_db_session.get(NotificationRule, uuid.UUID(body["id"]))
        assert rule is not None
        assert rule.project_id == seed_run["project"].id
        assert rule.name == "slack-alert"
        assert rule.enabled is True
        assert rule.conditions == payload["conditions"]
        assert rule.channels == [
            {
                "type": "webhook",
                "config": {"url": "https://hooks.example.com/test"},
            }
        ]
        assert rule.template is None

        audit = (
            await integration_db_session.execute(
                select(AuditEvent).where(
                    AuditEvent.action == "notification_rule.create",
                    AuditEvent.resource_id == rule.id,
                )
            )
        ).scalar_one()
        assert audit.tenant_id == seed_run["tenant"].id
        assert audit.user_id == seed_run["user"].id
        assert audit.resource_type == "notification_rule"
        assert audit.resource_id == rule.id
        assert audit.before_state is None
        assert audit.after_state == _notification_rule_audit_state(expected_body)

    @pytest.mark.parametrize("field", ["new_failed", "recovered"])
    async def test_create_notification_rule_accepts_noise_reduction_fields(
        self, integration_client, seed_run, field
    ):
        """T15 的降噪条件必须能创建并读回。

        领域层的 NOTIFICATION_CANONICAL_CONDITION_FIELDS 一直包含 new_failed 与
        recovered，worker 也实现了求值，但 API 层的 Literal 漏了它们：创建返回
        422；即便直接写库，读取时响应模型校验也会失败而 500。
        """
        project_id = str(seed_run["project"].id)
        payload = {
            "name": f"noise-reduction-{field}-{uuid.uuid4().hex}",
            "conditions": [{"field": field, "operator": "gt", "value": 0}],
            "channels": [{"type": "webhook", "config": {"url": "https://h.example.com"}}],
        }
        resp = await integration_client.post(
            f"/api/v1/projects/{project_id}/notification-rules", json=payload
        )
        assert resp.status_code == 201, resp.text
        rule_id = resp.json()["id"]
        assert resp.json()["conditions"] == payload["conditions"]

        # 回读路径：修复前这里会 500
        detail_resp = await integration_client.get(
            f"/api/v1/projects/{project_id}/notification-rules/{rule_id}"
        )
        assert detail_resp.status_code == 200, detail_resp.text
        assert detail_resp.json()["conditions"] == payload["conditions"]

        list_resp = await integration_client.get(
            f"/api/v1/projects/{project_id}/notification-rules"
        )
        assert list_resp.status_code == 200, list_resp.text
        assert any(r["id"] == rule_id for r in list_resp.json()["data"])

    @pytest.mark.parametrize(
        "condition",
        [
            {"field": "statuz", "operator": "eq", "value": "failed"},
            {"field": "consecutive_failed_runs", "operator": "gte", "value": 3},
        ],
    )
    async def test_create_notification_rule_rejects_invalid_condition(
        self, integration_client, integration_db_session, seed_run, condition
    ):
        """POST /notification-rules rejects undocumented condition fields before DB write."""
        project_id = str(seed_run["project"].id)
        name = f"invalid-condition-{uuid.uuid4().hex}"
        resp = await integration_client.post(
            f"/api/v1/projects/{project_id}/notification-rules",
            json={
                "name": name,
                "conditions": [condition],
                "channels": [{"type": "webhook", "config": {"url": "https://h.example.com"}}],
            },
        )

        assert resp.status_code == 422, resp.text
        assert _validation_error_projection(resp.json()["detail"]) == [
            {
                "type": "value_error",
                "loc": ["body", "conditions"],
                "msg": (
                    "Value error, conditions[0].field must be one of: "
                    "consecutive_failures, failed, new_failed, pass_rate, recovered, status"
                ),
                "input": [condition],
            }
        ]
        result = await integration_db_session.execute(
            select(NotificationRule).where(NotificationRule.name == name)
        )
        assert result.scalar_one_or_none() is None

    async def test_list_notification_rules(self, integration_client, seed_run):
        """GET /api/v1/projects/{id}/notification-rules -> paginated list."""
        project_id = str(seed_run["project"].id)
        # Create one first so the list is non-empty
        create_resp = await integration_client.post(
            f"/api/v1/projects/{project_id}/notification-rules",
            json={
                "name": "list-test-rule",
                "channels": [{"type": "email", "address": "a@b.com"}],
            },
        )
        assert create_resp.status_code == 201, create_resp.text
        created = create_resp.json()
        resp = await integration_client.get(
            f"/api/v1/projects/{project_id}/notification-rules"
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body == {
            "data": [created],
            "page": 1,
            "per_page": 20,
            "total": 1,
        }
    async def test_list_notification_rules_normalizes_legacy_channel_shape(
        self, integration_client, integration_db_session, seed_run
    ):
        """GET /api/v1/projects/{id}/notification-rules normalizes legacy DB JSON."""
        project_id = seed_run["project"].id
        webhook_url = f"https://hooks.example.com/legacy/{uuid.uuid4().hex}"
        legacy_rule = NotificationRule(
            project_id=project_id,
            name="legacy-channel-shape",
            channels=[{"type": "webhook", "webhook_url": webhook_url}],
            conditions=[],
        )
        integration_db_session.add(legacy_rule)
        await integration_db_session.commit()
        await integration_db_session.refresh(legacy_rule)

        resp = await integration_client.get(
            f"/api/v1/projects/{project_id}/notification-rules"
        )

        assert resp.status_code == 200, resp.text
        body = resp.json()
        expected_item = {
            "id": str(legacy_rule.id),
            "project_id": str(project_id),
            "name": "legacy-channel-shape",
            "enabled": True,
            "conditions": [],
            "channels": [
                {"type": "webhook", "config": {"url": webhook_url}, "template": None}
            ],
            "template": None,
            "created_at": _json_datetime(legacy_rule.created_at),
        }
        assert body == {
            "data": [expected_item],
            "page": 1,
            "per_page": 20,
            "total": 1,
        }
        assert "webhook_url" not in body["data"][0]["channels"][0]

    async def test_list_notification_rules_marks_historical_invalid_conditions(
        self, integration_client, integration_db_session, seed_run
    ):
        """GET /notification-rules surfaces historical bad condition rows without 500."""
        project_id = seed_run["project"].id
        dirty_rule = NotificationRule(
            project_id=project_id,
            name=f"historical-invalid-condition-{uuid.uuid4().hex}",
            channels=[
                {
                    "type": "webhook",
                    "config": {"url": "https://hooks.example.com/historical-invalid"},
                }
            ],
            conditions=[
                {"field": "statuz", "operator": "eq", "value": "failed"},
                {"all": [{"field": "failed", "operator": "around", "value": 1}]},
            ],
        )
        integration_db_session.add(dirty_rule)
        await integration_db_session.commit()
        await integration_db_session.refresh(dirty_rule)

        resp = await integration_client.get(
            f"/api/v1/projects/{project_id}/notification-rules"
        )

        assert resp.status_code == 200, resp.text
        assert resp.json() == {
            "data": [
                {
                    "id": str(dirty_rule.id),
                    "project_id": str(project_id),
                    "name": dirty_rule.name,
                    "enabled": True,
                    "conditions": [
                        {
                            "invalid": True,
                            "reason": (
                                "conditions[0].field must be one of: "
                                "consecutive_failures, failed, new_failed, pass_rate, recovered, status"
                            ),
                            "raw_field": "statuz",
                            "raw_operator": "eq",
                        },
                        {
                            "all": [
                                {
                                    "invalid": True,
                                    "reason": (
                                        "conditions[1].all[0].operator must be one of: "
                                        "eq, gt, gte, lt, lte, ne"
                                    ),
                                    "raw_field": "failed",
                                    "raw_operator": "around",
                                }
                            ]
                        },
                    ],
                    "channels": [
                        {
                            "type": "webhook",
                            "config": {"url": "https://hooks.example.com/historical-invalid"},
                            "template": None,
                        }
                    ],
                    "template": None,
                    "created_at": _json_datetime(dirty_rule.created_at),
                }
            ],
            "page": 1,
            "per_page": 20,
            "total": 1,
        }

    async def test_update_notification_rule(
        self, integration_client, integration_db_session, seed_run
    ):
        """PUT /api/v1/projects/{id}/notification-rules/{rule_id} -> 200."""
        project_id = str(seed_run["project"].id)
        # Create a rule
        create_resp = await integration_client.post(
            f"/api/v1/projects/{project_id}/notification-rules",
            json={
                "name": "before-update",
                "channels": [{"type": "webhook", "webhook_url": "https://h.example.com"}],
            },
        )
        assert create_resp.status_code == 201, create_resp.text
        created = create_resp.json()
        assert created == {
            "id": created["id"],
            "project_id": project_id,
            "name": "before-update",
            "enabled": True,
            "conditions": [],
            "channels": [
                {
                    "type": "webhook",
                    "config": {"url": "https://h.example.com"},
                    "template": None,
                }
            ],
            "template": None,
            "created_at": created["created_at"],
        }
        rule_id = created["id"]
        before_audit_state = _notification_rule_audit_state(created)

        # Update it
        resp = await integration_client.put(
            f"/api/v1/projects/{project_id}/notification-rules/{rule_id}",
            json={"name": "after-update", "enabled": False},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        expected_body = {**created, "name": "after-update", "enabled": False}
        assert body == expected_body

        rule = await integration_db_session.get(NotificationRule, uuid.UUID(rule_id))
        assert rule is not None
        assert rule.name == "after-update"
        assert rule.enabled is False
        assert rule.conditions == created["conditions"]
        assert rule.channels == [
            {"type": "webhook", "config": {"url": "https://h.example.com"}}
        ]

        audit = (
            await integration_db_session.execute(
                select(AuditEvent).where(
                    AuditEvent.action == "notification_rule.update",
                    AuditEvent.resource_id == rule.id,
                )
            )
        ).scalar_one()
        assert audit.tenant_id == seed_run["tenant"].id
        assert audit.user_id == seed_run["user"].id
        assert audit.resource_type == "notification_rule"
        assert audit.resource_id == rule.id
        assert audit.before_state == before_audit_state
        assert audit.after_state == _notification_rule_audit_state(expected_body)

    async def test_delete_notification_rule(
        self, integration_client, integration_db_session, seed_run
    ):
        """DELETE /api/v1/projects/{id}/notification-rules/{rule_id} -> 204."""
        project_id = str(seed_run["project"].id)
        # Create a rule
        create_resp = await integration_client.post(
            f"/api/v1/projects/{project_id}/notification-rules",
            json={
                "name": "to-delete",
                "channels": [{"type": "webhook", "webhook_url": "https://h.example.com"}],
            },
        )
        assert create_resp.status_code == 201
        created = create_resp.json()
        rule_id = created["id"]

        # Delete it
        del_resp = await integration_client.delete(
            f"/api/v1/projects/{project_id}/notification-rules/{rule_id}"
        )
        assert del_resp.status_code == 204
        assert del_resp.content == b""

        # Verify gone
        get_resp = await integration_client.get(
            f"/api/v1/projects/{project_id}/notification-rules/{rule_id}"
        )
        assert get_resp.status_code == 404, get_resp.text
        assert get_resp.json() == _not_found_body("Notification rule not found")
        for forbidden in [project_id, rule_id, "https://h.example.com"]:
            assert forbidden not in get_resp.text
        deleted_rule = await integration_db_session.get(NotificationRule, uuid.UUID(rule_id))
        assert deleted_rule is not None
        assert deleted_rule.deleted_at is not None

        audit = (
            await integration_db_session.execute(
                select(AuditEvent).where(
                    AuditEvent.action == "notification_rule.delete",
                    AuditEvent.resource_id == deleted_rule.id,
                )
            )
        ).scalar_one()
        assert audit.tenant_id == seed_run["tenant"].id
        assert audit.user_id == seed_run["user"].id
        assert audit.resource_type == "notification_rule"
        assert audit.resource_id == deleted_rule.id
        assert audit.before_state == {
            "id": rule_id,
            "project_id": project_id,
            "name": "to-delete",
            "enabled": True,
            "conditions": [],
            "channels": {
                "redacted": True,
                "count": 1,
                "types": ["webhook"],
            },
            "template": {
                "redacted": True,
                "present": False,
                "length": 0,
            },
            "created_at": created["created_at"],
        }
        assert audit.after_state is None
        serialized_audit = repr([audit.before_state, audit.after_state])
        for forbidden in [
            "https://h.example.com",
            "webhook_url",
            "config",
            '"url"',
        ]:
            assert forbidden not in serialized_audit


# --------------------------------------------------------------------------- #
# Analytics
# --------------------------------------------------------------------------- #


class TestAnalytics:
    """Tests 15-16: trends / flaky tests."""

    async def test_get_trends(
        self, integration_client, integration_db_session, seed_run
    ):
        """GET /api/v1/projects/{id}/analytics/trends aggregates terminal runs."""
        project_id = str(seed_run["project"].id)
        created_at = datetime.now(timezone.utc) - timedelta(days=2)
        runs = [
            Run(
                tenant_id=seed_run["tenant"].id,
                project_id=seed_run["project"].id,
                pipeline_id=seed_run["pipeline"].id,
                environment_id=seed_run["environment"].id,
                status=RunStatusEnum.DONE,
                trigger_type="manual",
                priority=1,
                triggered_by=seed_run["user"].id,
                git_ref="analytics-trend",
                attempt=1,
                chain_depth=0,
                metadata_={},
                created_at=created_at,
            ),
            Run(
                tenant_id=seed_run["tenant"].id,
                project_id=seed_run["project"].id,
                pipeline_id=seed_run["pipeline"].id,
                environment_id=seed_run["environment"].id,
                status=RunStatusEnum.FAILED,
                trigger_type="manual",
                priority=1,
                triggered_by=seed_run["user"].id,
                git_ref="analytics-trend",
                attempt=1,
                chain_depth=0,
                metadata_={},
                created_at=created_at + timedelta(minutes=5),
            ),
            Run(
                tenant_id=seed_run["tenant"].id,
                project_id=seed_run["project"].id,
                pipeline_id=seed_run["pipeline"].id,
                environment_id=seed_run["environment"].id,
                status=RunStatusEnum.DONE,
                trigger_type="manual",
                priority=1,
                triggered_by=seed_run["user"].id,
                git_ref="analytics-trend-soft-deleted",
                attempt=1,
                chain_depth=0,
                metadata_={},
                created_at=created_at + timedelta(minutes=10),
                deleted_at=datetime.now(timezone.utc),
            ),
        ]
        integration_db_session.add_all(runs)
        await integration_db_session.commit()

        resp = await integration_client.get(
            f"/api/v1/projects/{project_id}/analytics/trends?days=30"
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body == {
            "data": [
                {
                    "date": str(created_at.date()),
                    "total_runs": 2,
                    "passed_runs": 1,
                    "failed_runs": 1,
                    "pass_rate": 0.5,
                }
            ],
            "pagination": {"offset": 0, "limit": 365, "total": 1},
        }

    async def test_get_flaky(
        self, integration_client, integration_db_session, seed_run
    ):
        """GET /api/v1/projects/{id}/analytics/flaky detects mixed outcomes."""
        project_id = str(seed_run["project"].id)
        base_time = datetime.now(timezone.utc) - timedelta(days=1)
        passing_run = Run(
            tenant_id=seed_run["tenant"].id,
            project_id=seed_run["project"].id,
            pipeline_id=seed_run["pipeline"].id,
            environment_id=seed_run["environment"].id,
            status=RunStatusEnum.DONE,
            trigger_type="manual",
            priority=1,
            triggered_by=seed_run["user"].id,
            git_ref="analytics-flaky",
            attempt=1,
            chain_depth=0,
            metadata_={},
            created_at=base_time,
        )
        failing_run = Run(
            tenant_id=seed_run["tenant"].id,
            project_id=seed_run["project"].id,
            pipeline_id=seed_run["pipeline"].id,
            environment_id=seed_run["environment"].id,
            status=RunStatusEnum.FAILED,
            trigger_type="manual",
            priority=1,
            triggered_by=seed_run["user"].id,
            git_ref="analytics-flaky",
            attempt=1,
            chain_depth=0,
            metadata_={},
            created_at=base_time + timedelta(minutes=5),
        )
        stable_run = Run(
            tenant_id=seed_run["tenant"].id,
            project_id=seed_run["project"].id,
            pipeline_id=seed_run["pipeline"].id,
            environment_id=seed_run["environment"].id,
            status=RunStatusEnum.DONE,
            trigger_type="manual",
            priority=1,
            triggered_by=seed_run["user"].id,
            git_ref="analytics-flaky",
            attempt=1,
            chain_depth=0,
            metadata_={},
            created_at=base_time + timedelta(minutes=10),
        )
        soft_deleted_run = Run(
            tenant_id=seed_run["tenant"].id,
            project_id=seed_run["project"].id,
            pipeline_id=seed_run["pipeline"].id,
            environment_id=seed_run["environment"].id,
            status=RunStatusEnum.FAILED,
            trigger_type="manual",
            priority=1,
            triggered_by=seed_run["user"].id,
            git_ref="analytics-flaky-soft-deleted",
            attempt=1,
            chain_depth=0,
            metadata_={},
            created_at=base_time + timedelta(minutes=15),
            deleted_at=datetime.now(timezone.utc),
        )
        integration_db_session.add_all([
            passing_run,
            failing_run,
            stable_run,
            soft_deleted_run,
        ])
        await integration_db_session.flush()
        integration_db_session.add_all(
            [
                DbTestResult(
                    run_id=passing_run.id,
                    suite="analytics",
                    name="test_flaky_checkout",
                    status=DbTestResultStatusEnum.PASSED,
                    duration_ms=10,
                    tags=[],
                    metadata_={},
                ),
                DbTestResult(
                    run_id=failing_run.id,
                    suite="analytics",
                    name="test_flaky_checkout",
                    status=DbTestResultStatusEnum.FAILED,
                    duration_ms=12,
                    tags=[],
                    metadata_={},
                ),
                DbTestResult(
                    run_id=stable_run.id,
                    suite="analytics",
                    name="test_stable_login",
                    status=DbTestResultStatusEnum.PASSED,
                    duration_ms=8,
                    tags=[],
                    metadata_={},
                ),
                DbTestResult(
                    run_id=soft_deleted_run.id,
                    suite="analytics",
                    name="test_flaky_checkout",
                    status=DbTestResultStatusEnum.ERROR,
                    duration_ms=14,
                    tags=[],
                    metadata_={},
                ),
            ]
        )
        await integration_db_session.commit()

        resp = await integration_client.get(
            f"/api/v1/projects/{project_id}/analytics/flaky?days=30&min_runs=2"
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body == {
            "data": [
                {
                    "suite": "analytics",
                    "name": "test_flaky_checkout",
                    "total_runs": 2,
                    "passed_count": 1,
                    "failed_count": 1,
                    "flaky_rate": 0.5,
                    "observation_count": 2,
                    "window_days": 30,
                }
            ],
            "pagination": {"offset": 0, "limit": 50, "total": 1},
        }

    async def test_release_summary_and_git_ref_filtered_analytics(
        self, integration_client, integration_db_session, seed_run
    ):
        """Release summary compares target ref to baseline without cross-ref bleed."""
        project_id = str(seed_run["project"].id)
        base_time = datetime.now(timezone.utc) - timedelta(days=1)
        target_pass = Run(
            tenant_id=seed_run["tenant"].id,
            project_id=seed_run["project"].id,
            pipeline_id=seed_run["pipeline"].id,
            environment_id=seed_run["environment"].id,
            status=RunStatusEnum.DONE,
            trigger_type="manual",
            priority=1,
            triggered_by=seed_run["user"].id,
            git_ref="release/2026.06",
            attempt=1,
            chain_depth=0,
            metadata_={},
            created_at=base_time,
        )
        target_fail = Run(
            tenant_id=seed_run["tenant"].id,
            project_id=seed_run["project"].id,
            pipeline_id=seed_run["pipeline"].id,
            environment_id=seed_run["environment"].id,
            status=RunStatusEnum.FAILED,
            trigger_type="manual",
            priority=1,
            triggered_by=seed_run["user"].id,
            git_ref="release/2026.06",
            attempt=1,
            chain_depth=0,
            metadata_={},
            created_at=base_time + timedelta(minutes=5),
        )
        baseline_fail = Run(
            tenant_id=seed_run["tenant"].id,
            project_id=seed_run["project"].id,
            pipeline_id=seed_run["pipeline"].id,
            environment_id=seed_run["environment"].id,
            status=RunStatusEnum.FAILED,
            trigger_type="manual",
            priority=1,
            triggered_by=seed_run["user"].id,
            git_ref="main",
            attempt=1,
            chain_depth=0,
            metadata_={},
            created_at=base_time + timedelta(minutes=10),
        )
        other_ref_fail = Run(
            tenant_id=seed_run["tenant"].id,
            project_id=seed_run["project"].id,
            pipeline_id=seed_run["pipeline"].id,
            environment_id=seed_run["environment"].id,
            status=RunStatusEnum.FAILED,
            trigger_type="manual",
            priority=1,
            triggered_by=seed_run["user"].id,
            git_ref="feature/noise",
            attempt=1,
            chain_depth=0,
            metadata_={},
            created_at=base_time + timedelta(minutes=15),
        )
        integration_db_session.add_all([
            target_pass,
            target_fail,
            baseline_fail,
            other_ref_fail,
        ])
        await integration_db_session.flush()
        integration_db_session.add_all(
            [
                DbTestResult(
                    run_id=target_pass.id,
                    suite="analytics",
                    name="test_flaky_known",
                    status=DbTestResultStatusEnum.PASSED,
                    duration_ms=10,
                    tags=[],
                    metadata_={},
                ),
                DbTestResult(
                    run_id=target_pass.id,
                    suite="analytics",
                    name="test_stable_pass",
                    status=DbTestResultStatusEnum.PASSED,
                    duration_ms=8,
                    tags=[],
                    metadata_={},
                ),
                DbTestResult(
                    run_id=target_fail.id,
                    suite="analytics",
                    name="test_flaky_known",
                    status=DbTestResultStatusEnum.FAILED,
                    duration_ms=11,
                    tags=[],
                    metadata_={},
                ),
                DbTestResult(
                    run_id=target_fail.id,
                    suite="analytics",
                    name="test_new_failure",
                    status=DbTestResultStatusEnum.FAILED,
                    duration_ms=12,
                    tags=[],
                    metadata_={},
                ),
                DbTestResult(
                    run_id=baseline_fail.id,
                    suite="analytics",
                    name="test_flaky_known",
                    status=DbTestResultStatusEnum.FAILED,
                    duration_ms=9,
                    tags=[],
                    metadata_={},
                ),
                DbTestResult(
                    run_id=baseline_fail.id,
                    suite="analytics",
                    name="test_recovered",
                    status=DbTestResultStatusEnum.FAILED,
                    duration_ms=13,
                    tags=[],
                    metadata_={},
                ),
                DbTestResult(
                    run_id=other_ref_fail.id,
                    suite="analytics",
                    name="test_noise",
                    status=DbTestResultStatusEnum.FAILED,
                    duration_ms=14,
                    tags=[],
                    metadata_={},
                ),
            ]
        )
        await integration_db_session.commit()

        trends_resp = await integration_client.get(
            f"/api/v1/projects/{project_id}/analytics/trends",
            params={"days": 30, "git_ref": "release/2026.06"},
        )
        assert trends_resp.status_code == 200, trends_resp.text
        assert trends_resp.json() == {
            "data": [
                {
                    "date": str(base_time.date()),
                    "total_runs": 2,
                    "passed_runs": 1,
                    "failed_runs": 1,
                    "pass_rate": 0.5,
                }
            ],
            "pagination": {"offset": 0, "limit": 365, "total": 1},
        }

        flaky_resp = await integration_client.get(
            f"/api/v1/projects/{project_id}/analytics/flaky",
            params={"days": 30, "min_runs": 2, "git_ref": "release/2026.06"},
        )
        assert flaky_resp.status_code == 200, flaky_resp.text
        assert flaky_resp.json() == {
            "data": [
                {
                    "suite": "analytics",
                    "name": "test_flaky_known",
                    "total_runs": 2,
                    "passed_count": 1,
                    "failed_count": 1,
                    "flaky_rate": 0.5,
                    "observation_count": 2,
                    "window_days": 30,
                }
            ],
            "pagination": {"offset": 0, "limit": 50, "total": 1},
        }

        summary_resp = await integration_client.get(
            f"/api/v1/projects/{project_id}/analytics/release-summary",
            params={
                "days": 30,
                "git_ref": "release/2026.06",
                "baseline_git_ref": "main",
            },
        )
        assert summary_resp.status_code == 200, summary_resp.text
        assert summary_resp.json() == {
            "git_ref": "release/2026.06",
            "baseline_git_ref": "main",
            "total_runs": 2,
            "passed_runs": 1,
            "failed_runs": 1,
            "raw_pass_rate": 0.5,
            "flaky_adjusted_pass_rate": 0.5,
            "new_failing_tests": [
                {
                    "suite": "analytics",
                    "name": "test_new_failure",
                    "failed_count": 1,
                }
            ],
            "recovered_tests": [
                {
                    "suite": "analytics",
                    "name": "test_recovered",
                    "failed_count": 1,
                }
            ],
            "observation_count": 2,
            "window_days": 30,
            "quarantined_excluded": [],
        }

    async def test_get_test_history(
        self, integration_client, integration_db_session, seed_run
    ):
        """GET /api/v1/projects/{id}/analytics/test-history returns one test timeline."""
        project_id = str(seed_run["project"].id)
        base_time = datetime.now(timezone.utc) - timedelta(days=1)
        passing_run = Run(
            tenant_id=seed_run["tenant"].id,
            project_id=seed_run["project"].id,
            pipeline_id=seed_run["pipeline"].id,
            environment_id=seed_run["environment"].id,
            status=RunStatusEnum.DONE,
            trigger_type="manual",
            priority=1,
            triggered_by=seed_run["user"].id,
            git_ref="analytics-history-a",
            attempt=1,
            chain_depth=0,
            metadata_={},
            created_at=base_time,
        )
        failing_run = Run(
            tenant_id=seed_run["tenant"].id,
            project_id=seed_run["project"].id,
            pipeline_id=seed_run["pipeline"].id,
            environment_id=seed_run["environment"].id,
            status=RunStatusEnum.FAILED,
            trigger_type="manual",
            priority=1,
            triggered_by=seed_run["user"].id,
            git_ref="analytics-history-b",
            attempt=1,
            chain_depth=0,
            metadata_={},
            created_at=base_time + timedelta(minutes=5),
        )
        other_run = Run(
            tenant_id=seed_run["tenant"].id,
            project_id=seed_run["project"].id,
            pipeline_id=seed_run["pipeline"].id,
            environment_id=seed_run["environment"].id,
            status=RunStatusEnum.DONE,
            trigger_type="manual",
            priority=1,
            triggered_by=seed_run["user"].id,
            git_ref="analytics-history-other",
            attempt=1,
            chain_depth=0,
            metadata_={},
            created_at=base_time + timedelta(minutes=10),
        )
        soft_deleted_run = Run(
            tenant_id=seed_run["tenant"].id,
            project_id=seed_run["project"].id,
            pipeline_id=seed_run["pipeline"].id,
            environment_id=seed_run["environment"].id,
            status=RunStatusEnum.FAILED,
            trigger_type="manual",
            priority=1,
            triggered_by=seed_run["user"].id,
            git_ref="analytics-history-soft-deleted",
            attempt=1,
            chain_depth=0,
            metadata_={},
            created_at=base_time + timedelta(minutes=15),
            deleted_at=datetime.now(timezone.utc),
        )
        integration_db_session.add_all([
            passing_run,
            failing_run,
            other_run,
            soft_deleted_run,
        ])
        await integration_db_session.flush()
        integration_db_session.add_all(
            [
                DbTestResult(
                    run_id=passing_run.id,
                    suite="analytics",
                    name="test_flaky_checkout",
                    status=DbTestResultStatusEnum.PASSED,
                    duration_ms=10,
                    tags=[],
                    metadata_={},
                ),
                DbTestResult(
                    run_id=failing_run.id,
                    suite="analytics",
                    name="test_flaky_checkout",
                    status=DbTestResultStatusEnum.FAILED,
                    duration_ms=12,
                    error_message="expected checkout to pass",
                    tags=[],
                    metadata_={},
                ),
                DbTestResult(
                    run_id=other_run.id,
                    suite="analytics",
                    name="test_other_checkout",
                    status=DbTestResultStatusEnum.PASSED,
                    duration_ms=8,
                    tags=[],
                    metadata_={},
                ),
                DbTestResult(
                    run_id=soft_deleted_run.id,
                    suite="analytics",
                    name="test_flaky_checkout",
                    status=DbTestResultStatusEnum.ERROR,
                    duration_ms=14,
                    error_message="soft-deleted run should be hidden",
                    tags=[],
                    metadata_={},
                ),
            ]
        )
        await integration_db_session.commit()

        resp = await integration_client.get(
            f"/api/v1/projects/{project_id}/analytics/test-history",
            params={
                "suite": "analytics",
                "name": "test_flaky_checkout",
                "days": 30,
            },
        )

        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body == {
            "data": [
                {
                    "run_id": str(passing_run.id),
                    "run_created_at": base_time.isoformat().replace("+00:00", "Z"),
                    "run_status": "done",
                    "status": "passed",
                    "duration_ms": 10,
                    "error_message": None,
                    "git_ref": "analytics-history-a",
                    "observation_count": 2,
                },
                {
                    "run_id": str(failing_run.id),
                    "run_created_at": (base_time + timedelta(minutes=5))
                    .isoformat()
                    .replace("+00:00", "Z"),
                    "run_status": "failed",
                    "status": "failed",
                    "duration_ms": 12,
                    "error_message": "expected checkout to pass",
                    "git_ref": "analytics-history-b",
                    "observation_count": 2,
                },
            ],
            "pagination": {"offset": 0, "limit": 50, "total": 2},
        }

# --------------------------------------------------------------------------- #
# Cross-tenant isolation
# --------------------------------------------------------------------------- #


class TestCrossTenantIsolation:
    """Test 17: tenant A cannot access tenant B's project."""

    async def test_cross_tenant_project_access(
        self, integration_client_as, seed_run, seed_second_tenant
    ):
        """Tenant A user gets 404 when accessing tenant B's project."""
        tenant_a_user = seed_run["user"]
        tenant_a_tenant = seed_run["tenant"]
        tenant_b_project_id = str(seed_second_tenant["project"].id)
        tenant_b_tenant_id = str(seed_second_tenant["tenant"].id)
        tenant_b_user_id = str(seed_second_tenant["user"].id)
        random_project_id = str(uuid.uuid4())

        async with integration_client_as(
            tenant_a_user.id, tenant_a_tenant.id, role="owner"
        ) as client:
            resp = await client.get(f"/api/v1/projects/{tenant_b_project_id}")
            random_resp = await client.get(f"/api/v1/projects/{random_project_id}")
            assert resp.status_code == 404, (
                f"Expected 404 for cross-tenant access, got {resp.status_code}"
            )
            assert random_resp.status_code == 404, (
                f"Expected 404 for random project, got {random_resp.status_code}"
            )
            expected_body = {
                "error": {
                    "code": "NOT_FOUND",
                    "message": "Project not found",
                    "details": [],
                }
            }
            assert resp.json() == expected_body
            assert random_resp.json() == expected_body
            assert resp.json() == random_resp.json()
            leaked_cross_tenant_ids = {
                tenant_b_project_id,
                tenant_b_tenant_id,
                tenant_b_user_id,
            }
            leaked_cross_tenant_values = [
                value
                for value in sorted(leaked_cross_tenant_ids)
                if value in resp.text or value in random_resp.text
            ]
            leaked_random_values = [
                value for value in [random_project_id] if value in random_resp.text
            ]
            assert leaked_cross_tenant_values == []
            assert leaked_random_values == []
