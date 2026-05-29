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

from qaplatform.infra.database.models import AuditEvent, Pipeline, Run, RunStatusEnum

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_INTEGRATION_TESTS") != "1",
    reason="set RUN_INTEGRATION_TESTS=1 to run integration tests",
)


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _unique_slug(prefix: str = "proj") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


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
        assert body["name"] == "new-project"
        assert body["slug"] == slug
        assert body["git_url"] == payload["git_url"]
        assert body["status"] == "active"
        assert "id" in body
        assert "created_at" in body

    async def test_list_projects(self, integration_client, seed_run):
        """GET /api/v1/projects -> paginated list with at least the seeded project."""
        # Create a second project to ensure listing works
        slug = _unique_slug()
        await integration_client.post(
            "/api/v1/projects",
            json={"name": "list-test", "slug": slug, "git_url": "https://example.com/r.git"},
        )

        resp = await integration_client.get("/api/v1/projects")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert "data" in body
        assert "page" in body
        assert "per_page" in body
        assert "total" in body
        assert body["total"] >= 1
        # Verify pagination fields are present on each item
        for item in body["data"]:
            assert "id" in item
            assert "name" in item

    async def test_get_project(self, integration_client, seed_run):
        """GET /api/v1/projects/{id} -> 200 with correct fields."""
        project_id = str(seed_run["project"].id)
        resp = await integration_client.get(f"/api/v1/projects/{project_id}")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["id"] == project_id
        assert body["name"] == "integration-project"

    async def test_update_project(self, integration_client, seed_run):
        """PUT /api/v1/projects/{id} -> 200 with updated name."""
        project_id = str(seed_run["project"].id)
        resp = await integration_client.put(
            f"/api/v1/projects/{project_id}",
            json={"name": "renamed-project"},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["name"] == "renamed-project"
        assert body["id"] == project_id

    async def test_delete_project(self, integration_client, seed_run):
        """DELETE /api/v1/projects/{id} -> 204, subsequent GET -> 404."""
        # Create a throwaway project so we don't break other tests
        slug = _unique_slug()
        create_resp = await integration_client.post(
            "/api/v1/projects",
            json={"name": "to-delete", "slug": slug, "git_url": "https://example.com/r.git"},
        )
        assert create_resp.status_code == 201
        pid = create_resp.json()["id"]

        del_resp = await integration_client.delete(f"/api/v1/projects/{pid}")
        assert del_resp.status_code == 204

        get_resp = await integration_client.get(f"/api/v1/projects/{pid}")
        assert get_resp.status_code == 404


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
        assert body["pipeline_id"] == pipeline_id
        assert body["environment_id"] == environment_id
        assert body["status"] == "queued"
        assert body["git_ref"] == "main"
        assert body["git_sha"] == git_sha
        assert body["priority"] == 0

        run = await integration_db_session.get(Run, body["id"])
        assert run is not None
        assert str(run.environment_id) == environment_id
        assert run.git_sha == git_sha

        audit = (
            await integration_db_session.execute(
                select(AuditEvent).where(
                    AuditEvent.action == "run.trigger",
                    AuditEvent.resource_id == run.id,
                )
            )
        ).scalar_one()
        assert audit.after_state["environment_id"] == environment_id
        assert audit.after_state["git_sha"] == git_sha

    async def test_get_run(self, integration_client, seed_run):
        """GET /api/v1/runs/{id} -> 200 with correct fields."""
        run_id = str(seed_run["run"].id)
        resp = await integration_client.get(f"/api/v1/runs/{run_id}")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["id"] == run_id
        assert body["pipeline_id"] == str(seed_run["pipeline"].id)

    async def test_list_runs(self, integration_client, seed_run):
        """GET /api/v1/runs -> paginated list with seeded run."""
        resp = await integration_client.get("/api/v1/runs")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert "data" in body
        assert body["total"] >= 1
        # The seeded run should be in the list
        run_ids = [r["id"] for r in body["data"]]
        assert str(seed_run["run"].id) in run_ids

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
        assert str(target_run.id) in {run["id"] for run in pipeline_body["data"]}
        assert str(first_pipeline_run.id) not in {run["id"] for run in pipeline_body["data"]}
        assert all(
            run["pipeline_id"] == str(second_pipeline.id) for run in pipeline_body["data"]
        )

        git_ref_resp = await integration_client.get(
            "/api/v1/runs",
            params={"git_ref": target_run.git_ref, "per_page": 100},
        )
        assert git_ref_resp.status_code == 200, git_ref_resp.text
        git_ref_body = git_ref_resp.json()
        assert [run["id"] for run in git_ref_body["data"]] == [str(target_run.id)]
        assert git_ref_body["total"] == 1

        range_resp = await integration_client.get(
            "/api/v1/runs",
            params={
                "created_from": (base_time + timedelta(minutes=30)).isoformat(),
                "created_to": (base_time + timedelta(minutes=90)).isoformat(),
                "per_page": 100,
            },
        )
        assert range_resp.status_code == 200, range_resp.text
        range_ids = {run["id"] for run in range_resp.json()["data"]}
        assert str(target_run.id) in range_ids
        assert str(first_pipeline_run.id) not in range_ids
        assert str(later_run.id) not in range_ids


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
        assert body["name"] == "e2e-pipeline"
        assert body["project_id"] == project_id
        assert body["enabled"] is True
        assert body["stages"][0]["plugin"] == "shell"
        assert body["stages"][0]["config"]["command"].startswith("python -m pip")
        assert body["stages"][1]["phase"] == "execute"
        assert body["selector"]["include_paths"] == ["tests/api"]
        assert body["selector"]["on_empty"] == "warn"
        assert body["trigger_config"]["type"] == "manual"
        assert body["trigger_config"]["source"] == {"branch": "main"}
        assert body["trigger_config"]["conditions"] == {
            "changed_paths": ["tests/api/**"]
        }
        assert body["trigger_config"]["target"] == {"environment": "staging"}
        assert body["collectors"] == payload["collectors"]
        assert body["retry_policy"] == payload["retry_policy"]

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
        pipeline_id = create_resp.json()["id"]

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
        assert body["id"] == pipeline_id
        assert body["name"] == "after-update"
        assert body["enabled"] is False
        assert body["stages"][0]["plugin"] == "webhook"
        assert body["stages"][0]["config"]["url"] == "https://deploy.example/hooks/qa"
        assert body["stages"][0]["phase"] == "notify"
        assert body["selector"]["include_paths"] == ["tests/e2e"]
        assert body["selector"]["on_empty"] == "skip"
        assert body["trigger_config"]["type"] == "webhook"
        assert body["trigger_config"]["source"] == {"provider": "github"}
        assert body["trigger_config"]["conditions"] == {"event": "push"}
        assert body["trigger_config"]["target"] == {"environment": "prod"}
        assert body["collectors"] == payload["collectors"]
        assert body["retry_policy"] == payload["retry_policy"]

    async def test_list_pipelines(self, integration_client, seed_run):
        """GET /api/v1/projects/{id}/pipelines -> at least the seeded pipeline."""
        project_id = str(seed_run["project"].id)
        resp = await integration_client.get(
            f"/api/v1/projects/{project_id}/pipelines"
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert "data" in body
        assert body["total"] >= 1
        pipe_ids = [p["id"] for p in body["data"]]
        assert str(seed_run["pipeline"].id) in pipe_ids


# --------------------------------------------------------------------------- #
# Notification Rules
# --------------------------------------------------------------------------- #


class TestNotificationRules:
    """Tests 11-14: create / list / update / delete notification rules."""

    async def test_create_notification_rule(self, integration_client, seed_run):
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
        assert body["name"] == "slack-alert"
        assert body["enabled"] is True
        assert len(body["channels"]) == 1

    async def test_list_notification_rules(self, integration_client, seed_run):
        """GET /api/v1/projects/{id}/notification-rules -> paginated list."""
        project_id = str(seed_run["project"].id)
        # Create one first so the list is non-empty
        await integration_client.post(
            f"/api/v1/projects/{project_id}/notification-rules",
            json={
                "name": "list-test-rule",
                "channels": [{"type": "email", "address": "a@b.com"}],
            },
        )
        resp = await integration_client.get(
            f"/api/v1/projects/{project_id}/notification-rules"
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert "data" in body
        assert body["total"] >= 1

    async def test_update_notification_rule(self, integration_client, seed_run):
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
        assert create_resp.status_code == 201
        rule_id = create_resp.json()["id"]

        # Update it
        resp = await integration_client.put(
            f"/api/v1/projects/{project_id}/notification-rules/{rule_id}",
            json={"name": "after-update", "enabled": False},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["name"] == "after-update"
        assert body["enabled"] is False

    async def test_delete_notification_rule(self, integration_client, seed_run):
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
        rule_id = create_resp.json()["id"]

        # Delete it
        del_resp = await integration_client.delete(
            f"/api/v1/projects/{project_id}/notification-rules/{rule_id}"
        )
        assert del_resp.status_code == 204

        # Verify gone
        get_resp = await integration_client.get(
            f"/api/v1/projects/{project_id}/notification-rules/{rule_id}"
        )
        assert get_resp.status_code == 404


# --------------------------------------------------------------------------- #
# Analytics
# --------------------------------------------------------------------------- #


class TestAnalytics:
    """Tests 15-16: trends / flaky tests."""

    async def test_get_trends(self, integration_client, seed_run):
        """GET /api/v1/projects/{id}/analytics/trends -> 200 with data list."""
        project_id = str(seed_run["project"].id)
        resp = await integration_client.get(
            f"/api/v1/projects/{project_id}/analytics/trends?days=30"
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        # API may return a raw list or a paginated wrapper depending on version
        data = body if isinstance(body, list) else body.get("data", body)
        assert isinstance(data, list)
        # The seeded run is QUEUED (not DONE/FAILED/TIMEOUT), so trends may be empty.
        # That is acceptable — we are verifying the endpoint returns 200.

    async def test_get_flaky(self, integration_client, seed_run):
        """GET /api/v1/projects/{id}/analytics/flaky -> 200 with data list."""
        project_id = str(seed_run["project"].id)
        resp = await integration_client.get(
            f"/api/v1/projects/{project_id}/analytics/flaky?days=30&min_runs=2"
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        data = body if isinstance(body, list) else body.get("data", body)
        assert isinstance(data, list)


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

        async with integration_client_as(
            tenant_a_user.id, tenant_a_tenant.id, role="owner"
        ) as client:
            resp = await client.get(f"/api/v1/projects/{tenant_b_project_id}")
            assert resp.status_code == 404, (
                f"Expected 404 for cross-tenant access, got {resp.status_code}"
            )
