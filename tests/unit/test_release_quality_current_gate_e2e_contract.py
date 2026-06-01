from __future__ import annotations

from pathlib import Path

from tests.unit.release_quality_contract_helpers import (
    _quality_ops_row,
    _read,
)


ROOT = Path(__file__).resolve().parents[2]
BACKEND_TEST_AUDIT = ROOT / "docs" / "backend-test-audit.md"
REAL_RUN_TRIGGER_E2E = ROOT / "tests" / "e2e" / "real-run-trigger.spec.ts"
SPECIAL_REGRESSIONS_E2E = ROOT / "tests" / "e2e" / "special-regressions.spec.ts"
AUTH_FLOW_E2E = ROOT / "tests" / "e2e" / "auth-flow.spec.ts"
REAL_LOGIN_FLOW_E2E = ROOT / "tests" / "e2e" / "real-login-flow.spec.ts"
INTEGRATION_SKIP_REPORT_TEST = (
    ROOT / "tests" / "unit" / "test_integration_skip_report.py"
)
TEST_QUALITY_CONTRACTS = ROOT / "tests" / "unit" / "test_test_quality_contracts.py"


def test_quality_ops_records_current_gate_e2e_static_evidence():
    worker_e2e = _read(REAL_RUN_TRIGGER_E2E)
    auth_flow_e2e = _read(AUTH_FLOW_E2E)
    real_login_flow_e2e = _read(REAL_LOGIN_FLOW_E2E)
    special_regressions_e2e = _read(SPECIAL_REGRESSIONS_E2E)
    skip_report_test = _read(INTEGRATION_SKIP_REPORT_TEST)
    test_quality_contracts = _read(TEST_QUALITY_CONTRACTS)
    latest_row = _quality_ops_row(
        "| 2026-05-30 | collect-only `tests/integration` 212 tests"
    )
    frontend_auth_e2e_row = _quality_ops_row(
        "| 2026-05-30 | N/A（前端登录 refresh-cookie 竞态与 worker-backed E2E 抗并行契约）"
    )
    worker_backed_e2e_exact_row = _quality_ops_row(
        "| 2026-05-31 | N/A（worker-backed E2E evidence 精确契约）"
    )
    worker_backed_e2e_summary_exact_row = _quality_ops_row(
        "| 2026-05-31 | N/A（worker-backed E2E summary 精确契约）"
    )
    worker_backed_e2e_ui_exact_row = _quality_ops_row(
        "| 2026-05-31 | N/A（worker-backed E2E UI row/artifact 精确契约）"
    )
    e2e_ui_cell_exact_row = _quality_ops_row(
        "| 2026-05-31 | N/A（E2E UI row/cell exact text 契约）"
    )
    special_regressions_e2e_exact_row = _quality_ops_row(
        "| 2026-05-31 | N/A（special-regressions E2E 列表/审计精确契约）"
    )
    special_regressions_filtered_response_row = _quality_ops_row(
        "| 2026-05-31 | N/A（special-regressions filtered webhook response 精确契约）"
    )
    special_regressions_result_filters_row = _quality_ops_row(
        "| 2026-05-31 | N/A（special-regressions E2E result filters 精确契约）"
    )
    special_regressions_silent_windows_row = _quality_ops_row(
        "| 2026-05-31 | N/A（special-regressions E2E silent windows 响应精确契约）"
    )
    special_regressions_env_card_row = _quality_ops_row(
        "| 2026-05-31 | N/A（special-regressions env var UI scoped card 精确契约）"
    )
    integration_skip_report_exact_row = _quality_ops_row(
        "| 2026-05-31 | N/A（integration skip report 输出精确契约）"
    )
    empty_test_static_gate_row = _quality_ops_row(
        "| 2026-05-30 | N/A（空测试 / assert True 静态门禁）"
    )
    backend_test_audit = _read(BACKEND_TEST_AUDIT)

    assert "coverage unit 1379 passed" in latest_row
    assert (
        "`npx playwright test tests/e2e/auth-flow.spec.ts --project=chromium` 1 passed"
        in (latest_row)
    )
    assert (
        "`npx playwright test tests/e2e/special-regressions.spec.ts --project=chromium` 7 passed"
        in (latest_row)
    )
    assert "total 87.63%" in latest_row
    assert "statements 89.56%" in latest_row
    assert "branches 79.20%" in latest_row
    assert "total 87.52%" not in latest_row
    assert "branches 78.94%" not in latest_row
    assert "backend ruff passed" in latest_row
    assert "tenant isolation self-test passed" in latest_row
    assert "frontend lint/build passed" in latest_row
    assert "API token secret 校验先于 expiry 响应" in backend_test_audit
    assert "伪造 secret 枚举已过期 token_id" in backend_test_audit
    assert "API token owner 停用、用户软删除或租户软删除" in backend_test_audit
    assert "JWT 在有 DB session 时回查当前 user row" in backend_test_audit
    assert "停用账号、用户软删除、租户软删除、tenant/role 漂移" in (backend_test_audit)
    assert "generic webhook URL userinfo 凭据在 DNS/HTTP 前拒绝" in (backend_test_audit)
    assert "GitSource clone URL hostname DNS 解析到非公网或组播地址" in (
        backend_test_audit
    )
    assert "带 userinfo+port 的 `http://`/`ftp://` URL" in backend_test_audit
    assert (
        "内置 runner `test_path/test_paths` 只能指向 workspace 内相对路径且不能是空白路径"
        in (backend_test_audit)
    )
    assert "错误不回显 secret" in backend_test_audit
    assert "admin status 以 `done/failed/cancelled/timeout` 作为终态分母" in (
        backend_test_audit
    )
    assert "DingTalk/WeCom 上游 JSON 非 object 响应会返回安全失败结果" in (
        backend_test_audit
    )
    assert "JUnit XML duration 畸形输入不会打断结果采集" in backend_test_audit
    assert "Jest/Playwright 自定义 JUnit 输出目录会在执行前创建" in (backend_test_audit)
    assert "Go runner 对合法 JSON 非 object 行和畸形 elapsed" in (backend_test_audit)
    assert "env_vars 加密 ciphertext 空/截断 envelope" in backend_test_audit
    assert "`IndexError`/底层解密异常" in backend_test_audit
    assert "轮换 `encryption_keys` 的版本和 64 hex/32 bytes 约束" in (
        backend_test_audit
    )
    assert "Settings 与 CryptoService 构造阶段提前失败" in backend_test_audit
    assert "DB/Redis/S3/JWT/timeout/rate-limit/retention 等关键数值配置的 0 或负值" in (
        backend_test_audit
    )
    assert "非法/空白 `trusted_proxies` CIDR" in backend_test_audit
    assert "空白 S3 bucket/region、Docker host、OTel service name 和 CORS origin" in (
        backend_test_audit
    )
    assert "空白 OTel exporter endpoint 仅归一为未配置" in backend_test_audit
    assert "GitSource clone 后 HEAD SHA 解析失败或空输出会失败" in (backend_test_audit)
    assert "`npm audit --prefix frontend --audit-level=moderate` 0 vulnerabilities" in (
        latest_row
    )
    assert "`tests/unit/test_frontend_security_contracts.py` 8 passed" in (
        frontend_auth_e2e_row
    )
    assert (
        "worker-backed Playwright `real-login-flow.spec.ts` + "
        "`real-run-trigger.spec.ts` 2 passed（35.0s）"
    ) in frontend_auth_e2e_row
    assert "Select controlled/uncontrolled warning 已消除" in frontend_auth_e2e_row
    assert "登录页跳过初始 refresh" in frontend_auth_e2e_row
    assert "E2E helper 等待 authenticated shell" in frontend_auth_e2e_row
    assert "trigger modal Select 全程受控" in frontend_auth_e2e_row
    assert (
        "`npx playwright test tests/e2e/real-run-trigger.spec.ts --project=chromium --list`"
        in (worker_backed_e2e_exact_row)
    )
    assert "targeted docs contract passed" in worker_backed_e2e_exact_row
    assert "静态 contract 锁住断言形状" in worker_backed_e2e_exact_row
    assert "固定为单项 `{name,status}` 与单项 `{name,type}`" in (
        worker_backed_e2e_exact_row
    )
    assert "不再用 `expect.arrayContaining`" in worker_backed_e2e_exact_row
    assert "避免 worker-backed E2E 只证明“目标证据在里面”" in (
        worker_backed_e2e_exact_row
    )
    assert (
        "expect(results.map((result) => ({ name: result.name, status: result.status }))).toEqual(["
        in (worker_e2e)
    )
    assert (
        "expect(artifacts.map((artifact) => ({ name: artifact.name, type: artifact.type }))).toEqual(["
        in (worker_e2e)
    )
    assert (
        "`npx playwright test tests/e2e/real-run-trigger.spec.ts --project=chromium --list` 1 test listed"
        in (worker_backed_e2e_summary_exact_row)
    )
    assert (
        "`{total:1, passed:1, failed:0, skipped:0, error:0, pass_rate:1}`"
        in worker_backed_e2e_summary_exact_row
    )
    assert "不再接受 `toMatchObject` 的超集响应" in (
        worker_backed_e2e_summary_exact_row
    )
    assert "避免 worker-backed E2E 只证明“几个计数看起来对”" in (
        worker_backed_e2e_summary_exact_row
    )
    assert "expect(terminalRun.summary).toEqual({" in worker_e2e
    assert "skipped: 0" in worker_e2e
    assert "pass_rate: 1" in worker_e2e
    assert "expect(terminalRun.summary).toMatchObject({" not in worker_e2e
    assert (
        'expect.arrayContaining([expect.objectContaining({ name: testCaseName, status: "passed" })])'
        not in (worker_e2e)
    )
    assert (
        'expect.arrayContaining([expect.objectContaining({ name: "junit.xml" })])'
        not in (worker_e2e)
    )
    assert (
        "`npx playwright test tests/e2e/real-run-trigger.spec.ts --project=chromium --list` 1 test listed"
        in (worker_backed_e2e_ui_exact_row)
    )
    assert "run detail 的 Test Results 页面现在用结果行逐 `td` 锁定" in (
        worker_backed_e2e_ui_exact_row
    )
    assert "Artifacts 页面锁定 `junit.xml` heading" in worker_backed_e2e_ui_exact_row
    assert "只证明“页面某处出现了目标文本”" in worker_backed_e2e_ui_exact_row
    assert "async function expectPassedResultRow" in worker_e2e
    assert "await expect(cells.nth(1)).toHaveText(testCaseName);" in worker_e2e
    assert 'await expect(cells.nth(3)).toHaveText("Passed");' in worker_e2e
    assert 'page.getByRole("heading", { name: "junit.xml" })' in worker_e2e
    assert 'page.getByRole("button", { name: "Download junit.xml" })' in worker_e2e
    assert 'page.getByText("Passed").first()' not in worker_e2e
    assert "page.getByText(testCaseName)" not in worker_e2e
    assert 'page.getByText("junit.xml")' not in worker_e2e
    assert (
        "`npx playwright test tests/e2e/special-regressions.spec.ts --project=chromium --list`"
        in (special_regressions_e2e_exact_row)
    )
    assert "targeted docs contract passed" in special_regressions_e2e_exact_row
    assert "唯一 active webhook run" in special_regressions_e2e_exact_row
    assert "唯一 AuditEventResponse 投影" in special_regressions_e2e_exact_row
    assert "不再用 `filter(...).toHaveLength(1)` / `some(...).toBe(true)`" in (
        special_regressions_e2e_exact_row
    )
    assert "const activeRun = createActiveWebhookRunViaDb({" in special_regressions_e2e
    assert "id: activeRun.id" in special_regressions_e2e
    assert "total: 1" in special_regressions_e2e
    assert "git_ref: `refs/heads/${allowedBranch}`" in special_regressions_e2e
    assert (
        "action=project.create&resource_type=project&resource_id=${project.id}&per_page=10"
        in (special_regressions_e2e)
    )
    assert "projectCreateAudit.after_state.created_at" in special_regressions_e2e
    assert "runs.data.filter((run) => run.git_sha === gitSha)).toHaveLength(1)" not in (
        special_regressions_e2e
    )
    assert "runs.data.some((run) => run.git_ref ===" not in special_regressions_e2e
    assert "ownerAuditBody.data.some(" not in special_regressions_e2e
    assert (
        "`npx playwright test tests/e2e/special-regressions.spec.ts --project=chromium --list` 7 tests listed"
        in (special_regressions_filtered_response_row)
    )
    assert '`{status:"filtered", reason:"branch_not_allowed"}`' in (
        special_regressions_filtered_response_row
    )
    assert "不再接受 `toMatchObject` 的超集响应" in (
        special_regressions_filtered_response_row
    )
    assert "避免 branch-filter E2E 只证明“看起来被过滤了”" in (
        special_regressions_filtered_response_row
    )
    assert "expect(await filtered.json()).toEqual({" in special_regressions_e2e
    assert (
        "expect(await filtered.json()).toMatchObject({" not in special_regressions_e2e
    )
    assert (
        "`npx playwright test tests/e2e/special-regressions.spec.ts --project=chromium --list` 7 tests listed"
        in (special_regressions_silent_windows_row)
    )
    assert "不再保留 `toHaveLength` / arrayContaining / objectContaining" in (
        special_regressions_silent_windows_row
    )
    assert "silent_windows 响应固定完整单项对象" in (
        special_regressions_silent_windows_row
    )
    assert "只证明“有一条数据”" in special_regressions_silent_windows_row
    assert "expect(refreshed.silent_windows).toEqual([" in special_regressions_e2e
    assert "const savedWindow = refreshed.silent_windows[0];" in special_regressions_e2e
    assert "expect(ownerAuditBody.data).toHaveLength(1);" not in special_regressions_e2e
    assert "toHaveLength(" not in special_regressions_e2e
    assert "expect.arrayContaining" not in special_regressions_e2e
    assert "expect.objectContaining" not in special_regressions_e2e
    assert (
        "`npx playwright test tests/e2e/special-regressions.spec.ts --project=chromium --list` 7 tests listed"
        in (special_regressions_env_card_row)
    )
    assert "具名 environment region 锁定目标卡片" in special_regressions_env_card_row
    assert "只证明“页面某处第一个输入框看起来对”" in (special_regressions_env_card_row)
    assert "name: `Decoy Env ${suffix}`" in special_regressions_e2e
    assert 'page.getByRole("region", { name: `Masked Env ${suffix} environment` })' in (
        special_regressions_e2e
    )
    assert (
        "environmentCard.locator('input[placeholder=\"KEY\"]')"
        in special_regressions_e2e
    )
    assert (
        "environmentCard.locator('input[placeholder=\"VALUE\"]')"
        in special_regressions_e2e
    )
    assert 'environmentCard.getByRole("button", { name: "Show value" })' in (
        special_regressions_e2e
    )
    assert "page.locator('input[placeholder=\"KEY\"]').first()" not in (
        special_regressions_e2e
    )
    assert "page.locator('input[placeholder=\"VALUE\"]').first()" not in (
        special_regressions_e2e
    )
    assert (
        "`npx playwright test tests/e2e/special-regressions.spec.ts --project=chromium --list`"
        in (special_regressions_result_filters_row)
    )
    assert "完整 TestResultResponse 投影" in special_regressions_result_filters_row
    assert "run_id/suite/name/status/duration/error/stack/tags/metadata" in (
        special_regressions_result_filters_row
    )
    assert "只断言 total 加 name/status" in special_regressions_result_filters_row
    assert "type TestResultPage = Paginated<{" in special_regressions_e2e
    assert "const normalizeResultPage = (body: TestResultPage) => ({" in (
        special_regressions_e2e
    )
    assert "const expectedFailedResult = {" in special_regressions_e2e
    assert "expect(normalizeResultPage(failedBody)).toEqual({" in (
        special_regressions_e2e
    )
    assert "expect(normalizeResultPage(suiteBody)).toEqual({" in special_regressions_e2e
    assert "expect(normalizeResultPage(queryBody)).toEqual({" in special_regressions_e2e
    assert "expect(failedBody.total).toBe(1)" not in special_regressions_e2e
    assert "expect(failedBody.data[0].name)" not in special_regressions_e2e
    assert "expect(suiteBody.data[0].name)" not in special_regressions_e2e
    assert "expect(queryBody.data[0].status)" not in special_regressions_e2e
    assert "`tests/unit/test_integration_skip_report.py` 3 passed" in (
        integration_skip_report_exact_row
    )
    assert "完整 entry 字段" in integration_skip_report_exact_row
    assert "markdown 表格全文" in integration_skip_report_exact_row
    assert "只证明“有个标题和原因文本”" in integration_skip_report_exact_row
    assert '"junit_path": str(junit)' in skip_report_test
    assert '"classname": "tests.integration.test_a"' in skip_report_test
    assert '"gate_policy": "required_in_ci"' in skip_report_test
    assert '"gate_policy": "investigate_before_release"' in skip_report_test
    assert "assert payload == {" in skip_report_test
    assert "assert markdown == (" in skip_report_test
    assert 'assert [entry["category"] for entry in entries]' not in skip_report_test
    assert 'assert "# Integration Skip Inventory" in markdown' not in skip_report_test
    assert (
        'assert "temporary local fixture unavailable" in markdown'
        not in skip_report_test
    )
    assert (
        "禁止 E2E spec 回流 `expect.arrayContaining` / `expect.objectContaining` / "
        "`toMatchObject` / `toBeTruthy()` / `toContainText`"
    ) in empty_test_static_gate_row
    assert "响应大概包含 / 值非空或行里有词就行" in empty_test_static_gate_row
    assert '"expect.arrayContaining",' in test_quality_contracts
    assert '"expect.objectContaining",' in test_quality_contracts
    assert '".toMatchObject(",' in test_quality_contracts
    assert '".toBeTruthy()",' in test_quality_contracts
    assert '".toContainText(",' in test_quality_contracts
    assert "presence_only_e2e_matcher" in test_quality_contracts
    assert (
        "`npx playwright test tests/e2e/auth-flow.spec.ts tests/e2e/real-login-flow.spec.ts --project=chromium --list` 2 tests listed"
        in (e2e_ui_cell_exact_row)
    )
    assert (
        "`npx playwright test tests/e2e/auth-flow.spec.ts --project=chromium` 1 passed"
        in (e2e_ui_cell_exact_row)
    )
    assert "`NO_COLOR` / `FORCE_COLOR` 环境提示" in e2e_ui_cell_exact_row
    assert "禁止 `.toContainText(` 回流" in e2e_ui_cell_exact_row
    assert "逐 `td` exact text 断言" in e2e_ui_cell_exact_row
    assert "只证明“某行里有这些词”" in e2e_ui_cell_exact_row
    assert "async function expectTableCells" in auth_flow_e2e
    assert "await expect(cells.nth(index)).toHaveText(expectedText);" in auth_flow_e2e
    assert (
        'await expect(projectLink.getByRole("heading", { name: project.name })).toBeVisible();'
        in (real_login_flow_e2e)
    )
    assert ".toContainText(" not in auth_flow_e2e
    assert ".toContainText(" not in real_login_flow_e2e
