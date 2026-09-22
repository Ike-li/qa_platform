"""Integration tests for test quarantine (T17) over real database & endpoints."""

from __future__ import annotations

import os

import pytest
from sqlalchemy import select

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_INTEGRATION_TESTS") != "1",
    reason="set RUN_INTEGRATION_TESTS=1 to run integration tests",
)

_HEADERS = {
    "Authorization": "Bearer fake",
}


@pytest.mark.asyncio
async def test_quarantine_lifecycle_and_audit(
    integration_client, integration_db_session, seed_run
):
    """Test full quarantine lifecycle (add, list, remove) and audit trail verification."""
    from qaplatform.infra.database.models import AuditEvent, TestQuarantine

    project = seed_run["project"]

    # 1. Add to quarantine
    payload = {
        "suite": "tests.suite_integration",
        "name": "test_unstable_lifecycle",
        "reason": "Temporary isolation",
    }
    resp = await integration_client.post(
        f"/api/v1/projects/{project.id}/quarantine", json=payload, headers=_HEADERS
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["suite"] == "tests.suite_integration"
    assert body["name"] == "test_unstable_lifecycle"
    assert body["reason"] == "Temporary isolation"

    # Verify DB state directly
    stmt = select(TestQuarantine).where(
        TestQuarantine.project_id == project.id,
        TestQuarantine.suite == "tests.suite_integration",
        TestQuarantine.name == "test_unstable_lifecycle",
    )
    db_record = (await integration_db_session.execute(stmt)).scalar_one_or_none()
    assert db_record is not None
    assert db_record.reason == "Temporary isolation"

    # Verify audit event write for add
    audit_stmt = select(AuditEvent).where(
        AuditEvent.tenant_id == project.tenant_id,
        AuditEvent.action == "quarantine.add",
    )
    audit_record = (await integration_db_session.execute(audit_stmt)).scalar_one_or_none()
    assert audit_record is not None
    assert audit_record.resource_type == "quarantine"
    assert audit_record.after_state is not None
    assert audit_record.after_state["name"] == "test_unstable_lifecycle"

    # 2. List quarantine
    list_resp = await integration_client.get(
        f"/api/v1/projects/{project.id}/quarantine", headers=_HEADERS
    )
    assert list_resp.status_code == 200
    list_body = list_resp.json()
    assert list_body["total"] >= 1
    assert any(item["name"] == "test_unstable_lifecycle" for item in list_body["data"])

    # 3. Remove from quarantine
    remove_resp = await integration_client.delete(
        f"/api/v1/projects/{project.id}/quarantine",
        params={
            "suite": "tests.suite_integration",
            "name": "test_unstable_lifecycle",
        },
        headers=_HEADERS,
    )
    assert remove_resp.status_code == 204

    # Verify DB state deleted
    db_record_after = (await integration_db_session.execute(stmt)).scalar_one_or_none()
    assert db_record_after is None

    # Verify audit event write for remove
    audit_remove_stmt = select(AuditEvent).where(
        AuditEvent.tenant_id == project.tenant_id,
        AuditEvent.action == "quarantine.remove",
    )
    audit_remove_record = (await integration_db_session.execute(audit_remove_stmt)).scalar_one_or_none()
    assert audit_remove_record is not None
    assert audit_remove_record.before_state is not None
    assert audit_remove_record.before_state["name"] == "test_unstable_lifecycle"


@pytest.mark.asyncio
async def test_quarantine_cross_tenant_isolation(
    integration_client, integration_client_as, seed_run, seed_second_tenant
):
    """Test that users from other tenants cannot access or modify project quarantine."""
    project = seed_run["project"]
    other_user = seed_second_tenant["user"]
    other_tenant = seed_second_tenant["tenant"]

    payload = {
        "suite": "tests.suite_isolated",
        "name": "test_tenant_breach",
        "reason": "isolation checking",
    }

    # Verify list, add, remove all return 404 under other tenant context
    async with integration_client_as(other_user.id, other_tenant.id) as client:
        # 1. Accessing other tenant project list returns 404
        list_resp = await client.get(f"/api/v1/projects/{project.id}/quarantine")
        assert list_resp.status_code == 404

        # 2. Creating quarantine for other tenant project returns 404
        post_resp = await client.post(
            f"/api/v1/projects/{project.id}/quarantine", json=payload
        )
        assert post_resp.status_code == 404

        # 3. Deleting from quarantine for other tenant project returns 404
        delete_resp = await client.delete(
            f"/api/v1/projects/{project.id}/quarantine",
            params={"suite": "s", "name": "n"},
        )
        assert delete_resp.status_code == 404


def _junit_xml(suite: str, cases: list[tuple[str, str, str | None]]) -> str:
    """构造 JUnit XML：cases = [(name, passed|failed, failure_message), ...]。"""
    rows = []
    for name, status, message in cases:
        if status == "passed":
            rows.append(f'<testcase classname="{suite}" name="{name}" time="0.01"/>')
        else:
            rows.append(
                f'<testcase classname="{suite}" name="{name}" time="0.01">'
                f'<failure message="{message}">Traceback ...</failure>'
                "</testcase>"
            )
    return (
        '<?xml version="1.0"?>'
        f'<testsuite name="suite" tests="{len(cases)}">{"".join(rows)}</testsuite>'
    )


@pytest.mark.asyncio
async def test_quarantine_exclusion_in_release_summary(
    integration_client, integration_db_session, seed_run
):
    """Verify that quarantined failing tests are excluded from release-summary calculations."""
    project = seed_run["project"]

    # 1. Create a baseline and target run with failure in target run via import endpoint
    # baseline_run: test_quarantine_exclude passed on "main"
    baseline_xml = _junit_xml("tests.suite_summary", [("test_quarantine_exclude", "passed", None)])
    resp_base = await integration_client.post(
        f"/api/v1/projects/{project.id}/runs/import?git_ref=main",
        content=baseline_xml,
        headers={"Content-Type": "application/xml", "Authorization": "Bearer fake"},
    )
    assert resp_base.status_code == 201

    # target_run: test_quarantine_exclude failed on "feature-branch"
    target_xml = _junit_xml("tests.suite_summary", [("test_quarantine_exclude", "failed", "Miserable failure")])
    resp_target = await integration_client.post(
        f"/api/v1/projects/{project.id}/runs/import?git_ref=feature-branch",
        content=target_xml,
        headers={"Content-Type": "application/xml", "Authorization": "Bearer fake"},
    )
    assert resp_target.status_code == 201

    # 2. Fetch Release Summary before quarantine
    summary_resp = await integration_client.get(
        f"/api/v1/projects/{project.id}/analytics/release-summary",
        params={"git_ref": "feature-branch", "baseline_git_ref": "main"},
        headers=_HEADERS,
    )
    assert summary_resp.status_code == 200
    summary_body = summary_resp.json()
    # Should list test_quarantine_exclude as new failing test
    new_fails = [f["name"] for f in summary_body["new_failing_tests"]]
    assert "test_quarantine_exclude" in new_fails
    assert not any(f["name"] == "test_quarantine_exclude" for f in summary_body["quarantined_excluded"])

    # 3. Post to quarantine the failing test
    payload = {
        "suite": "tests.suite_summary",
        "name": "test_quarantine_exclude",
        "reason": "Confirmed flaky under investigation",
    }
    add_resp = await integration_client.post(
        f"/api/v1/projects/{project.id}/quarantine", json=payload, headers=_HEADERS
    )
    assert add_resp.status_code == 201

    # 4. Fetch Release Summary after quarantine
    summary_resp_after = await integration_client.get(
        f"/api/v1/projects/{project.id}/analytics/release-summary",
        params={"git_ref": "feature-branch", "baseline_git_ref": "main"},
        headers=_HEADERS,
    )
    assert summary_resp_after.status_code == 200
    summary_body_after = summary_resp_after.json()
    # Failing test should be excluded from new_failing_tests
    new_fails_after = [f["name"] for f in summary_body_after["new_failing_tests"]]
    assert "test_quarantine_exclude" not in new_fails_after
    # Failing test should appear in quarantined_excluded
    quarantine_ex = [f["name"] for f in summary_body_after["quarantined_excluded"]]
    assert "test_quarantine_exclude" in quarantine_ex

    # 5. Clean up from quarantine to prevent interference with other tests
    remove_resp = await integration_client.delete(
        f"/api/v1/projects/{project.id}/quarantine",
        params={
            "suite": "tests.suite_summary",
            "name": "test_quarantine_exclude",
        },
        headers=_HEADERS,
    )
    assert remove_resp.status_code == 204



@pytest.mark.asyncio
async def test_quarantine_repeat_add_updates_reason_and_returns_200(
    integration_client, integration_db_session, seed_run
):
    """重复隔离同一用例是更新而非新建，应返回 200。

    T17 §2.2 规定「已存在则更新 reason，返回 200；新建返回 201」，实现却对
    两种情况都返回 201。调用方无法从状态码区分自己是新建了一条还是覆盖了
    别人写的隔离理由。
    """
    from qaplatform.infra.database.models import TestQuarantine

    project = seed_run["project"]
    payload = {
        "suite": "tests.suite_repeat",
        "name": "test_repeat_quarantine",
        "reason": "first reason",
    }

    first = await integration_client.post(
        f"/api/v1/projects/{project.id}/quarantine", json=payload, headers=_HEADERS
    )
    assert first.status_code == 201, first.text
    first_body = first.json()

    second = await integration_client.post(
        f"/api/v1/projects/{project.id}/quarantine",
        json={**payload, "reason": "second reason"},
        headers=_HEADERS,
    )
    assert second.status_code == 200, second.text
    second_body = second.json()

    # upsert 语义：同一行被更新，id 与 created_at 不变，reason 已覆盖
    assert second_body["id"] == first_body["id"]
    assert second_body["created_at"] == first_body["created_at"]
    assert second_body["reason"] == "second reason"

    stmt = select(TestQuarantine).where(
        TestQuarantine.project_id == project.id,
        TestQuarantine.suite == "tests.suite_repeat",
        TestQuarantine.name == "test_repeat_quarantine",
    )
    rows = (await integration_db_session.execute(stmt)).scalars().all()
    assert len(rows) == 1
    assert rows[0].reason == "second reason"
