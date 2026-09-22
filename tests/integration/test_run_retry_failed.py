"""retry-failed 端点的集成测试。

这个文件曾经整体标着 `heavy_docker`，因此从不在 PR CI 里运行。它打的
`/api/v1/projects/{id}/runs/trigger` 路由并不存在、引用的 `seed_tenant_b`
fixture 也不存在，所以一次都没跑通过——直到 2026-09-22 手动触发
release_candidate gate 才暴露。

现在用真实存在的路由与 fixture 重写，并去掉 `heavy_docker`：这些用例验证的
是 API 层行为（终态校验、失败子集提取、跨租户隔离），只需要 PG + Redis，
不需要真实 Docker 执行——heavy_docker 档本来也不起 worker，标着它既跑不到
也名不副实。

执行侧「重跑是否只跑失败用例」由 tests/unit/test_engine/test_executor.py 的
TestRetryFailedSubsetFiltering 用真实 PytestRunner 断言最终命令行来覆盖。
"""

from __future__ import annotations

import os
from uuid import uuid4

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_INTEGRATION_TESTS") != "1",
    reason="set RUN_INTEGRATION_TESTS=1 to run integration tests",
)

FAILING_JUNIT = """<?xml version="1.0"?>
<testsuite name="suite" tests="3">
  <testcase classname="tests.unit.test_x" name="test_pass" time="0.01"/>
  <testcase classname="tests.unit.test_x" name="test_fail_a" time="0.01">
    <failure message="AssertionError">boom</failure>
  </testcase>
  <testcase classname="tests.unit.test_x" name="test_fail_b" time="0.01">
    <error message="RuntimeError">kaboom</error>
  </testcase>
</testsuite>"""

PASSING_JUNIT = """<?xml version="1.0"?>
<testsuite name="suite" tests="2">
  <testcase classname="tests.unit.test_x" name="test_a" time="0.01"/>
  <testcase classname="tests.unit.test_x" name="test_b" time="0.01"/>
</testsuite>"""


async def _import_run(client, project_id, junit: str, *, git_ref: str = "main") -> dict:
    """用外部结果导入造一个终态 run——它不入队、不需要 worker。"""
    resp = await client.post(
        f"/api/v1/projects/{project_id}/runs/import?git_ref={git_ref}",
        content=junit,
        headers={"Content-Type": "application/xml"},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


@pytest.mark.asyncio
async def test_retry_failed_creates_run_carrying_only_the_failed_cases(
    integration_client, integration_db_session, seed_run
):
    """有失败用例时创建重跑 run，metadata 只带失败的那些。"""
    from uuid import UUID

    from qaplatform.infra.database.models import Run

    project = seed_run["project"]
    original = await _import_run(integration_client, project.id, FAILING_JUNIT)
    assert original["status"] == "failed"

    resp = await integration_client.post(
        f"/api/v1/runs/{original['id']}/retry-failed"
    )
    # 200 而非 201：端点未声明 status_code，FastAPI 取默认值，
    # tests/api_matrix/openapi_operation_matrix.yml 也已按 200 基线化。
    # 按 REST 语义这里创建了新资源、更该是 201，但那属于 API 契约变更，
    # 不在本次修测试的范围内。
    assert resp.status_code == 200, resp.text
    retry_run = resp.json()

    assert retry_run["trigger_type"] == "retry_failed"
    assert retry_run["id"] != original["id"]

    # RunResponse 不暴露 metadata，失败子集要从库里查
    run = await integration_db_session.get(Run, UUID(retry_run["id"]))
    await integration_db_session.refresh(run)
    assert run.source_run_id == UUID(original["id"])

    # 只带失败与 error 的两条，通过的那条不在其中
    cases = run.metadata_["retry_failed_cases"]
    assert {c["name"] for c in cases} == {"test_fail_a", "test_fail_b"}
    assert all(c["suite"] == "tests.unit.test_x" for c in cases)


@pytest.mark.asyncio
async def test_retry_failed_rejects_run_without_failures(
    integration_client, seed_run
):
    """全通过的 run 没有可重跑的东西，返回 409。"""
    project = seed_run["project"]
    original = await _import_run(integration_client, project.id, PASSING_JUNIT)
    assert original["status"] == "done"

    resp = await integration_client.post(
        f"/api/v1/runs/{original['id']}/retry-failed"
    )
    assert resp.status_code == 409, resp.text
    assert "No failed test cases" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_retry_failed_rejects_non_terminal_run(
    integration_client, integration_db_session, seed_run
):
    """非终态 run 的失败集合还没定下来，不允许重跑。"""
    from uuid import UUID

    from qaplatform.infra.database.models import Run, RunStatusEnum

    project = seed_run["project"]
    original = await _import_run(integration_client, project.id, FAILING_JUNIT)

    # 导入出来的 run 是终态的，直接把它掰回 running 来构造这个场景
    run = await integration_db_session.get(Run, UUID(original["id"]))
    run.status = RunStatusEnum.RUNNING
    await integration_db_session.commit()

    resp = await integration_client.post(
        f"/api/v1/runs/{original['id']}/retry-failed"
    )
    assert resp.status_code == 409, resp.text
    assert "terminal state" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_retry_failed_on_unknown_run_is_404(integration_client, seed_run):
    """不存在的 run 返回 404。"""
    resp = await integration_client.post(f"/api/v1/runs/{uuid4()}/retry-failed")
    assert resp.status_code == 404, resp.text


@pytest.mark.asyncio
async def test_retry_failed_across_tenants_is_404_not_403(
    integration_client_as, seed_run, seed_second_tenant
):
    """跨租户访问必须是 404 而不是 403。

    403 会泄露「这个 id 确实存在」这一事实，等于给了对方一个可枚举的探针。
    """
    project_a = seed_run["project"]
    tenant_b = seed_second_tenant

    async with integration_client_as(
        seed_run["user"].id, seed_run["tenant"].id, role="owner"
    ) as client_a:
        original = await _import_run(client_a, project_a.id, FAILING_JUNIT)

    # 换成租户 B 的身份去重跑租户 A 的 run
    async with integration_client_as(
        tenant_b["user"].id, tenant_b["tenant"].id, role="owner"
    ) as client_b:
        resp = await client_b.post(f"/api/v1/runs/{original['id']}/retry-failed")

    assert resp.status_code == 404, resp.text
    assert resp.json()["error"]["code"] == "NOT_FOUND"
