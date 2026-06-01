from __future__ import annotations

from tests.unit.release_quality_contract_helpers import _quality_ops_row


CURRENT_GATE_SUMMARY_REVIEW_ITEMS = (
    "API token 请求体验证",
    "API token create 空白文本请求体验证",
    "Auth login 请求体验证短路验证",
    "Auth register password 文本边界验证",
    "Analytics 查询成功路径仓储/RBAC 验证",
    "Notification rule update 条件/渠道归一化验证",
    "Worker notification project_name 懒加载验证",
    "Worker notification log write 异常语义验证",
    "Webhook provider/dedup route 验证",
    "Dependency transaction boundary 验证",
    "Run repository scheduler lock 验证",
    "Schedule repository due lock 验证",
    "API token secret-before-expiry 验证",
    "API token owner status 验证",
    "JWT current-user lifecycle 验证",
    "Webhook URL userinfo 防凭据嵌入验证",
    "Admin status terminal denominator 验证",
    "DingTalk/WeCom JSON object 响应验证",
    "JUnit duration 输入容错验证",
    "Jest/Playwright JUnit parent 目录验证",
    "GitSource non-public DNS 防 SSRF 验证",
    "GitSource rev-parse 失败/空 SHA 验证",
    "GitSource URL scheme/SSH 判定顺序验证",
    "Runner test_paths 工作区边界验证",
    "Runner test_paths 空白路径验证",
    "Go runner malformed event/elapsed 验证",
    "Env vars truncated ciphertext 防泄漏验证",
    "Encryption keys rotation 配置边界验证",
    "Required config blank values 启动期验证",
    "Log config invalid value 启动期验证",
    "Numeric config invalid bounds 启动期验证",
    "Trusted proxies CIDR 启动期验证",
    "Default string config blank 启动期验证",
    "审计架构边界测试",
    "GitHub provider webhook SHA 验证",
    "GitHub provider ref 空白 payload 验证",
    "batch run_ids 唯一性验证",
    "batch internal failure 防泄漏验证",
    "Auth middleware JWT claim shape 防泄漏验证",
    "pipeline selector/retry policy/trigger_config 请求体验证",
    "pipeline core text 请求体验证",
    "pipeline selector/retry 列表文本请求体验证",
    "domain pipeline 配置文本验证",
    "webhook git_sha 请求体验证",
    "webhook git_sha 空白请求体验证",
    "run results 文本过滤请求参数验证",
    "run list sort/status/git_ref/created range 请求参数验证",
    "project list tenant filter 与 q/status 请求参数验证",
    "Project list tenant filter 默认列表验证",
    "audit-events 查询参数验证",
    "analytics test-history 文本过滤请求参数验证",
    "RBAC project membership lookup scope 验证",
    "SSE ticket malformed payload 防泄漏验证",
    "ready degraded 双失败防泄漏验证",
    "artifact download 404 短路与 no-storage 验证",
    "notification rule name 请求体验证",
    "credential name 请求体验证",
    "credential rotate 缺失资源无副作用验证",
    "project member update 缺失成员无副作用验证",
    "environment name/cache_key 请求体验证",
    "project core text 请求体验证",
    "schedule cron_expr 请求体验证",
    "run trigger git_ref 请求体验证",
    "webhook git_ref 请求体验证",
)


def test_quality_ops_records_current_gate_summary_evidence():
    latest_row = _quality_ops_row(
        "| 2026-05-30 | collect-only `tests/integration` 212 tests"
    )
    review_sentence = (
        "本轮复核发现新增 "
        + "、".join(CURRENT_GATE_SUMMARY_REVIEW_ITEMS)
        + "后"
    )

    assert "smoke shell syntax passed" in latest_row
    assert review_sentence in latest_row
    assert "同日已刷新" in latest_row
    assert "再次复核到 1379 passed" in latest_row
    assert "覆盖率为 87.63%" in latest_row
    assert "`tests/unit/test_release_quality_docs_contract.py` 88 passed" in latest_row
