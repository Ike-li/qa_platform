"""build_run_triage 组装逻辑（T12）单测：归类优先级、签名聚类、履历、置信度。

组装逻辑不触 DB：用 SimpleNamespace 模拟 ORM Run/TestResult 与批量历史
查询行。端点层用 mock repos + ASGI client 走完整 HTTP 路径。
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from qaplatform.api.run_triage import (
    TRIAGE_CONFIDENCE_MIN_OBSERVATIONS,
    TRIAGE_FLAKY_MIN_RUNS,
    TRIAGE_FLAKY_SCAN_LIMIT,
    TRIAGE_HISTORY_LENGTH,
    TRIAGE_WINDOW_DAYS,
    build_run_triage,
    categorize_failure,
    triage_history_cutoff,
)

NOW = datetime(2026, 6, 10, 12, 0, 0, tzinfo=timezone.utc)


def _run(created_at=NOW):
    return SimpleNamespace(id=uuid4(), created_at=created_at)


def _failed_result(suite="tests.unit.test_x", name="test_a", status="failed",
                   error_message="boom", stack_trace=None, duration_ms=10):
    return SimpleNamespace(
        suite=suite,
        name=name,
        status=status,
        error_message=error_message,
        stack_trace=stack_trace,
        duration_ms=duration_ms,
    )


def _observation(status, *, age_minutes=10):
    return SimpleNamespace(
        run_id=uuid4(),
        run_created_at=NOW - timedelta(minutes=age_minutes),
        status=status,
    )


class TestCategorizeFailure:
    def test_known_flaky_wins_over_persistent(self):
        # 优先级 known_flaky > persistent：即使最近 3 次全失败也归 flaky。
        prior = [_observation("failed"), _observation("failed"), _observation("failed")]
        assert categorize_failure(
            case_key=("s", "n"), flaky_keys={("s", "n")}, prior_rows=prior
        ) == "known_flaky"

    def test_persistent_requires_three_consecutive_failures(self):
        prior = [_observation("failed"), _observation("error"), _observation("failed")]
        assert categorize_failure(
            case_key=("s", "n"), flaky_keys=set(), prior_rows=prior
        ) == "persistent"

    def test_two_failures_only_is_new(self):
        # 不足 3 次历史观测 → 不满足 persistent 定义，归 new。
        prior = [_observation("failed"), _observation("failed")]
        assert categorize_failure(
            case_key=("s", "n"), flaky_keys=set(), prior_rows=prior
        ) == "new"

    def test_last_passed_is_new(self):
        prior = [_observation("passed"), _observation("failed"), _observation("failed")]
        assert categorize_failure(
            case_key=("s", "n"), flaky_keys=set(), prior_rows=prior
        ) == "new"

    def test_no_history_is_new(self):
        assert categorize_failure(
            case_key=("s", "n"), flaky_keys=set(), prior_rows=[]
        ) == "new"


class TestBuildRunTriage:
    def test_three_categories_assigned(self):
        run = _run()
        flaky_case = _failed_result(name="test_flaky", error_message="flaky boom")
        persistent_case = _failed_result(name="test_stuck", error_message="stuck boom")
        new_case = _failed_result(name="test_fresh", error_message="fresh boom")
        prior_history = {
            ("tests.unit.test_x", "test_flaky"): [_observation("passed")],
            ("tests.unit.test_x", "test_stuck"): [
                _observation("failed"), _observation("failed"), _observation("failed"),
            ],
        }
        response = build_run_triage(
            run=run,
            failed_results=[flaky_case, persistent_case, new_case],
            flaky_keys={("tests.unit.test_x", "test_flaky")},
            prior_history=prior_history,
            prior_counts={
                ("tests.unit.test_x", "test_flaky"): 1,
                ("tests.unit.test_x", "test_stuck"): 3,
            },
        )

        assert response.total_failed == 3
        assert [i.name for c in response.known_flaky for i in c.items] == ["test_flaky"]
        assert [i.name for c in response.persistent for i in c.items] == ["test_stuck"]
        assert [i.name for c in response.new for i in c.items] == ["test_fresh"]

    def test_same_signature_clustered(self):
        run = _run()
        a = _failed_result(name="test_a", error_message="AssertionError: expected 1 got 2")
        b = _failed_result(name="test_b", error_message="AssertionError: expected 3 got 7")
        c = _failed_result(name="test_c", error_message="TypeError: boom")
        response = build_run_triage(
            run=run,
            failed_results=[a, b, c],
            flaky_keys=set(),
            prior_history={},
            prior_counts={},
        )

        assert len(response.new) == 2
        # 组按数量降序：2 个同签名的 AssertionError 在前。
        first = response.new[0]
        assert first.count == 2
        assert first.signature == "AssertionError: expected <num> got <num>"
        assert [item.name for item in first.items] == ["test_a", "test_b"]
        assert response.new[1].count == 1

    def test_recent_history_ascending_with_current_run_last(self):
        run = _run()
        prior = [
            _observation("failed", age_minutes=10),   # 最新的历史观测
            _observation("passed", age_minutes=20),
            _observation("passed", age_minutes=30),   # 最旧
        ]
        case = _failed_result()
        response = build_run_triage(
            run=run,
            failed_results=[case],
            flaky_keys=set(),
            prior_history={(case.suite, case.name): prior},
            prior_counts={(case.suite, case.name): 3},
        )

        item = response.new[0].items[0]
        history = item.recent_history
        assert len(history) == 4
        # 升序（旧 → 新），最后一格是本次 run 的失败。
        assert [obs.status for obs in history] == ["passed", "passed", "failed", "failed"]
        assert history[-1].run_id == run.id
        timestamps = [obs.run_created_at for obs in history]
        assert timestamps == sorted(timestamps)

    def test_history_capped_at_ten_entries(self):
        run = _run()
        prior = [_observation("failed", age_minutes=i + 1) for i in range(20)]
        case = _failed_result()
        response = build_run_triage(
            run=run,
            failed_results=[case],
            flaky_keys=set(),
            prior_history={(case.suite, case.name): prior[:TRIAGE_HISTORY_LENGTH - 1]},
            prior_counts={(case.suite, case.name): 20},
        )

        item = response.persistent[0].items[0]
        assert len(item.recent_history) == TRIAGE_HISTORY_LENGTH

    def test_confidence_observing_below_threshold(self):
        run = _run()
        case = _failed_result()
        response = build_run_triage(
            run=run,
            failed_results=[case],
            flaky_keys=set(),
            prior_history={},
            prior_counts={},
        )
        item = response.new[0].items[0]
        assert item.observation_count == 1
        assert item.confidence == "observing"

    def test_confidence_established_at_threshold(self):
        run = _run()
        case = _failed_result()
        prior_count = TRIAGE_CONFIDENCE_MIN_OBSERVATIONS - 1  # 含本次正好到阈值
        response = build_run_triage(
            run=run,
            failed_results=[case],
            flaky_keys=set(),
            prior_history={
                (case.suite, case.name): [
                    _observation("failed", age_minutes=i + 1) for i in range(9)
                ]
            },
            prior_counts={(case.suite, case.name): prior_count},
        )
        item = response.persistent[0].items[0]
        assert item.observation_count == TRIAGE_CONFIDENCE_MIN_OBSERVATIONS
        assert item.confidence == "established"

    def test_no_message_failures_share_placeholder_cluster(self):
        run = _run()
        a = _failed_result(name="test_a", error_message=None)
        b = _failed_result(name="test_b", error_message=None)
        response = build_run_triage(
            run=run,
            failed_results=[a, b],
            flaky_keys=set(),
            prior_history={},
            prior_counts={},
        )
        assert len(response.new) == 1
        assert response.new[0].count == 2


def test_triage_history_cutoff_is_run_anchored():
    run = _run(created_at=NOW)
    assert triage_history_cutoff(run) == NOW - timedelta(days=TRIAGE_WINDOW_DAYS)


# --------------------------------------------------------------------------- #
# 端点层：mock repos + ASGI client 走完整 HTTP 路径
# --------------------------------------------------------------------------- #


def _make_endpoint_run(tenant_id):
    from qaplatform.infra.database.models import RunStatusEnum

    run = MagicMock()
    run.id = uuid4()
    run.tenant_id = tenant_id
    run.project_id = uuid4()
    run.status = RunStatusEnum.FAILED
    run.created_at = NOW
    return run


@pytest.fixture
def mock_repos():
    repos = MagicMock()
    repos.run = AsyncMock()
    repos.project = AsyncMock()
    repos.test_result = AsyncMock()
    repos.audit = AsyncMock()
    repos.quarantine = AsyncMock()
    repos.quarantine.list_keys = AsyncMock(return_value=set())
    return repos


@pytest.fixture
def tenant_id():
    return uuid.uuid4()


@pytest.fixture
def mock_user(tenant_id):
    user = MagicMock()
    user.user_id = str(uuid.uuid4())
    user.role = "platform_admin"
    user.tenant_id = tenant_id
    return user


@pytest.fixture
async def app(mock_repos, mock_user):
    from qaplatform.api.deps import _get_db_session, _get_repos, get_current_user
    from qaplatform.main import create_app

    container = MagicMock()
    container.redis_client = None
    app = create_app(container=container)

    async def _override_repos():
        return mock_repos

    async def _override_user():
        return mock_user

    async def _override_session():
        yield MagicMock()

    app.dependency_overrides[_get_repos] = _override_repos
    app.dependency_overrides[get_current_user] = _override_user
    app.dependency_overrides[_get_db_session] = _override_session
    return app


@pytest.fixture
async def client(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


_AUTH = {"Authorization": "Bearer fake"}


@pytest.mark.asyncio
async def test_triage_endpoint_run_not_found(client, mock_repos):
    mock_repos.run.get_for_tenant.return_value = None
    resp = await client.get(f"/api/v1/runs/{uuid4()}/triage", headers=_AUTH)
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_triage_endpoint_empty_run_short_circuits(
    client, mock_repos, tenant_id
):
    run = _make_endpoint_run(tenant_id)
    mock_repos.run.get_for_tenant.return_value = run
    mock_repos.test_result.list_failed_by_run.return_value = []

    resp = await client.get(f"/api/v1/runs/{run.id}/triage", headers=_AUTH)

    assert resp.status_code == 200
    assert resp.json() == {
        "run_id": str(run.id),
        "total_failed": 0,
        "new": [],
        "known_flaky": [],
        "persistent": [],
    }
    # 无失败时不应触发 flaky / 历史查询。
    mock_repos.test_result.list_flaky_tests.assert_not_awaited()
    (
        mock_repos.test_result.list_prior_observations_for_failed_cases
    ).assert_not_awaited()


@pytest.mark.asyncio
async def test_triage_endpoint_categorizes_and_passes_window_params(
    client, mock_repos, tenant_id
):
    run = _make_endpoint_run(tenant_id)
    flip = SimpleNamespace(
        suite="tests.unit.test_x", name="test_flip", status="failed",
        duration_ms=5, error_message="boom 1", stack_trace="tb",
    )
    fresh = SimpleNamespace(
        suite="tests.unit.test_x", name="test_fresh", status="error",
        duration_ms=7, error_message=None, stack_trace=None,
    )
    mock_repos.run.get_for_tenant.return_value = run
    mock_repos.test_result.list_failed_by_run.return_value = [flip, fresh]
    mock_repos.test_result.list_flaky_tests.return_value = (
        [SimpleNamespace(suite="tests.unit.test_x", name="test_flip")],
        1,
    )
    prior = SimpleNamespace(
        run_id=uuid4(),
        run_created_at=run.created_at - timedelta(hours=1),
        status="passed",
    )
    (
        mock_repos.test_result.list_prior_observations_for_failed_cases
    ).return_value = (
        {("tests.unit.test_x", "test_flip"): [prior]},
        {("tests.unit.test_x", "test_flip"): 1},
    )

    resp = await client.get(f"/api/v1/runs/{run.id}/triage", headers=_AUTH)

    assert resp.status_code == 200
    body = resp.json()
    assert body["total_failed"] == 2
    assert [i["name"] for c in body["known_flaky"] for i in c["items"]] == [
        "test_flip"
    ]
    assert [i["name"] for c in body["new"] for i in c["items"]] == ["test_fresh"]
    flip_item = body["known_flaky"][0]["items"][0]
    assert flip_item["observation_count"] == 2
    assert [obs["status"] for obs in flip_item["recent_history"]] == [
        "passed", "failed",
    ]

    # 窗口参数与 analytics flaky 端点默认一致；cutoff 锚定 run.created_at。
    flaky_kwargs = mock_repos.test_result.list_flaky_tests.await_args.kwargs
    assert flaky_kwargs["min_runs"] == TRIAGE_FLAKY_MIN_RUNS
    assert flaky_kwargs["limit"] == TRIAGE_FLAKY_SCAN_LIMIT
    assert flaky_kwargs["cutoff"] == run.created_at - timedelta(
        days=TRIAGE_WINDOW_DAYS
    )
    prior_kwargs = (
        mock_repos.test_result.list_prior_observations_for_failed_cases
    ).await_args.kwargs
    assert prior_kwargs["before_created_at"] == run.created_at
    assert prior_kwargs["before_run_id"] == run.id
    assert prior_kwargs["per_case_limit"] == TRIAGE_HISTORY_LENGTH - 1
