from __future__ import annotations

import ast
from pathlib import Path

from tests.unit.release_quality_contract_helpers import (
    _block_between,
    _quality_ops_row,
    _quality_ops_row_containing,
    _read,
)


ROOT = Path(__file__).resolve().parents[2]
ADMIN_TEST = ROOT / "tests" / "unit" / "test_api" / "test_admin.py"
AUTH_ROUTES_TEST = ROOT / "tests" / "unit" / "test_auth" / "test_auth_routes.py"
CROSS_TENANT_ISOLATION = ROOT / "tests" / "integration" / "test_cross_tenant_isolation.py"
ENVIRONMENTS_TEST = ROOT / "tests" / "unit" / "test_api" / "test_environments.py"
HEALTH_TEST = ROOT / "tests" / "unit" / "test_api" / "test_health.py"
RATE_LIMIT_TEST = ROOT / "tests" / "unit" / "test_api" / "test_rate_limit.py"
RBAC_DEPS_TEST = ROOT / "tests" / "unit" / "test_api" / "test_rbac_deps.py"
SECURITY_HEADERS_TEST = ROOT / "tests" / "unit" / "test_api" / "test_security_headers.py"
SOFT_DELETE_INFRA = (
    ROOT / "tests" / "integration" / "test_infra" / "test_soft_delete.py"
)
TEST_QUALITY_CONTRACTS = ROOT / "tests" / "unit" / "test_test_quality_contracts.py"
WEBHOOK_SIGNATURE_TEST = (
    ROOT / "tests" / "unit" / "test_api" / "test_webhook_signature.py"
)


def test_quality_ops_capture_admin_status_exact_response_body_contract():
    admin_test = _read(ADMIN_TEST)

    row = _quality_ops_row("| 2026-05-31 | N/A（Admin status exact response body 契约）")

    assert "`tests/unit/test_api/test_admin.py` 4 passed" in row
    assert "release quality docs contract full 295 passed" in row
    assert "targeted ruff passed" in row
    assert "queue_depth、in_flight、success_rate_1h、total_runs_1h" in row
    assert "保留队列/运行中/终态分母/成功分子的查询契约" in row
    assert "zero-run 分支只断言 `success_rate_1h == 1.0`" in row
    assert "系统状态页测试只证明“查询正确且某个指标看起来对”" in row

    assert admin_test.count("assert body == {") >= 2
    for expected in [
        '"queue_depth": 5',
        '"in_flight": 2',
        '"success_rate_1h": 0.6667',
        '"total_runs_1h": 12',
        '"queue_depth": 0',
        '"in_flight": 0',
        '"success_rate_1h": 1.0',
        '"total_runs_1h": 0',
    ]:
        assert expected in admin_test
    assert 'assert body["success_rate_1h"] == 1.0' not in admin_test
    assert 'assert body["queue_depth"] == 5' not in admin_test
    assert "_assert_status_query_contract(repos)" in admin_test


def test_quality_ops_capture_cross_tenant_isolation_response_contracts():
    row = _quality_ops_row_containing(
        "tests/integration/test_cross_tenant_isolation.py` 14 passed",
        "完整 `NOT_FOUND` envelope 相等",
    )
    cross_tenant_tests = _read(CROSS_TENANT_ISOLATION)

    assert "tests/integration/test_cross_tenant_isolation.py` 14 passed" in row
    assert "完整 `NOT_FOUND` envelope 相等" in row
    assert "响应不回显被探测的 tenant B 或随机 UUID" in row
    assert "_assert_same_404_result" in cross_tenant_tests
    assert '"code": "NOT_FOUND"' in cross_tenant_tests
    assert '"details": []' in cross_tenant_tests
    assert "assert body_l == body_r == expected_body" in cross_tenant_tests
    assert 'body.get("detail") or body.get("error"' not in cross_tenant_tests
    assert "expected_detail=\"Pipeline not found\"" in cross_tenant_tests
    assert "expected_detail=\"Run not found\"" in cross_tenant_tests
    assert "expected_detail=\"Artifact not found\"" in cross_tenant_tests
    assert "forbidden_values=[pipeline_b_id, random_id]" in cross_tenant_tests


def test_quality_ops_capture_webhook_signature_empty_secret_contract():
    row = _quality_ops_row_containing("Webhook signature empty-secret helper 契约")
    webhook_signature_test = _read(WEBHOOK_SIGNATURE_TEST)

    assert "Webhook signature empty-secret helper 契约" in row
    assert "`verify_webhook_signature` 现在对空 secret 固定返回 False" in (
        row
    )
    assert "是否跳过验签仍由路由层显式策略决定" in row
    assert "test_empty_secret_rejects_signature_header" in webhook_signature_test
    assert "test_empty_secret_rejects_missing_signature_header" in webhook_signature_test
    assert 'verify_webhook_signature("", b"payload", "sha256=garbage") is False' in (
        webhook_signature_test
    )
    assert 'verify_webhook_signature("", b"", "") is False' in webhook_signature_test
    assert 'verify_webhook_signature("", b"payload", "sha256=garbage") is True' not in (
        webhook_signature_test
    )
    assert 'verify_webhook_signature("", b"", "") is True' not in webhook_signature_test


def test_quality_ops_capture_webhook_signature_compare_digest_runtime_contract():
    webhook_signature_test = _read(WEBHOOK_SIGNATURE_TEST)
    row = _quality_ops_row(
        "| 2026-05-31 | N/A（Webhook signature compare_digest runtime 契约）"
    )

    assert "Webhook signature compare_digest runtime 契约" in row
    assert "`tests/unit/test_api/test_webhook_signature.py::TestTimingSafety` 2 passed" in row
    assert "webhook signature full 15 passed" in row
    assert "release quality docs contract full 215 passed" in row
    assert "targeted ruff passed" in row
    assert "runtime patch `qaplatform.infra.webhook_signature.hmac.compare_digest`" in row
    assert "以 `(expected, supplied)` 调用 compare_digest" in row
    assert "空 secret 早退路径固定不触发 compare_digest" in row
    assert "`inspect.getsource` 查找 `\"compare_digest\"` 字符串" in row
    assert "注释、死代码或错误包装" in row
    assert "源码文本里出现过 compare_digest" in row

    for expected in [
        "from unittest.mock import patch",
        "expected = generate_webhook_signature(secret, payload)",
        'supplied = "sha256=" + "f" * 64',
        '"qaplatform.infra.webhook_signature.hmac.compare_digest"',
        "compare_digest.assert_called_once_with(expected, supplied)",
        "compare_digest.assert_not_called()",
    ]:
        assert expected in webhook_signature_test
    for removed in [
        "import inspect",
        "inspect.getsource(verify_webhook_signature)",
        'assert "compare_digest" in src',
    ]:
        assert removed not in webhook_signature_test


def test_quality_ops_capture_unit_all_assertion_direct_contract_sweep():
    row = _quality_ops_row_containing("Unit all-assertion direct contract sweep")
    environments_test = _read(ENVIRONMENTS_TEST)
    auth_routes_test = _read(AUTH_ROUTES_TEST)
    rate_limit_test = _read(RATE_LIMIT_TEST)
    webhook_signature_test = _read(WEBHOOK_SIGNATURE_TEST)

    assert "Unit all-assertion direct contract sweep" in row
    assert (
        "`tests/unit/test_api/test_environments.py::test_environment_routes_return_503_when_crypto_unavailable tests/unit/test_auth/test_auth_routes.py::TestLogin::test_login_inactive_user tests/unit/test_auth/test_auth_routes.py::TestRefresh::test_refresh_missing_cookie tests/unit/test_api/test_rate_limit.py::TestRateLimitMiddlewareDispatch::test_different_tokens_independent_quotas tests/unit/test_api/test_rate_limit.py::TestRateLimitMiddlewareDispatch::test_third_token_passes_when_others_exhausted tests/unit/test_api/test_rate_limit.py::TestRateLimitMiddlewareDispatch::test_uuid_path_segments_share_one_bucket tests/unit/test_api/test_webhook_signature.py::TestGenerateAndVerify::test_signature_format_is_sha256_equals_hex` 7 passed"
        in row
    )
    assert "unit 测试中的 `assert all(...)` 已清空" in row
    assert "五个响应体直接列表匹配" in row
    assert "refresh cookie header 精确等于空列表" in row
    assert "渲染后的 key 文本不含原 token/run id" in row
    assert "`sha256=[0-9a-f]{64}` fullmatch" in row
    assert "all 里藏判断" in row

    assert '[resp.json() for resp in responses] == [' in environments_test
    assert '{"detail": "Crypto service not initialised"}' in environments_test
    assert "refresh_cookie_headers = [" in auth_routes_test
    assert 'if header.lower().startswith("refresh_token=")' in auth_routes_test
    assert "assert refresh_cookie_headers == []" in auth_routes_test
    assert 'rendered_keys = "\\n".join(zadd_keys)' in rate_limit_test
    assert 'rendered_keys = "\\n".join(keys)' in rate_limit_test
    assert "assert token_a not in rendered_keys" in rate_limit_test
    assert "assert run_a not in rendered_keys" in rate_limit_test
    assert "import re" in webhook_signature_test
    assert 're.fullmatch(r"sha256=[0-9a-f]{64}", sig)' in webhook_signature_test
    for path_text in [
        environments_test,
        auth_routes_test,
        rate_limit_test,
        webhook_signature_test,
    ]:
        assert "assert all(" not in path_text


def test_quality_ops_capture_error_subfield_static_gate_contract():
    test_quality_contracts = _read(TEST_QUALITY_CONTRACTS)

    row = _quality_ops_row(
        "| 2026-05-31 | N/A（Error subfield equality static gate 契约） | `tests/unit/test_test_quality_contracts.py::test_python_tests_do_not_assert_error_subfields_as_whole_response` 1 passed；release quality docs contract full 269 passed"
    )

    assert "仓库级测试质量门" in row
    assert "AST 扫描 unit/integration Python 测试" in row
    assert "禁止把 response JSON 的 `detail`/`error` 子字段直接当作完整响应断言" in row
    assert "validation projection" in row
    assert "字段级错误体等值断言清零" in row
    assert "顶层 ID、hint、debug 或配置路径泄漏" in row
    assert "Error subfield equality static gate" in row
    assert "避免这类弱断言回流" in row

    assert "def _json_subscript_field(node: ast.AST) -> str | None:" in (
        test_quality_contracts
    )
    assert "def _direct_json_error_subfield_equality(compare: ast.Compare) -> str | None:" in (
        test_quality_contracts
    )
    assert "def test_python_tests_do_not_assert_error_subfields_as_whole_response()" in (
        test_quality_contracts
    )
    assert 'node.value.func.attr != "json"' in test_quality_contracts
    assert 'node.slice.value not in {"detail", "error"}' in test_quality_contracts
    assert "ast.walk(assert_node.test)" in test_quality_contracts
    assert "json_subfield:{field}" in test_quality_contracts
    assert "assert offenders == []" in test_quality_contracts


def test_quality_ops_capture_rbac_project_lookup_sequence_exact_contract():
    quality_ops = _quality_ops_row_containing(
        "RBAC project visibility/member lookup 序列精确契约"
    )
    rbac_deps_test = _read(RBAC_DEPS_TEST)

    assert "RBAC project visibility/member lookup 序列精确契约" in quality_ops
    assert (
        "`tests/unit/test_api/test_rbac_deps.py::TestRequireProjectPermission::test_missing_or_cross_tenant_project_raises_404_before_rbac tests/unit/test_api/test_rbac_deps.py::TestRequireProjectPermission::test_visible_project_member_without_membership_is_403` 2 passed"
        in quality_ops
    )
    assert "固定只执行 `{project_id, tenant_id}` visibility 查询" in quality_ops
    assert "固定按顺序执行 visibility 查询后再执行 `{project_id, user_id, tenant_id}` membership 查询" in (
        quality_ops
    )
    assert "`session.execute.await_count == 1` / `== 2`" in quality_ops
    assert "包含式参数检查" in quality_ops
    assert "visibility 查询意外带上 user_id 导致存在性泄漏风险" in (
        quality_ops
    )
    assert "只证明“查了一次/两次且大概包含关键参数”" in quality_ops
    assert "def _assert_execute_param_sequence(" in rbac_deps_test
    assert "_executed_statement_column_params(session, index, list(expected_params))" in (
        rbac_deps_test
    )
    assert '"project.id": project_id' in rbac_deps_test
    assert '"project.tenant_id": user.tenant_id' in rbac_deps_test
    assert '"project_member.project_id": project_id' in rbac_deps_test
    assert '"project_member.user_id": user.user_id' in rbac_deps_test
    assert '"project_member.tenant_id": user.tenant_id' in rbac_deps_test
    assert "_executed_statement_params(session, index)" not in rbac_deps_test
    assert "{project_id, user.user_id, user.tenant_id}" not in rbac_deps_test
    assert "assert session.execute.await_count == 1" not in rbac_deps_test
    assert "assert session.execute.await_count == 2" not in rbac_deps_test


def test_quality_ops_capture_soft_delete_infra_exact_empty_list_contract():
    soft_delete_infra = _read(SOFT_DELETE_INFRA)
    row = _quality_ops_row("| 2026-05-31 | `RUN_INTEGRATION_TESTS=1 "
            "tests/integration/test_infra/test_soft_delete.py --collect-only` "
            "7 tests collected")
    test_block = _block_between(soft_delete_infra, "async def test_list_excludes_soft_deleted", "\n\n@pytest.mark.asyncio")

    assert "targeted docs contract passed" in row
    assert "targeted ruff/py_compile passed" in row
    assert "`items == []` 与 `total == 0`" in row
    assert "soft-delete infra exact empty list 契约" in row
    assert "只证明“数量为 0”" in row
    assert "assert items == []" in test_block
    assert "assert total == 0" in test_block
    assert "assert len(items) == 0" not in test_block


def test_quality_ops_capture_global_204_empty_body_guard_contract():
    offenders: list[str] = []
    tests_root = ROOT / "tests"

    for path in sorted(tests_root.rglob("test_*.py")):
        source = _read(path)
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if not isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)):
                continue
            if not node.name.startswith("test_"):
                continue
            block = ast.get_source_segment(source, node) or ""
            if "status_code == 204" in block and ".content" not in block:
                offenders.append(f"{path.relative_to(ROOT)}:{node.lineno}:{node.name}")

    row = _quality_ops_row("| 2026-05-31 | N/A（全局 204 响应空 body 防回退契约）")
    assert "` 10 passed" in row
    assert "release quality docs contract full 251 passed" in row
    assert "用 AST 扫描禁止任何测试函数只断言 204 而不校验响应内容" in row
    assert "避免项目继续积累“只证明状态码”的 204 测试" in row
    assert offenders == []


def test_quality_ops_capture_global_201_response_body_guard_contract():
    offenders: list[str] = []
    tests_root = ROOT / "tests"

    for path in sorted(tests_root.rglob("test_*.py")):
        source = _read(path)
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if not isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)):
                continue
            if not node.name.startswith("test_"):
                continue
            block = ast.get_source_segment(source, node) or ""
            has_created_assert = any(
                isinstance(assertion, ast.Assert)
                and isinstance(assertion.test, ast.Compare)
                and any(
                    isinstance(comparator, ast.Constant)
                    and comparator.value == 201
                    for comparator in assertion.test.comparators
                )
                and (
                    isinstance(assertion.test.left, ast.Attribute)
                    and assertion.test.left.attr == "status_code"
                    or any(
                        isinstance(comparator, ast.Attribute)
                        and comparator.attr == "status_code"
                        for comparator in assertion.test.comparators
                    )
                )
                for assertion in ast.walk(node)
            )
            if has_created_assert and ".json(" not in block and ".content" not in block:
                offenders.append(f"{path.relative_to(ROOT)}:{node.lineno}:{node.name}")

    row = _quality_ops_row("| 2026-05-31 | N/A（全局 201 创建响应 body 防回退契约）")
    assert "` 6 passed" in row
    assert "release quality docs contract full 252 passed" in row
    assert "用 AST 扫描禁止任何测试函数只断言 201 而不校验响应内容" in row
    assert "避免创建类测试只证明“写入副作用发生且状态码是 Created”" in row
    assert offenders == []


def test_quality_ops_capture_health_uptime_numeric_seconds_contract():
    health_test = _read(HEALTH_TEST)
    row = _quality_ops_row(
        "| 2026-05-31 | N/A（Health uptime numeric seconds 精确契约）"
    )

    assert "Health uptime numeric seconds 精确契约" in row
    assert "`tests/unit/test_api/test_health.py` 6 passed" in row
    assert "release quality docs contract full 208 passed" in row
    assert "targeted ruff passed" in row
    assert "两位小数的非负秒数字符串" in row
    assert "整数/小数部分都可解析" in row
    assert "此前只证明 `uptime` 以 s 结尾" in row
    assert "`oks`、`nans`、`infs`" in row
    assert "只证明“字段像个秒单位字符串”" in row

    for expected in [
        "def _assert_uptime_seconds(value: str) -> float:",
        'assert value.endswith("s")',
        'seconds_text = value.removesuffix("s")',
        'whole, dot, fraction = seconds_text.partition(".")',
        'assert dot == "."',
        'assert whole == "0" or (whole.isdecimal() and not whole.startswith("0"))',
        "assert fraction.isdecimal()",
        "assert len(fraction) == 2",
        "seconds = float(seconds_text)",
        "assert seconds >= 0",
        'body["uptime"]',
        '_assert_uptime_seconds(body["uptime"])',
    ]:
        assert expected in health_test
    assert 'body["uptime"].endswith("s")' not in health_test


def test_quality_ops_capture_health_liveness_exact_response_body_contract():
    health_test = _read(HEALTH_TEST)
    row = _quality_ops_row(
        "| 2026-05-31 | N/A（Health liveness exact response body 契约）"
    )
    test_block = _block_between(health_test, "async def test_health_returns_lightweight_liveness_contract", "async def test_ready_returns_ok_when_database_and_redis_probes_pass")

    assert "`tests/unit/test_api/test_health.py::test_health_returns_lightweight_liveness_contract` 1 passed" in row
    assert "health full 6 passed" in row
    assert "release quality docs contract full 301 passed" in row
    assert "完整响应 body 只能包含 `status/version/uptime`" in row
    assert "liveness 与 readiness 壳混用" in row
    assert "Health liveness exact response body 契约" in row
    assert "只证明“几个字段看起来对”" in row

    assert "assert body == {" in test_block
    assert '"status": "ok"' in test_block
    assert '"version": app.version' in test_block
    assert '"uptime": body["uptime"]' in test_block
    assert '_assert_uptime_seconds(body["uptime"])' in test_block
    assert 'body["status"] == "ok"' not in test_block
    assert 'body["version"] == app.version' not in test_block


def test_quality_ops_capture_security_headers_exact_map_hsts_contract():
    security_headers_test = _read(SECURITY_HEADERS_TEST)
    row = _quality_ops_row(
        "| 2026-05-31 | N/A（Security headers exact map/HSTS 契约）"
    )

    assert "Security headers exact map/HSTS 契约" in row
    assert "`tests/unit/test_api/test_security_headers.py` 2 passed" in row
    assert "release quality docs contract full 214 passed" in row
    assert "targeted ruff passed" in row
    assert "`EXPECTED_SECURITY_HEADERS` 固定无 HSTS 时完整 header map" in row
    assert "`Strict-Transport-Security: max-age=31536000; includeSubDomains`" in row
    assert "此前用 14 条用例重复检查单个 header 与 CSP substring" in row
    assert "CSP 夹带额外 directive" in row
    assert "HSTS 开关污染默认路径" in row
    assert "覆盖数量错觉" in row
    assert "只证明“几个安全头片段存在”" in row

    for expected in [
        "EXPECTED_SECURITY_HEADERS = {",
        '"Content-Security-Policy": (',
        'EXPECTED_HSTS = "max-age=31536000; includeSubDomains"',
        "async def test_exact_headers_when_hsts_disabled",
        "assert headers == EXPECTED_SECURITY_HEADERS",
        "async def test_exact_headers_when_hsts_enabled",
        "assert headers == {",
        "**EXPECTED_SECURITY_HEADERS,",
        '"Strict-Transport-Security": EXPECTED_HSTS,',
    ]:
        assert expected in security_headers_test
    for removed in [
        "class TestCSPDirectives",
        "async def test_default_src_self",
        "async def test_script_src_self",
        "async def test_style_src_self_unsafe_inline",
        "async def test_img_src_self_data",
        "async def test_connect_src_self",
        "async def test_frame_ancestors_none",
        'assert "default-src',
        'assert "Strict-Transport-Security" in headers',
        'assert "Strict-Transport-Security" not in headers',
    ]:
        assert removed not in security_headers_test


def test_quality_ops_capture_rbac_dependency_sql_column_bound_params_contract():
    rbac_deps_test = _read(RBAC_DEPS_TEST)
    row = _quality_ops_row(
        "| 2026-06-01 | N/A（RBAC dependency SQL column-bound params 契约）"
    )

    assert "RBAC dependency SQL column-bound params 契约" in row
    assert "`tests/unit/test_api/test_rbac_deps.py` 15 passed" in row
    assert "release quality docs contract full 351 passed" in row
    assert "targeted ruff/py_compile passed" in row
    assert "编译为 PostgreSQL SQL" in row
    assert "`project.id/project.tenant_id`" in row
    assert "`project_member.project_id/user_id/tenant_id`" in row
    assert "column-bound 参数映射" in row
    assert "sequence helper 同时固定 execute 次数" in row
    assert "`statement.compile().params.values()` 转成 set" in row
    assert "tenant_id 与 user_id 绑定错列" in row
    assert "project visibility 查询夹带 user_id" in row
    assert "execute 次数漂移" in row
    assert "几个 UUID 出现在参数集合里" in row

    for expected in [
        "import re",
        "from sqlalchemy.dialects import postgresql",
        "def _executed_statement_column_params(",
        "compiled = statement.compile(dialect=postgresql.dialect())",
        "assert set(compiled.params) == param_names",
        "assert len(session.execute.await_args_list) == len(expected_param_maps)",
        '"project.id": project_id',
        '"project.tenant_id": user.tenant_id',
        '"project_member.project_id": project_id',
        '"project_member.user_id": user.user_id',
        '"project_member.tenant_id": user.tenant_id',
    ]:
        assert expected in rbac_deps_test
    assert "statement.compile().params.values()" not in rbac_deps_test
    assert "project_id in params" not in rbac_deps_test
    assert "user.tenant_id in params" not in rbac_deps_test
