"""外部结果导入 API（T11）集成测试：完整 HTTP 路径 + 真实 PG。"""

from __future__ import annotations

import os
from uuid import uuid4

import pytest
from sqlalchemy import select

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_INTEGRATION_TESTS") != "1",
    reason="set RUN_INTEGRATION_TESTS=1 to run integration tests",
)

FAILING_XML = """<?xml version="1.0"?>
<testsuites>
  <testsuite name="suite1" tests="3">
    <testcase classname="tests.unit.test_math" name="test_add" time="0.10"/>
    <testcase classname="tests.unit.test_math" name="test_div" time="0.20">
      <failure message="ZeroDivisionError">Traceback (most recent call last)...</failure>
    </testcase>
    <testcase classname="tests.unit.test_math" name="test_skip" time="0">
      <skipped message="not on this platform"/>
    </testcase>
  </testsuite>
</testsuites>"""

PASSING_XML = """<?xml version="1.0"?>
<testsuite name="suite1" tests="2">
  <testcase classname="tests.unit.test_math" name="test_add" time="0.10"/>
  <testcase classname="tests.unit.test_math" name="test_div" time="0.15"/>
</testsuite>"""

_XML_HEADERS = {
    "Content-Type": "application/xml",
    "Authorization": "Bearer fake",
}


def _import_url(project_id, **params) -> str:
    extra = "&".join(f"{k}={v}" for k, v in params.items())
    return f"/api/v1/projects/{project_id}/runs/import?git_ref=main" + (
        f"&{extra}" if extra else ""
    )


async def _import_xml(client, project_id, xml: str, **params):
    return await client.post(
        _import_url(project_id, **params), content=xml, headers=_XML_HEADERS
    )


@pytest.mark.asyncio
async def test_import_full_http_roundtrip(integration_client, seed_run):
    """验收 1/3：导入 → 201 RunResponse；详情/列表/结果过滤可见；坏 XML 422。"""
    project = seed_run["project"]

    resp = await _import_xml(integration_client, project.id, FAILING_XML)
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["trigger_type"] == "import"
    assert body["status"] == "failed"
    assert body["pipeline_name"] == "external-import"
    assert body["summary"]["total"] == 3
    assert body["summary"]["failed"] == 1
    assert body["summary"]["skipped"] == 1
    assert body["duration_ms"] == 300
    run_id = body["id"]

    # Run 详情
    detail = await integration_client.get(
        f"/api/v1/runs/{run_id}", headers=_XML_HEADERS
    )
    assert detail.status_code == 200
    assert detail.json()["status"] == "failed"

    # Run 列表（按 project 过滤）
    listing = await integration_client.get(
        f"/api/v1/runs?project_id={project.id}&status=failed",
        headers=_XML_HEADERS,
    )
    assert listing.status_code == 200
    assert run_id in [item["id"] for item in listing.json()["data"]]

    # 测试结果可过滤查询
    results = await integration_client.get(
        f"/api/v1/runs/{run_id}/results?status=failed", headers=_XML_HEADERS
    )
    assert results.status_code == 200
    failed_rows = results.json()
    assert failed_rows["total"] == 1
    assert failed_rows["data"][0]["suite"] == "tests.unit.test_math"
    assert failed_rows["data"][0]["name"] == "test_div"
    assert failed_rows["data"][0]["error_message"] == "ZeroDivisionError"

    # 坏 XML → 422
    bad = await _import_xml(integration_client, project.id, "<testsuite><oops")
    assert bad.status_code == 422


@pytest.mark.asyncio
async def test_import_duplicate_uploads_create_independent_runs(
    integration_client, seed_run
):
    """验收 4：import 不去重，重复上传同一文件生成两条独立 Run。"""
    project = seed_run["project"]

    first = await _import_xml(integration_client, project.id, PASSING_XML)
    second = await _import_xml(integration_client, project.id, PASSING_XML)

    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json()["id"] != second.json()["id"]
    # 复用同一占位 pipeline/environment（get-or-create 幂等）
    assert first.json()["pipeline_id"] == second.json()["pipeline_id"]
    assert first.json()["environment_id"] == second.json()["environment_id"]


@pytest.mark.asyncio
async def test_import_data_visible_in_all_analytics_endpoints(
    integration_client, seed_run
):
    """验收 2：导入数据进入 trends / flaky / release-summary / test-history。"""
    project = seed_run["project"]

    # 3 个终态 run、同 (suite,name) 既有 passed 又有 failed → 满足 flaky 判定
    # （min_runs 默认 3）。
    for xml in (FAILING_XML, PASSING_XML, FAILING_XML):
        resp = await _import_xml(integration_client, project.id, xml)
        assert resp.status_code == 201

    trends = await integration_client.get(
        f"/api/v1/projects/{project.id}/analytics/trends", headers=_XML_HEADERS
    )
    assert trends.status_code == 200
    trend_points = trends.json()["data"]
    assert sum(point["total_runs"] for point in trend_points) >= 3

    flaky = await integration_client.get(
        f"/api/v1/projects/{project.id}/analytics/flaky", headers=_XML_HEADERS
    )
    assert flaky.status_code == 200
    flaky_cases = {
        (item["suite"], item["name"]) for item in flaky.json()["data"]
    }
    assert ("tests.unit.test_math", "test_div") in flaky_cases

    release = await integration_client.get(
        f"/api/v1/projects/{project.id}/analytics/release-summary",
        headers=_XML_HEADERS,
    )
    assert release.status_code == 200
    assert release.json()["total_runs"] >= 3

    history = await integration_client.get(
        f"/api/v1/projects/{project.id}/analytics/test-history"
        "?suite=tests.unit.test_math&name=test_div",
        headers=_XML_HEADERS,
    )
    assert history.status_code == 200
    statuses = [point["status"] for point in history.json()["data"]]
    assert statuses.count("failed") == 2
    assert statuses.count("passed") == 1


@pytest.mark.asyncio
async def test_import_cross_tenant_project_is_404(
    integration_client, seed_run, seed_second_tenant
):
    """验收 3：跨租户 project_id 返回 404（不泄露存在性）。"""
    other_project = seed_second_tenant["project"]

    resp = await _import_xml(integration_client, other_project.id, PASSING_XML)

    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_import_missing_project_is_404(integration_client, seed_run):
    resp = await _import_xml(integration_client, uuid4(), PASSING_XML)

    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_import_writes_terminal_run_and_audit_to_db(
    integration_client, seed_run, integration_db_session
):
    """导入落库断言：终态 Run、占位 pipeline enabled=False、审计事件。"""
    from qaplatform.infra.database.models import AuditEvent, Pipeline, Run

    project = seed_run["project"]
    sha = "f" * 40

    resp = await _import_xml(
        integration_client, project.id, PASSING_XML, git_sha=sha, branch="main"
    )
    assert resp.status_code == 201
    run_id = resp.json()["id"]

    run = (
        await integration_db_session.execute(select(Run).where(Run.id == run_id))
    ).scalar_one()
    assert run.status.value == "done"
    assert run.trigger_type == "import"
    assert run.git_sha == sha
    assert run.finished_at is not None
    assert run.metadata_["import"]["branch"] == "main"

    pipeline = (
        await integration_db_session.execute(
            select(Pipeline).where(Pipeline.id == run.pipeline_id)
        )
    ).scalar_one()
    assert pipeline.name == "external-import"
    assert pipeline.enabled is False

    audit_actions = (
        await integration_db_session.execute(
            select(AuditEvent.action).where(AuditEvent.resource_id == run.id)
        )
    ).scalars().all()
    assert audit_actions == ["run.import"]


@pytest.mark.asyncio
async def test_import_with_api_token_auth(no_auth_integration_client):
    """验收 1：API token（qap_ Bearer）经认证中间件走通 import。"""
    client = no_auth_integration_client

    username = f"imp_{uuid4().hex[:10]}"
    register = await client.post(
        "/api/v1/auth/register",
        json={
            "username": username,
            "email": f"{username}@qaplatform.dev",
            "password": f"TestPass-{uuid4().hex[:16]}",
        },
    )
    assert register.status_code == 201, register.text
    jwt_headers = {"Authorization": f"Bearer {register.json()['access_token']}"}

    project_resp = await client.post(
        "/api/v1/projects",
        headers=jwt_headers,
        json={
            "name": f"import-{username}",
            "slug": f"import-{username}".replace("_", "-"),
            "git_url": "https://github.com/example/import.git",
            "default_branch": "main",
        },
    )
    assert project_resp.status_code == 201, project_resp.text
    project_id = project_resp.json()["id"]

    token_resp = await client.post(
        "/api/v1/auth/tokens",
        headers=jwt_headers,
        json={"name": "ci-import", "scopes": ["run.trigger"]},
    )
    assert token_resp.status_code == 201, token_resp.text
    api_token = token_resp.json()["token"]
    assert api_token.startswith("qap_")

    resp = await client.post(
        _import_url(project_id),
        content=PASSING_XML,
        headers={
            "Content-Type": "application/xml",
            "Authorization": f"Bearer {api_token}",
        },
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["trigger_type"] == "import"
