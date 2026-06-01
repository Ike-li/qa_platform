from __future__ import annotations

from pathlib import Path

from tests.unit.release_quality_contract_helpers import (
    _quality_ops_row,
    _read,
)

ROOT = Path(__file__).resolve().parents[2]
README = ROOT / "README.md"
ARCHITECTURE = ROOT / "docs" / "architecture.md"
BACKEND_TEST_AUDIT = ROOT / "docs" / "backend-test-audit.md"
TODO = ROOT / "docs" / "TODO.md"
FEATURE_CATALOG = ROOT / "docs" / "feature-catalog.md"


def test_quality_ops_records_current_gate_evidence():
    notification_json_object_row = _quality_ops_row(
        "| 2026-05-30 | N/A（DingTalk/WeCom JSON object 响应契约）"
    )
    webhook_url_userinfo_row = _quality_ops_row(
        "| 2026-05-30 | N/A（Webhook URL userinfo 防凭据嵌入契约）"
    )
    webhook_provider_dedup_row = _quality_ops_row(
        "| 2026-05-30 | N/A（Webhook provider/dedup route 契约）"
    )
    dep_audit_row = _quality_ops_row(
        "| 2026-05-30 | N/A（frontend runtime dependency audit 复核）"
    )
    dep_risk_row = _quality_ops_row("| RISK-DEP-001 |")
    audit_route_row = _quality_ops_row(
        "| 2026-05-30 | N/A（mutating API route 审计写入架构契约）"
    )
    readme = _read(README)
    todo = _read(TODO)
    architecture = _read(ARCHITECTURE)
    backend_test_audit = _read(BACKEND_TEST_AUDIT)
    feature_catalog = _read(FEATURE_CATALOG)

    assert "`tests/unit/test_worker/test_channels.py` 38 passed" in (
        notification_json_object_row
    )
    assert "coverage unit 1282 passed" in notification_json_object_row
    assert "JSON body 必须是 object" in notification_json_object_row
    assert "`invalid JSON object` 失败" in notification_json_object_row
    assert "不抛 `AttributeError`" in notification_json_object_row
    assert "不回显 access_token、secret 或 webhook_key" in (
        notification_json_object_row
    )
    assert "已有渠道测试覆盖 HTTP 500、errcode 和 JSON decode 失败" in (
        notification_json_object_row
    )
    assert "能 decode、形状错误" in notification_json_object_row
    assert "避免渠道测试只证明正常 object JSON 和明显 parse error" in (
        notification_json_object_row
    )

    assert (
        "`tests/unit/test_worker/test_channels.py::TestWebhookChannel::test_rejects_url_credentials_before_dns_or_http_client` 1 passed"
    ) in webhook_url_userinfo_row
    assert "`tests/unit/test_worker/test_channels.py` 36 passed" in (
        webhook_url_userinfo_row
    )
    assert "coverage unit 1280 passed" in webhook_url_userinfo_row
    assert "generic webhook URL 现在拒绝 `user:password@host`" in (
        webhook_url_userinfo_row
    )
    assert "DNS 解析和 HTTP client 创建前短路" in webhook_url_userinfo_row
    assert "不回显 token/userinfo" in webhook_url_userinfo_row
    assert "总覆盖率 87.35%" in webhook_url_userinfo_row
    assert "branches 78.61%" in webhook_url_userinfo_row
    assert "用例多数 patch 掉 `_validate_webhook_url`" in (webhook_url_userinfo_row)
    assert "no-DNS/no-HTTP/no-secret echo" in webhook_url_userinfo_row
    assert "避免 webhook channel 测试只证明“可发送”和“私网 IP 被挡”" in (
        webhook_url_userinfo_row
    )

    assert "`tests/unit/test_api/test_p3.py` 60 passed" in webhook_provider_dedup_row
    assert "coverage unit 1255 passed" in webhook_provider_dedup_row
    assert "项目级 dedup 预命中不创建 run" in webhook_provider_dedup_row
    assert "签名错误在 RBAC 前短路" in webhook_provider_dedup_row
    assert "GitHub provider 签名错误/歧义匹配不触发 run" in (webhook_provider_dedup_row)
    assert "provider 成功路径使用系统身份" in webhook_provider_dedup_row
    assert "provider/delivery/repository metadata" in webhook_provider_dedup_row
    assert "覆盖率从 83% 提升到 92%" in webhook_provider_dedup_row
    assert "dedup 预检查被绕过" in webhook_provider_dedup_row
    assert "多个同仓库项目同时验签后误选一个项目" in webhook_provider_dedup_row
    assert "五条 route 级契约" in webhook_provider_dedup_row

    assert "`npm audit --prefix frontend --audit-level=moderate` 0 vulnerabilities" in (
        dep_audit_row
    )
    assert "`dompurify` runtime 依赖锁定为 `3.4.7`" in dep_audit_row
    assert "不能只凭本地 audit 直接关闭" in dep_audit_row
    assert (
        "当前分支 `npm audit --prefix frontend --audit-level=moderate` 返回 0 vulnerabilities"
        in (dep_risk_row)
    )
    assert "Dependabot alerts 在默认分支关闭的证据" in dep_risk_row

    assert "`tests/unit/test_architecture_boundaries.py` 17 passed" in audit_route_row
    assert "直接写审计或委托 `_create_webhook_run`" in audit_route_row
    assert "仅出现 repository constructor 不算通过" in audit_route_row
    assert "直接审计写入还必须显式携带 `resource_id`" in audit_route_row
    assert "API 写路径审计基线由架构契约锁住" in readme
    assert "新增写路径仍需按不含 PII/Secret 的 schema 补回归" not in readme
    assert "test_mutating_api_routes_keep_audit_write_contract" in todo
    assert "当前 API POST/PUT/PATCH/DELETE 路由由架构契约锁住" in architecture
    assert "新增写接口必须同步补审计与敏感字段脱敏回归" in architecture
    assert "当前 API POST/PUT/PATCH/DELETE 路由由 AST 架构契约锁住" in feature_catalog
    assert "剩余写操作按安全风险继续补齐" not in feature_catalog
    assert "审计写入覆盖已由 AST 架构契约守住" in backend_test_audit
    assert "尚未进入业务矩阵的写路径" not in backend_test_audit
