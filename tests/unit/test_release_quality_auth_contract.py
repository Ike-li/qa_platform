from __future__ import annotations

from pathlib import Path

from tests.unit.release_quality_contract_helpers import (
    _after,
    _before,
    _block_between,
    _marked_block,
    _marked_block_or_tail,
    _quality_ops_row,
    _quality_ops_row_containing,
    _quality_ops_rows_containing,
    _read,
)


ROOT = Path(__file__).resolve().parents[2]
AUTH_AUDIT_FAILURE_PATHS = (
    ROOT / "tests" / "integration" / "test_auth_audit_failure_paths.py"
)
AUTH_MIDDLEWARE_TEST = ROOT / "tests" / "unit" / "test_auth_middleware.py"
AUTH_ROUTES_TEST = ROOT / "tests" / "unit" / "test_auth" / "test_auth_routes.py"
AUTH_TOKEN_SERVICE_TEST = (
    ROOT / "tests" / "unit" / "test_auth" / "test_token_service.py"
)
BACKEND_TEST_AUDIT = ROOT / "docs" / "backend-test-audit.md"
RATE_LIMIT_TEST = ROOT / "tests" / "unit" / "test_api" / "test_rate_limit.py"
TESTING_STRATEGY = ROOT / "docs" / "testing-strategy.md"


def test_quality_ops_capture_rate_limit_pass_through_response_identity_contract():
    rate_limit_test = _read(RATE_LIMIT_TEST)

    row = _quality_ops_row("| 2026-05-31 | N/A（Rate limit pass-through response identity 契约）")

    assert (
        "test_different_tokens_independent_quotas "
        "tests/unit/test_api/test_rate_limit.py::TestRateLimitMiddlewareDispatch::"
        "test_third_token_passes_when_others_exhausted "
        "tests/unit/test_api/test_rate_limit.py::TestRateLimitMiddlewareDispatch::"
        "test_no_trusted_proxy_xff_ignored_in_key "
        "tests/unit/test_api/test_rate_limit.py::TestRateLimitMiddlewareDispatch::"
        "test_uuid_path_segments_share_one_bucket"
    ) in row
    assert "rate limit full 28 passed" in row
    assert "release quality docs contract full 296 passed" in row
    assert "targeted ruff passed" in row
    assert "固定返回对象 identity" in row
    assert "未超限 token、无 trusted proxy 的 direct IP" in row
    assert "两个 UUID 请求返回错 downstream 对象" in row
    assert "只证明“下游被调用且最终状态码是 200”" in row

    for expected in [
        "assert resp_b is downstream_response",
        "assert resp_c is downstream_response",
        "assert resp is downstream_response",
        "assert resp_a is downstream_responses[0]",
        "assert resp_b is downstream_responses[1]",
    ]:
        assert expected in rate_limit_test
    assert "call_next = AsyncMock(side_effect=downstream_responses)" in (
        rate_limit_test
    )
    assert "_assert_rate_limited_response(resp_a, mw.settings.rate_limit_window_seconds)" in (
        rate_limit_test
    )
    assert "zadd_keys == [" in rate_limit_test


def test_testing_docs_capture_api_token_missing_auth_contract():
    row = _quality_ops_row_containing(
        "API token create/list/delete 缺失 Authorization 固定 401"
    )
    testing_strategy = _read(TESTING_STRATEGY)
    backend_audit = _read(BACKEND_TEST_AUDIT)

    assert "API token create/list/delete 缺失 Authorization 固定 401" in row
    assert "真实 DB 不新增 token 或 create/revoke audit" in row
    assert "API token create/list/delete 缺失 Authorization 固定 401" in (
        testing_strategy
    )
    assert "API token create/list/delete 缺失 Authorization 固定 401" in backend_audit


def test_quality_ops_capture_rate_limit_strict_redis_outage_envelope():
    row = _quality_ops_row_containing("Rate limit strict Redis outage envelope")
    rate_limit_tests = _read(RATE_LIMIT_TEST)

    assert "Rate limit strict Redis outage envelope" in row
    assert "503 `SERVICE_UNAVAILABLE` envelope" in row
    assert "不 await downstream handler" in row
    assert "_assert_rate_limit_unavailable_response" in rate_limit_tests
    assert '"code": "SERVICE_UNAVAILABLE"' in rate_limit_tests
    assert '"message": "Service temporarily unavailable"' in rate_limit_tests
    assert 'resp.headers["Retry-After"] == "5"' in rate_limit_tests
    assert "call_next.assert_not_awaited()" in rate_limit_tests


def test_quality_ops_capture_rate_limit_multi_token_429_exact_response_contract():
    rate_limit_test = _read(RATE_LIMIT_TEST)

    row = _quality_ops_row(
        "| 2026-05-31 | N/A（Rate limit multi-token 429 exact response 契约） | `tests/unit/test_api/test_rate_limit.py::TestRateLimitMiddlewareDispatch::test_third_token_passes_when_others_exhausted` 1 passed；release quality docs contract full 271 passed"
    )

    assert "三个 bearer token 隔离用例" in row
    assert "两个耗尽 token 都复用 `_assert_rate_limited_response`" in row
    assert "固定 429、`Retry-After` 使用普通 API window" in row
    assert "`TOO_MANY_REQUESTS` error envelope" in row
    assert "第三个 token 进入 downstream" in row
    assert "Redis bucket key 精确序列" in row
    assert "此前只断言 token A/B 返回 429" in row
    assert "缺 `Retry-After`、错误体漂移为空/调试字段" in row
    assert "窗口误用 strict auth window" in row
    assert "只证明“两个耗尽 token 被限流”" in row

    block = _block_between(rate_limit_test, "async def test_third_token_passes_when_others_exhausted", "async def test_no_bearer_uses_ip_identity")

    assert (
        "_assert_rate_limited_response(resp_a, mw.settings.rate_limit_window_seconds)"
        in block
    )
    assert (
        "_assert_rate_limited_response(resp_b, mw.settings.rate_limit_window_seconds)"
        in block
    )
    assert "assert resp_c.status_code == 200" in block
    assert "call_next.assert_awaited_once_with(req_c)" in block
    assert "f\"rate_limit:token:{hash_a}:/api/v1/runs\"" in block
    assert "f\"rate_limit:token:{hash_b}:/api/v1/runs\"" in block
    assert "f\"rate_limit:token:{hash_c}:/api/v1/runs\"" in block
    assert "assert resp_a.status_code == 429" not in block
    assert "assert resp_b.status_code == 429" not in block


def test_quality_ops_capture_auth_real_rate_limit_429_exact_envelope_contract():
    auth_audit_failure_paths = _read(AUTH_AUDIT_FAILURE_PATHS)

    row = _quality_ops_row(
        "| 2026-05-31 | `RUN_INTEGRATION_TESTS=1 tests/integration/test_auth_audit_failure_paths.py::test_auth_login_rate_limit_uses_real_redis_token_hash_bucket tests/integration/test_auth_audit_failure_paths.py::test_auth_register_rate_limit_uses_real_redis_ip_bucket_and_audit_count tests/integration/test_auth_audit_failure_paths.py::test_auth_refresh_rate_limit_uses_real_redis_ip_bucket_and_audit_count tests/integration/test_auth_audit_failure_paths.py::test_auth_api_token_create_rate_limit_uses_real_redis_token_bucket tests/integration/test_auth_audit_failure_paths.py::test_auth_sse_ticket_rate_limit_uses_real_redis_token_hash_bucket` 5 passed | release quality docs contract full 274 passed"
    )

    assert "真实 auth strict rate-limit 五条集成路径" in row
    assert "统一用 `_assert_rate_limited_response`" in row
    assert "固定 429、`Retry-After` strict auth window" in row
    assert (
        '`{"error":{"code":"TOO_MANY_REQUESTS","message":"Rate limit exceeded. Please try again later."}}`'
        in row
    )
    assert "真实 Redis bucket" in row
    assert "原始 token/password/cookie 不进 key" in row
    assert "限流请求不写额外 audit" in row
    assert '此前只检查 `limited.json()["error"]["code"]`' in row
    assert "429 body message 漂移" in row
    assert "debug/key/token hint" in row
    assert "响应壳退化但 code 字段仍在" in row
    assert "第 6 次被限流且 code 字段正确" in row

    assert "def _assert_rate_limited_response(response, retry_after: int) -> None:" in (
        auth_audit_failure_paths
    )
    assert "assert response.status_code == 429, response.text" in (
        auth_audit_failure_paths
    )
    assert 'assert response.headers["Retry-After"] == str(retry_after)' in (
        auth_audit_failure_paths
    )
    assert "assert response.json() == {" in auth_audit_failure_paths
    assert '"code": "TOO_MANY_REQUESTS"' in auth_audit_failure_paths
    assert '"message": "Rate limit exceeded. Please try again later."' in (
        auth_audit_failure_paths
    )

    expected_tests = [
        "async def test_auth_login_rate_limit_uses_real_redis_token_hash_bucket",
        "async def test_auth_register_rate_limit_uses_real_redis_ip_bucket_and_audit_count",
        "async def test_auth_refresh_rate_limit_uses_real_redis_ip_bucket_and_audit_count",
        "async def test_auth_api_token_create_rate_limit_uses_real_redis_token_bucket",
        "async def test_auth_sse_ticket_rate_limit_uses_real_redis_token_hash_bucket",
    ]
    for test_name in expected_tests:
        block = _marked_block_or_tail(
            auth_audit_failure_paths,
            test_name,
            "\n@pytest.mark.asyncio",
        )
        assert "_assert_rate_limited_response(" in block

    assert 'limited.json()["error"]["code"]' not in auth_audit_failure_paths


def test_quality_ops_capture_api_token_list_exact_response_contract():
    ops_row = _quality_ops_row_containing("API token list 精确响应契约")
    auth_routes = _read(AUTH_ROUTES_TEST)
    row = _quality_ops_row(
        "| 2026-05-31 | N/A（API token list exact pagination body 契约）"
    )
    test_block = _marked_block(
        auth_routes,
        "async def test_list_tokens",
        "\n\n# --- JWT Blacklist / Logout tests ---",
    )

    assert "API token list exact pagination body 契约" in row
    assert (
        "`tests/unit/test_auth/test_auth_routes.py::TestTokenRoutes::test_list_tokens` 1 passed"
        in row
    )
    assert "release quality docs contract full 335 passed" in row
    assert "完整分页 body" in row
    assert "`page=2`、`per_page=1`、`total=1`" in row
    assert "完整 API token item 必须整体等值" in row
    assert "精确排除 token/secret_hash" in row
    assert "revoked token 仍出现在列表" in row
    assert 'body["page"]` / `body["per_page"]` / `body["total"]' in row
    assert "`set(body[\"data\"][0])`" in row
    assert "API token list exact pagination body 契约" in row
    assert "data 和几个分页数字分别看起来对且没看到 secret" in row

    assert "API token list 精确响应契约" in ops_row
    assert "包含 token_id/name/scopes/expires_at/last_used_at/is_revoked/created_at" in (
        ops_row
    )
    assert "字段集合精确排除 token/secret_hash" in ops_row
    assert "assert body == {" in test_block
    assert '"scopes": ["run.read", "audit.read"]' in test_block
    assert '"last_used_at": last_used_at.isoformat().replace("+00:00", "Z")' in (
        test_block
    )
    assert '"page": 2' in test_block
    assert '"per_page": 1' in test_block
    assert '"total": 1' in test_block
    for rejected in [
        'assert body["page"] == 2',
        'assert body["per_page"] == 1',
        'assert body["total"] == 1',
        'assert body["data"] == [',
        'assert set(body["data"][0]) == {',
        'assert len(body["data"]) == 1',
        'body["data"][0]["token_id"] == "tok1"',
    ]:
        assert rejected not in test_block


def test_quality_ops_capture_auth_audit_outage_integration_exact_warning_contract():
    audit_failure_paths = _read(AUTH_AUDIT_FAILURE_PATHS)

    row = _quality_ops_row("| 2026-05-31 | `RUN_INTEGRATION_TESTS=1 "
            "tests/integration/test_auth_audit_failure_paths.py::"
            "test_login_nonexistent_user_returns_401_when_audit_write_fails", contains="test_logout_without_authorization_returns_204_when_audit_write_fails")

    assert (
        "tests/integration/test_auth_audit_failure_paths.py::"
        "test_refresh_invalid_token_returns_401_when_audit_write_fails"
        in row
    )
    assert (
        "tests/integration/test_auth_audit_failure_paths.py::"
        "test_logout_without_authorization_returns_204_when_audit_write_fails"
        in row
    )
    assert "` 3 passed" in row
    assert "release quality docs contract full 224 passed" in row
    assert "targeted ruff passed" in row
    assert "每条只记录一条 `qaplatform.api.v1.auth` WARNING" in row
    assert "message 为 `audit_write_failed`" in row
    assert (
        "`record.action` 分别是 `auth.login_failed` / `auth.refresh_failed` / "
        "`auth.logout`"
        in row
    )
    assert "exc_info 保留原始 `RuntimeError(\"audit store unavailable\")`" in row
    assert "此前只用 `caplog.text` 包含式断言" in row
    assert "日志里出现过 audit_write_failed" in row

    helper_block = _marked_block(
        audit_failure_paths,
        "def _assert_auth_audit_warning",
        "# --------------------------------------------------------------------------- #\n# Tests",
    )

    assert 'record.name == "qaplatform.api.v1.auth"' in helper_block
    assert "record.levelno == logging.WARNING" in helper_block
    assert 'getattr(record, "action", None) == action' in helper_block
    assert '"message": record.getMessage()' in helper_block
    assert '"exc_type": type(record.exc_info[1]) if record.exc_info else None' in (
        helper_block
    )
    assert '"exc_message": str(record.exc_info[1]) if record.exc_info else None' in (
        helper_block
    )
    assert '"message": "audit_write_failed"' in helper_block
    assert '"exc_type": RuntimeError' in helper_block
    assert '"exc_message": "audit store unavailable"' in helper_block
    assert "assert len(records) == 1" not in helper_block
    assert "assert records[0]" not in helper_block
    for action in ["auth.login_failed", "auth.refresh_failed", "auth.logout"]:
        assert f'_assert_auth_audit_warning(caplog, "{action}")' in (
            audit_failure_paths
        )
    assert 'assert "audit_write_failed" in caplog.text' not in audit_failure_paths


def test_quality_ops_capture_auth_rate_limit_audit_direct_projection_contract():
    audit_failure_paths = _read(AUTH_AUDIT_FAILURE_PATHS)

    row = _quality_ops_row("| 2026-05-31 | `RUN_INTEGRATION_TESTS=1 "
            "tests/integration/test_auth_audit_failure_paths.py --collect-only`")

    assert "12 tests collected" in row
    assert "targeted docs contract passed" in row
    assert "targeted ruff/py_compile passed" in row
    assert "同 action 的 WARNING 投影为唯一 `{message,exc_type,exc_message}`" in row
    assert "register/refresh strict rate-limit Redis IP bucket 用单元素解包" in row
    assert "refresh cookie rotation 用 6 个 token 的顺序解包和集合等值" in row
    assert "`len(records) == 1`、`len(keys) == 1`" in row
    assert "`len(seen_refresh_tokens) == 6`" in row
    assert "bucket 泄漏 key 变成多条" in row
    assert "认证安全测试只证明“数量看起来对”" in row

    helper_block = _marked_block(
        audit_failure_paths,
        "def _assert_auth_audit_warning",
        "# --------------------------------------------------------------------------- #\n# Tests",
    )

    assert '"message": record.getMessage()' in helper_block
    assert '"exc_type": type(record.exc_info[1]) if record.exc_info else None' in (
        helper_block
    )
    assert '"exc_message": str(record.exc_info[1]) if record.exc_info else None' in (
        helper_block
    )
    assert '"message": "audit_write_failed"' in helper_block
    assert '"exc_type": RuntimeError' in helper_block
    assert '"exc_message": "audit store unavailable"' in helper_block

    register_block = _block_between(audit_failure_paths, "async def test_auth_register_rate_limit_uses_real_redis_ip_bucket_and_audit_count", "def _refresh_cookie")
    assert "(bucket_key,) = keys" in register_block
    assert "assert prefix not in bucket_key" in register_block
    assert "assert password not in bucket_key" in register_block
    assert "assert await redis.zcard(bucket_key) == 6" in register_block
    assert "assert len(keys) == 1" not in register_block

    refresh_block = _block_between(audit_failure_paths, "async def test_auth_refresh_rate_limit_uses_real_redis_ip_bucket_and_audit_count", "async def test_auth_api_token_create_rate_limit")
    assert "refresh_tokens = [_refresh_cookie(auth_client)]" in refresh_block
    assert "refresh_tokens.append(_refresh_cookie(auth_client))" in refresh_block
    assert "initial_refresh_token," in refresh_block
    assert "fifth_rotated_token," in refresh_block
    assert "assert sorted(refresh_tokens) == sorted(" in refresh_block
    assert "(bucket_key,) = keys" in refresh_block
    assert "for token in refresh_tokens:" in refresh_block
    assert "assert token not in bucket_key" in refresh_block
    assert "assert await redis.zcard(bucket_key) == 6" in refresh_block
    assert "assert len(seen_refresh_tokens) == 6" not in refresh_block
    assert "assert len(keys) == 1" not in refresh_block


def test_quality_ops_capture_auth_failure_401_exact_body_contract():
    audit_failure_paths = _read(AUTH_AUDIT_FAILURE_PATHS)

    row = _quality_ops_row("| 2026-05-31 | `RUN_INTEGRATION_TESTS=1 "
            "tests/integration/test_auth_audit_failure_paths.py::"
            "test_login_nonexistent_user_returns_401_when_audit_write_fails", contains="test_refresh_with_invalid_token_returns_401_not_500")

    assert "` 3 passed" in row
    assert "release quality docs contract full 253 passed" in row
    assert "login 为 `{\"detail\": \"Invalid credentials\"}`" in row
    assert "refresh 为 `{\"detail\": \"Invalid refresh token\"}`" in row
    assert "避免认证失败集成测试只证明“状态码和后端副作用对”" in row

    for test_name, expected_body in {
        "test_login_nonexistent_user_returns_401_when_audit_write_fails": '{"detail": "Invalid credentials"}',
        "test_refresh_with_invalid_token_returns_401_not_500": '{"detail": "Invalid refresh token"}',
        "test_refresh_invalid_token_returns_401_when_audit_write_fails": '{"detail": "Invalid refresh token"}',
    }.items():
        block = _block_between(audit_failure_paths, f"async def {test_name}", "\n\n@pytest.mark.asyncio")
        assert "assert resp.status_code == 401" in block
        assert f"assert resp.json() == {expected_body}" in block


def test_quality_ops_capture_login_unknown_user_exact_audit_no_secret_contract():
    audit_failure_paths = _read(AUTH_AUDIT_FAILURE_PATHS)

    row = _quality_ops_row("| 2026-05-31 | `RUN_INTEGRATION_TESTS=1 "
            "tests/integration/test_auth_audit_failure_paths.py::"
            "test_login_nonexistent_user_returns_401_not_500")

    assert "` 1 passed" in row
    assert "release quality docs contract full 227 passed" in row
    assert "targeted ruff passed" in row
    assert '401 body `{"detail": "Invalid credentials"}`' in row
    assert "tenant_id/user_id 均为 None" in row
    assert (
        'after_state 精确等于 `{"reason": "invalid_credentials", '
        '"username": username}`'
        in row
    )
    assert "不泄露 password" in row
    assert "此前只用 `invalid_credentials in str(row.after_state)`" in row
    assert "reason 字段名漂移" in row
    assert "username 丢失" in row
    assert "夹带 password" in row
    assert "审计里出现过 invalid_credentials" in row

    block = _marked_block(
        audit_failure_paths,
        "async def test_login_nonexistent_user_returns_401_not_500",
        "async def test_auth_login_rate_limit_uses_real_redis_token_hash_bucket",
    )

    assert 'username = "totally_nonexistent_user"' in block
    assert 'password = "wrong"' in block
    assert 'assert resp.json() == {"detail": "Invalid credentials"}' in block
    assert 'assert row.action == "auth.login_failed"' in block
    assert "assert row.tenant_id is None" in block
    assert "assert row.user_id is None" in block
    assert "assert row.after_state == {" in block
    assert '"reason": "invalid_credentials"' in block
    assert '"username": username' in block
    assert "assert password not in repr(row.after_state)" in block
    assert '"invalid_credentials" in str(row.after_state)' not in block


def test_quality_ops_capture_auth_success_token_claims_exact_contract():
    row = _quality_ops_row_containing("Auth success token claims 精确契约")
    auth_routes_test = _read(AUTH_ROUTES_TEST)

    assert "Auth success token claims 精确契约" in row
    assert (
        "`tests/unit/test_auth/test_auth_routes.py::TestLogin::test_login_success tests/unit/test_auth/test_auth_routes.py::TestRegister::test_register_success tests/unit/test_auth/test_auth_routes.py::TestRefresh::test_refresh_success` 3 passed"
        in row
    )
    assert "固定完整响应 body" in row
    assert "`token_type=bearer`" in row
    assert "access token 的 `sub/role/tenant_id/is_platform_admin/type/jti/exp/iat` claims" in (
        row
    )
    assert "refresh cookie token 的 `sub/type/jti/exp/iat`" in row
    assert "测试 helper 默认用户也显式 `is_platform_admin=False`" in row
    assert "`access_token` 存在" in row
    assert "响应夹带额外字段" in row
    assert "`MagicMock.is_platform_admin` truthy 化成错误 admin claim" in (
        row
    )
    assert "认证成功测试只证明“发了某个 token”" in row

    assert 'user.is_platform_admin = overrides.get("is_platform_admin", False)' in (
        auth_routes_test
    )
    assert "def _assert_access_token_claims(" in auth_routes_test
    assert "def _assert_refresh_cookie_claims(" in auth_routes_test
    assert '"is_platform_admin": payload["is_platform_admin"]' in auth_routes_test
    assert '"type": "access"' in auth_routes_test
    assert '"type": "refresh"' in auth_routes_test
    assert 'assert payload["exp"] > payload["iat"]' in auth_routes_test

    blocks = [
        _marked_block(
            auth_routes_test,
            "async def test_login_success",
            "async def test_login_wrong_password",
        ),
        _marked_block(
            auth_routes_test,
            "async def test_register_success",
            "async def test_register_username_conflict",
        ),
        _marked_block(
            auth_routes_test,
            "async def test_refresh_success",
            "async def test_refresh_missing_cookie",
        ),
    ]

    for block in blocks:
        assert "_assert_access_token_claims(" in block
        assert "_assert_refresh_cookie_claims(" in block
        assert "assert data == {" in block
        assert '"token_type": "bearer"' in block
        assert 'assert "refresh_token" not in data' in block
        assert 'assert "access_token" in data' not in block

    assert 'assert set(data) == {"access_token", "token_type", "user"}' not in (
        blocks[0]
    )
    assert 'assert set(data) == {"access_token", "token_type", "user"}' not in (
        blocks[1]
    )
    assert 'assert set(data) == {"access_token", "token_type"}' not in blocks[2]
    assert '"role": "developer"' in blocks[0]
    assert '"role": "owner"' in blocks[1]
    assert "user_repo.get_by_id.assert_awaited_once_with(user_id)" in blocks[2]


def test_quality_ops_capture_auth_register_conflict_exact_rollback_contract():
    row = _quality_ops_row_containing("Auth register conflict exact rollback 契约")
    auth_routes_test = _read(AUTH_ROUTES_TEST)

    assert "Auth register conflict exact rollback 契约" in row
    assert (
        "`tests/unit/test_auth/test_auth_routes.py::TestRegister::test_register_username_conflict` 1 passed"
        in row
    )
    assert "targeted auth routes passed" in row
    assert "完整 409 响应体" in row
    assert "无 access/refresh token" in row
    assert "无 refresh cookie" in row
    assert "只执行 tenant name lookup" in row
    assert "不会构造 UserRepository/AuditEventRepository" in row
    assert "session rollback 且不 commit" in row
    assert "只断言 409 与 `already taken` 子串" in row
    assert "注册冲突测试只证明“返回了一个包含 already taken 的 409”" in (
        row
    )

    conflict_block = _marked_block(
        auth_routes_test,
        "async def test_register_username_conflict",
        "@pytest.mark.parametrize",
    )

    assert 'assert resp.json() == {"detail": "Username already taken"}' in (
        conflict_block
    )
    assert "_assert_no_login_tokens(resp)" in conflict_block
    assert "session_factory.assert_called_once_with()" in conflict_block
    assert 'tenant_repo.get_by_name.assert_awaited_once_with("alice")' in (
        conflict_block
    )
    assert "tenant_repo.create.assert_not_awaited()" in conflict_block
    assert "user_repo_cls.assert_not_called()" in conflict_block
    assert "user_repo.create.assert_not_awaited()" in conflict_block
    assert "audit_repo_cls.assert_not_called()" in conflict_block
    assert "session.commit.assert_not_awaited()" in conflict_block
    assert "session.rollback.assert_awaited_once()" in conflict_block
    assert 'assert "already taken" in resp.json()["detail"].lower()' not in (
        conflict_block
    )


def test_quality_ops_capture_auth_refresh_rotation_exact_token_audit_contract():
    row = _quality_ops_row_containing("Auth refresh rotation exact token/audit 契约")
    audit_row = _quality_ops_row_containing("Auth refresh audit new_jti 真实追踪契约")
    auth_routes_test = _read(AUTH_ROUTES_TEST)

    assert "Auth refresh rotation exact token/audit 契约" in row
    assert (
        "`tests/unit/test_auth/test_auth_routes.py::TestRefreshRevokesOldToken::test_refresh_revokes_old_refresh_token` 1 passed"
        in row
    )
    assert "targeted auth routes passed" in row
    assert "新 access token claims" in row
    assert "新 refresh cookie claims" in row
    assert "旧 refresh token 不再作为 cookie 返回" in row
    assert "old jti blacklist lookup" in row
    assert "`redis.set(..., ex<=refresh_ttl)`" in row
    assert "真实非空 `new_jti`" in audit_row
    assert "`auth.refresh` audit 的 `old_jti/new_jti`" in row
    assert "只断言 200 和旧 jti 进入内存 store" in row
    assert "refresh rotation 测试只证明“旧 jti 进了某个字典”" in (
        row
    )

    refresh_block = _marked_block(
        auth_routes_test,
        "async def test_refresh_revokes_old_refresh_token",
        "async def test_refresh_with_revoked_token_returns_401",
    )

    assert "assert body == {" in refresh_block
    assert '"token_type": "bearer"' in refresh_block
    assert 'assert set(body) == {"access_token", "token_type"}' not in refresh_block
    assert 'assert body["token_type"] == "bearer"' not in refresh_block
    assert 'assert resp.cookies["refresh_token"] != old_refresh_token' in (
        refresh_block
    )
    assert "_assert_access_token_claims(" in refresh_block
    assert "_assert_refresh_cookie_claims(resp, jwt_svc, user_id=user.id)" in (
        refresh_block
    )
    assert 'new_refresh_payload = jwt_svc.decode_token(resp.cookies["refresh_token"])' in (
        refresh_block
    )
    assert 'new_jti = new_refresh_payload["jti"]' in refresh_block
    assert "assert new_jti != old_jti" in refresh_block
    assert "user_repo.get_by_id.assert_awaited_once_with(user_id)" in refresh_block
    assert "redis_mock.exists.assert_awaited_once_with" in refresh_block
    assert "redis_mock.set.assert_awaited_once()" in refresh_block
    assert "redis_mock.set.await_args.args == (f\"jwt:revoked:{old_jti}\", \"1\")" in (
        refresh_block
    )
    assert (
        "0 < redis_mock.set.await_args.kwargs[\"ex\"] <= settings.jwt_refresh_token_ttl"
        in refresh_block
    )
    assert "audit_repo.create.assert_awaited_once()" in refresh_block
    assert 'audit_kwargs["action"] == "auth.refresh"' in refresh_block
    assert 'audit_kwargs["before_state"] == {"old_jti": old_jti}' in refresh_block
    assert 'audit_kwargs["after_state"] == {"new_jti": new_jti}' in refresh_block
    assert "old_refresh_token not in repr(audit_kwargs)" in refresh_block
    assert "session.commit.assert_awaited_once()" in refresh_block
    assert "session.rollback.assert_not_awaited()" in refresh_block


def test_quality_ops_capture_api_token_create_exact_response_contract():
    row = _quality_ops_row_containing("API token create exact response body 契约")
    auth_routes_test = _read(AUTH_ROUTES_TEST)

    assert "API token create exact response body 契约" in row
    assert (
        "`tests/unit/test_auth/test_auth_routes.py::TestTokenRoutes::test_create_token` 1 passed"
        in row
    )
    assert "targeted auth routes passed" in row
    assert "完整响应体 `{token_id, token, name, scopes, expires_at, created_at}`" in (
        row
    )
    assert "`expires_at` 必须来自仓储 create 入参" in row
    assert "响应不含 `secret_hash`/`hashed-secret`" in row
    assert "hash 只接收 64 hex secret" in row
    assert "audit 不泄露明文/哈希" in row
    assert "只抽查 `token_id/token/name/scopes`" in row
    assert "时间格式漂移" in row
    assert "API token 创建测试只证明“几个关键字段看起来对且 data 里没有 secret_hash”" in (
        row
    )

    create_block = _marked_block(
        auth_routes_test,
        "async def test_create_token",
        "@pytest.mark.parametrize",
    )

    assert "async def _create_token_record(**kwargs):" in create_block
    assert 'fake_record.expires_at = kwargs["expires_at"]' in create_block
    assert "api_token_repo.create.side_effect = _create_token_record" in create_block
    assert "assert data == {" in create_block
    assert '"token_id": token_id' in create_block
    assert '"token": full_token' in create_block
    assert '"name": "ci"' in create_block
    assert '"scopes": ["runs:read"]' in create_block
    expires_fragment = _before(
        _after(
            create_block,
            '"expires_at": create_kwargs["expires_at"]',
        ),
        '"created_at"',
    )
    assert ".isoformat()" in expires_fragment
    assert ".replace(" in expires_fragment
    assert '"+00:00"' in expires_fragment
    assert '"Z"' in expires_fragment
    assert '"created_at": "2026-05-31T07:08:09Z"' in create_block
    assert 'assert "secret_hash" not in resp.text' in create_block
    assert 'assert "hashed-secret" not in resp.text' in create_block
    assert "hash_token.assert_called_once_with(token_secret)" in create_block
    assert "assert audit_kwargs == {" in create_block
    assert '"action": "auth.api_token_create"' in create_block
    assert '"resource_type": "auth"' in create_block
    assert '"resource_id": fake_record.id' in create_block
    assert '"after_state": {"name": "ci", "scopes": ["runs:read"]}' in create_block
    assert '"ip_address": "127.0.0.1"' in create_block
    assert '"user_agent": "api-token-create-audit-test"' in create_block
    assert 'data["token_id"]' not in create_block
    assert 'data["token"]' not in create_block
    assert 'data["name"]' not in create_block
    assert 'data["scopes"]' not in create_block


def test_quality_ops_capture_api_token_audit_redundant_weak_tests_removed():
    row = _quality_ops_row_containing("API token audit 冗余弱测试清理")
    auth_routes_test = _read(AUTH_ROUTES_TEST)

    assert "API token audit 冗余弱测试清理" in row
    assert (
        "`tests/unit/test_auth/test_auth_routes.py::TestTokenRoutes::test_create_token tests/unit/test_auth/test_auth_routes.py::TestTokenRoutes::test_revoke_token` 2 passed"
        in row
    )
    assert "auth routes full 59 passed" in row
    assert "API token create/revoke 审计现在由主 CRUD 契约负责" in row
    assert "`auth.api_token_create` 的 resource/after_state/脱敏/事务" in (
        row
    )
    assert "`auth.api_token_revoke` 的 resource/before_state/事务" in row
    assert "删除底部 `TestAuditApiTokens`" in row
    assert "只看 action/name/user_id 的重复弱测试" in row
    assert "非生产 token_id record" in row
    assert "resource_id、scopes、脱敏或事务漂移" in row
    assert "API token 审计靠重复低信号测试凑覆盖" in row

    create_block = _marked_block(
        auth_routes_test,
        "async def test_create_token",
        "@pytest.mark.parametrize",
    )
    revoke_block = _marked_block(
        auth_routes_test,
        "async def test_revoke_token",
        "async def test_revoke_token_not_found",
    )

    assert "assert audit_kwargs == {" in create_block
    assert '"tenant_id": UUID("b0000000-0000-0000-0000-000000000001")' in (
        create_block
    )
    assert '"user_id": UUID("a0000000-0000-0000-0000-000000000001")' in (
        create_block
    )
    assert '"action": "auth.api_token_create"' in create_block
    assert '"resource_type": "auth"' in create_block
    assert '"resource_id": fake_record.id' in create_block
    assert '"after_state": {"name": "ci", "scopes": ["runs:read"]}' in (
        create_block
    )
    assert '"ip_address": "127.0.0.1"' in create_block
    assert '"user_agent": "api-token-create-audit-test"' in create_block
    assert "assert token_secret not in str(audit_kwargs)" in create_block
    assert "assert full_token not in str(audit_kwargs)" in create_block
    assert 'assert "hashed-secret" not in str(audit_kwargs)' in create_block
    assert "session.commit.assert_awaited_once()" in create_block
    assert "session.rollback.assert_not_awaited()" in create_block

    assert "assert audit_kwargs == {" in revoke_block
    assert '"tenant_id": UUID("b0000000-0000-0000-0000-000000000001")' in (
        revoke_block
    )
    assert '"user_id": UUID("a0000000-0000-0000-0000-000000000001")' in (
        revoke_block
    )
    assert '"action": "auth.api_token_revoke"' in revoke_block
    assert '"resource_type": "auth"' in revoke_block
    assert '"resource_id": fake_token.id' in revoke_block
    assert '"before_state": {"name": fake_token.name}' in (
        revoke_block
    )
    assert '"ip_address": "127.0.0.1"' in revoke_block
    assert '"user_agent": "api-token-revoke-audit-test"' in revoke_block
    assert "session.commit.assert_awaited_once()" in revoke_block
    assert "session.rollback.assert_not_awaited()" in revoke_block

    assert "class TestAuditApiTokens" not in auth_routes_test
    assert "async def test_create_token_emits_audit" not in auth_routes_test
    assert "async def test_revoke_token_emits_audit" not in auth_routes_test
    assert 'fake_record = _make_orm_token(token_id="tok123", name="ci")' not in (
        auth_routes_test
    )


def test_quality_ops_capture_api_token_revoke_hidden_404_exact_body_contract():
    auth_routes_test = _read(AUTH_ROUTES_TEST)

    row = _quality_ops_row(
        "| 2026-05-31 | N/A（API token revoke hidden 404 exact body 契约） | `tests/unit/test_auth/test_auth_routes.py::TestTokenRoutes::test_revoke_token_not_found tests/unit/test_auth/test_auth_routes.py::TestTokenRoutes::test_revoke_token_hides_other_users_token_without_side_effects` 2 passed；release quality docs contract full 266 passed"
    )

    assert "不存在 token 与他人 token" in row
    assert "`{\"detail\": \"Token not found\"}`" in row
    assert "只查 token_id、不 revoke、不写 audit、不 commit、rollback" in row
    assert '只断言 `resp.json()["detail"]`' in row
    assert "token_id、owner hint、revoked/existence reason 或 debug 字段" in row
    assert "API token revoke hidden 404 exact body 契约" in row
    assert "只证明“detail 文案相同”" in row

    not_found_block = _block_between(auth_routes_test, "async def test_revoke_token_not_found", "async def test_revoke_token_hides_other_users_token_without_side_effects")
    other_user_block = _block_between(auth_routes_test, "async def test_revoke_token_hides_other_users_token_without_side_effects", "async def test_list_tokens")

    for block in (not_found_block, other_user_block):
        assert 'assert resp.json() == {"detail": "Token not found"}' in block
        assert 'resp.json()["detail"]' not in block
        assert "api_token_repo.revoke.assert_not_awaited()" in block
        assert "audit_repo.create.assert_not_awaited()" in block
        assert "session.commit.assert_not_awaited()" in block
        assert "session.rollback.assert_awaited_once()" in block


def test_quality_ops_capture_api_token_audit_complete_client_metadata_contract():
    row = _quality_ops_row_containing("API token audit 完整 client metadata 契约")
    auth_routes_test = _read(AUTH_ROUTES_TEST)

    assert "API token audit 完整 client metadata 契约" in row
    assert (
        "`tests/unit/test_auth/test_auth_routes.py::TestTokenRoutes::test_create_token tests/unit/test_auth/test_auth_routes.py::TestTokenRoutes::test_revoke_token` 2 passed"
        in row
    )
    assert "auth routes full 57 passed" in row
    assert "API token create/revoke 主 CRUD 用例现在固定完整审计 payload" in (
        row
    )
    assert "tenant/user、resource_type/resource_id、before/after_state、ip_address/user_agent" in (
        row
    )
    assert "token secret/full token/hash 不进 create audit" in row
    assert "主 CRUD 用例仍逐字段抽查 action/resource/state" in row
    assert "audit payload 夹带多余字段" in row
    assert "API token 审计只证明“关键字段大概存在”" in row

    create_block = _marked_block(
        auth_routes_test,
        "async def test_create_token",
        "@pytest.mark.parametrize",
    )
    revoke_block = _marked_block(
        auth_routes_test,
        "async def test_revoke_token",
        "async def test_revoke_token_not_found",
    )

    assert 'headers={"user-agent": "api-token-create-audit-test"}' in create_block
    assert "assert audit_kwargs == {" in create_block
    assert '"tenant_id": UUID("b0000000-0000-0000-0000-000000000001")' in (
        create_block
    )
    assert '"user_id": UUID("a0000000-0000-0000-0000-000000000001")' in (
        create_block
    )
    assert '"action": "auth.api_token_create"' in create_block
    assert '"resource_type": "auth"' in create_block
    assert '"resource_id": fake_record.id' in create_block
    assert '"after_state": {"name": "ci", "scopes": ["runs:read"]}' in create_block
    assert '"ip_address": "127.0.0.1"' in create_block
    assert '"user_agent": "api-token-create-audit-test"' in create_block
    assert "assert token_secret not in str(audit_kwargs)" in create_block
    assert "assert full_token not in str(audit_kwargs)" in create_block
    assert 'assert "hashed-secret" not in str(audit_kwargs)' in create_block
    assert 'audit_kwargs["action"]' not in create_block

    assert '"user-agent": "api-token-revoke-audit-test"' in revoke_block
    assert "assert audit_kwargs == {" in revoke_block
    assert '"tenant_id": UUID("b0000000-0000-0000-0000-000000000001")' in (
        revoke_block
    )
    assert '"user_id": UUID("a0000000-0000-0000-0000-000000000001")' in (
        revoke_block
    )
    assert '"action": "auth.api_token_revoke"' in revoke_block
    assert '"resource_type": "auth"' in revoke_block
    assert '"resource_id": fake_token.id' in revoke_block
    assert '"before_state": {"name": fake_token.name}' in revoke_block
    assert '"ip_address": "127.0.0.1"' in revoke_block
    assert '"user_agent": "api-token-revoke-audit-test"' in revoke_block
    assert 'audit_kwargs["action"]' not in revoke_block


def test_quality_ops_capture_auth_login_audit_success_contract_and_failure_cleanup():
    row = _quality_ops_row_containing("Auth login audit 成功契约与失败冗余清理")
    auth_routes_test = _read(AUTH_ROUTES_TEST)

    assert "Auth login audit 成功契约与失败冗余清理" in row
    assert (
        "`tests/unit/test_auth/test_auth_routes.py::TestAuditLogin::test_login_success_emits_audit tests/unit/test_auth/test_auth_routes.py::TestLogin::test_login_wrong_password tests/unit/test_auth/test_auth_routes.py::TestLogin::test_login_user_not_found tests/unit/test_auth/test_auth_routes.py::TestLogin::test_login_inactive_user` 4 passed"
        in row
    )
    assert "auth routes full 57 passed" in row
    assert "完整 payload `{tenant_id,user_id,action,resource_type,resource_id,after_state,ip_address,user_agent}`" in (
        row
    )
    assert "不含明文密码" in row
    assert "last_login update 与 commit/no rollback" in row
    assert "login 失败审计由主失败路径用例负责" in row
    assert "删除底部 `TestAuditLogin`" in row
    assert "只看 action/reason" in row
    assert "重复低信号测试凑覆盖" in row

    success_block = _marked_block(
        auth_routes_test,
        "async def test_login_success_emits_audit",
        "class TestAuditRegister",
    )

    assert 'headers={"user-agent": "auth-audit-test"}' in success_block
    assert "assert call_kwargs == {" in success_block
    assert '"tenant_id": user.tenant_id' in success_block
    assert '"user_id": user.id' in success_block
    assert '"action": "auth.login"' in success_block
    assert '"resource_type": "auth"' in success_block
    assert '"resource_id": None' in success_block
    assert '"after_state": {"username": user.username}' in success_block
    assert '"ip_address": "127.0.0.1"' in success_block
    assert '"user_agent": "auth-audit-test"' in success_block
    assert 'assert "correct-password" not in repr(call_kwargs)' in success_block
    assert "user_repo.update_last_login.assert_awaited_once()" in success_block
    assert "session.commit.assert_awaited_once()" in success_block
    assert "session.rollback.assert_not_awaited()" in success_block

    failed_audit_helper = _marked_block(
        auth_routes_test,
        "def _assert_login_failed_audit",
        "def _setup_overrides",
    )

    assert "user_agent: str" in failed_audit_helper
    assert "assert call_kwargs == {" in failed_audit_helper
    assert '"tenant_id": tenant_id' in failed_audit_helper
    assert '"user_id": user_id' in failed_audit_helper
    assert '"action": "auth.login_failed"' in failed_audit_helper
    assert '"resource_type": "auth"' in failed_audit_helper
    assert '"resource_id": None' in failed_audit_helper
    assert '"after_state": {"reason": reason, "username": username}' in (
        failed_audit_helper
    )
    assert '"ip_address": "127.0.0.1"' in failed_audit_helper
    assert '"user_agent": user_agent' in failed_audit_helper
    assert 'call_kwargs["action"] == "auth.login_failed"' not in failed_audit_helper
    assert 'call_kwargs["resource_type"] == "auth"' not in failed_audit_helper
    assert 'call_kwargs["resource_id"] is None' not in failed_audit_helper

    wrong_password_block = _marked_block(
        auth_routes_test,
        "async def test_login_wrong_password",
        "async def test_login_user_not_found",
    )
    user_not_found_block = _marked_block(
        auth_routes_test,
        "async def test_login_user_not_found",
        "async def test_login_inactive_user",
    )
    inactive_block = _marked_block(
        auth_routes_test,
        "async def test_login_inactive_user",
        "# --- Register tests ---",
    )

    assert "_assert_login_failed_audit(" in wrong_password_block
    assert 'reason="invalid_credentials"' in wrong_password_block
    assert "tenant_id=user.tenant_id" in wrong_password_block
    assert "user_id=user.id" in wrong_password_block
    assert '"user-agent": "login-wrong-password-audit-test"' in wrong_password_block
    assert 'user_agent="login-wrong-password-audit-test"' in wrong_password_block
    assert "_assert_login_failed_audit(" in user_not_found_block
    assert 'reason="invalid_credentials"' in user_not_found_block
    assert "tenant_id=None" in user_not_found_block
    assert "user_id=None" in user_not_found_block
    assert '"user-agent": "login-user-not-found-audit-test"' in user_not_found_block
    assert 'user_agent="login-user-not-found-audit-test"' in user_not_found_block
    assert "_assert_login_failed_audit(" in inactive_block
    assert 'reason="account_deactivated"' in inactive_block
    assert "tenant_id=user.tenant_id" in inactive_block
    assert "user_id=user.id" in inactive_block
    assert '"user-agent": "login-inactive-user-audit-test"' in inactive_block
    assert 'user_agent="login-inactive-user-audit-test"' in inactive_block

    assert "async def test_login_failed_emits_audit" not in auth_routes_test
    assert "async def test_login_failed_wrong_password_emits_audit" not in (
        auth_routes_test
    )


def test_quality_ops_capture_auth_login_failure_helper_complete_payload_contract():
    row = _quality_ops_row_containing(
        "Auth login failure helper 完整 payload 契约"
    )
    auth_routes_test = _read(AUTH_ROUTES_TEST)

    assert "Auth login failure helper 完整 payload 契约" in row
    assert (
        "`tests/unit/test_auth/test_auth_routes.py::TestLogin::test_login_wrong_password tests/unit/test_auth/test_auth_routes.py::TestLogin::test_login_user_not_found tests/unit/test_auth/test_auth_routes.py::TestLogin::test_login_inactive_user` 3 passed"
        in row
    )
    assert "auth routes full 57 passed" in row
    assert "login wrong-password、user-not-found、inactive 三条失败路径" in (
        row
    )
    assert "`_assert_login_failed_audit` 固定完整 payload `{tenant_id,user_id,action,resource_type,resource_id,after_state,ip_address,user_agent}`" in (
        row
    )
    assert "不发 token/cookie、不更新 last_login" in row
    assert "失败 helper 仍逐字段抽查且漏掉 ip/user-agent" in row
    assert "payload 夹带多余敏感字段" in row
    assert "login 失败审计只证明“失败原因和用户名写进去了”" in (
        row
    )

    helper_block = _marked_block(
        auth_routes_test,
        "def _assert_login_failed_audit",
        "def _setup_overrides",
    )

    assert "user_agent: str" in helper_block
    assert "assert call_kwargs == {" in helper_block
    assert '"tenant_id": tenant_id' in helper_block
    assert '"user_id": user_id' in helper_block
    assert '"action": "auth.login_failed"' in helper_block
    assert '"resource_type": "auth"' in helper_block
    assert '"resource_id": None' in helper_block
    assert '"after_state": {"reason": reason, "username": username}' in helper_block
    assert '"ip_address": "127.0.0.1"' in helper_block
    assert '"user_agent": user_agent' in helper_block
    assert 'assert call_kwargs["action"] == "auth.login_failed"' not in helper_block
    assert 'assert call_kwargs["resource_type"] == "auth"' not in helper_block
    assert 'assert call_kwargs["resource_id"] is None' not in helper_block

    wrong_password_block = _marked_block(
        auth_routes_test,
        "async def test_login_wrong_password",
        "async def test_login_user_not_found",
    )
    user_not_found_block = _marked_block(
        auth_routes_test,
        "async def test_login_user_not_found",
        "async def test_login_inactive_user",
    )
    inactive_block = _marked_block(
        auth_routes_test,
        "async def test_login_inactive_user",
        "# --- Register tests ---",
    )

    assert '"user-agent": "login-wrong-password-audit-test"' in wrong_password_block
    assert 'reason="invalid_credentials"' in wrong_password_block
    assert 'username="alice"' in wrong_password_block
    assert "tenant_id=user.tenant_id" in wrong_password_block
    assert "user_id=user.id" in wrong_password_block
    assert 'user_agent="login-wrong-password-audit-test"' in wrong_password_block
    assert "_assert_no_login_tokens(resp)" in wrong_password_block
    assert "user_repo.update_last_login.assert_not_awaited()" in wrong_password_block

    assert '"user-agent": "login-user-not-found-audit-test"' in user_not_found_block
    assert 'reason="invalid_credentials"' in user_not_found_block
    assert 'username="nobody"' in user_not_found_block
    assert "tenant_id=None" in user_not_found_block
    assert "user_id=None" in user_not_found_block
    assert 'user_agent="login-user-not-found-audit-test"' in user_not_found_block
    assert "_assert_no_login_tokens(resp)" in user_not_found_block
    assert "user_repo.update_last_login.assert_not_awaited()" in user_not_found_block

    assert '"user-agent": "login-inactive-user-audit-test"' in inactive_block
    assert 'reason="account_deactivated"' in inactive_block
    assert 'username="alice"' in inactive_block
    assert "tenant_id=user.tenant_id" in inactive_block
    assert "user_id=user.id" in inactive_block
    assert 'user_agent="login-inactive-user-audit-test"' in inactive_block
    assert "_assert_no_login_tokens(resp)" in inactive_block
    assert "user_repo.update_last_login.assert_not_awaited()" in inactive_block


def test_quality_ops_capture_auth_register_audit_complete_payload_contract():
    row = _quality_ops_row_containing("Auth register audit 完整 payload/脱敏契约")
    auth_routes_test = _read(AUTH_ROUTES_TEST)

    assert "Auth register audit 完整 payload/脱敏契约" in row
    assert (
        "`tests/unit/test_auth/test_auth_routes.py::TestAuditRegister::test_register_success_emits_audit` 1 passed"
        in row
    )
    assert "auth routes full 57 passed" in row
    assert "register 成功审计现在固定完整 payload `{tenant_id,user_id,action,resource_type,resource_id,after_state,ip_address,user_agent}`" in (
        row
    )
    assert "不含明文密码或 password_hash" in row
    assert "tenant/user repository 入参与 commit/no rollback" in row
    assert "只抽查 action/resource_type 和 after_state 的 username/email" in (
        row
    )
    assert "tenant_id/user_id/resource_id/user_agent 漂移" in row
    assert "注册审计测试只证明“写过一个看起来像 register 的事件”" in (
        row
    )

    register_block = _marked_block(
        auth_routes_test,
        "async def test_register_success_emits_audit",
        "class TestAuditLogout",
    )

    assert "tenant = SimpleNamespace(id=uuid4(), name=\"bob\")" in register_block
    assert "user = SimpleNamespace(" in register_block
    assert 'headers={"user-agent": "register-audit-test"}' in register_block
    assert "assert call_kwargs == {" in register_block
    assert '"tenant_id": tenant.id' in register_block
    assert '"user_id": user.id' in register_block
    assert '"action": "auth.register"' in register_block
    assert '"resource_type": "auth"' in register_block
    assert '"resource_id": None' in register_block
    assert (
        '"after_state": {"username": "bob", "email": "bob@example.com"}'
        in register_block
    )
    assert '"ip_address": "127.0.0.1"' in register_block
    assert '"user_agent": "register-audit-test"' in register_block
    assert 'assert "secure-password-1" not in rendered_audit' in register_block
    assert (
        'assert user_repo.create.await_args.kwargs["password_hash"] not in rendered_audit'
        in register_block
    )
    assert "tenant_repo.create.assert_awaited_once_with(name=\"bob\")" in (
        register_block
    )
    assert "user_repo.create.assert_awaited_once_with(" in register_block
    assert "tenant_id=tenant.id" in register_block
    assert "username=\"bob\"" in register_block
    assert "email=\"bob@example.com\"" in register_block
    assert "role=\"owner\"" in register_block
    assert "session.commit.assert_awaited_once()" in register_block
    assert "session.rollback.assert_not_awaited()" in register_block

    assert 'assert call_kwargs["action"] == "auth.register"' not in register_block
    assert 'assert call_kwargs["resource_type"] == "auth"' not in register_block
    assert 'assert call_kwargs["after_state"]["username"] == "bob"' not in (
        register_block
    )
    assert 'assert call_kwargs["after_state"]["email"] == "bob@example.com"' not in (
        register_block
    )


def test_quality_ops_capture_auth_refresh_audit_complete_client_metadata_contract():
    row = _quality_ops_row_containing("Auth refresh audit 完整 client metadata 契约")
    jti_row = _quality_ops_row_containing("Auth refresh audit new_jti 真实追踪契约")
    auth_routes_test = _read(AUTH_ROUTES_TEST)

    assert "Auth refresh audit 完整 client metadata 契约" in row
    assert (
        "`tests/unit/test_auth/test_auth_routes.py::TestAuditRefresh::test_refresh_success_emits_audit_with_jti tests/unit/test_auth/test_auth_routes.py::TestAuditRefresh::test_refresh_failed_emits_audit` 2 passed"
        in row
    )
    assert "auth routes full 57 passed" in row
    assert "refresh 成功/失败审计现在固定完整 payload" in row
    assert "`tenant_id/user_id/action/resource_type/resource_id/before_state/after_state/ip_address/user_agent`" in (
        row
    )
    assert "真实新 refresh cookie 的 jti" in jti_row
    assert "refresh token 原文不进入 audit" in row
    assert "未锁住 ip/user-agent" in row
    assert "完整 payload 防止多余字段漂移" in row
    assert "refresh 审计测试只证明“核心审计字段大概存在”" in (
        row
    )

    refresh_block = _marked_block(
        auth_routes_test,
        "async def test_refresh_success_emits_audit_with_jti",
        "async def test_refresh_failed_emits_audit",
    )
    failed_block = _marked_block(
        auth_routes_test,
        "async def test_refresh_failed_emits_audit",
        "session.rollback.assert_not_awaited()",
    )

    assert 'headers={"user-agent": "refresh-audit-test"}' in refresh_block
    assert 'new_refresh_payload = jwt_svc.decode_token(resp.cookies["refresh_token"])' in (
        refresh_block
    )
    assert 'new_jti = new_refresh_payload["jti"]' in refresh_block
    assert "assert new_jti != old_jti" in refresh_block
    assert "assert call_kwargs == {" in refresh_block
    assert '"tenant_id": user.tenant_id' in refresh_block
    assert '"user_id": user.id' in refresh_block
    assert '"action": "auth.refresh"' in refresh_block
    assert '"resource_type": "auth"' in refresh_block
    assert '"resource_id": None' in refresh_block
    assert '"before_state": {"old_jti": old_jti}' in refresh_block
    assert '"after_state": {"new_jti": new_jti}' in refresh_block
    assert '"ip_address": "127.0.0.1"' in refresh_block
    assert '"user_agent": "refresh-audit-test"' in refresh_block
    assert "assert old_refresh_token not in repr(call_kwargs)" in refresh_block
    assert "session.commit.assert_awaited_once()" in refresh_block
    assert "session.rollback.assert_not_awaited()" in refresh_block
    assert 'assert call_kwargs["action"] == "auth.refresh"' not in refresh_block
    assert 'assert call_kwargs["resource_type"] == "auth"' not in refresh_block
    assert 'assert call_kwargs["resource_id"] is None' not in refresh_block

    assert 'headers={"user-agent": "refresh-failed-audit-test"}' in failed_block
    assert "audit_repo.create.assert_awaited_once()" in failed_block
    assert "assert call_kwargs == {" in failed_block
    assert '"tenant_id": None' in failed_block
    assert '"user_id": None' in failed_block
    assert '"action": "auth.refresh_failed"' in failed_block
    assert '"resource_type": "auth"' in failed_block
    assert '"resource_id": None' in failed_block
    assert '"after_state": {"reason": "invalid_refresh_token"}' in failed_block
    assert '"ip_address": "127.0.0.1"' in failed_block
    assert '"user_agent": "refresh-failed-audit-test"' in failed_block
    assert 'assert "not-a-valid-token" not in repr(call_kwargs)' in failed_block
    assert "_assert_refresh_failed_audit(" not in failed_block
    assert "session.commit.assert_awaited_once()" in failed_block


def test_quality_ops_capture_auth_refresh_failed_audit_exact_response_contract():
    auth_routes_test = _read(AUTH_ROUTES_TEST)
    row = _quality_ops_row(
        "| 2026-05-31 | N/A（Auth refresh failed audit exact response 契约）"
    )
    failed_block = _marked_block(
        auth_routes_test,
        "async def test_refresh_failed_emits_audit",
        "session.rollback.assert_not_awaited()",
    )

    assert "Auth refresh failed audit exact response 契约" in row
    assert (
        "`tests/unit/test_auth/test_auth_routes.py::TestAuditRefresh::test_refresh_failed_emits_audit` 1 passed"
        in row
    )
    assert "release quality docs contract full 259 passed" in row
    assert "targeted ruff passed" in row
    assert '401 body `{"detail": "Invalid refresh token"}`' in row
    assert "refresh cookie 清理" in row
    assert "原始 refresh token 不进 audit payload" in row
    assert "只证明“失败审计写了”" in row

    for expected in [
        'assert resp.json() == {"detail": "Invalid refresh token"}',
        "_assert_refresh_cookie_cleared(resp)",
        "audit_repo.create.assert_awaited_once()",
        "assert call_kwargs == {",
        '"after_state": {"reason": "invalid_refresh_token"}',
        '"user_agent": "refresh-failed-audit-test"',
        'assert "not-a-valid-token" not in repr(call_kwargs)',
        "session.commit.assert_awaited_once()",
    ]:
        assert expected in failed_block
    assert (
        "assert resp.status_code == 401\n"
        "        audit_repo.create.assert_awaited_once()"
        not in failed_block
    )


def test_quality_ops_capture_auth_refresh_failure_helper_complete_payload_contract():
    row = _quality_ops_row_containing(
        "Auth refresh failure helper 完整 payload 契约"
    )
    auth_routes_test = _read(AUTH_ROUTES_TEST)

    assert "Auth refresh failure helper 完整 payload 契约" in row
    assert (
        "`tests/unit/test_auth/test_auth_routes.py::TestRefresh::test_refresh_with_access_token_rejected tests/unit/test_auth/test_auth_routes.py::TestRefresh::test_refresh_expired_token tests/unit/test_auth/test_auth_routes.py::TestRefreshRevokesOldToken::test_refresh_with_revoked_token_returns_401` 3 passed"
        in row
    )
    assert "auth routes full 57 passed" in row
    assert "refresh access-token-as-refresh、expired refresh token、revoked replay 三条失败路径" in (
        row
    )
    assert "`_assert_refresh_failed_audit` 固定完整 payload `{tenant_id,user_id,action,resource_type,resource_id,after_state,ip_address,user_agent}`" in (
        row
    )
    assert "原 token 不进入 audit" in row
    assert "cookie 清理与 audit session commit/no rollback" in row
    assert "helper 仍逐字段抽查且漏掉 ip/user-agent" in row
    assert "payload 多出敏感字段" in row
    assert "refresh 失败审计只证明“失败原因写进去了”" in row

    helper_block = _marked_block(
        auth_routes_test,
        "def _assert_refresh_failed_audit",
        "class TestAuditLogin",
    )

    assert "user_agent: str" in helper_block
    assert "assert call_kwargs == {" in helper_block
    assert '"tenant_id": None' in helper_block
    assert '"user_id": None' in helper_block
    assert '"action": "auth.refresh_failed"' in helper_block
    assert '"resource_type": "auth"' in helper_block
    assert '"resource_id": None' in helper_block
    assert '"after_state": {"reason": reason}' in helper_block
    assert '"ip_address": "127.0.0.1"' in helper_block
    assert '"user_agent": user_agent' in helper_block
    assert "for value in forbidden_values or []:" in helper_block
    assert 'assert call_kwargs["action"] == "auth.refresh_failed"' not in (
        helper_block
    )
    assert 'assert call_kwargs["resource_type"] == "auth"' not in helper_block
    assert 'assert call_kwargs["resource_id"] is None' not in helper_block

    refresh_success_block = _marked_block(
        auth_routes_test,
        "async def test_refresh_success(",
        "async def test_refresh_with_access_token_rejected",
    )
    access_token_block = _marked_block(
        auth_routes_test,
        "async def test_refresh_with_access_token_rejected",
        "async def test_refresh_expired_token",
    )
    expired_block = _marked_block(
        auth_routes_test,
        "async def test_refresh_expired_token",
        "async def test_refresh_missing_user_clears_cookie_without_revoking_token",
    )
    missing_user_block = _marked_block(
        auth_routes_test,
        "async def test_refresh_missing_user_clears_cookie_without_revoking_token",
        "async def test_refresh_with_revoked_token_returns_401",
    )
    revoked_block = _marked_block(
        auth_routes_test,
        "async def test_refresh_with_revoked_token_returns_401",
        "class TestLogoutRevokesTokens",
    )

    assert "refresh-revoked-audit-test" not in refresh_success_block
    assert "refresh-revoked-audit-test" not in missing_user_block

    assert '"user-agent": "refresh-access-token-audit-test"' in access_token_block
    assert 'reason="invalid_token_type"' in access_token_block
    assert 'user_agent="refresh-access-token-audit-test"' in access_token_block
    assert "forbidden_values=[access_token]" in access_token_block
    assert "_assert_refresh_cookie_cleared(resp)" in access_token_block
    assert "session.commit.assert_awaited_once()" in access_token_block
    assert "session.rollback.assert_not_awaited()" in access_token_block

    assert '"user-agent": "refresh-expired-audit-test"' in expired_block
    assert 'reason="invalid_refresh_token"' in expired_block
    assert 'user_agent="refresh-expired-audit-test"' in expired_block
    assert "forbidden_values=[refresh_token]" in expired_block
    assert "_assert_refresh_cookie_cleared(resp)" in expired_block
    assert "session.commit.assert_awaited_once()" in expired_block
    assert "session.rollback.assert_not_awaited()" in expired_block

    assert '"user-agent": "refresh-revoked-audit-test"' in revoked_block
    assert 'reason="revoked_refresh_token"' in revoked_block
    assert 'user_agent="refresh-revoked-audit-test"' in revoked_block
    assert "forbidden_values=[refresh_token]" in revoked_block
    assert "user_repo.get_by_id.assert_not_awaited()" in revoked_block
    assert "_assert_refresh_cookie_cleared(resp)" in revoked_block
    assert "session.commit.assert_awaited_once()" in revoked_block
    assert "session.rollback.assert_not_awaited()" in revoked_block


def test_quality_ops_capture_auth_logout_audit_complete_client_metadata_contract():
    row = _quality_ops_row_containing("Auth logout audit 完整 client metadata 契约")
    auth_routes_test = _read(AUTH_ROUTES_TEST)

    assert "Auth logout audit 完整 client metadata 契约" in row
    assert (
        "`tests/unit/test_auth/test_auth_routes.py::TestAuditLogout` 2 passed"
        in row
    )
    assert "auth routes full 57 passed" in row
    assert "logout 有/无 token 审计现在通过 helper 固定完整 payload `{tenant_id,user_id,action,resource_type,resource_id,after_state,ip_address,user_agent}`" in (
        row
    )
    assert "access/refresh token 原文不进入 audit" in row
    assert "refresh cookie 清理与 commit/no rollback" in row
    assert "helper 仍逐字段抽查且漏掉 ip/user-agent" in row
    assert "审计调用夹带多余字段" in row
    assert "logout 审计测试只证明“核心字段大概存在”" in row

    helper_block = _marked_block(
        auth_routes_test,
        "def _assert_logout_audit",
        "def _assert_refresh_failed_audit",
    )

    assert "user_agent: str" in helper_block
    assert "assert call_kwargs == {" in helper_block
    assert '"tenant_id": tenant_id' in helper_block
    assert '"user_id": user_id' in helper_block
    assert '"action": "auth.logout"' in helper_block
    assert '"resource_type": "auth"' in helper_block
    assert '"resource_id": None' in helper_block
    assert '"after_state": {"had_access_token": had_access_token}' in helper_block
    assert '"ip_address": "127.0.0.1"' in helper_block
    assert '"user_agent": user_agent' in helper_block
    assert "for value in forbidden_values or []:" in helper_block
    assert 'assert call_kwargs["action"] == "auth.logout"' not in helper_block
    assert 'assert call_kwargs["resource_type"] == "auth"' not in helper_block
    assert 'assert call_kwargs["resource_id"] is None' not in helper_block

    logout_block = _marked_block(
        auth_routes_test,
        "class TestAuditLogout",
        "class TestAuditRefresh",
    )

    assert '"user-agent": "logout-audit-test"' in logout_block
    assert 'user_agent="logout-audit-test"' in logout_block
    assert '"user-agent": "logout-empty-audit-test"' in logout_block
    assert 'user_agent="logout-empty-audit-test"' in logout_block
    assert "forbidden_values=[access_token, refresh_token]" in logout_block
    assert "_assert_refresh_cookie_cleared(resp)" in logout_block
    assert "session.commit.assert_awaited_once()" in logout_block
    assert "session.rollback.assert_not_awaited()" in logout_block


def test_quality_ops_capture_logout_revoke_redis_contract():
    row = _quality_ops_row_containing("Logout revoke Redis 参数契约")
    auth_routes_test = _read(AUTH_ROUTES_TEST)

    assert "Logout revoke Redis 参数契约" in row
    assert (
        "`tests/unit/test_auth/test_auth_routes.py::TestLogoutRevokesTokens` 4 passed"
        in row
    )
    assert "access-only、refresh-only、双 token、无 token 路径" in row
    assert "固定 204 空响应与 refresh cookie 清理" in row
    assert "access/refresh 撤销分别锁住 `redis.set` key/value 与 TTL 上界" in (
        row
    )
    assert "双 token 路径继续锁住两次 revoke 顺序" in row
    assert "无 token 路径锁住不写 Redis" in row
    assert "只断言 blacklist key 出现在内存 store" in row
    assert "TTL 缺失/过长" in row
    assert "204 响应夹带 body" in row
    assert "logout 撤销测试只证明“jti 进了某个字典”" in row

    access_block = _marked_block(
        auth_routes_test,
        "async def test_logout_revokes_access_token",
        "async def test_logout_revokes_refresh_token",
    )
    refresh_block = _marked_block(
        auth_routes_test,
        "async def test_logout_revokes_refresh_token",
        "async def test_logout_revokes_both_tokens",
    )
    both_block = _marked_block(
        auth_routes_test,
        "async def test_logout_revokes_both_tokens",
        "async def test_logout_no_tokens_still_returns_204",
    )
    no_token_block = _marked_block(
        auth_routes_test,
        "async def test_logout_no_tokens_still_returns_204",
        "class TestRevokedTokenMiddleware",
    )

    assert 'assert resp.content == b""' in access_block
    assert "redis_mock.set.assert_awaited_once()" in access_block
    assert 'redis_mock.set.await_args.args == (f"jwt:revoked:{access_jti}", "1")' in (
        access_block
    )
    assert 'redis_mock.set.await_args.kwargs["ex"] <= settings.jwt_access_token_ttl' in (
        access_block
    )
    assert "_assert_refresh_cookie_cleared(resp)" in access_block

    assert 'assert resp.content == b""' in refresh_block
    assert "redis_mock.set.assert_awaited_once()" in refresh_block
    assert 'redis_mock.set.await_args.args == (f"jwt:revoked:{refresh_jti}", "1")' in (
        refresh_block
    )
    assert 'redis_mock.set.await_args.kwargs["ex"] <= settings.jwt_refresh_token_ttl' in (
        refresh_block
    )
    assert "_assert_refresh_cookie_cleared(resp)" in refresh_block

    assert 'assert resp.content == b""' in both_block
    assert "revoke_calls = redis_mock.set.await_args_list" in both_block
    assert "assert [call.args for call in revoke_calls] == [" in both_block
    assert "(f\"jwt:revoked:{a_payload['jti']}\", \"1\")," in both_block
    assert "(f\"jwt:revoked:{r_payload['jti']}\", \"1\")," in both_block
    assert 'revoke_calls[0].kwargs["ex"] <= settings.jwt_access_token_ttl' in (
        both_block
    )
    assert 'revoke_calls[1].kwargs["ex"] <= settings.jwt_refresh_token_ttl' in (
        both_block
    )
    assert "_assert_refresh_cookie_cleared(resp)" in both_block

    assert 'assert resp.content == b""' in no_token_block
    assert "redis_mock.set.assert_not_awaited()" in no_token_block
    assert "_assert_refresh_cookie_cleared(resp)" in no_token_block


def test_quality_ops_capture_api_token_argon2_phc_parameter_exact_contract():
    token_service_test = _read(AUTH_TOKEN_SERVICE_TEST)

    row = _quality_ops_row("| 2026-05-31 | N/A（API token Argon2 PHC parameter exact 契约）")
    assert (
        "`tests/unit/test_auth/test_token_service.py::TestCreateApiToken::test_hash_is_argon2id` 1 passed"
        in row
    )
    assert "release quality docs contract full 277 passed" in row
    assert "targeted ruff passed" in row
    assert "`extract_parameters(hash_value)` 固定 PHC 参数" in row
    assert "Type.ID" in row
    assert "memory_cost 65536" in row
    assert '此前只断言 `hash_value.startswith("$argon2id$")`' in row
    assert "看起来是 Argon2id" in row

    block = _after(token_service_test, "async def test_hash_is_argon2id")
    for expected in [
        "from argon2 import Type, extract_parameters",
        "parameters = extract_parameters(hash_value)",
        '"type": parameters.type',
        '"version": parameters.version',
        '"salt_len": parameters.salt_len',
        '"hash_len": parameters.hash_len',
        '"time_cost": parameters.time_cost',
        '"memory_cost": parameters.memory_cost',
        '"parallelism": parameters.parallelism',
        '"type": Type.ID',
        '"version": 19',
        '"salt_len": 16',
        '"hash_len": 32',
        '"time_cost": 3',
        '"memory_cost": 65536',
        '"parallelism": 1',
        "assert TokenService.verify_token(secret, hash_value) is True",
    ]:
        assert expected in token_service_test
    assert 'assert hash_value.startswith("$argon2id$")' not in block


def test_quality_ops_capture_api_token_generated_format_entropy_contract():
    quality_ops = _quality_ops_rows_containing(
        "TokenService generated token 冗余 smoke 清理",
        "API token generated format/entropy 精确契约",
        "API token create secret hash 精确契约",
        "API token parser generated-shape 短路契约",
        "API token create exact response body 契约",
        "TokenService real hash repository args 契约",
    )
    auth_routes_test = _read(AUTH_ROUTES_TEST)
    token_service_test = _read(AUTH_TOKEN_SERVICE_TEST)
    auth_middleware_test = _read(AUTH_MIDDLEWARE_TEST)

    assert "TokenService generated token 冗余 smoke 清理" in quality_ops
    assert (
        "`tests/unit/test_auth/test_token_service.py::TestGenerateToken` 2 passed"
        in quality_ops
    )
    assert "完整 public format/roundtrip 契约" in quality_ops
    assert "唯一性契约改为 token_id/full_token/secret 的重复值投影必须为空" in (
        quality_ops
    )
    assert "`startswith`、三段数量、token_id 匹配、token_id 长度" in quality_ops
    assert "多条弱断言" in quality_ops
    assert "full token secret 固定复用" in quality_ops
    assert "重复值被集合长度断言吞掉上下文" in quality_ops
    assert "多条低价值用例制造覆盖感" in quality_ops
    assert "API token generated format/entropy 精确契约" in quality_ops
    assert "API token create secret hash 精确契约" in quality_ops
    assert "API token parser generated-shape 短路契约" in quality_ops
    assert "`qap_<32 hex token_id>_<64 hex secret>`" in quality_ops
    assert "`qap_<32 lowercase hex token_id>_<64 lowercase hex secret>`" in (
        quality_ops
    )
    assert "`parse_bearer_token` roundtrip" in quality_ops
    assert "畸形 qap token 固定 401 format 且不打开 DB" in quality_ops
    assert "`qap_abc123_secret456` 和带下划线 secret 视为有效" in (
        quality_ops
    )
    assert "`qap_tokenid_secret` 覆盖成功路径" in quality_ops
    assert "`qap_tok123_plain-secret` 这类非生产 token 形状" in (
        quality_ops
    )
    assert "create-token 路由测试返回一个后续无法认证的 token" in quality_ops
    assert "固化非生产生成格式" in quality_ops
    assert "hash 只接收 64 hex secret" in quality_ops
    assert "`$argon2id$` PHC 格式" in quality_ops
    assert "生成 token 第三段 secret 验证通过" in quality_ops
    assert "未锁住 secret 长度/hex/roundtrip" in quality_ops
    assert "误 hash 完整 token、token_id/user_id" in quality_ops
    assert "secret 退化成短随机值" in quality_ops
    assert "看起来像 qap token" in quality_ops
    assert "Argon2-looking hash" in quality_ops
    assert "TokenService real hash repository args 契约" in quality_ops
    assert "`create_api_token` 的真实 Argon2 hash 用例现在解析真实生成的 public token" in (
        quality_ops
    )
    assert "`repo.create` 完整 kwargs：user_id/name/token_id/secret_hash/scopes/expires_at" in (
        quality_ops
    )
    assert "只证明仓储 create 被调用一次" in quality_ops
    assert "错误 token_id 落库" in quality_ops
    assert "返回的 record 不是仓储结果" in quality_ops
    assert "仓储被碰过且 hash 看起来对" in quality_ops
    assert "def test_token_has_exact_public_format_and_entropy_lengths" in (
        token_service_test
    )
    assert "re.fullmatch(" in token_service_test
    assert "r\"qap_(?P<token_id>[0-9a-f]{32})_(?P<secret>[0-9a-f]{64})\"" in (
        token_service_test
    )
    assert 'assert match.group("token_id") == token_id' in token_service_test
    assert "assert full_token == f\"qap_{token_id}_{secret}\"" in (
        token_service_test
    )
    assert "TokenService.parse_bearer_token(full_token) == (token_id, secret)" in (
        token_service_test
    )
    assert "def test_unique_tokens" in token_service_test
    assert "generated = [TokenService.generate_token() for _ in range(100)]" in (
        token_service_test
    )
    assert "from collections import Counter" in token_service_test
    assert "def _duplicate_values(values: list[str]) -> list[str]:" in (
        token_service_test
    )
    assert "Counter(values).items()" in token_service_test
    assert "assert _duplicate_values(token_ids) == []" in token_service_test
    assert "assert _duplicate_values(full_tokens) == []" in token_service_test
    assert "assert _duplicate_values(secrets) == []" in token_service_test
    assert "assert len(set(token_ids)) == len(generated)" not in token_service_test
    assert "assert len(set(full_tokens)) == len(generated)" not in token_service_test
    assert "assert len(set(secrets)) == len(generated)" not in token_service_test
    assert "def test_format_starts_with_qap" not in token_service_test
    assert "def test_token_has_three_parts" not in token_service_test
    assert "def test_token_id_matches" not in token_service_test
    assert "def test_token_id_is_32_hex_chars" not in token_service_test
    assert 'assert full_token.startswith("qap_")' not in token_service_test
    assert "assert len(parts) == 3" not in token_service_test
    assert "result = await svc.create_api_token(user_id, \"t\", [], expires)" in (
        token_service_test
    )
    assert "assert result[\"record\"] is fake_record" in token_service_test
    assert "parsed = TokenService.parse_bearer_token(result[\"token\"])" in (
        token_service_test
    )
    assert "assert parsed is not None" in token_service_test
    assert "token_id, secret = parsed" in token_service_test
    assert "create_kwargs = mock_repo.create.await_args.kwargs" in (
        token_service_test
    )
    assert "assert create_kwargs == {" in token_service_test
    assert '"token_id": token_id' in token_service_test
    assert '"secret_hash": hash_value' in token_service_test
    assert '"scopes": []' in token_service_test
    assert '"expires_at": expires' in token_service_test
    assert "parameters = extract_parameters(hash_value)" in token_service_test
    assert '"type": Type.ID' in token_service_test
    assert '"memory_cost": 65536' in token_service_test
    assert "assert TokenService.verify_token(secret, hash_value) is True" in (
        token_service_test
    )
    assert "assert TokenService.verify_token(result[\"token\"], hash_value) is False" in (
        token_service_test
    )
    assert "assert TokenService.verify_token(user_id.hex, hash_value) is False" in (
        token_service_test
    )
    assert "mock_repo.create.assert_awaited_once()" not in token_service_test
    assert 'assert hash_value.startswith("$argon2")' not in token_service_test
    assert "VALID_API_TOKEN = f\"qap_{VALID_TOKEN_ID}_{VALID_SECRET}\"" in (
        token_service_test
    )
    assert "assert result == (VALID_TOKEN_ID, VALID_SECRET)" in (
        token_service_test
    )
    assert "def test_rejects_non_generated_token_shapes" in token_service_test
    assert '"qap_abc123_secret456"' in token_service_test
    assert '"qap_tokid_my_secret_with_underscores"' in token_service_test
    assert "assert result == (\"abc123\", \"secret456\")" not in token_service_test
    assert "def test_secret_can_contain_underscores" not in token_service_test
    assert "API_BEARER_TOKEN = f'qap_{API_TOKEN_ID}_{API_TOKEN_SECRET}'" in (
        auth_middleware_test
    )
    assert "repo.get_by_token_id.assert_awaited_once_with(API_TOKEN_ID)" in (
        auth_middleware_test
    )
    assert (
        "verify_token.assert_called_once_with(API_TOKEN_SECRET, token.secret_hash)"
        in auth_middleware_test
    )
    assert (
        "verify_token.assert_called_once_with(API_TOKEN_SECRET, token_record.secret_hash)"
        in auth_middleware_test
    )
    assert "'qap_abc123_secret456'" in auth_middleware_test
    assert "'qap_tokid_my_secret_with_underscores'" in auth_middleware_test
    assert "'qap_tokenid_secret'" not in auth_middleware_test
    assert "assert_awaited_once_with('tokenid')" not in auth_middleware_test
    assert "verify_token.assert_called_once_with('secret'" not in (
        auth_middleware_test
    )
    assert 'token_id = "c" * 32' in auth_routes_test
    assert 'token_secret = "d" * 64' in auth_routes_test
    assert "full_token = f\"qap_{token_id}_{token_secret}\"" in (
        auth_routes_test
    )
    assert "return_value=(token_id, full_token)" in auth_routes_test
    assert "hash_token.assert_called_once_with(token_secret)" in auth_routes_test
    assert "assert data == {" in auth_routes_test
    assert '"token": full_token' in auth_routes_test
    assert 'assert "hashed-secret" not in resp.text' in auth_routes_test
    assert 'data["token"] == full_token' not in auth_routes_test
    assert "assert token_secret not in str(audit_kwargs)" in auth_routes_test
    assert "assert full_token not in str(audit_kwargs)" in auth_routes_test
    assert '"qap_tok123_plain-secret"' not in auth_routes_test


def test_quality_ops_capture_auth_middleware_bearer_dispatch_exact_args_contract():
    quality_ops = _quality_ops_row_containing(
        "Auth middleware bearer dispatch exact args 契约"
    )
    auth_middleware_test = _read(AUTH_MIDDLEWARE_TEST)

    assert "Auth middleware bearer dispatch exact args 契约" in quality_ops
    assert "`get_current_user` 的 API token/JWT 分发测试现在固定" in (
        quality_ops
    )
    assert "`_authenticate_api_token(raw_bearer, container)`" in quality_ops
    assert "`_authenticate_jwt(raw_bearer, container)`" in quality_ops
    assert "`assert_awaited_once()` 证明正确认证函数被碰过" in quality_ops
    assert "碰过对应认证函数" in quality_ops
    assert "bearer token 被截断/预处理" in quality_ops

    assert "container = MagicMock()" in auth_middleware_test
    assert (
        "patch('qaplatform.api.auth.middleware._get_container', return_value=container)"
        in auth_middleware_test
    )
    assert "api_auth.assert_awaited_once_with(API_BEARER_TOKEN, container)" in (
        auth_middleware_test
    )
    assert "jwt_auth.assert_awaited_once_with('jwt-token', container)" in (
        auth_middleware_test
    )
    assert "api_auth.assert_awaited_once()" not in auth_middleware_test
    assert "jwt_auth.assert_awaited_once()" not in auth_middleware_test


def test_quality_ops_capture_api_token_last_used_success_exact_auth_flow_contract():
    auth_middleware_test = _read(AUTH_MIDDLEWARE_TEST)

    row = _quality_ops_row("| 2026-05-31 | N/A（API token last_used success exact auth flow 契约）")

    assert (
        "`tests/unit/test_auth_middleware.py::test_authenticate_api_token_returns_current_user_and_updates_last_used` 1 passed"
        in row
    )
    assert "auth middleware full 45 passed" in row
    assert "release quality docs contract full 218 passed" in row
    assert "targeted ruff passed" in row
    assert "`TokenService.verify_token(API_TOKEN_SECRET, token.secret_hash)`" in row
    assert "完整 `CurrentUser` 等值" in row
    assert "`update_last_used(token, utc_datetime)` 时间窗口与空 kwargs" in row
    assert "commit/no rollback" in row
    assert "此前只逐字段抽查 user" in row
    assert "last_used 使用非 UTC 或额外 kwargs" in row
    assert "返回用户字段大概对且更新过 last_used" in row

    block = _marked_block(
        auth_middleware_test,
        "async def test_authenticate_api_token_returns_current_user_and_updates_last_used",
        "async def test_authenticate_api_token_rolls_back_last_used_failure_but_allows_user",
    )

    assert "started_at = datetime.now(timezone.utc)" in block
    assert "finished_at = datetime.now(timezone.utc)" in block
    assert "assert user == CurrentUser(" in block
    for expected_field in [
        "user_id=str(token.user_id)",
        "role='developer'",
        "tenant_id=str(token.user.tenant_id)",
        "is_platform_admin=False",
        "scopes=['runs:read', 'runs:write']",
    ]:
        assert expected_field in block
    assert "repo.get_by_token_id.assert_awaited_once_with(API_TOKEN_ID)" in block
    assert "verify_token.assert_called_once_with(API_TOKEN_SECRET, token.secret_hash)" in (
        block
    )
    assert "repo.update_last_used.assert_awaited_once()" in block
    assert "update_args = repo.update_last_used.await_args.args" in block
    assert "assert update_args[0] is token" in block
    assert "assert started_at <= update_args[1] <= finished_at" in block
    assert "assert update_args[1].tzinfo is timezone.utc" in block
    assert "assert repo.update_last_used.await_args.kwargs == {}" in block
    assert "session.commit.assert_awaited_once_with()" in block
    assert "session.rollback.assert_not_awaited()" in block

    assert "assert user.user_id == str(token.user_id)" not in block
    assert "assert user.scopes == ['runs:read', 'runs:write']" not in block
    assert "assert repo.update_last_used.await_args.args[1].tzinfo is not None" not in (
        block
    )
    assert "session.commit.assert_awaited_once()" not in block


def test_quality_ops_capture_jwt_blacklist_lookup_exact_jti_fail_open_contract():
    auth_middleware_test = _read(AUTH_MIDDLEWARE_TEST)

    row = _quality_ops_row("| 2026-05-31 | N/A（JWT blacklist lookup exact jti/fail-open 契约）")

    assert (
        "`tests/unit/test_auth_middleware.py::test_authenticate_jwt_passes_when_blacklist_lookup_fails "
        "tests/unit/test_auth_middleware.py::test_authenticate_jwt_rejects_when_token_actually_revoked` "
        "2 passed"
        in row
    )
    assert "auth middleware full 45 passed" in row
    assert "release quality docs contract full 204 passed" in row
    assert "targeted ruff passed" in row
    assert "`JWTService.is_revoked(jti)` 的 exact await 参数" in row
    assert "401 `Token has been revoked` 与 no DB session" in row
    assert "拿错 jti 查 blacklist" in row
    assert "detail 包含 `revoked`" in row
    assert "Redis 被碰过/错误里有 revoked" in row

    fail_open_block = _marked_block(
        auth_middleware_test,
        "async def test_authenticate_jwt_passes_when_blacklist_lookup_fails",
        "async def test_authenticate_jwt_rejects_when_token_actually_revoked",
    )
    revoked_block = _marked_block(
        auth_middleware_test,
        "async def test_authenticate_jwt_rejects_when_token_actually_revoked",
        "async def test_get_current_user_rejects_missing_authorization_header",
    )

    assert ") as is_revoked:" in fail_open_block
    assert "is_revoked.assert_awaited_once_with(jti)" in fail_open_block
    assert "assert mock_container.db_session_factory is None" in fail_open_block
    assert "assert result == CurrentUser(" in fail_open_block
    assert "assert isinstance(result, CurrentUser)" not in fail_open_block
    assert ") as is_revoked:" in revoked_block
    assert "is_revoked.assert_awaited_once_with(jti)" in revoked_block
    assert "assert exc_info.value.detail == 'Token has been revoked'" in revoked_block
    assert "assert 'revoked' in exc_info.value.detail.lower()" not in revoked_block


def test_quality_ops_capture_auth_revoked_access_route_exact_rejection_contract():
    auth_routes_test = _read(AUTH_ROUTES_TEST)

    row = _quality_ops_row("| 2026-05-31 | N/A（Auth revoked access middleware route exact rejection 契约）")

    assert (
        "`tests/unit/test_auth/test_auth_routes.py::TestRevokedTokenMiddleware::test_revoked_access_token_returns_401` "
        "1 passed"
        in row
    )
    assert "auth routes full 57 passed" in row
    assert "release quality docs contract full 221 passed" in row
    assert "targeted ruff passed" in row
    assert '401 body `{"detail": "Token has been revoked"}`' in row
    assert "Redis blacklist exact `jwt:revoked:{jti}` 查询" in row
    assert "不打开 DB session" in row
    assert "不回显 access token 或 jti" in row
    assert "只断言 detail 包含 `revoked`" in row
    assert "查错 jti" in row
    assert "拒绝路径误进 DB" in row
    assert "返回了某个含 revoked 的 401" in row

    block = _marked_block(
        auth_routes_test,
        "async def test_revoked_access_token_returns_401",
        "async def test_jti_missing_token_passes_through",
    )

    assert "container.db_session_factory = MagicMock(" in block
    assert "revoked access token must not open DB sessions" in block
    assert 'assert resp.json() == {"detail": "Token has been revoked"}' in block
    assert "redis_mock.exists.assert_awaited_once_with(f\"jwt:revoked:{jti}\")" in block
    assert "container.db_session_factory.assert_not_called()" in block
    assert "assert access_token not in resp.text" in block
    assert "assert jti not in resp.text" in block
    assert 'assert "revoked" in resp.json()["detail"].lower()' not in block
    assert "container.db_session_factory = None" not in block


def test_quality_ops_capture_api_token_last_used_failure_exact_auth_flow_contract():
    quality_ops = _quality_ops_row_containing(
        "API token last_used failure exact auth flow 契约"
    )
    auth_middleware_test = _read(AUTH_MIDDLEWARE_TEST)

    assert "API token last_used failure exact auth flow 契约" in quality_ops
    assert (
        "`_authenticate_api_token` 的 last_used 更新失败降级用例现在固定 token id 查询"
        in quality_ops
    )
    assert "`TokenService.verify_token(API_TOKEN_SECRET, token.secret_hash)`" in (
        quality_ops
    )
    assert "`update_last_used(token, aware_datetime)`" in quality_ops
    assert "rollback/no commit" in quality_ops
    assert "`verify_token.assert_called_once()`、role、rollback" in quality_ops
    assert "拿错 token hash" in quality_ops
    assert "降级返回丢 scopes" in quality_ops
    assert "校验函数被碰过且回滚了" in quality_ops

    block = _marked_block(
        auth_middleware_test,
        "async def test_authenticate_api_token_rolls_back_last_used_failure_but_allows_user",
        "@pytest.mark.asyncio\n@pytest.mark.parametrize",
    )

    assert "token = _api_token_record(" in block
    assert "secret_hash='stored-secret-hash'" in block
    assert "scopes=['runs:read', 'runs:write']" in block
    assert "repo.get_by_token_id.assert_awaited_once_with(API_TOKEN_ID)" in block
    assert "verify_token.assert_called_once_with(API_TOKEN_SECRET, token.secret_hash)" in (
        block
    )
    assert "repo.update_last_used.assert_awaited_once()" in block
    assert "assert repo.update_last_used.await_args.args[0] is token" in block
    assert "assert repo.update_last_used.await_args.args[1].tzinfo is not None" in block
    assert "assert repo.update_last_used.await_args.kwargs == {}" in block
    assert "session.commit.assert_not_awaited()" in block
    assert "session.rollback.assert_awaited_once()" in block
    assert "assert user.scopes == ['runs:read', 'runs:write']" in block
    assert "verify_token.assert_called_once()" not in block


def test_quality_ops_capture_auth_middleware_exact_exception_detail_sweep_contract():
    auth_middleware_test = _read(AUTH_MIDDLEWARE_TEST)

    row = _quality_ops_row(
        "| 2026-05-31 | N/A（Auth middleware exact exception detail sweep 契约） | `tests/unit/test_auth_middleware.py::test_get_current_user_rejects_missing_authorization_header tests/unit/test_auth_middleware.py::test_authenticate_jwt_rejects_expired_tokens tests/unit/test_auth_middleware.py::test_authenticate_api_token_rejects_malformed_token_without_database tests/unit/test_auth_middleware.py::test_authenticate_api_token_rejects_when_database_unavailable` 4 passed；auth middleware full 45 passed；release quality docs contract full 273 passed"
    )

    assert "missing Authorization、expired JWT、malformed API token、API token DB unavailable" in row
    assert "`Missing Authorization header`" in row
    assert "`Token has expired`" in row
    assert "`Invalid API token format`" in row
    assert "`API token authentication not available`" in row
    assert "不查 blacklist/不打开 DB" in row
    assert "此前只用 `detail.lower()` 子串匹配" in row
    assert "token、claim、数据库状态、debug hint" in row
    assert "不同认证路径文案串线" in row
    assert "错误大概提到了 authorization/expired/format/unavailable" in row

    for expected in [
        "assert exc_info.value.detail == 'Missing Authorization header'",
        "assert exc_info.value.detail == 'Token has expired'",
        "assert exc_info.value.detail == 'Invalid API token format'",
        "assert exc_info.value.detail == 'API token authentication not available'",
    ]:
        assert expected in auth_middleware_test

    for weak_assert in [
        "assert 'authorization' in exc_info.value.detail.lower()",
        "assert 'expired' in exc_info.value.detail.lower()",
        "assert 'format' in exc_info.value.detail.lower()",
        "assert 'not available' in exc_info.value.detail.lower()",
    ]:
        assert weak_assert not in auth_middleware_test


def test_quality_ops_capture_api_token_invalid_records_exact_denial_detail_contract():
    auth_middleware_test = _read(AUTH_MIDDLEWARE_TEST)

    row = _quality_ops_row(
        "| 2026-05-31 | N/A（API token invalid records exact denial detail 契约） | `tests/unit/test_auth_middleware.py::test_authenticate_api_token_rejects_invalid_records` 8 passed；auth middleware full 45 passed；release quality docs contract full 272 passed"
    )

    assert "API token 无记录、已撤销、owner/tenant 失效、secret 错误" in row
    assert "`Invalid or revoked API token`" in row
    assert "secret 匹配后过期才固定 `API token has expired`" in row
    assert "不回显 token_id、secret 或完整 bearer token" in row
    assert "此前只用 detail 子串匹配" in row
    assert "失效原因被细分" in row
    assert "过期顺序回退" in row
    assert "token id/secret/debug 信息" in row
    assert "detail 大概含 invalid/expired" in row

    block = _marked_block_or_tail(
        auth_middleware_test,
        "(None, True, 'Invalid or revoked API token')",
        "\n\n@pytest.mark.asyncio",
    )

    assert "(None, True, 'Invalid or revoked API token')" in block
    assert "(_api_token_record(is_revoked=True), True, 'Invalid or revoked API token')" in (
        block
    )
    assert "'API token has expired'" in block
    assert "(_api_token_record(user_is_active=False), True, 'Invalid or revoked API token')" in (
        block
    )
    assert "(_api_token_record(), False, 'Invalid or revoked API token')" in block
    assert "assert exc_info.value.detail == expected_detail" in block
    assert "assert API_TOKEN_ID not in exc_info.value.detail" in block
    assert "assert API_TOKEN_SECRET not in exc_info.value.detail" in block
    assert "assert API_BEARER_TOKEN not in exc_info.value.detail" in block
    assert "expected_detail in exc_info.value.detail.lower()" not in block


def test_quality_ops_capture_auth_login_tenant_lookup_last_login_exact_contract():
    auth_routes_test = _read(AUTH_ROUTES_TEST)
    row = _quality_ops_row(
        "| 2026-05-31 | N/A（Auth login tenant lookup/last_login exact 契约）"
    )

    assert "Auth login tenant lookup/last_login exact 契约" in row
    assert (
        "`tests/unit/test_auth/test_auth_routes.py::TestLogin::test_login_success tests/unit/test_auth/test_auth_routes.py::TestLogin::test_login_wrong_password tests/unit/test_auth/test_auth_routes.py::TestLogin::test_login_user_not_found tests/unit/test_auth/test_auth_routes.py::TestLogin::test_login_inactive_user` 4 passed"
        in row
    )
    assert "auth routes full 57 passed" in row
    assert "release quality docs contract full 188 passed" in row
    assert "resolver 返回的 tenant_id 调用 `user_repo.get_by_username`" in row
    assert "last_login timestamp 落在请求窗口且 timezone-aware" in row
    assert "此前只让 `get_by_username` 的 AsyncMock 返回目标用户/None" in row
    assert "未校验 tenant scope" in row
    assert "跨租户宽查询" in row
    assert "只证明“登录结果和审计看起来对”" in row

    success_block = _marked_block(
        auth_routes_test,
        "async def test_login_success",
        "async def test_login_wrong_password",
    )
    wrong_password_block = _marked_block(
        auth_routes_test,
        "async def test_login_wrong_password",
        "async def test_login_user_not_found",
    )
    user_not_found_block = _marked_block(
        auth_routes_test,
        "async def test_login_user_not_found",
        "async def test_login_inactive_user",
    )
    inactive_block = _marked_block(
        auth_routes_test,
        "async def test_login_inactive_user",
        "# --- Register tests ---",
    )

    for expected in [
        "tenant_id = uuid4()",
        "before_login = datetime.now(timezone.utc)",
        "after_login = datetime.now(timezone.utc)",
        "mock_resolve.assert_awaited_once_with(session, None)",
        'user_repo.get_by_username.assert_awaited_once_with(tenant_id, "alice")',
        "assert before_login <= last_login_args[1] <= after_login",
        "assert last_login_args[1].tzinfo is timezone.utc",
    ]:
        assert expected in success_block

    for block, expected_username in [
        (wrong_password_block, "alice"),
        (user_not_found_block, "nobody"),
        (inactive_block, "alice"),
    ]:
        assert "tenant_id = uuid4()" in block
        assert "mock_resolve.assert_awaited_once()" in block
        assert "assert mock_resolve.await_args.args[1] is None" in block
        assert (
            f'user_repo.get_by_username.assert_awaited_once_with(tenant_id, "{expected_username}")'
            in block
        )


def test_quality_ops_capture_jwt_no_jti_pass_through_exact_no_blacklist_contract():
    auth_routes_test = _read(AUTH_ROUTES_TEST)
    row = _quality_ops_row(
        "| 2026-05-31 | N/A（JWT no-jti pass-through exact no-blacklist 契约）"
    )

    assert "JWT no-jti pass-through exact no-blacklist 契约" in row
    assert (
        "`tests/unit/test_auth/test_auth_routes.py::TestRevokedTokenMiddleware::test_jti_missing_token_passes_through` 1 passed"
        in row
    )
    assert "完整响应体" in row
    assert "`{\"user_id\": user_id}`" in row
    assert "不查询 Redis revoked blacklist" in row
    assert "不回显原 JWT" in row
    assert "只断言 status 200 与局部 `user_id`" in row
    assert "legacy token 没被拒绝" in row

    block = _marked_block(
        auth_routes_test,
        "async def test_jti_missing_token_passes_through",
        "# ---------------------------------------------------------------------------",
    )

    for expected in [
        'assert resp.json() == {"user_id": user_id}',
        "redis_mock.exists.assert_not_awaited()",
        "assert token_no_jti not in resp.text",
    ]:
        assert expected in block
    assert 'assert resp.json()["user_id"] == user_id' not in block
