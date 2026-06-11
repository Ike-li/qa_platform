"""失败分诊 API（T12）集成测试：完整 HTTP 路径 + 真实 PG。

历史用 T11 的 import API 构造（每份 XML 一条终态 Run），验证三类归类、
签名聚类、空态、跨租户 404 与批量历史查询的性能粗断言。
"""

from __future__ import annotations

import os
import time
from datetime import datetime, timedelta, timezone
from statistics import median
from uuid import uuid4

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_INTEGRATION_TESTS") != "1",
    reason="set RUN_INTEGRATION_TESTS=1 to run integration tests",
)

SUITE = "tests.integration.test_demo"

_HEADERS = {
    "Content-Type": "application/xml",
    "Authorization": "Bearer fake",
}


def _junit_xml(cases: list[tuple[str, str, str | None]]) -> str:
    """构造 JUnit XML：cases = [(name, passed|failed, failure_message), ...]。"""
    rows = []
    for name, status, message in cases:
        if status == "passed":
            rows.append(f'<testcase classname="{SUITE}" name="{name}" time="0.01"/>')
        else:
            rows.append(
                f'<testcase classname="{SUITE}" name="{name}" time="0.01">'
                f'<failure message="{message}">Traceback ...</failure>'
                "</testcase>"
            )
    return (
        '<?xml version="1.0"?>'
        f'<testsuite name="suite" tests="{len(cases)}">{"".join(rows)}</testsuite>'
    )


async def _import_run(client, project_id, cases) -> str:
    resp = await client.post(
        f"/api/v1/projects/{project_id}/runs/import?git_ref=main",
        content=_junit_xml(cases),
        headers=_HEADERS,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _items_by_name(clusters: list[dict]) -> dict[str, dict]:
    return {
        item["name"]: item for cluster in clusters for item in cluster["items"]
    }


@pytest.mark.asyncio
async def test_triage_categorizes_flaky_persistent_and_new(
    integration_client, seed_run
):
    """验收 1：A 翻转 → known_flaky、B 连续失败 3 次 → persistent、C 首次失败 → new。"""
    project = seed_run["project"]
    flip = ("test_flip", "AssertionError: flip broke")
    stuck = ("test_stuck", "TimeoutError: stuck forever")
    fresh = ("test_fresh", "RuntimeError: first time")

    # 历史：A 翻转（passed/failed 交替），B 连续失败 3 次。
    await _import_run(integration_client, project.id, [
        (flip[0], "passed", None), (stuck[0], "failed", stuck[1]),
    ])
    await _import_run(integration_client, project.id, [
        (flip[0], "failed", flip[1]), (stuck[0], "failed", stuck[1]),
    ])
    await _import_run(integration_client, project.id, [
        (flip[0], "passed", None), (stuck[0], "failed", stuck[1]),
    ])
    # 目标 run：A、B、C 全部失败。
    target_run_id = await _import_run(integration_client, project.id, [
        (flip[0], "failed", flip[1]),
        (stuck[0], "failed", stuck[1]),
        (fresh[0], "failed", fresh[1]),
    ])

    resp = await integration_client.get(
        f"/api/v1/runs/{target_run_id}/triage", headers=_HEADERS
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert body["run_id"] == target_run_id
    assert body["total_failed"] == 3
    assert list(_items_by_name(body["known_flaky"])) == [flip[0]]
    assert list(_items_by_name(body["persistent"])) == [stuck[0]]
    assert list(_items_by_name(body["new"])) == [fresh[0]]

    # 履历：升序（旧 → 新），最后一格是本次失败；观测数与置信度。
    flip_item = _items_by_name(body["known_flaky"])[flip[0]]
    assert flip_item["observation_count"] == 4
    assert flip_item["confidence"] == "observing"
    history = flip_item["recent_history"]
    assert [obs["status"] for obs in history] == [
        "passed", "failed", "passed", "failed",
    ]
    assert history[-1]["run_id"] == target_run_id

    fresh_item = _items_by_name(body["new"])[fresh[0]]
    assert fresh_item["observation_count"] == 1
    assert len(fresh_item["recent_history"]) == 1

    stuck_item = _items_by_name(body["persistent"])[stuck[0]]
    assert stuck_item["observation_count"] == 4
    assert stuck_item["category"] == "persistent"


@pytest.mark.asyncio
async def test_triage_clusters_same_signature(integration_client, seed_run):
    """验收 2：数字归一后同签名的失败折叠为一组。"""
    project = seed_run["project"]
    run_id = await _import_run(integration_client, project.id, [
        ("test_a", "failed", "AssertionError: expected 1 got 2"),
        ("test_b", "failed", "AssertionError: expected 33 got 777"),
        ("test_c", "failed", "TypeError: boom"),
    ])

    resp = await integration_client.get(
        f"/api/v1/runs/{run_id}/triage", headers=_HEADERS
    )
    assert resp.status_code == 200
    new_clusters = resp.json()["new"]

    assert len(new_clusters) == 2
    first = new_clusters[0]  # 组按数量降序
    assert first["count"] == 2
    assert first["signature"] == "AssertionError: expected <num> got <num>"
    assert sorted(item["name"] for item in first["items"]) == ["test_a", "test_b"]
    assert new_clusters[1]["count"] == 1


@pytest.mark.asyncio
async def test_triage_empty_for_run_without_failures(
    integration_client, seed_run
):
    """无失败的 run：total_failed=0、三组为空（前端空态依据）。"""
    project = seed_run["project"]
    run_id = await _import_run(integration_client, project.id, [
        ("test_ok", "passed", None),
    ])

    resp = await integration_client.get(
        f"/api/v1/runs/{run_id}/triage", headers=_HEADERS
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["total_failed"] == 0
    assert body["new"] == []
    assert body["known_flaky"] == []
    assert body["persistent"] == []


@pytest.mark.asyncio
async def test_triage_cross_tenant_and_missing_run_404(
    integration_client, integration_client_as, seed_run, seed_second_tenant
):
    """跨租户访问与不存在的 run 均返回 404（不泄露存在性）。"""
    project = seed_run["project"]
    run_id = await _import_run(integration_client, project.id, [
        ("test_x", "failed", "boom"),
    ])

    other_user = seed_second_tenant["user"]
    other_tenant = seed_second_tenant["tenant"]
    async with integration_client_as(other_user.id, other_tenant.id) as client:
        cross = await client.get(f"/api/v1/runs/{run_id}/triage")
        assert cross.status_code == 404

    missing = await integration_client.get(
        f"/api/v1/runs/{uuid4()}/triage", headers=_HEADERS
    )
    assert missing.status_code == 404


@pytest.mark.asyncio
@pytest.mark.performance
async def test_triage_performance_5000_cases(
    integration_client, integration_db_session, seed_run
):
    """验收 4：5000 失败用例的 run，triage 端点中位耗时 < 500ms（粗粒度）。"""
    from qaplatform.infra.database.models import Run, RunStatusEnum, TestResult

    session = integration_db_session
    project = seed_run["project"]
    now = datetime.now(timezone.utc)

    def _make_run(created_at: datetime) -> Run:
        return Run(
            tenant_id=project.tenant_id,
            project_id=project.id,
            pipeline_id=seed_run["pipeline"].id,
            environment_id=seed_run["environment"].id,
            status=RunStatusEnum.FAILED,
            trigger_type="import",
            priority=1,
            git_ref="main",
            attempt=1,
            chain_depth=0,
            metadata_={},
            created_at=created_at,
        )

    # created_at 显式给值：同一事务内 now() 相同，会破坏"本 run 之前"的排序。
    history_run = _make_run(now - timedelta(hours=1))
    target_run = _make_run(now)
    session.add_all([history_run, target_run])
    await session.flush()

    def _rows(run_id, status: str) -> list[dict]:
        return [
            {
                "run_id": run_id,
                "suite": SUITE,
                "name": f"test_case_{i}",
                "status": status,
                "duration_ms": 1,
                "error_message": f"AssertionError: case {i} expected {i} got {i + 1}",
                "tags": [],
                "metadata_": {},
            }
            for i in range(5000)
        ]

    from sqlalchemy import insert

    await session.execute(insert(TestResult), _rows(history_run.id, "passed"))
    await session.execute(insert(TestResult), _rows(target_run.id, "failed"))
    await session.commit()

    durations = []
    for _ in range(5):
        start = time.perf_counter()
        resp = await integration_client.get(
            f"/api/v1/runs/{target_run.id}/triage", headers=_HEADERS
        )
        durations.append(time.perf_counter() - start)
        assert resp.status_code == 200

    body = resp.json()
    assert body["total_failed"] == 5000
    # 数字归一后所有用例共享同一签名 → 单一聚类。
    assert body["new"][0]["count"] == 5000
    assert body["new"][0]["items"][0]["observation_count"] == 2

    median_seconds = median(durations)
    print(f"\ntriage 5000-case durations: {[round(d, 3) for d in durations]} "
          f"median={median_seconds:.3f}s")
    assert median_seconds < 0.5, f"triage median {median_seconds:.3f}s >= 500ms"
