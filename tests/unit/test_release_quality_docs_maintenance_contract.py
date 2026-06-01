from __future__ import annotations

from pathlib import Path

from tests.unit.release_quality_contract_helpers import (
    _contract_maintenance_counts,
    _quality_ops_row,
    _read,
)


ROOT = Path(__file__).resolve().parents[2]
CONTRACT_HELPERS = ROOT / "tests" / "unit" / "release_quality_contract_helpers.py"
CONTRACT_PATHS = (
    Path("tests/unit/test_release_quality_docs_contract.py"),
    Path("tests/unit/test_release_quality_docs_maintenance_contract.py"),
    Path("tests/unit/test_release_quality_docs_runtime_external_index_contract.py"),
    Path("tests/unit/test_release_quality_notification_channels_contract.py"),
    Path("tests/unit/test_release_quality_performance_contract.py"),
    Path("tests/unit/test_release_quality_worker_external_stack_contract.py"),
    Path("tests/unit/test_release_quality_real_auth_results_contract.py"),
    Path("tests/unit/test_release_quality_auth_contract.py"),
    Path("tests/unit/test_release_quality_run_api_contract.py"),
    Path("tests/unit/test_release_quality_runtime_scheduler_contract.py"),
    Path("tests/unit/test_release_quality_worker_notifications_contract.py"),
    Path("tests/unit/test_release_quality_worker_lifecycle_contract.py"),
    Path("tests/unit/test_release_quality_git_source_contract.py"),
    Path("tests/unit/test_release_quality_api_integration_contract.py"),
    Path("tests/unit/test_release_quality_project_surface_contract.py"),
    Path("tests/unit/test_release_quality_docs_status_contract.py"),
    Path("tests/unit/test_release_quality_docs_current_gate_contract.py"),
    Path("tests/unit/test_release_quality_executor_engine_contract.py"),
    Path("tests/unit/test_release_quality_plugin_runner_contract.py"),
    Path("tests/unit/test_release_quality_release_gate_contract.py"),
    Path("tests/unit/test_release_quality_resource_api_contract.py"),
    Path("tests/unit/test_release_quality_audit_contract.py"),
    Path("tests/unit/test_release_quality_pipeline_repository_contract.py"),
    Path("tests/unit/test_release_quality_frontend_contract.py"),
    Path("tests/unit/test_release_quality_api_guardrails_contract.py"),
    Path("tests/unit/test_release_quality_observability_contract.py"),
    Path("tests/unit/test_release_quality_analytics_contract.py"),
    Path("tests/unit/test_release_quality_migration_contract.py"),
)
QUALITY_GATE_ROW_PREFIX = (
    "| 2026-06-01 | N/A（质量门禁维护分层 / release-quality helper 收敛）"
)
HELPER_API_MARKERS = (
    "@lru_cache(maxsize=None)",
    "def _read(path: Path) -> str:",
    "def _quality_ops_row(prefix: str, *, contains: str | None = None) -> str:",
    "def _quality_ops_row_containing(*needles: str) -> str:",
    "def _quality_ops_rows_containing(*needle_groups: str | tuple[str, ...]) -> str:",
    "def _contract_maintenance_counts(*contract_sources: str) -> dict[str, int]:",
    "def _after(text: str, marker: str) -> str:",
    "def _before(text: str, marker: str) -> str:",
    "def _block_between(text: str, start: str, end: str) -> str:",
    "def _marked_block(text: str, start: str, end: str) -> str:",
    "def _marked_block_or_tail(text: str, start: str, end: str) -> str:",
    "def _test_block(",
    "def _notification_channel_sections(channels_test: str) -> dict[str, str]:",
    "def _notification_channel_http_case_blocks(channels_test: str) -> dict[str, str]:",
)
MAINTENANCE_ROW_MARKERS = (
    "release quality docs maintenance contract targeted 2 passed",
    "`_read` 加缓存",
    "`_quality_ops_row` / `_quality_ops_row_containing` / `_quality_ops_rows_containing` / `_test_block` / `_block_between` / `_after` / `_marked_block` / `_marked_block_or_tail`",
    "通用 helper 移入 `tests/unit/release_quality_contract_helpers.py`",
    "self-check AST 计数收敛到 `_contract_maintenance_counts`",
    "scheduler/frontend/retry/SQL follow-up 契约继续切到共享 helper",
    "65 个只切台账行契约改用 `_quality_ops_row`",
    "40 个复杂 row/direct/helper 台账切片也改用 `_quality_ops_row`",
    "471 个 helper 外 direct `.read_text(...)` 调用统一改用 `_read(...)`",
    "224 个 quality-ops `next(line...)` 查行统一改用 `_quality_ops_row`",
    "145 个双边界 `.split(...)[1].split(...)[0]` 切片统一改用 `_block_between`",
    "13 个单边界 `.split(..., 1)[1]` 切片统一改用 `_after`",
    "446 个 `.index`/`.find` 手工区块定位统一改用 `_marked_block`/`_marked_block_or_tail`",
    "158 个 helper 外 `_read(QUALITY_OPS)` 整表读取改用 `_quality_ops_row_containing`",
    "9 个多行 quality-ops 台账拼接改用 `_quality_ops_rows_containing`",
    "helper 外 `_read(QUALITY_OPS)` 调用上限下调到 0",
    "helper 外 `.index`/`.find` 调用上限下调到 0",
    "剩余 `QUALITY_OPS` 读取统一走缓存 `_read(QUALITY_OPS)`",
    "旧式 direct `QUALITY_OPS.read_text` / `row_start` 模式上限下调为 0/0",
    'helper 外 direct `.read_text(encoding="utf-8")` 上限固定为 0',
    "继续复制 `read_text`、`next(line...)`、`split(...)[1]`",
    "后续新增门禁先合并同类、优先复用 helper",
)
LEGACY_TEXT_PATTERNS = (
    "QUALITY_OPS." + 'read_text(encoding="utf-8")',
    "\n    row_start = quality_ops." + "index(",
    "\n    direct_row_start = quality_ops." + "index(",
    "\n    helper_row_start = quality_ops." + "index(",
)
EXPECTED_MAINTENANCE_COUNTS = {
    "direct_read_calls": 1,
    "direct_next_calls": 1,
    "manual_block_split_slices": 0,
    "manual_single_split_slices": 0,
    "manual_index_find_calls": 0,
    "quality_ops_join_assignments": 0,
    "quality_ops_read_calls": 0,
}


def _maintenance_sources() -> list[str]:
    return [_read(CONTRACT_HELPERS), *(_read(ROOT / path) for path in CONTRACT_PATHS)]


def test_quality_gate_helper_api_is_documented_and_available():
    helper_source = _read(CONTRACT_HELPERS)
    row = _quality_ops_row(QUALITY_GATE_ROW_PREFIX)

    for marker in HELPER_API_MARKERS:
        assert marker in helper_source
    for marker in MAINTENANCE_ROW_MARKERS:
        assert marker in row
    assert 'return path.read_text(encoding="utf-8")' in helper_source


def test_quality_gate_static_maintenance_limits_are_zeroed():
    maintenance_sources = _maintenance_sources()
    maintenance_source = "\n".join(maintenance_sources)

    for legacy_pattern in LEGACY_TEXT_PATTERNS:
        assert maintenance_source.count(legacy_pattern) == 0
    assert _contract_maintenance_counts(*maintenance_sources) == (
        EXPECTED_MAINTENANCE_COUNTS
    )
