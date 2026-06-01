from __future__ import annotations

from tests.unit.release_quality_contract_helpers import _quality_ops_row


def test_quality_ops_records_current_gate_pipeline_api_evidence():
    pipeline_core_text_row = _quality_ops_row(
        "| 2026-05-30 | N/A（Pipeline core text 请求体验证短路契约）"
    )
    pipeline_list_text_row = _quality_ops_row(
        "| 2026-05-30 | N/A（Pipeline selector/retry 列表文本短路契约）"
    )
    pipeline_item_cross_project_row = _quality_ops_row(
        "| 2026-05-30 | N/A（Pipeline item 跨项目 404 等价性契约）"
    )
    domain_pipeline_text_row = _quality_ops_row(
        "| 2026-05-30 | N/A（Domain pipeline 配置文本短路契约）"
    )
    pipeline_selector_row = _quality_ops_row(
        "| 2026-05-30 | N/A（Pipeline selector 请求体验证短路契约）"
    )
    pipeline_retry_policy_row = _quality_ops_row(
        "| 2026-05-30 | N/A（Pipeline retry policy 请求体验证短路契约）"
    )
    pipeline_trigger_config_row = _quality_ops_row(
        "| 2026-05-30 | N/A（Pipeline trigger_config 请求体验证短路契约）"
    )

    assert "`tests/unit/test_api/test_pipelines.py` 23 passed" in pipeline_core_text_row
    assert "coverage unit 1190 passed" in pipeline_core_text_row
    assert "空白 `name`、stage `name/plugin`、collector `plugin`" in (
        pipeline_core_text_row
    )
    assert "trigger_config `type`" in pipeline_core_text_row
    assert "不查 project、不读 pipeline、不创建/更新 pipeline、不写 audit" in (
        pipeline_core_text_row
    )
    assert "只靠 `min_length=1`" in pipeline_core_text_row
    assert "进入 stages/collectors/trigger_config JSONB 或 pipeline name" in (
        pipeline_core_text_row
    )
    assert "只证明明显空串会失败" in pipeline_core_text_row
    assert "`tests/unit/test_api/test_pipelines.py` 27 passed" in (
        pipeline_list_text_row
    )
    assert "coverage unit 1194 passed" in pipeline_list_text_row
    assert "selector `include_paths` / `exclude_paths` / `tags` 空白元素" in (
        pipeline_list_text_row
    )
    assert "retry_policy `retry_on` 空白原因" in pipeline_list_text_row
    assert "不查 project、不读 pipeline、不创建/更新 pipeline、不写 audit" in (
        pipeline_list_text_row
    )
    assert "空白路径、tag、retry reason 会通过 `min_length=1`" in (
        pipeline_list_text_row
    )
    assert "进入发现规则或重试配置 JSONB" in pipeline_list_text_row
    assert "保留下标错误信息" in pipeline_list_text_row
    assert (
        "test_pipeline_item_routes_hide_other_project_pipeline_without_side_effects"
        in (pipeline_item_cross_project_row)
    )
    assert "1 passed" in pipeline_item_cross_project_row
    assert (
        "pipeline get/update/delete 对跨项目 pipeline 与缺失 pipeline 返回同一 `NOT_FOUND` envelope"
        in (pipeline_item_cross_project_row)
    )
    assert "不 update/delete/audit" in pipeline_item_cross_project_row
    assert "响应不回显外部 project_id" in pipeline_item_cross_project_row
    assert "详情已覆盖跨项目 404 等价性，但 update/delete 只覆盖正常路径" in (
        pipeline_item_cross_project_row
    )
    assert "只证明详情页能隐藏跨项目 ID" in pipeline_item_cross_project_row
    assert (
        "`tests/unit/test_domain_models.py tests/unit/test_services/test_discovery.py` 18 passed"
        in (domain_pipeline_text_row)
    )
    assert "coverage unit 1198 passed" in domain_pipeline_text_row
    assert "domain `TestSelector` include/exclude/tags" in domain_pipeline_text_row
    assert "`RetryPolicy.retry_on`" in domain_pipeline_text_row
    assert "`TriggerConfig.type`" in domain_pipeline_text_row
    assert "`StageDefinition.name/plugin`" in domain_pipeline_text_row
    assert "`CollectorDefinition.plugin`" in domain_pipeline_text_row
    assert "`Pipeline.name`" in domain_pipeline_text_row
    assert "旧断言只测空字符串" in domain_pipeline_text_row
    assert (
        "空白字符串仍会进入发现规则、重试原因、触发配置、stage/collector/pipeline 名称"
        in (domain_pipeline_text_row)
    )
    assert "长度/数量边界和下标错误信息断言" in domain_pipeline_text_row
    assert "`tests/unit/test_api/test_pipelines.py` 14 passed" in pipeline_selector_row
    assert "`tests/unit/test_services/test_discovery.py` 12 passed" in (
        pipeline_selector_row
    )
    assert "coverage unit 1137 passed" in pipeline_selector_row
    assert "拒绝空条目和超过 100 项的列表" in pipeline_selector_row
    assert "不查项目、不读写 pipeline、不写 audit" in pipeline_selector_row
    assert "domain `TestSelector` 同步拒绝歧义发现规则" in pipeline_selector_row
    assert "`tests/unit/test_api/test_pipelines.py` 16 passed" in (
        pipeline_retry_policy_row
    )
    assert "`tests/unit/test_domain_models.py` 4 passed" in pipeline_retry_policy_row
    assert "coverage unit 1140 passed" in pipeline_retry_policy_row
    assert "拒绝空原因和超过 20 项的列表" in pipeline_retry_policy_row
    assert "不查项目、不读写 pipeline、不写 audit" in pipeline_retry_policy_row
    assert "domain `RetryPolicy` 同步拒绝歧义重试原因" in pipeline_retry_policy_row
    assert "`tests/unit/test_api/test_pipelines.py` 18 passed" in (
        pipeline_trigger_config_row
    )
    assert "`tests/unit/test_domain_models.py` 5 passed" in (
        pipeline_trigger_config_row
    )
    assert "coverage unit 1143 passed" in pipeline_trigger_config_row
    assert "`type` 现在拒绝空字符串" in pipeline_trigger_config_row
    assert "`dedup_window_seconds` 现在拒绝负数" in pipeline_trigger_config_row
    assert "不查项目、不读写 pipeline、不写 audit" in pipeline_trigger_config_row
    assert "domain `TriggerConfig` 同步拒绝歧义触发配置" in (
        pipeline_trigger_config_row
    )
