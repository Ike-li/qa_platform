"""Integration tests: core API endpoints end-to-end.

Covers Projects CRUD, Runs, Pipelines, Notification Rules, Analytics,
and cross-tenant isolation. Each test is independent and uses real DB
(no mocking).
"""
from __future__ import annotations

import os
import uuid

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_INTEGRATION_TESTS") != "1",
    reason="set RUN_INTEGRATION_TESTS=1 to run integration tests",
)


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _unique_slug(prefix: str = "proj") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


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

    async def test_trigger_run(self, integration_client, seed_run):
        """POST /api/v1/runs -> 201 with correct pipeline_id."""
        pipeline_id = str(seed_run["pipeline"].id)
        payload = {"pipeline_id": pipeline_id, "git_ref": "main"}
        resp = await integration_client.post("/api/v1/runs", json=payload)
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["pipeline_id"] == pipeline_id
        assert body["status"] == "queued"
        assert body["git_ref"] == "main"

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


# --------------------------------------------------------------------------- #
# Pipelines
# --------------------------------------------------------------------------- #


class TestPipelines:
    """Tests 9-10: create / list pipelines."""

    async def test_create_pipeline(self, integration_client, seed_run):
        """POST /api/v1/projects/{id}/pipelines -> 201."""
        project_id = str(seed_run["project"].id)
        payload = {
            "name": "e2e-pipeline",
            "stages": [
                {
                    "name": "run-tests",
                    "plugin": "pytest",
                    "phase": "execute",
                    "config": {},
                }
            ],
            "trigger_config": {"type": "manual"},
            "timeout_seconds": 600,
        }
        resp = await integration_client.post(
            f"/api/v1/projects/{project_id}/pipelines", json=payload
        )
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["name"] == "e2e-pipeline"
        assert body["project_id"] == project_id
        assert body["enabled"] is True

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
