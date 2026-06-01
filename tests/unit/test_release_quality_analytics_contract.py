from __future__ import annotations

from pathlib import Path

from tests.unit.release_quality_contract_helpers import (
    _quality_ops_row_containing,
    _read,
)


ROOT = Path(__file__).resolve().parents[2]
ANALYTICS_TEST = ROOT / "tests" / "unit" / "test_api" / "test_analytics.py"


def test_quality_ops_capture_analytics_success_exact_kwargs_cutoff_window_contract():
    row = _quality_ops_row_containing(
        "Analytics success exact kwargs/cutoff window 契约"
    )
    analytics_test = _read(ANALYTICS_TEST)

    assert "Analytics success exact kwargs/cutoff window 契约" in row
    assert (
        "`tests/unit/test_api/test_analytics.py::test_trends_success_uses_project_rbac_and_repository_pagination tests/unit/test_api/test_analytics.py::test_flaky_success_uses_project_rbac_and_repository_filters tests/unit/test_api/test_analytics.py::test_test_history_success_uses_project_rbac_and_repository_filters` 3 passed"
        in row
    )
    assert "analytics API full 6 passed" in row
    assert "release quality docs contract full 181 passed" in row
    assert "通过 4 元组解包固定 `RUN_READ` 权限完整调用、仓储 kwargs 字段集合、零 positional args" in (
        row
    )
    assert "`days=7/21/14` 的 timezone-aware cutoff" in row
    assert "仓储调用仍逐字段抽查，cutoff 只看 `tzinfo`" in row
    assert "RBAC helper 还靠 `len(args) == 4` 证明参数数目" in row
    assert "cutoff 没减 days、额外/缺失 kwargs、RBAC 调错 action 或参数顺序" in (
        row
    )
    assert "analytics API success path 只证明“响应体来自 mock 且仓储大概被调用”" in (
        row
    )

    assert "from datetime import date, datetime, timedelta, timezone" in analytics_test
    assert "from qaplatform.api.auth.permissions import Action" in analytics_test
    assert "def _assert_cutoff_window(" in analytics_test
    assert "assert cutoff.tzinfo is timezone.utc" in analytics_test
    assert "started_at - timedelta(days=days) <= cutoff <= finished_at - timedelta(" in (
        analytics_test
    )
    assert "def _assert_run_read_enforced(" in analytics_test
    assert "assert enforce_project_action.await_args.kwargs == {}" in analytics_test
    assert "_session, enforced_user, enforced_project_id, enforced_action = (" in (
        analytics_test
    )
    assert "enforce_project_action.await_args.args" in analytics_test
    assert "assert enforced_user is user" in analytics_test
    assert "assert enforced_project_id == project_id" in analytics_test
    assert "assert enforced_action is Action.RUN_READ" in analytics_test
    assert "assert len(enforce_project_action.await_args.args) == 4" not in (
        analytics_test
    )

    for expected in [
        "request_started = datetime.now(timezone.utc)",
        "request_finished = datetime.now(timezone.utc)",
        "assert mock_repos.run.list_trend_points.await_args.args == ()",
        "assert mock_repos.test_result.list_flaky_tests.await_args.args == ()",
        "assert mock_repos.test_result.list_test_history.await_args.args == ()",
        'trend_cutoff = trend_kwargs.pop("cutoff")',
        'flaky_cutoff = flaky_kwargs.pop("cutoff")',
        'history_cutoff = list_kwargs.pop("cutoff")',
        "_assert_cutoff_window(",
        "days=7,",
        "days=21,",
        "days=14,",
        "started_at=request_started,",
        "finished_at=request_finished,",
    ]:
        assert expected in analytics_test

    for expected in [
        'assert trend_kwargs == {"project_id": project_id, "offset": 5, "limit": 25}',
        '"min_runs": 4',
        '"suite": "checkout"',
        '"name": "test_payment"',
        '"offset": 20',
        '"limit": 10',
    ]:
        assert expected in analytics_test

    assert 'assert trend_kwargs["project_id"] == project_id' not in analytics_test
    assert 'assert flaky_kwargs["min_runs"] == 4' not in analytics_test
    assert 'assert list_kwargs["suite"] == "checkout"' not in analytics_test
    assert 'assert list_kwargs["cutoff"].tzinfo is timezone.utc' not in analytics_test
    assert "assert enforce_args[3].value == \"run.read\"" not in analytics_test
