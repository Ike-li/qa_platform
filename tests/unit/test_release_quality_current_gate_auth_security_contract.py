from __future__ import annotations

from pathlib import Path

from tests.unit.release_quality_contract_helpers import (
    _quality_ops_row,
    _read,
)

ROOT = Path(__file__).resolve().parents[2]
AUTH_JWT_SERVICE_TEST = ROOT / "tests" / "unit" / "test_auth" / "test_jwt_service.py"


def test_quality_ops_records_current_gate_auth_security_evidence():
    auth_jwt_service_test = _read(AUTH_JWT_SERVICE_TEST)
    auth_audit_wrong_password_row = _quality_ops_row(
        "| 2026-05-30 | `RUN_INTEGRATION_TESTS=1 "
        "tests/integration/test_auth_audit_failure_paths.py::"
        "test_login_nonexistent_user_returns_401_not_500 "
        "tests/integration/test_auth_audit_failure_paths.py::"
        "test_auth_login_rate_limit_uses_real_redis_token_hash_bucket "
        "tests/integration/test_auth_audit_failure_paths.py::"
        "test_login_nonexistent_user_returns_401_when_audit_write_fails "
        "tests/integration/test_auth_audit_failure_paths.py::"
        "test_login_valid_user_wrong_password_returns_401_with_tenant_id`"
    )
    api_token_secret_before_expiry_row = _quality_ops_row(
        "| 2026-05-30 | N/A（API token secret-before-expiry 防枚举契约）"
    )
    api_token_owner_status_row = _quality_ops_row(
        "| 2026-05-30 | N/A（API token owner status 防失效账号继续访问契约）"
    )
    jwt_current_user_lifecycle_row = _quality_ops_row(
        "| 2026-05-30 | N/A（JWT current-user lifecycle 防陈旧权限契约）"
    )
    jwt_invalid_short_circuit_row = _quality_ops_row(
        "| 2026-05-30 | N/A（JWT invalid/revoked 前置短路契约）"
    )
    auth_middleware_claim_shape_row = _quality_ops_row(
        "| 2026-05-30 | N/A（Auth middleware JWT claim shape 防泄漏契约）"
    )
    jwt_decode_failure_row = _quality_ops_row(
        "| 2026-05-30 | N/A（JWT decode 失败原因与不泄密契约）"
    )
    jwt_tampered_payload_row = _quality_ops_row(
        "| 2026-05-31 | N/A（JWT tampered payload decode 精确契约）"
    )
    auth_logout_audit_row = _quality_ops_row(
        "| 2026-05-30 | N/A（Auth logout audit payload/transaction 契约）"
    )
    auth_refresh_audit_row = _quality_ops_row(
        "| 2026-05-30 | N/A（Auth refresh audit resource_id/token 契约）"
    )
    assert "revoked JWT 固定在 blacklist 命中后 401 且不打开 DB" in (
        jwt_invalid_short_circuit_row
    )
    assert "expired、invalid 和 refresh token type 固定在 decode/type 阶段 401" in (
        jwt_invalid_short_circuit_row
    )
    assert "不查 blacklist、不打开 DB" in jwt_invalid_short_circuit_row
    assert "认证拒绝测试只证明状态码" in jwt_invalid_short_circuit_row
    assert "4 passed" in auth_audit_wrong_password_row
    assert "username pattern 和 32 字符上限" in auth_audit_wrong_password_row
    assert "真实命中登录业务路径" in auth_audit_wrong_password_row
    assert "unknown user 和 audit outage 固定 401" in auth_audit_wrong_password_row
    assert "token-bucket login rate limit 前 5 次固定 401 且第 6 次 429" in (
        auth_audit_wrong_password_row
    )
    assert "精确 tenant_id/user_id" in auth_audit_wrong_password_row
    assert "正确密码和错误密码都不进 audit payload" in auth_audit_wrong_password_row
    assert "`rate-limit-missing-*`" in auth_audit_wrong_password_row
    assert "部分还超过 32 字符" in auth_audit_wrong_password_row
    assert "请求体验证阶段 422" in auth_audit_wrong_password_row
    assert (
        "没有证明 unknown-user、audit outage、rate-limit bucket 或“已知用户错密码”审计路径"
        in (auth_audit_wrong_password_row)
    )
    assert "`tests/unit/test_auth_middleware.py` 29 passed" in (
        api_token_secret_before_expiry_row
    )
    assert "coverage unit 1269 passed" in api_token_secret_before_expiry_row
    assert "先验证 secret" in api_token_secret_before_expiry_row
    assert "secret 匹配后返回 expired" in api_token_secret_before_expiry_row
    assert "伪造 secret 即使命中过期 token_id" in (api_token_secret_before_expiry_row)
    assert "`Invalid or revoked API token`" in api_token_secret_before_expiry_row
    assert "不更新 last_used" in api_token_secret_before_expiry_row
    assert "旧单测把“过期 token 不调用 `TokenService.verify_token()`”锁成期望" in (
        api_token_secret_before_expiry_row
    )
    assert "枚举 token 存在和状态" in api_token_secret_before_expiry_row
    assert "避免认证测试固化错误短路顺序" in (api_token_secret_before_expiry_row)
    assert "`tests/unit/test_auth_middleware.py` 32 passed" in (
        api_token_owner_status_row
    )
    assert "coverage unit 1272 passed" in api_token_owner_status_row
    assert "secret 匹配后还会拒绝 inactive owner" in (api_token_owner_status_row)
    assert "soft-deleted owner" in api_token_owner_status_row
    assert "soft-deleted tenant" in api_token_owner_status_row
    assert "不更新 last_used" in api_token_owner_status_row
    assert "旧实现只检查 token revoked/expired" in api_token_owner_status_row
    assert "不检查 owner 生命周期" in api_token_owner_status_row
    assert "机器 token 仍可构造 `CurrentUser`" in (api_token_owner_status_row)
    assert "避免 API token 测试只证明 token 行本身有效" in (api_token_owner_status_row)
    assert "`tests/unit/test_auth_middleware.py` 39 passed" in (
        jwt_current_user_lifecycle_row
    )
    assert (
        "`tests/unit/test_auth_middleware.py tests/unit/test_auth/test_auth_routes.py` 100 passed"
        in (jwt_current_user_lifecycle_row)
    )
    assert "coverage unit 1279 passed" in jwt_current_user_lifecycle_row
    assert "回查当前 user row" in jwt_current_user_lifecycle_row
    assert "missing/inactive/soft-deleted user" in (jwt_current_user_lifecycle_row)
    assert "soft-deleted tenant" in jwt_current_user_lifecycle_row
    assert "tenant/role 漂移" in jwt_current_user_lifecycle_row
    assert "legacy 无 `jti` token" in jwt_current_user_lifecycle_row
    assert "旧 middleware 只对 platform-admin claim 查 DB" in (
        jwt_current_user_lifecycle_row
    )
    assert "普通 JWT 在账号停用、租户软删除或角色降级后" in (
        jwt_current_user_lifecycle_row
    )
    assert "避免 JWT 测试只证明签名和 claim shape" in (jwt_current_user_lifecycle_row)
    assert "`tests/unit/test_auth_middleware.py` 28 passed" in (
        auth_middleware_claim_shape_row
    )
    assert "非 UUID `sub`/`tenant_id`" in auth_middleware_claim_shape_row
    assert "非字符串 `role`" in auth_middleware_claim_shape_row
    assert "空 `jti`" in auth_middleware_claim_shape_row
    assert "非 bool `is_platform_admin`" in auth_middleware_claim_shape_row
    assert "401 `Invalid token claims`" in auth_middleware_claim_shape_row
    assert "不查 Redis blacklist" in auth_middleware_claim_shape_row
    assert "不打开 DB session" in auth_middleware_claim_shape_row
    assert "不回显 claim secret" in auth_middleware_claim_shape_row
    assert "后续 UUID 转换、权限矩阵或 blacklist/DB 副作用" in (
        auth_middleware_claim_shape_row
    )
    assert "claims shape 校验前移到认证边界" in (auth_middleware_claim_shape_row)
    assert "JWT 测试只证明明显缺字段会失败" in (auth_middleware_claim_shape_row)
    assert (
        "`tests/unit/test_auth/test_jwt_service.py::TestDecodeToken::test_raises_on_expired_token tests/unit/test_auth/test_jwt_service.py::TestDecodeToken::test_raises_on_wrong_secret tests/unit/test_auth/test_jwt_service.py::TestDecodeToken::test_raises_on_malformed_token` 3 passed"
        in (jwt_decode_failure_row)
    )
    assert "JWT decode 三条失败用例从 raises-only 补成精确 PyJWT 原因与不泄密契约" in (
        jwt_decode_failure_row
    )
    assert "只靠异常类型和 message 片段" in jwt_decode_failure_row
    assert "错误文本回显 token、subject/role claims 或不同 secret" in (
        jwt_decode_failure_row
    )
    assert "exact exception type、`args`" in jwt_decode_failure_row
    assert "不包含原 token、`u1`、`viewer` 或 `different-secret`" in (
        jwt_decode_failure_row
    )
    assert "认证 token 解码测试只为异常覆盖率服务" in jwt_decode_failure_row
    assert (
        "`tests/unit/test_auth/test_jwt_service.py::TestDecodeToken::test_raises_on_tampered_payload` 1 passed"
        in (jwt_tampered_payload_row)
    )
    assert "固定抛出 `jwt.InvalidSignatureError`" in jwt_tampered_payload_row
    assert '`args == ("Signature verification failed",)`' in (jwt_tampered_payload_row)
    assert "不包含原 token、篡改 token、`u1` 或 `viewer` claim" in (
        jwt_tampered_payload_row
    )
    assert '只断言 `"Signature verification failed"` 出现在异常字符串里' in (
        jwt_tampered_payload_row
    )
    assert "异常类型退化、args 漂移" in jwt_tampered_payload_row
    assert "某段签名失败文案出现过" in jwt_tampered_payload_row
    assert "with pytest.raises(jwt.InvalidSignatureError) as exc_info" in (
        auth_jwt_service_test
    )
    assert "assert exc_info.type is jwt.InvalidSignatureError" in (
        auth_jwt_service_test
    )
    assert 'assert exc_info.value.args == ("Signature verification failed",)' in (
        auth_jwt_service_test
    )
    assert "assert tampered not in str(exc_info.value)" in auth_jwt_service_test
    assert 'assert "Signature verification failed" in str(exc_info.value)' not in (
        auth_jwt_service_test
    )
    assert "`tests/unit/test_auth/test_auth_routes.py::TestAuditLogout` 2 passed" in (
        auth_logout_audit_row
    )
    assert "`tests/unit/test_auth/test_auth_routes.py` 51 passed" in (
        auth_logout_audit_row
    )
    assert "`resource_id=None`" in auth_logout_audit_row
    assert "raw access/refresh token 不入审计 payload" in auth_logout_audit_row
    assert "audit session commit/rollback 边界" in auth_logout_audit_row
    assert "`tests/unit/test_auth/test_auth_routes.py` 51 passed" in (
        auth_refresh_audit_row
    )
    assert "`tests/unit/test_architecture_boundaries.py` 17 passed" in (
        auth_refresh_audit_row
    )
    assert (
        "`auth.refresh` 与 `auth.refresh_failed` 审计现在显式写 `resource_id=None`"
        in (auth_refresh_audit_row)
    )
    assert "raw refresh/access token 不入审计 payload" in auth_refresh_audit_row
