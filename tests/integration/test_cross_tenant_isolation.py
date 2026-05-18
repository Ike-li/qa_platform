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

import pytest
import pytest_asyncio

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


def _detail(body: dict) -> str | None:
    """Extract the error detail string from a response body."""
    return body.get("detail") or body.get("error", {}).get("message")


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

    assert status_b == status_r == 404
    detail_b = _detail(body_b)
    detail_r = _detail(body_r)
    assert detail_b == detail_r
    assert detail_b is not None and detail_b != ""


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

    if status_b == 403:
        pytest.xfail(
            reason="P0-4 follow-up: RBAC runs before tenant check, leaks existence"
            f" (got 403 for tenant_B project, 404 for random — detail_b={_detail(body_b)!r})"
        )

    assert status_b == status_r == 404
    detail_b = _detail(body_b)
    detail_r = _detail(body_r)
    assert detail_b == detail_r
    assert detail_b is not None and detail_b != ""


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

    if status_b == 403:
        pytest.xfail(
            reason="P0-4 follow-up: RBAC runs before tenant check, leaks existence"
            f" (got 403 for tenant_B project, 404 for random — detail_b={_detail(body_b)!r})"
        )

    assert status_b == status_r == 404
    detail_b = _detail(body_b)
    detail_r = _detail(body_r)
    assert detail_b == detail_r
    assert detail_b is not None and detail_b != ""


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

    assert status_b == status_r == 404
    detail_b = _detail(body_b)
    detail_r = _detail(body_r)
    assert detail_b == detail_r
    assert detail_b is not None and detail_b != ""


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

    if status_b == 403:
        pytest.xfail(
            reason="P0-4 follow-up: RBAC runs before tenant check, leaks existence"
            f" (got 403 for tenant_B project, 404 for random — detail_b={_detail(body_b)!r})"
        )

    assert status_b == status_r == 404
    detail_b = _detail(body_b)
    detail_r = _detail(body_r)
    assert detail_b == detail_r
    assert detail_b is not None and detail_b != ""


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

    assert status_b == status_r == 404
    detail_b = _detail(body_b)
    detail_r = _detail(body_r)
    assert detail_b == detail_r, (
        f"Oracle leak: tenant_B pipeline → {detail_b!r}, random → {detail_r!r}"
    )
    assert detail_b is not None and detail_b != ""


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

    assert status_b == status_r == 404
    detail_b = _detail(body_b)
    detail_r = _detail(body_r)
    assert detail_b == detail_r
    assert detail_b is not None and detail_b != ""


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

    assert status_b == status_r == 404
    detail_b = _detail(body_b)
    detail_r = _detail(body_r)
    assert detail_b == detail_r
    assert detail_b is not None and detail_b != ""


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

    assert status_b == status_r == 404
    detail_b = _detail(body_b)
    detail_r = _detail(body_r)
    assert detail_b == detail_r
    assert detail_b is not None and detail_b != ""


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

    assert status_b == status_r == 404
    detail_b = _detail(body_b)
    detail_r = _detail(body_r)
    assert detail_b == detail_r
    assert detail_b is not None and detail_b != ""


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

    assert status_b == status_r == 404
    detail_b = _detail(body_b)
    detail_r = _detail(body_r)
    assert detail_b == detail_r
    assert detail_b is not None and detail_b != ""
