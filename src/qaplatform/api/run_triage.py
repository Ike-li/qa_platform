"""失败分诊（T12）：把 run 内的失败归入 新增失败 / 已知 flaky / 持续失败。

判定优先级 known_flaky > persistent > new：
- ``known_flaky``：命中现有 flaky 判定（复用 ``list_flaky_tests``，窗口
  参数与 analytics flaky 端点默认一致：30 天 / min_runs=3）。
- ``persistent``：本 run 之前同项目最近 3 次观测全部 failed/error。
- ``new``：其余（上次观测 passed，或无历史）。

历史口径与 analytics 一致：project 级按 (suite, name) 聚合（经
``analytics_run_filters``），不按 pipeline 切分。窗口锚定 run 的
created_at（前 30 天）而非查询时刻，保证分诊结论不随查看时间漂移。
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from qaplatform.api.schemas import (
    RunTriageResponse,
    TriageCluster,
    TriageItem,
    TriageObservation,
)
from qaplatform.domain.services.triage import failure_signature
from qaplatform.infra.database.models import Run, TestResult, TestResultStatusEnum

# 与 analytics flaky 端点的默认窗口参数保持一致（days=30, min_runs=3）。
TRIAGE_WINDOW_DAYS = 30
TRIAGE_FLAKY_MIN_RUNS = 3
# flaky 判定取全量：list_flaky_tests 带分页，用大 limit 一次取齐。
TRIAGE_FLAKY_SCAN_LIMIT = 100_000
# persistent = 本 run 之前最近 3 次观测全部失败。
TRIAGE_PERSISTENT_STREAK = 3
# 履历迷你条 10 格（含本次）；批量历史查询因此取本 run 之前最多 9 条。
TRIAGE_HISTORY_LENGTH = 10
# 观测次数（含本次）低于该值时 confidence 为 observing。
TRIAGE_CONFIDENCE_MIN_OBSERVATIONS = 10

_FAILED_STATUS_VALUES = frozenset({
    TestResultStatusEnum.FAILED.value,
    TestResultStatusEnum.ERROR.value,
})


def _status_value(status: Any) -> str:
    return status.value if isinstance(status, TestResultStatusEnum) else str(status)


def categorize_failure(
    *,
    case_key: tuple[str, str],
    flaky_keys: set[tuple[str, str]],
    prior_rows: list[Any],
) -> str:
    """单个失败用例的三类归类（prior_rows 按时间降序，最新在前）。"""
    if case_key in flaky_keys:
        return "known_flaky"
    streak = prior_rows[:TRIAGE_PERSISTENT_STREAK]
    if len(streak) == TRIAGE_PERSISTENT_STREAK and all(
        _status_value(row.status) in _FAILED_STATUS_VALUES for row in streak
    ):
        return "persistent"
    return "new"


def triage_history_cutoff(run: Run):
    """分诊历史窗口下界：run 创建时刻前 TRIAGE_WINDOW_DAYS 天。"""
    return run.created_at - timedelta(days=TRIAGE_WINDOW_DAYS)


def build_run_triage(
    *,
    run: Run,
    failed_results: list[TestResult],
    flaky_keys: set[tuple[str, str]],
    prior_history: dict[tuple[str, str], list[Any]],
    prior_counts: dict[tuple[str, str], int],
    quarantined: set[tuple[str, str]] | None = None,
) -> RunTriageResponse:
    """组装 triage 响应：归类 → 同签名聚类 → 附履历与置信度。"""
    items_by_category: dict[str, list[TriageItem]] = {
        "new": [],
        "known_flaky": [],
        "persistent": [],
    }
    quarantine_set = quarantined or set()
    for result in failed_results:
        key = (result.suite, result.name)
        prior_rows = prior_history.get(key, [])
        category = categorize_failure(
            case_key=key, flaky_keys=flaky_keys, prior_rows=prior_rows
        )
        observation_count = prior_counts.get(key, 0) + 1

        history = [
            TriageObservation(
                run_id=row.run_id,
                run_created_at=row.run_created_at,
                status=_status_value(row.status),
            )
            for row in reversed(prior_rows[: TRIAGE_HISTORY_LENGTH - 1])
        ]
        history.append(
            TriageObservation(
                run_id=run.id,
                run_created_at=run.created_at,
                status=_status_value(result.status),
            )
        )

        items_by_category[category].append(
            TriageItem(
                suite=result.suite,
                name=result.name,
                status=_status_value(result.status),
                duration_ms=result.duration_ms,
                error_message=result.error_message,
                stack_trace=result.stack_trace,
                category=category,
                confidence=(
                    "observing"
                    if observation_count < TRIAGE_CONFIDENCE_MIN_OBSERVATIONS
                    else "established"
                ),
                observation_count=observation_count,
                quarantined=key in quarantine_set,
                recent_history=history,
            )
        )

    return RunTriageResponse(
        run_id=run.id,
        total_failed=len(failed_results),
        new=_cluster_by_signature(items_by_category["new"]),
        known_flaky=_cluster_by_signature(items_by_category["known_flaky"]),
        persistent=_cluster_by_signature(items_by_category["persistent"]),
    )


def _cluster_by_signature(items: list[TriageItem]) -> list[TriageCluster]:
    """同签名折叠为一组；组按数量降序、签名升序，组内保持用例名序。"""
    grouped: dict[str, list[TriageItem]] = {}
    for item in items:
        grouped.setdefault(failure_signature(item.error_message), []).append(item)
    return [
        TriageCluster(signature=signature, count=len(members), items=members)
        for signature, members in sorted(
            grouped.items(), key=lambda entry: (-len(entry[1]), entry[0])
        )
    ]
