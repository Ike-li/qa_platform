"""Integration tests: P0-4 cross-tenant isolation.

Every test verifies that tenant_A's authenticated user receives an
indistinguishable 404 when accessing tenant_B's legitimate resource IDs,
compared to accessing a completely random (non-existent) UUID.

This prevents "existence oracle" leaks where an attacker could distinguish
"resource belongs to another tenant" (403) from "resource does not exist"
(404) by observing status codes or error messages.
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_INTEGRATION_TESTS") != "1",
    reason="set RUN_INTEGRATION_TESTS=1 to run integration tests",
)


# --------------------------------------------------------------------------- #
# Helper
# --------------------------------------------------------------------------- #


async def _hit(client, method: str, path: str, **kw) -> tuple[int, dict]:
    """Fire a request and return (status_code, response_json)."""
    fn = getattr(client, method.lower())
    resp = await fn(path, **kw)
    try:
        body = resp.json()
    except Exception:
        body = {}
    return resp.status_code, body


def _assert_same_404_result(
    status_l: int,
    body_l: dict,
    status_r: int,
    body_r: dict,
    *,
    expected_detail: str,
    forbidden_values=(),
) -> None:
    expected_body = {
        "error": {
            "code": "NOT_FOUND",
            "message": expected_detail,
            "details": [],
        }
    }
    assert status_l == status_r == 404
    assert body_l == body_r == expected_body
    serialized = repr(body_l) + repr(body_r)
    for value in forbidden_values:
        assert str(value) not in serialized


async def _assert_same_404(
    client,
    method: str,
    left_path: str,
    right_path: str,
    *,
    expected_detail: str = "Project not found",
    forbidden_values=(),
    **kw,
):
    status_l, body_l = await _hit(client, method, left_path, **kw)
    status_r, body_r = await _hit(client, method, right_path, **kw)
    _assert_same_404_result(
        status_l,
        body_l,
        status_r,
        body_r,
        expected_detail=expected_detail,
        forbidden_values=forbidden_values,
    )


# --------------------------------------------------------------------------- #
# Tests
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_project_get_cross_tenant_returns_same_404(
    seed_run, seed_second_tenant, integration_client_as
):
    """GET /projects/{id} — tenant_A owner cannot distinguish tenant_B project from non-existent."""
    tenant_a = seed_run["tenant"]
    user_a = seed_run["user"]
    proj_b_id = seed_second_tenant["project"].id
    random_id = uuid.uuid4()

    async with integration_client_as(user_a.id, tenant_a.id) as client:
        status_b, body_b = await _hit(client, "GET", f"/api/v1/projects/{proj_b_id}")
        status_r, body_r = await _hit(client, "GET", f"/api/v1/projects/{random_id}")

    _assert_same_404_result(
        status_b,
        body_b,
        status_r,
        body_r,
        expected_detail="Project not found",
        forbidden_values=[proj_b_id, random_id],
    )


@pytest.mark.asyncio
async def test_project_put_cross_tenant_returns_same_404(
    seed_run, seed_second_tenant, integration_client_as
):
    """PUT /projects/{id} — tenant_A owner cannot distinguish tenant_B project from non-existent."""
    tenant_a = seed_run["tenant"]
    user_a = seed_run["user"]
    proj_b_id = seed_second_tenant["project"].id
    random_id = uuid.uuid4()
    body_payload = {"name": "x"}

    async with integration_client_as(user_a.id, tenant_a.id) as client:
        status_b, body_b = await _hit(
            client, "PUT", f"/api/v1/projects/{proj_b_id}", json=body_payload
        )
        status_r, body_r = await _hit(
            client, "PUT", f"/api/v1/projects/{random_id}", json=body_payload
        )

    _assert_same_404_result(
        status_b,
        body_b,
        status_r,
        body_r,
        expected_detail="Project not found",
        forbidden_values=[proj_b_id, random_id],
    )


@pytest.mark.asyncio
async def test_project_delete_cross_tenant_returns_same_404(
    seed_run, seed_second_tenant, integration_client_as
):
    """DELETE /projects/{id} — tenant_A owner cannot distinguish tenant_B project from non-existent."""
    tenant_a = seed_run["tenant"]
    user_a = seed_run["user"]
    proj_b_id = seed_second_tenant["project"].id
    random_id = uuid.uuid4()

    async with integration_client_as(user_a.id, tenant_a.id) as client:
        status_b, body_b = await _hit(client, "DELETE", f"/api/v1/projects/{proj_b_id}")
        status_r, body_r = await _hit(client, "DELETE", f"/api/v1/projects/{random_id}")

    _assert_same_404_result(
        status_b,
        body_b,
        status_r,
        body_r,
        expected_detail="Project not found",
        forbidden_values=[proj_b_id, random_id],
    )


@pytest.mark.asyncio
async def test_project_environment_get_cross_tenant_returns_same_404(
    seed_run, seed_second_tenant, integration_client_as
):
    """GET /projects/{id}/environments/{env_id} — outer project check fires first."""
    tenant_a = seed_run["tenant"]
    user_a = seed_run["user"]
    proj_b_id = seed_second_tenant["project"].id
    env_b_id = seed_second_tenant["environment"].id
    random_proj_id = uuid.uuid4()
    random_env_id = uuid.uuid4()

    async with integration_client_as(user_a.id, tenant_a.id) as client:
        status_b, body_b = await _hit(
            client, "GET", f"/api/v1/projects/{proj_b_id}/environments/{env_b_id}"
        )
        status_r, body_r = await _hit(
            client, "GET", f"/api/v1/projects/{random_proj_id}/environments/{random_env_id}"
        )

    _assert_same_404_result(
        status_b,
        body_b,
        status_r,
        body_r,
        expected_detail="Project not found",
        forbidden_values=[proj_b_id, env_b_id, random_proj_id, random_env_id],
    )


@pytest.mark.asyncio
async def test_project_credentials_list_cross_tenant_returns_same_404(
    seed_run, seed_second_tenant, integration_client_as
):
    """GET /projects/{id}/credentials — _verify_project_access fires before listing."""
    tenant_a = seed_run["tenant"]
    user_a = seed_run["user"]
    proj_b_id = seed_second_tenant["project"].id
    random_id = uuid.uuid4()

    async with integration_client_as(user_a.id, tenant_a.id) as client:
        status_b, body_b = await _hit(
            client, "GET", f"/api/v1/projects/{proj_b_id}/credentials"
        )
        status_r, body_r = await _hit(
            client, "GET", f"/api/v1/projects/{random_id}/credentials"
        )

    _assert_same_404_result(
        status_b,
        body_b,
        status_r,
        body_r,
        expected_detail="Project not found",
        forbidden_values=[proj_b_id, random_id],
    )


@pytest.mark.asyncio
async def test_project_scoped_routes_member_viewer_cross_tenant_return_same_404(
    seed_run, seed_second_tenant, integration_client_as
):
    """Member/Viewer cannot distinguish tenant_B project IDs from random IDs."""
    tenant_a = seed_run["tenant"]
    user_a = seed_run["user"]
    proj_b_id = seed_second_tenant["project"].id

    route_matrix = [
        (
            "PUT",
            f"/api/v1/projects/{proj_b_id}",
            f"/api/v1/projects/{uuid.uuid4()}",
            {"json": {"name": "no-oracle"}},
        ),
        (
            "GET",
            f"/api/v1/projects/{proj_b_id}/credentials",
            f"/api/v1/projects/{uuid.uuid4()}/credentials",
            {},
        ),
        (
            "GET",
            f"/api/v1/projects/{proj_b_id}/pipelines",
            f"/api/v1/projects/{uuid.uuid4()}/pipelines",
            {},
        ),
    ]

    checked = 0
    for role in ("member", "viewer"):
        async with integration_client_as(user_a.id, tenant_a.id, role=role) as client:
            for method, tenant_b_path, random_path, kwargs in route_matrix:
                await _assert_same_404(
                    client,
                    method,
                    tenant_b_path,
                    random_path,
                    forbidden_values=[proj_b_id],
                    **kwargs,
                )
                checked += 1

    assert checked == len(route_matrix) * 2


@pytest.mark.asyncio
async def test_project_scoped_routes_member_viewer_soft_deleted_return_same_404(
    seed_run, integration_db_session, integration_client_as
):
    """Soft-deleted project IDs collapse to the same 404 as random UUIDs."""
    tenant = seed_run["tenant"]
    user = seed_run["user"]
    project = seed_run["project"]
    project.deleted_at = datetime.now(timezone.utc)
    await integration_db_session.commit()

    checked = 0
    for role in ("member", "viewer"):
        async with integration_client_as(user.id, tenant.id, role=role) as client:
            await _assert_same_404(
                client,
                "GET",
                f"/api/v1/projects/{project.id}/credentials",
                f"/api/v1/projects/{uuid.uuid4()}/credentials",
                forbidden_values=[project.id],
            )
            checked += 1

    assert checked == 2


@pytest.mark.asyncio
async def test_trigger_run_cross_tenant_pipeline_returns_same_404(
    seed_run, seed_second_tenant, integration_client_as
):
    """POST /runs with tenant_B pipeline_id — oracle防护重点.

    Both tenant_B's real pipeline_id and a random UUID must return identical
    404 + detail so an attacker cannot enumerate pipeline IDs across tenants.
    """
    tenant_a = seed_run["tenant"]
    user_a = seed_run["user"]
    pipeline_b_id = seed_second_tenant["pipeline"].id
    random_id = uuid.uuid4()

    async with integration_client_as(user_a.id, tenant_a.id) as client:
        status_b, body_b = await _hit(
            client, "POST", "/api/v1/runs", json={"pipeline_id": str(pipeline_b_id)}
        )
        status_r, body_r = await _hit(
            client, "POST", "/api/v1/runs", json={"pipeline_id": str(random_id)}
        )

    _assert_same_404_result(
        status_b,
        body_b,
        status_r,
        body_r,
        expected_detail="Pipeline not found",
        forbidden_values=[pipeline_b_id, random_id],
    )


@pytest.mark.asyncio
async def test_run_get_cross_tenant_returns_same_404(
    seed_run, seed_second_tenant, integration_client_as
):
    """GET /runs/{id} — tenant_A cannot see tenant_B run."""
    tenant_a = seed_run["tenant"]
    user_a = seed_run["user"]
    run_b_id = seed_second_tenant["run"].id
    random_id = uuid.uuid4()

    async with integration_client_as(user_a.id, tenant_a.id) as client:
        status_b, body_b = await _hit(client, "GET", f"/api/v1/runs/{run_b_id}")
        status_r, body_r = await _hit(client, "GET", f"/api/v1/runs/{random_id}")

    _assert_same_404_result(
        status_b,
        body_b,
        status_r,
        body_r,
        expected_detail="Run not found",
        forbidden_values=[run_b_id, random_id],
    )


@pytest.mark.asyncio
async def test_run_cancel_cross_tenant_returns_same_404(
    seed_run, seed_second_tenant, integration_client_as
):
    """POST /runs/{id}/cancel — tenant_A cannot cancel tenant_B run."""
    tenant_a = seed_run["tenant"]
    user_a = seed_run["user"]
    run_b_id = seed_second_tenant["run"].id
    random_id = uuid.uuid4()

    async with integration_client_as(user_a.id, tenant_a.id) as client:
        status_b, body_b = await _hit(client, "POST", f"/api/v1/runs/{run_b_id}/cancel")
        status_r, body_r = await _hit(client, "POST", f"/api/v1/runs/{random_id}/cancel")

    _assert_same_404_result(
        status_b,
        body_b,
        status_r,
        body_r,
        expected_detail="Run not found",
        forbidden_values=[run_b_id, random_id],
    )


@pytest.mark.asyncio
async def test_run_results_cross_tenant_returns_same_404(
    seed_run, seed_second_tenant, integration_client_as
):
    """GET /runs/{id}/results — tenant_A cannot read tenant_B run results."""
    tenant_a = seed_run["tenant"]
    user_a = seed_run["user"]
    run_b_id = seed_second_tenant["run"].id
    random_id = uuid.uuid4()

    async with integration_client_as(user_a.id, tenant_a.id) as client:
        status_b, body_b = await _hit(client, "GET", f"/api/v1/runs/{run_b_id}/results")
        status_r, body_r = await _hit(client, "GET", f"/api/v1/runs/{random_id}/results")

    _assert_same_404_result(
        status_b,
        body_b,
        status_r,
        body_r,
        expected_detail="Run not found",
        forbidden_values=[run_b_id, random_id],
    )


@pytest.mark.asyncio
async def test_run_artifacts_cross_tenant_returns_same_404(
    seed_run, seed_second_tenant, integration_client_as
):
    """GET /runs/{id}/artifacts — tenant_A cannot list tenant_B run artifacts."""
    tenant_a = seed_run["tenant"]
    user_a = seed_run["user"]
    run_b_id = seed_second_tenant["run"].id
    random_id = uuid.uuid4()

    async with integration_client_as(user_a.id, tenant_a.id) as client:
        status_b, body_b = await _hit(client, "GET", f"/api/v1/runs/{run_b_id}/artifacts")
        status_r, body_r = await _hit(client, "GET", f"/api/v1/runs/{random_id}/artifacts")

    _assert_same_404_result(
        status_b,
        body_b,
        status_r,
        body_r,
        expected_detail="Run not found",
        forbidden_values=[run_b_id, random_id],
    )


@pytest.mark.asyncio
async def test_archived_logs_cross_tenant_returns_same_404(
    seed_run, seed_second_tenant, integration_client_as
):
    """GET /runs/{id}/logs/archive — tenant_A cannot probe tenant_B archived logs."""
    tenant_a = seed_run["tenant"]
    user_a = seed_run["user"]
    run_b_id = seed_second_tenant["run"].id
    random_id = uuid.uuid4()

    async with integration_client_as(user_a.id, tenant_a.id) as client:
        status_b, body_b = await _hit(
            client,
            "GET",
            f"/api/v1/runs/{run_b_id}/logs/archive",
        )
        status_r, body_r = await _hit(
            client,
            "GET",
            f"/api/v1/runs/{random_id}/logs/archive",
        )

    _assert_same_404_result(
        status_b,
        body_b,
        status_r,
        body_r,
        expected_detail="Run not found",
        forbidden_values=[run_b_id, random_id],
    )


@pytest.mark.asyncio
async def test_artifact_download_cross_tenant_returns_same_404(
    seed_run, seed_second_tenant, integration_client_as
):
    """GET /artifacts/{id}/download — _get_artifact_or_404 hides cross-tenant artifacts."""
    tenant_a = seed_run["tenant"]
    user_a = seed_run["user"]
    artifact_b_id = seed_second_tenant["artifact"].id
    random_id = uuid.uuid4()

    async with integration_client_as(user_a.id, tenant_a.id) as client:
        status_b, body_b = await _hit(
            client, "GET", f"/api/v1/artifacts/{artifact_b_id}/download"
        )
        status_r, body_r = await _hit(
            client, "GET", f"/api/v1/artifacts/{random_id}/download"
        )

    _assert_same_404_result(
        status_b,
        body_b,
        status_r,
        body_r,
        expected_detail="Artifact not found",
        forbidden_values=[artifact_b_id, random_id],
    )
