from __future__ import annotations

from pathlib import Path

from tests.unit.release_quality_contract_helpers import (
    _after,
    _block_between,
    _quality_ops_row_containing,
    _read,
)


ROOT = Path(__file__).resolve().parents[2]
README = ROOT / "README.md"
ARCHITECTURE = ROOT / "docs" / "architecture.md"
BACKEND_TEST_AUDIT = ROOT / "docs" / "backend-test-audit.md"
DOC_CONFLICT_AUDIT = ROOT / "docs" / "archive" / "doc-conflict-audit.md"
RELEASE_SLICES = ROOT / "docs" / "release-quality-review-slices.md"
TESTING_STRATEGY = ROOT / "docs" / "testing-strategy.md"
TODO = ROOT / "docs" / "TODO.md"
FEATURE_CATALOG = ROOT / "docs" / "feature-catalog.md"
CANCEL_E2E = ROOT / "tests" / "integration" / "test_cancel_e2e.py"
TASKS_README = ROOT / "docs" / "tasks" / "README.md"
T02_AUDIT_QUERY = ROOT / "docs" / "tasks" / "T02_audit_query_api.md"
T06_WEBHOOK_BRANCH_DEDUP = ROOT / "docs" / "tasks" / "T06_webhook_branch_dedup.md"
T07_TEST_RESULTS_FILTER = ROOT / "docs" / "tasks" / "T07_test_results_filter.md"


def test_release_review_slices_do_not_claim_unrecorded_remote_success():
    text = _read(RELEASE_SLICES)
    remote_evidence = _block_between(text, "## Remote Evidence", "## QA Sign-Off And Post-Merge")

    assert "Sign-off requirement: all jobs pass" in remote_evidence
    assert "Required release evidence markers" in remote_evidence
    assert "Required backend integration gate evidence" in remote_evidence
    assert "required integration: 161 tests, 0 skipped" in remote_evidence
    assert "required integration: 147 tests, 0 skipped" not in remote_evidence
    assert "Result: all jobs passed" not in remote_evidence
    assert "latest release candidate evidence reported zero skipped tests" not in text




def test_release_review_slices_reflect_current_oom_signoff_gap():
    row = _quality_ops_row_containing(
        "release_candidate 完整发版门仍需 CI Linux 环境补 OOM 零 skip 证据"
    )
    release_slices = _read(RELEASE_SLICES)

    assert "release_candidate 完整发版门仍需 CI Linux 环境补 OOM 零 skip 证据" in row
    assert "Linux CI release candidate evidence must record zero skipped tests" in release_slices
    assert "local macOS OOM-gated runs do not satisfy" in release_slices




def test_backend_test_audit_reflects_current_local_baselines():
    text = _read(BACKEND_TEST_AUDIT)
    coverage_section = _block_between(text, "当前基线结果（2026-05-30 复核）：", "真实 DB / API 集成验证：")
    integration_section = _block_between(text, "当前结果（2026-05-30 复核）：", "E2E 冒烟验证：")
    e2e_section = _block_between(text, "E2E 冒烟验证：", "关键补强模块：")

    assert "单元测试：1379 passed" in coverage_section
    assert "qap-coverage-after-default-string-config-contracts.json" in text
    assert "qap-coverage-after-trusted-proxies-config-contracts.json" not in text
    assert "qap-coverage-after-numeric-config-contracts.json" not in text
    assert "qap-coverage-after-log-config-contracts.json" not in text
    assert "qap-coverage-after-required-config-blank-contracts.json" not in text
    assert "qap-coverage-after-encryption-keys-rotation-contracts.json" not in text
    assert "qap-coverage-after-env-vars-truncated-ciphertext-contracts.json" not in text
    assert "qap-coverage-after-go-helper-malformed-elapsed-contracts.json" not in text
    assert "qap-coverage-after-go-runner-malformed-event-contracts.json" not in text
    assert "qap-coverage-after-runner-blank-path-contracts.json" not in text
    assert "qap-coverage-after-runner-test-path-contracts.json" not in text
    assert "qap-coverage-after-git-url-scheme-contracts.json" not in text
    assert "qap-coverage-after-git-rev-parse-contracts.json" not in text
    assert "qap-coverage-after-git-non-public-url-contracts.json" not in text
    assert "qap-coverage-after-runner-junit-parent-contracts.json" not in text
    assert "qap-coverage-after-junit-duration-contracts.json" not in text
    assert "qap-coverage-after-notification-json-object-contracts.json" not in (
        text
    )
    assert "qap-coverage-after-admin-status-terminal-denominator-contracts.json" not in (
        text
    )
    assert "qap-coverage-after-webhook-url-userinfo-contracts.json" not in (
        text
    )
    assert "总覆盖率：87.63%" in coverage_section
    assert "语句覆盖率：89.56%" in coverage_section
    assert "分支覆盖率：79.20%" in coverage_section
    assert "单元测试：1372 passed" not in coverage_section
    assert "单元测试：1368 passed" not in coverage_section
    assert "单元测试：1349 passed" not in coverage_section
    assert "总覆盖率：87.58%" not in coverage_section
    assert "总覆盖率：87.60%" not in coverage_section
    assert "单元测试：1345 passed" not in coverage_section
    assert "单元测试：1339 passed" not in coverage_section
    assert "单元测试：1332 passed" not in coverage_section
    assert "单元测试：1329 passed" not in coverage_section
    assert "单元测试：1328 passed" not in coverage_section
    assert "总覆盖率：87.52%" not in coverage_section
    assert "单元测试：1323 passed" not in coverage_section
    assert "总覆盖率：87.50%" not in coverage_section
    assert "语句覆盖率：89.45%" not in coverage_section
    assert "分支覆盖率：78.89%" not in coverage_section
    assert "单元测试：1313 passed" not in coverage_section
    assert "总覆盖率：87.49%" not in coverage_section
    assert "分支覆盖率：78.86%" not in coverage_section
    assert "单元测试：1297 passed" not in coverage_section
    assert "总覆盖率：87.42%" not in coverage_section
    assert "语句覆盖率：89.41%" not in coverage_section
    assert "分支覆盖率：78.69%" not in coverage_section
    assert "单元测试：1295 passed" not in coverage_section
    assert "总覆盖率：87.44%" not in coverage_section
    assert "语句覆盖率：89.42%" not in coverage_section
    assert "分支覆盖率：78.72%" not in coverage_section
    assert "单元测试：1293 passed" not in coverage_section
    assert "总覆盖率：87.40%" not in coverage_section
    assert "语句覆盖率：89.37%" not in coverage_section
    assert "分支覆盖率：78.73%" not in coverage_section
    assert "单元测试：1289 passed" not in coverage_section
    assert "总覆盖率：87.41%" not in coverage_section
    assert "分支覆盖率：78.75%" not in coverage_section
    assert "单元测试：1287 passed" not in coverage_section
    assert "总覆盖率：87.38%" not in coverage_section
    assert "语句覆盖率：89.35%" not in coverage_section
    assert "单元测试：1282 passed" not in coverage_section
    assert "总覆盖率：87.36%" not in coverage_section
    assert "语句覆盖率：89.33%" not in coverage_section
    assert "分支覆盖率：78.66%" not in coverage_section
    assert "单元测试：1280 passed" not in coverage_section
    assert "总覆盖率：87.35%" not in coverage_section
    assert "分支覆盖率：78.61%" not in coverage_section
    assert "单元测试：1279 passed" not in coverage_section
    assert "总覆盖率：87.34%" not in coverage_section
    assert "分支覆盖率：78.59%" not in coverage_section
    assert "单元测试：1272 passed" not in coverage_section
    assert "总覆盖率：87.33%" not in coverage_section
    assert "语句覆盖率：89.32%" not in coverage_section
    assert "分支覆盖率：78.56%" not in coverage_section
    assert "单元测试：1269 passed" not in coverage_section
    assert "总覆盖率：87.32%" not in coverage_section
    assert "语句覆盖率：89.31%" not in coverage_section
    assert "分支覆盖率：78.54%" not in coverage_section
    assert "单元测试：1268 passed" not in coverage_section
    assert "单元测试：1267 passed" not in coverage_section
    assert "总覆盖率：87.28%" not in coverage_section
    assert "语句覆盖率：89.26%" not in coverage_section
    assert "单元测试：1263 passed" not in coverage_section
    assert "总覆盖率：87.14%" not in coverage_section
    assert "语句覆盖率：89.09%" not in coverage_section
    assert "单元测试：1255 passed" not in coverage_section
    assert "总覆盖率：86.80%" not in coverage_section
    assert "语句覆盖率：88.73%" not in coverage_section
    assert "分支覆盖率：78.25%" not in coverage_section
    assert "单元测试：1250 passed" not in coverage_section
    assert "总覆盖率：86.47%" not in coverage_section
    assert "语句覆盖率：88.51%" not in coverage_section
    assert "分支覆盖率：77.49%" not in coverage_section
    assert "单元测试：1247 passed" not in coverage_section
    assert "总覆盖率：86.45%" not in coverage_section
    assert "语句覆盖率：88.48%" not in coverage_section
    assert "单元测试：1246 passed" not in coverage_section
    assert "单元测试：1244 passed" not in coverage_section
    assert "总覆盖率：86.18%" not in coverage_section
    assert "语句覆盖率：88.28%" not in coverage_section
    assert "分支覆盖率：76.91%" not in coverage_section
    assert "单元测试：1242 passed" not in coverage_section
    assert "单元测试：1241 passed" not in coverage_section
    assert "单元测试：1239 passed" not in coverage_section
    assert "总覆盖率：86.17%" not in coverage_section
    assert "语句覆盖率：88.27%" not in coverage_section
    assert "分支覆盖率：76.88%" not in coverage_section
    assert "单元测试：1233 passed" not in coverage_section
    assert "总覆盖率：86.16%" not in coverage_section
    assert "语句覆盖率：88.26%" not in coverage_section
    assert "分支覆盖率：76.85%" not in coverage_section
    assert "总覆盖率：86.11%" not in coverage_section
    assert "语句覆盖率：88.23%" not in coverage_section
    assert "分支覆盖率：76.74%" not in coverage_section
    assert "单元测试：1226 passed" not in coverage_section
    assert "单元测试：1224 passed" not in coverage_section
    assert "总覆盖率：86.05%" not in coverage_section
    assert "语句覆盖率：88.14%" not in coverage_section
    assert "单元测试：1216 passed" not in coverage_section
    assert "总覆盖率：85.98%" not in coverage_section
    assert "语句覆盖率：88.10%" not in coverage_section
    assert "分支覆盖率：76.56%" not in coverage_section
    assert "单元测试：1215 passed" not in coverage_section
    assert "单元测试：1214 passed" not in coverage_section
    assert "单元测试：1213 passed" not in coverage_section
    assert "总覆盖率：85.96%" not in coverage_section
    assert "语句覆盖率：88.09%" not in coverage_section
    assert "分支覆盖率：76.51%" not in coverage_section
    assert "单元测试：1212 passed" not in coverage_section
    assert "总覆盖率：85.94%" not in coverage_section
    assert "语句覆盖率：88.08%" not in coverage_section
    assert "分支覆盖率：76.45%" not in coverage_section
    assert "单元测试：1211 passed" not in coverage_section
    assert "单元测试：1210 passed" not in coverage_section
    assert "单元测试：1209 passed" not in coverage_section
    assert "单元测试：1208 passed" not in coverage_section
    assert "单元测试：1202 passed" not in coverage_section
    assert "总覆盖率：85.88%" not in coverage_section
    assert "总覆盖率：85.84%" not in coverage_section
    assert "总覆盖率：85.80%" not in coverage_section
    assert "总覆盖率：85.75%" not in coverage_section
    assert "语句覆盖率：88.04%" not in coverage_section
    assert "语句覆盖率：88.01%" not in coverage_section
    assert "语句覆盖率：87.98%" not in coverage_section
    assert "语句覆盖率：87.96%" not in coverage_section
    assert "分支覆盖率：76.33%" not in coverage_section
    assert "分支覆盖率：76.21%" not in coverage_section
    assert "分支覆盖率：76.09%" not in coverage_section
    assert "分支覆盖率：75.97%" not in coverage_section
    assert "单元测试：1197 passed" not in coverage_section
    assert "总覆盖率：85.69%" not in coverage_section
    assert "语句覆盖率：87.90%" not in coverage_section
    assert "分支覆盖率：75.89%" not in coverage_section
    assert "单元测试：1195 passed" not in coverage_section
    assert "单元测试：1194 passed" not in coverage_section
    assert "总覆盖率：85.68%" not in coverage_section
    assert "语句覆盖率：87.89%" not in coverage_section
    assert "分支覆盖率：75.86%" not in coverage_section
    assert "单元测试：1190 passed" not in coverage_section
    assert "总覆盖率：85.65%" not in coverage_section
    assert "语句覆盖率：87.87%" not in coverage_section
    assert "分支覆盖率：75.80%" not in coverage_section
    assert "单元测试：1185 passed" not in coverage_section
    assert "总覆盖率：85.61%" not in coverage_section
    assert "语句覆盖率：87.83%" not in coverage_section
    assert "分支覆盖率：75.77%" not in coverage_section
    assert "单元测试：1184 passed" not in coverage_section
    assert "总覆盖率：85.59%" not in coverage_section
    assert "语句覆盖率：87.82%" not in coverage_section
    assert "分支覆盖率：75.74%" not in coverage_section
    assert "单元测试：1183 passed" not in coverage_section
    assert "总覆盖率：85.60%" not in coverage_section
    assert "分支覆盖率：75.78%" not in coverage_section
    assert "单元测试：1182 passed" not in coverage_section
    assert "总覆盖率：85.58%" not in coverage_section
    assert "语句覆盖率：87.80%" not in coverage_section
    assert "分支覆盖率：75.75%" not in coverage_section
    assert "单元测试：1174 passed" not in coverage_section
    assert "总覆盖率：85.56%" not in coverage_section
    assert "语句覆盖率：87.78%" not in coverage_section
    assert "分支覆盖率：75.72%" not in coverage_section
    assert "单元测试：1172 passed" not in coverage_section
    assert "总覆盖率：85.52%" not in coverage_section
    assert "语句覆盖率：87.75%" not in coverage_section
    assert "分支覆盖率：75.69%" not in coverage_section
    assert "总覆盖率：85.51%" not in coverage_section
    assert "语句覆盖率：87.74%" not in coverage_section
    assert "分支覆盖率：75.66%" not in coverage_section
    assert "单元测试：1171 passed" not in coverage_section
    assert "单元测试：1168 passed" not in coverage_section
    assert "单元测试：1164 passed" not in coverage_section
    assert "单元测试：1158 passed" not in coverage_section
    assert "单元测试：1154 passed" not in coverage_section
    assert "单元测试：1151 passed" not in coverage_section
    assert "单元测试：1149 passed" not in coverage_section
    assert "单元测试：1145 passed" not in coverage_section
    assert "单元测试：1143 passed" not in coverage_section
    assert "单元测试：1140 passed" not in coverage_section
    assert "单元测试：1137 passed" not in coverage_section
    assert "单元测试：1132 passed" not in coverage_section
    assert "单元测试：1130 passed" not in coverage_section
    assert "单元测试：1127 passed" not in coverage_section
    assert "单元测试：1122 passed" not in coverage_section
    assert "单元测试：1121 passed" not in coverage_section
    assert "单元测试：1110 passed" not in coverage_section
    assert "单元测试：1109 passed" not in coverage_section
    assert "单元测试：1108 passed" not in coverage_section
    assert "单元测试：1050 passed" not in coverage_section
    assert "总覆盖率：85.07%" not in coverage_section
    assert "语句覆盖率：87.39%" not in coverage_section
    assert "分支覆盖率：74.66%" not in coverage_section
    assert "单元测试：1049 passed" not in coverage_section
    assert "单元测试：980 passed" not in coverage_section
    assert "总覆盖率：84.71%" not in coverage_section

    assert "integration 收集：212 tests" in integration_section
    assert "PR/push 必跑 required integration：161 passed, 51 deselected" in integration_section
    assert "integration 收集：203 tests" not in integration_section
    assert "PR/push 必跑 required integration：152 passed, 51 deselected" not in integration_section
    assert "真实后端/worker-backed 主路径" in e2e_section
    assert "real-login-flow.spec.ts tests/e2e/real-run-trigger.spec.ts" in e2e_section
    assert "本轮并行复核 2 passed（35.0s）" in e2e_section
    assert "登录页初始 refresh 401 清 cookie" in e2e_section
    assert "trigger modal pipeline Select" in e2e_section
    assert "Select warning 已消除" in e2e_section




def test_architecture_reflects_github_provider_webhook_implementation():
    text = _read(ARCHITECTURE)

    assert "尚未实现 Git 平台事件类型解析与按 repo URL 匹配项目的 provider 级入口" not in text
    assert "POST /webhooks/github" in text
    assert "POST /api/v1/webhooks/github" in text
    assert "repository URL candidates" in text
    assert "GitLab/Gitee provider" in text




def test_architecture_reflects_audit_retention_cleanup_implementation():
    text = _read(ARCHITECTURE)

    assert "当前 `main` 只有配置项，尚未发现独立审计清理任务" not in text
    assert "cleanup_old_audit_events" in text
    assert "AuditEventRepository.delete_older_than()" in text
    assert "retention_audit_days" in text




def test_doc_conflict_audit_does_not_keep_resolved_audit_cleanup_as_decision():
    text = _read(DOC_CONFLICT_AUDIT)
    pending_section = _block_between(text, "### 17.1 仍需确认", "### 17.2 已决策 / 已实现承接")
    resolved_section = _after(text, "### 17.2 已决策 / 已实现承接")

    assert "独立审计日志清理任务已实现" not in pending_section
    assert "独立审计日志清理任务已实现" in resolved_section
    assert "是否需要实现独立的审计日志清理任务" not in text
    assert "当前配置有 `retention_audit_days=1095`，但本轮只发现执行记录清理 cron" not in text
    assert "worker `cleanup_old_audit_events` 已按 `retention_audit_days` 清理 `audit.event`" in text




def test_docs_reflect_audit_events_query_api_completion():
    architecture = _read(ARCHITECTURE)
    audit = _read(DOC_CONFLICT_AUDIT)
    task_index = _read(TASKS_README)
    t02 = _read(T02_AUDIT_QUERY)

    live_docs = "\n".join([architecture, task_index, t02])

    assert "`GET /api/v1/audit-events`" in architecture
    assert "audit_events.list" in architecture
    assert "`audit.read`" in architecture
    assert "查询路由待 T02 补齐" not in live_docs
    assert "新增 `src/qaplatform/api/v1/audit_events.py`" not in task_index
    assert "审计日志查询 API 验收档案" in task_index
    assert "| [T02_audit_query_api.md](T02_audit_query_api.md) | P0 / 已完成 |" in task_index

    assert "状态：已完成于 `main`" in t02
    assert "src/qaplatform/api/v1/audit_events.py" in t02
    assert "Action.AUDIT_READ" in t02
    assert "- [x] API token scope" in t02
    assert "当前 `Action` 枚举没有 `AUDIT_READ`" not in t02
    assert "新建 `src/qaplatform/api/v1/audit_events.py`" not in t02

    assert "T02 待办" not in audit
    assert "计划中的 `/api/v1/audit-events`" not in audit
    assert "4 个为 T02 `/api/v1/audit-events` 计划新增" not in audit
    assert "T02 已完成验收档案" in audit
    assert "正式 PRD 章节待补" in "\n".join([architecture, audit, t02])




def test_task_archives_reflect_webhook_and_result_filter_completion():
    task_index = _read(TASKS_README)
    doc_conflict_audit = _read(DOC_CONFLICT_AUDIT)
    t06 = _read(T06_WEBHOOK_BRANCH_DEDUP)
    t07 = _read(T07_TEST_RESULTS_FILTER)

    assert "Webhook 分支过滤 + 同 commit 去重验收档案" in task_index
    assert "测试结果 `status` / `suite` / `q` 组合过滤验收档案" in task_index
    assert "| [T06_webhook_branch_dedup.md](T06_webhook_branch_dedup.md) | P1 / 已完成 |" in task_index
    assert "| [T07_test_results_filter.md](T07_test_results_filter.md) | P0 / 已完成 |" in task_index

    assert "状态**：已完成于 `main`" in t06
    assert "`Project.settings.allowed_branches`" in t06
    assert "`Run.dedup_key`" in t06
    assert "tests/integration/test_webhook_branch_dedup.py" in t06
    assert "- [x] 同 commit 在活跃状态时再次 push" in t06
    assert "GitLab/Gitee、PR/fork 和 URL 规范化属于 F-EX-03 剩余增强" in t06
    assert "两项过滤都缺" not in t06
    assert "当前 `api/v1/webhooks.py` 仅做 HMAC-SHA256 签名验证" not in t06

    assert "状态**：已完成于 `main`" in t07
    assert "`GET /api/v1/runs/{run_id}/results` 支持 `status`、`suite`、`q`" in t07
    assert "src/qaplatform/api/v1/_filters.py::escape_like" in t07
    assert "tests/integration/test_real_auth_results_artifacts.py::test_run_results_api_filters_real_rows_and_recovers_after_duplicate" in t07
    assert "- [x] 多过滤参数可组合" in t07
    assert "只有 `status` 参数" not in t07
    assert "本任务只补 suite / q" not in t07

    assert "T07 已完成验收档案" in doc_conflict_audit
    assert "当前 `main` 仅 status" not in doc_conflict_audit
    assert "当前 `main` 尚未合入 T07" not in doc_conflict_audit
    assert "feature/T07-test-results-filter` 已推送但未合入" not in doc_conflict_audit




def test_todo_maintainer_decisions_separate_pending_from_resolved():
    text = _read(TODO)
    maintainer_section = _block_between(text, "### Maintainer 决策承接", "## 5. 当前范围不做")
    pending_section = _block_between(maintainer_section, "#### 仍需确认", "#### 已决策 / 已实现承接")
    resolved_section = _after(maintainer_section, "#### 已决策 / 已实现承接")

    assert "### Maintainer 决策待确认" not in text
    assert "是否需要独立审计日志清理任务" not in pending_section
    assert "Pipeline collector 配置是补实现" not in pending_section
    assert "F-NT-01 是否支持 OR / 连续失败条件" not in pending_section
    assert "F-EX-05 归档日志回看走流式 API 还是 artifact 复用" not in (
        pending_section
    )
    assert "T10 是否允许新增 OTLP HTTP exporter 依赖" in pending_section
    assert "是否需要 DB 行冷归档" in pending_section
    assert "是否需要独立审计日志清理任务" in resolved_section
    assert "F-NT-01 是否支持 OR / 连续失败条件" in resolved_section




def test_backlog_docs_distinguish_current_status_from_remaining_gaps():
    todo = _read(TODO)
    catalog = _read(FEATURE_CATALOG)

    assert "本文件按优先级排序验收状态、剩余缺口与不做范围" in todo
    assert "## 1. 高优先级 — PRD 验收状态与剩余必做项" in todo
    assert "## 1. 高优先级 — PRD 验收未达（必须做）" not in todo
    assert "| # | 项 | 来源 | 状态 / 剩余缺口 |" in todo

    assert "## 4. PRD 验收矩阵与待办（状态 + 剩余缺口）" in catalog
    assert "### 4.1 验收状态与剩余必做项" in catalog
    assert "### 4.1 未达 PRD 验收（必须做）" not in catalog
    assert "| ID / 项 | 必要性 | 当前状态 / 剩余缺口 | 备注 |" in catalog




def test_backlog_docs_reflect_project_search_sorting_completion():
    todo = _read(TODO)
    catalog = _read(FEATURE_CATALOG)

    assert "F-LS-03 项目搜索排序补齐 | PRD §3.7 验收 | 已完成" in todo
    assert "F-LS-03 | 项目搜索 | P1 | ✅" in catalog
    assert "当前搜索 name/description，默认仍按 `created_at desc`" not in catalog
    assert "结果仍按 `created_at desc`，缺名称字母序" not in todo




def test_backlog_docs_reflect_silent_windows_completion():
    todo = _read(TODO)
    catalog = _read(FEATURE_CATALOG)
    architecture = _read(ARCHITECTURE)
    audit = _read(DOC_CONFLICT_AUDIT)
    task = _read(ROOT / "docs" / "tasks" / "T05_silent_windows.md")

    assert "F-EX-02 | Cron 定时触发 | P1 | ✅" in catalog
    assert "F-EX-02 静默窗口 | PRD §3.3 验收 | 已完成" in todo
    assert "settings 当前承载 `webhook_secret`、`allowed_branches`、`silent_windows`" in architecture
    assert "`PUT /api/v1/projects/{project_id}` 接受 silent_windows" in task
    assert "- [x] cron tick 命中窗口" in task
    assert "T05 的 `Schedule.quiet_windows` 与 `Project.settings.silent_windows` 是否共存" not in audit
    assert "项目级\"静默窗口（发布冻结期）\"未实现" not in catalog
    assert "发布冻结期不触发 cron 的产品化入口仍未实现" not in todo
    assert "`silent_windows` 为 T05 计划写入同一 JSONB 的字段" not in architecture




def test_backlog_docs_reflect_single_test_history_completion():
    todo = _read(TODO)
    catalog = _read(FEATURE_CATALOG)
    audit = _read(DOC_CONFLICT_AUDIT)
    row = _quality_ops_row_containing(
        "RUN_INTEGRATION_TESTS=1 tests/integration/test_api_endpoints.py::TestAnalytics::test_get_test_history"
    )

    assert "F-RE-05 | 历史趋势 | P1 | ✅" in catalog
    assert "F-RE-05 单用例历史趋势补齐 | PRD §3.4 验收 | 已完成" in todo
    assert "/analytics/test-history" in catalog
    assert "run_created_at" in catalog
    assert "用例 status" in catalog
    assert "RUN_INTEGRATION_TESTS=1 tests/integration/test_api_endpoints.py::TestAnalytics" in row
    assert "单用例历史趋势 API / 前端入口存在" in audit
    assert "单个用例的历史趋势视图/API 未实现" not in catalog
    assert "缺单个用例历史趋势 API/视图" not in todo
    assert "单用例历史趋势仍缺" not in todo




def test_backlog_docs_reflect_worker_logging_completion():
    todo = _read(TODO)
    catalog = _read(FEATURE_CATALOG)

    assert "T-LOGGING | 已完成：结构化日志全局化" in todo
    assert "structlog（JSON 格式） | P1 | ✅" in catalog
    assert "worker/arq 入口未调用 `configure_logging`" not in todo
    assert "worker 入口未调用该配置" not in catalog




def test_backlog_docs_reflect_arch_layer_first_stage_completion():
    architecture = _read(ARCHITECTURE)
    todo = _read(TODO)
    audit = _read(DOC_CONFLICT_AUDIT)

    live_docs = "\n".join([architecture, todo])
    followup_section = _block_between(audit, "## 15. 后续建议拆分任务", "## 16.")

    assert "qaplatform.observability.metrics" in architecture
    assert "`engine/reclaim.py` 已直接使用 `engine.redact`" in architecture
    assert "ProjectRepository` / `ProjectMemberRepository`" in architecture
    assert "`RunRepository`" in architecture
    assert "`UserRepository` / `TenantRepository`" in architecture
    assert "tests/unit/test_architecture_boundaries.py" in live_docs
    assert "已完成：`engine` 不再反向依赖" in todo
    assert "`api/deps.py` 项目 RBAC 查询" in todo
    assert "`api/auth/middleware.py` 平台管理员复核" in todo
    assert "`api/v1/auth.py` 租户注册 / fallback 查询" in todo
    assert "`api/v1/runs.py` 成员项目过滤" in todo
    assert "`api/v1/analytics.py` 聚合查询" in todo
    assert "engine 反向依赖已收敛到 `observability.metrics` / `engine.redact`" in (
        followup_section
    )
    assert "`api/v1/analytics.py` 的 route 层直接查询已下沉到 repositories" in (
        followup_section
    )
    assert "未处理，已记录为技术债专项" not in followup_section
    assert "`api/v1/admin.py`、`api/v1/analytics.py`" not in architecture
    assert "`api/v1/runs.py` 和 `api/deps.py` 仍存在直接 SQLAlchemy 查询" not in (
        architecture
    )
    assert "`api/auth/middleware.py`、`api/v1/auth.py`、`api/v1/analytics.py`" not in architecture
    assert "剩余 `api/v1/analytics.py` 待下沉" not in followup_section
    assert "仍存在直接 SQLAlchemy 查询" not in architecture
    assert "局部 import `api.metrics.run_terminal_total`" not in architecture
    assert "通过 worker 兼容 shim 引用 `worker._redact.redact_url_userinfo`" not in (
        architecture
    )




def test_test_quality_docs_reflect_soft_deleted_run_state_write_guard():
    audit = _read(BACKEND_TEST_AUDIT)
    strategy = _read(TESTING_STRATEGY)
    row = _quality_ops_row_containing(
        "test_run_repository_state_writes_ignore_soft_deleted_runs"
    )

    assert "soft-deleted Run 状态/元数据写入 no-op" in audit
    assert "soft-deleted Run 的状态/队列/worker/git/execution 写入 no-op" in (
        strategy
    )
    assert "test_run_repository_state_writes_ignore_soft_deleted_runs" in row
    assert "soft-deleted run 保持原状态、worker/queue/git/execution 字段不被污染" in (
        row
    )




def test_test_quality_docs_reflect_soft_deleted_schedule_due_query_guard():
    audit = _read(BACKEND_TEST_AUDIT)
    strategy = _read(TESTING_STRATEGY)
    row = _quality_ops_row_containing(
        "test_schedule_repository_due_query_ignores_soft_deleted_schedules",
        "避免调度测试只是覆盖 worker 外壳",
    )

    assert "soft-deleted due Schedule 查询隔离" in audit
    assert "due query 只返回未删除且到期的 schedule" in strategy
    assert "test_schedule_repository_due_query_ignores_soft_deleted_schedules" in (
        row
    )
    assert "避免调度测试只是覆盖 worker 外壳" in row




def test_backlog_docs_reflect_opentelemetry_partial_implementation():
    readme = _read(ROOT / "README.md")
    architecture = _read(ARCHITECTURE)
    audit = _read(DOC_CONFLICT_AUDIT)
    todo = _read(TODO)
    catalog = _read(FEATURE_CATALOG)
    task_index = _read(ROOT / "docs" / "tasks" / "README.md")
    t10 = _read(ROOT / "docs" / "tasks" / "T10_opentelemetry.md")

    live_docs = "\n".join([readme, architecture, todo, catalog, task_index, t10])

    assert "OpenTelemetry 基础追踪装配已落地" in readme
    assert "基础追踪装配已实现" in architecture
    assert "基础装配已补" in todo
    assert "OpenTelemetry 追踪 | P2 | ⚠️" in catalog
    assert "src/qaplatform/observability/tracing.py" in catalog
    assert "setup_tracing" in catalog
    assert "instrument_fastapi" in catalog
    assert "instrument_infra" in catalog
    assert "tests/unit/test_observability/test_tracing.py" in catalog
    assert "OTLP HTTP exporter 依赖决策" in live_docs
    assert "接收端部署验证" in live_docs

    audit_t10_dependency_section = _block_between(audit, "### 4.3 T10 OpenTelemetry 缺 exporter 依赖", "### 4.4")
    audit_otel_progress_section = _block_between(audit, "### 9.7 OpenTelemetry 依赖描述不完整", "### 9.8")
    assert "T10 已从“新增 OpenTelemetry 基础装配”改为“OpenTelemetry 装配收口”" in (
        audit_t10_dependency_section
    )
    assert "OpenTelemetry 基础追踪装配已落地" in audit_otel_progress_section
    assert "OpenTelemetry 追踪待 T10 装配" not in audit_otel_progress_section

    assert "基础 OpenTelemetry 追踪已经落地" in t10
    assert "不要重复新增 `src/qaplatform/observability/tracing.py`" in t10
    assert "新增 `observability/tracing.py` + `main.py`" not in task_index
    assert "代码无 `TracerProvider` / `FastAPIInstrumentor` 装配" not in live_docs
    assert "缺 OTLP HTTP exporter 与 instrumentation 代码" not in live_docs
    assert "仅声明部分依赖，无 OTLP HTTP exporter" not in live_docs
    assert "OpenTelemetry 追踪待 T10 装配" not in live_docs




def test_doc_conflict_audit_reflects_manual_trigger_completion():
    audit = _read(DOC_CONFLICT_AUDIT)
    followup_section = _block_between(audit, "## 15. 后续建议拆分任务", "## 16.")

    assert (
        "| `T-MANUAL-TRIGGER` | 补齐 F-EX-01 手动触发参数与入队验收"
        in followup_section
    )
    assert "`RunTrigger` 接收 `pipeline_id` / `git_ref` / 40 位 `git_sha`" in (
        followup_section
    )
    assert "unit 锁住 run.create、queue/job id、mark_enqueued" in followup_section
    assert "一线入队 SLO 已进入 nightly/manual performance smoke" in followup_section
    assert "未处理，已记录为 PRD F-EX-01 缺口" not in followup_section




def test_backlog_docs_reflect_notification_template_partial_completion():
    todo = _read(TODO)
    catalog = _read(FEATURE_CATALOG)

    assert "`channels[].template` 每渠道覆盖" in catalog
    assert "project_name" in catalog
    assert "failed_tests" in catalog
    assert "把失败/错误用例名写入真实执行 summary" in catalog
    assert "F-NT-01 条件通知验收补齐 | PRD §3.5 验收 | 已完成" in todo
    assert "consecutive_failures" in todo
    assert "嵌套 `any`/`all` 条件组" in todo
    assert "OR 条件、连续失败次数" not in todo
    assert "真实执行 summary 自动填充失败用例名仍未实现" not in catalog
    assert "真实执行 summary 自动填充失败用例名" not in todo
    assert "当前仅状态/pass_rate/失败数 AND 条件和规则级基础变量模板" not in todo




def test_backlog_docs_reflect_notification_channels_completion():
    todo = _read(TODO)
    catalog = _read(FEATURE_CATALOG)

    assert "F-NT-02 多渠道通知 | PRD §8 | 已完成" in todo
    assert "F-NT-02 | 多渠道通知 | P1 | ✅" in catalog
    assert "DingTalk 自定义机器人" in todo
    assert "WeCom 群机器人" in catalog
    assert "钉钉/企业微信未实现" not in catalog
    assert "钉钉/企微仍缺" not in todo




def test_testing_docs_capture_notification_api_worker_contract():
    row = _quality_ops_row_containing(
        "API 创建的 notification rule 实际发送时拿到空 config",
        "历史脏 condition response 标记 invalid 而不是 500",
    )
    testing_strategy = _read(TESTING_STRATEGY)
    backend_audit = _read(BACKEND_TEST_AUDIT)

    assert "API 创建的 notification rule 实际发送时拿到空 config" in row
    assert "API 创建 notification rule 后 worker delivery 会使用 canonical channel config" in (
        testing_strategy
    )
    assert "notification channel 的 `NotificationChannelPayload`" in testing_strategy
    assert "API-created notification channel 会归一成 worker 可发送的 canonical `config`" in (
        backend_audit
    )
    assert "OpenAPI 也用 `NotificationChannelPayload` 暴露可校验字段" in backend_audit
    assert "condition typo 曾在 worker 中 warning 后返回 true" in row
    assert "OpenAPI condition schema 收紧到 canonical 字段/operator" in row
    assert "response-only `NotificationInvalidCondition`" in row
    assert "历史脏 condition response 标记 invalid 而不是 500" in row
    assert "通知条件 typo/未知 operator/未文档化 `consecutive_failed_runs` alias 会在 API 写入前 422" in (
        testing_strategy
    )
    assert "未文档化 `consecutive_failed_runs` alias 会在 API 写入前 422" in (
        testing_strategy
    )
    assert "response-only `NotificationInvalidCondition`" in testing_strategy
    assert "历史脏 condition 读接口会返回 response-only invalid 标记而不是 500" in (
        testing_strategy
    )
    assert "notification condition typo/未知 operator/未文档化 `consecutive_failed_runs` alias 会在 API 写入前 422" in backend_audit
    assert "`NotificationCondition*` 暴露 canonical 条件字段/operator" in backend_audit
    assert "worker 对历史脏条件 fail-closed" in backend_audit
    assert "`NotificationInvalidCondition` 标记历史脏 condition 而不是 500" in (
        backend_audit
    )




def test_testing_docs_capture_sse_missing_ticket_contract():
    row = _quality_ops_row_containing("SSE 缺失 ticket 统一返回 401")
    testing_strategy = _read(TESTING_STRATEGY)
    backend_audit = _read(BACKEND_TEST_AUDIT)

    assert "SSE 缺失 ticket 统一返回 401" in row
    assert "不调用 Redis" in row
    assert "缺失 ticket 401" in testing_strategy
    assert "缺失 ticket 固定返回 401 且不消费 Redis ticket" in backend_audit




def test_repeated_http_cancel_assertion_is_exact_terminal_conflict():
    cancel_e2e = _read(CANCEL_E2E)
    quality_ops = _quality_ops_row_containing("重复 HTTP cancel 第二次固定 409")
    testing_strategy = _read(TESTING_STRATEGY)
    backend_audit = _read(BACKEND_TEST_AUDIT)

    assert "status_code in {200, 409}" not in cancel_e2e
    assert "second.status_code == 409" in cancel_e2e
    assert "Run already in terminal status: cancelled" in cancel_e2e
    assert "重复 HTTP cancel 第二次固定 409" in quality_ops
    assert "重复 HTTP cancel 第二次固定 409" in testing_strategy
    assert "重复 HTTP cancel 第二次固定 409" in backend_audit




def test_testing_docs_capture_run_priority_validation_contract():
    quality_ops = _quality_ops_row_containing(
        "非法 run priority 422 会在请求体校验阶段短路"
    )
    testing_strategy = _read(TESTING_STRATEGY)
    backend_audit = _read(BACKEND_TEST_AUDIT)

    assert "非法 run priority 422 会在请求体校验阶段短路" in quality_ops
    assert "非法 run priority 请求体校验 422 且无 repository/audit 副作用" in (
        testing_strategy
    )
    assert "非法 run priority 请求体校验 422 且无 repository/audit 副作用" in (
        backend_audit
    )




def test_testing_docs_do_not_overclaim_generic_html_artifact_preview_e2e():
    feature_catalog = _read(FEATURE_CATALOG)
    testing_strategy = _read(TESTING_STRATEGY)
    backend_audit = _read(BACKEND_TEST_AUDIT)
    doc_conflict = _read(DOC_CONFLICT_AUDIT)
    todo = _read(TODO)

    assert "前端 Allure/HTML 预览主路径已有 E2E" not in feature_catalog
    assert "前端 run detail 已有 HTML artifact 预览 E2E" not in feature_catalog
    assert "HTML artifact 预览主路径已有 E2E" not in doc_conflict
    assert "前端 run detail 已补 HTML artifact 预览 E2E" not in todo
    assert "前端 Allure HTML 预览主路径已有 E2E" in feature_catalog
    assert "普通 `html`/`text/html` artifact 预览由前端契约测试锁住" in (
        feature_catalog
    )
    assert "Allure HTML artifact 预览" in testing_strategy
    assert "普通 HTML/report artifact 预览由前端契约测试覆盖" in testing_strategy
    assert "Allure HTML artifact 预览" in backend_audit
    assert "普通 HTML/report artifact 预览由前端契约测试覆盖" in backend_audit
    assert "前端 Allure HTML 预览有 E2E" in doc_conflict
    assert "普通 HTML/report 预览有前端契约" in doc_conflict
    assert "前端 Allure HTML 预览有 E2E，普通 HTML/report 预览由前端契约测试覆盖" in (
        todo
    )




def test_testing_docs_do_not_treat_printed_worker_secrets_as_unimplemented():
    feature_catalog = _read(FEATURE_CATALOG)
    todo = _read(TODO)
    quality_ops = _quality_ops_row_containing(
        "Worker stdout/stderr secret redaction 文档契约"
    )
    testing_strategy = _read(TESTING_STRATEGY)
    backend_audit = _read(BACKEND_TEST_AUDIT)

    docs = "\n".join([feature_catalog, todo, quality_ops])
    stale_phrases = [
        "用户测试进程主动打印密钥后的平台级日志脱敏策略未另行实现",
        "用户测试进程主动打印密钥后的日志脱敏策略未另行实现",
        "平台级日志脱敏仍需另立产品策略",
    ]

    for phrase in stale_phrases:
        assert phrase not in docs

    assert "executor 写 Redis 前会按环境变量敏感值脱敏" in feature_catalog
    assert "executor 写 Redis 前会按环境变量敏感值脱敏" in todo
    assert "Worker stdout/stderr secret redaction 文档契约" in quality_ops
    assert "live SSE、archived logs 与真实 `run.read` token 读面只出现 `[REDACTED]`" in (
        docs
    )
    assert "fake pytest 主动把该密钥打印到 stdout/stderr 时" in testing_strategy
    assert "主动 stdout/stderr 打印密钥也会在 live SSE、archived logs 与 `run.read` token 读面脱敏为 `[REDACTED]`" in (
        backend_audit
    )
