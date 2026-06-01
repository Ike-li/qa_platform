from __future__ import annotations

from tests.unit.release_quality_contract_helpers import _quality_ops_row


def test_quality_ops_records_current_gate_api_evidence():
    project_status_enum_row = _quality_ops_row(
        "| 2026-05-30 | N/A（Project list status OpenAPI enum 契约）"
    )
    api_token_create_validation_row = _quality_ops_row(
        "| 2026-05-30 | N/A（API token create 请求体验证短路契约）"
    )
    api_token_create_blank_text_row = _quality_ops_row(
        "| 2026-05-30 | N/A（API token create 空白文本请求体验证契约）"
    )
    auth_login_validation_row = _quality_ops_row(
        "| 2026-05-30 | N/A（Auth login 请求体验证短路契约）"
    )
    auth_register_password_row = _quality_ops_row(
        "| 2026-05-30 | N/A（Auth register password 文本边界短路契约）"
    )
    github_webhook_sha_row = _quality_ops_row(
        "| 2026-05-30 | N/A（GitHub provider webhook SHA 短路契约）"
    )
    webhook_git_sha_row = _quality_ops_row(
        "| 2026-05-30 | N/A（Webhook git_sha 请求体验证短路契约）"
    )
    run_results_text_filter_row = _quality_ops_row(
        "| 2026-05-30 | N/A（Run results text filter 请求参数短路契约）"
    )
    run_list_sort_row = _quality_ops_row(
        "| 2026-05-30 | N/A（Run list sort 请求参数短路契约）"
    )
    run_list_status_empty_row = _quality_ops_row(
        "| 2026-05-30 | N/A（Run list status 空段短路契约）"
    )
    project_list_query_row = _quality_ops_row(
        "| 2026-05-30 | N/A（Project list q/status 请求参数短路契约）"
    )
    project_list_tenant_filter_row = _quality_ops_row(
        "| 2026-05-30 | N/A（Project list tenant filter 默认列表契约）"
    )
    run_list_git_ref_created_row = _quality_ops_row(
        "| 2026-05-30 | N/A（Run list git_ref/created range 请求参数短路契约）"
    )
    analytics_history_query_row = _quality_ops_row(
        "| 2026-05-30 | N/A（Analytics test-history 文本过滤短路契约）"
    )
    notification_rule_update_row = _quality_ops_row(
        "| 2026-05-30 | N/A（Notification rule update 条件/渠道归一化契约）"
    )
    notification_rule_name_row = _quality_ops_row(
        "| 2026-05-30 | N/A（Notification rule name 请求体验证短路契约）"
    )
    credential_name_row = _quality_ops_row(
        "| 2026-05-30 | N/A（Credential name 请求体验证短路契约）"
    )
    environment_text_row = _quality_ops_row(
        "| 2026-05-30 | N/A（Environment name/cache_key 请求体验证短路契约）"
    )
    project_core_text_row = _quality_ops_row(
        "| 2026-05-30 | N/A（Project core text 请求体验证短路契约）"
    )
    schedule_cron_expr_row = _quality_ops_row(
        "| 2026-05-30 | N/A（Schedule cron_expr 请求体验证短路契约）"
    )
    run_trigger_git_ref_row = _quality_ops_row(
        "| 2026-05-30 | N/A（Run trigger git_ref 请求体验证短路契约）"
    )
    webhook_git_ref_row = _quality_ops_row(
        "| 2026-05-30 | N/A（Webhook git_ref 请求体验证短路契约）"
    )
    webhook_git_sha_blank_row = _quality_ops_row(
        "| 2026-05-30 | N/A（Webhook git_sha 空白请求体验证短路契约）"
    )
    github_provider_ref_row = _quality_ops_row(
        "| 2026-05-30 | N/A（GitHub provider ref 空白 payload 短路契约）"
    )
    batch_run_ids_row = _quality_ops_row(
        "| 2026-05-30 | N/A（Batch run_ids 唯一性短路契约）"
    )
    assert "`tests/unit/test_api/test_projects.py` 43 passed" in project_status_enum_row
    assert "coverage unit 1122 passed" in project_status_enum_row
    assert "OpenAPI 参数 schema 暴露 `active` / `archived` enum" in (
        project_status_enum_row
    )
    assert "`tests/unit/test_auth/test_auth_routes.py` 51 passed" in (
        api_token_create_validation_row
    )
    assert "coverage unit 1127 passed" in api_token_create_validation_row
    assert "空/超长 name 与空/超长 scope 字符串" in (api_token_create_validation_row)
    assert "保留 `scopes=[]` 作为无权限 token 语义" in (api_token_create_validation_row)
    assert "`tests/unit/test_auth/test_auth_routes.py` 53 passed" in (
        api_token_create_blank_text_row
    )
    assert "空白 `name` / `scopes[]`" in api_token_create_blank_text_row
    assert "不实例化 ApiTokenRepository/AuditEventRepository" in (
        api_token_create_blank_text_row
    )
    assert "`generate_token` / `hash_token`" in api_token_create_blank_text_row
    assert "只靠 `min_length=1` 会放行的空白字符串" in (api_token_create_blank_text_row)
    assert "token service、DB 和 audit" in api_token_create_blank_text_row
    assert "`tests/unit/test_auth/test_auth_routes.py` 59 passed" in (
        auth_login_validation_row
    )
    assert "username 空/空白/超长/非法格式" in auth_login_validation_row
    assert "password 空/空白/超长" in auth_login_validation_row
    assert "不打开 DB session" in auth_login_validation_row
    assert "UserRepository/AuditEventRepository" in auth_login_validation_row
    assert "不解析 tenant" in auth_login_validation_row
    assert "不发 token/cookie" in auth_login_validation_row
    assert "login 裸 `str`" in auth_login_validation_row
    assert "业务失败 401" in auth_login_validation_row
    assert "`tests/unit/test_auth/test_auth_routes.py` 61 passed" in (
        auth_register_password_row
    )
    assert "password 短/空白/超长" in auth_register_password_row
    assert "请求体验证阶段 422" in auth_register_password_row
    assert "不打开 DB session" in auth_register_password_row
    assert "不创建 tenant/user" in auth_register_password_row
    assert "不写 audit" in auth_register_password_row
    assert "不发 token/cookie" in auth_register_password_row
    assert "只靠 `min_length=8` 会放行的 8 个空格" in auth_register_password_row
    assert "创建空白密码账户" in auth_register_password_row
    assert "`tests/unit/test_api/test_p3.py` 45 passed" in github_webhook_sha_row
    assert "coverage unit 1130 passed" in github_webhook_sha_row
    assert "push `after` 与 PR `head.sha` 现在只接受 40 位 hex SHA" in (
        github_webhook_sha_row
    )
    assert "不会查项目、验签、建 Run 或写 audit" in github_webhook_sha_row
    assert "项目级自定义 webhook 的既有短 SHA 兼容语义不变" in (github_webhook_sha_row)
    assert "`tests/unit/test_api/test_p3.py` 49 passed" in webhook_git_sha_row
    assert "coverage unit 1145 passed" in webhook_git_sha_row
    assert "保留短 SHA 兼容" in webhook_git_sha_row
    assert "拒绝空字符串和超过 100 字符" in webhook_git_sha_row
    assert "不查项目、不查 pipeline/environment、不 dedup、不创建 Run、不写 audit" in (
        webhook_git_sha_row
    )
    assert "空字符串会绕过 dedup，超长值会污染 Run 记录" in webhook_git_sha_row
    assert "`tests/unit/test_api/test_runs.py` 39 passed" in run_results_text_filter_row
    assert "coverage unit 1149 passed" in run_results_text_filter_row
    assert "拒绝空字符串和超过 500 字符" in run_results_text_filter_row
    assert "不查 Run、不查 TestResult" in run_results_text_filter_row
    assert "空 `q` 会退化成无过滤全量读" in run_results_text_filter_row
    assert "LIKE wildcard 转义" in run_results_text_filter_row
    assert "`tests/unit/test_api/test_runs.py` 41 passed" in run_list_sort_row
    assert "coverage unit 1151 passed" in run_list_sort_row
    assert "只接受 `created_at` / `-created_at`" in run_list_sort_row
    assert "不查 project member、不查 run list" in run_list_sort_row
    assert "拼错字段会静默退化成 `created_at` 升序" in run_list_sort_row
    assert "`tests/unit/test_api/test_runs.py` 44 passed" in run_list_status_empty_row
    assert "coverage unit 1154 passed" in run_list_status_empty_row
    assert "`/runs?status=`、`,`、`queued,,running`" in run_list_status_empty_row
    assert "不查 project member、不查 run list" in run_list_status_empty_row
    assert "被当作“无过滤”或静默忽略" in run_list_status_empty_row
    assert "`tests/unit/test_api/test_projects.py` 47 passed" in project_list_query_row
    assert "coverage unit 1158 passed" in project_list_query_row
    assert "`/projects?status=`、`q=`、空白 q" in project_list_query_row
    assert "不查 project list" in project_list_query_row
    assert "空 status 会退化成无过滤列表" in project_list_query_row
    assert "超长 q 会进入 LIKE" in project_list_query_row
    assert "`tests/unit/test_api/test_projects.py` 55 passed" in (
        project_list_tenant_filter_row
    )
    assert "offset=0" in project_list_tenant_filter_row
    assert "limit=20" in project_list_tenant_filter_row
    assert "tenant_id" in project_list_tenant_filter_row
    assert "project.name ASC" in project_list_tenant_filter_row
    assert "默认 list 只证明 200/序列化" in project_list_tenant_filter_row
    assert "repository 参数" in project_list_tenant_filter_row
    assert "跨租户枚举" in project_list_tenant_filter_row
    assert "`tests/unit/test_api/test_runs.py` 48 passed" in (
        run_list_git_ref_created_row
    )
    assert "coverage unit 1168 passed" in run_list_git_ref_created_row
    assert "`/runs?git_ref=`、空白 `git_ref`、超过 200 字符的 `git_ref`" in (
        run_list_git_ref_created_row
    )
    assert "`created_from > created_to`" in run_list_git_ref_created_row
    assert "不查 project member、不查 run list" in run_list_git_ref_created_row
    assert "空 ref 会形成无意义精确过滤" in run_list_git_ref_created_row
    assert "超长 ref/反向时间范围也会打到 DB" in (run_list_git_ref_created_row)
    assert "`tests/unit/test_api/test_analytics.py` 3 passed" in (
        analytics_history_query_row
    )
    assert "coverage unit 1171 passed" in analytics_history_query_row
    assert "`/projects/{project_id}/analytics/test-history?suite=%20%20%20`" in (
        analytics_history_query_row
    )
    assert "`name=%20%20%20`" in analytics_history_query_row
    assert "不查 project、不查 test history" in analytics_history_query_row
    assert "空白 suite/name 会继续查项目、走权限并打 TestResult 仓储" in (
        analytics_history_query_row
    )
    assert "`tests/unit/test_api/test_notifications.py` 21 passed" in (
        notification_rule_update_row
    )
    assert "coverage unit 1246 passed" in notification_rule_update_row
    assert "`NOTIFICATION_EDIT` RBAC" in notification_rule_update_row
    assert "conditions/channels/template 仓储参数" in notification_rule_update_row
    assert "canonical webhook config" in notification_rule_update_row
    assert "audit 脱敏" in notification_rule_update_row
    assert "非法 update conditions 固定在请求体验证阶段 422" in (
        notification_rule_update_row
    )
    assert "不触碰项目/规则/audit" in notification_rule_update_row
    assert "update 成功路径主要证明改名/模板" in notification_rule_update_row
    assert "conditions/channels 归一化丢失" in notification_rule_update_row
    assert "audit 泄露 webhook URL/template" in notification_rule_update_row
    assert "`tests/unit/test_api/test_notifications.py` 18 passed" in (
        notification_rule_name_row
    )
    assert "coverage unit 1172 passed" in notification_rule_name_row
    assert "create/update 的空白 `name`" in notification_rule_name_row
    assert "不查 project、不查 notification_rule、不写 audit" in (
        notification_rule_name_row
    )
    assert "`name` 只靠 `min_length=1`" in notification_rule_name_row
    assert "空白 name 会继续走项目权限并创建/更新规则" in (notification_rule_name_row)
    assert "`tests/unit/test_api/test_credentials.py` 13 passed" in (
        credential_name_row
    )
    assert "coverage unit 1172 passed" in credential_name_row
    assert "凭据创建的空白 `name`" in credential_name_row
    assert (
        "不查 project、不查 credential name、不加密、不创建 credential、不写 audit"
        in (credential_name_row)
    )
    assert (
        "空白 name 会继续进入 project lookup、name exists、AAD 加密上下文和 credential create"
        in (credential_name_row)
    )
    assert "合法 name 能绑定 AAD" in credential_name_row
    assert "`tests/unit/test_api/test_environments.py` 27 passed" in (
        environment_text_row
    )
    assert "coverage unit 1174 passed" in environment_text_row
    assert "空白 `name` / `cache_key`" in environment_text_row
    assert (
        "不查 project、不查 environment、不加密 env_vars、不创建/更新 environment、不写 audit"
        in (environment_text_row)
    )
    assert (
        "空白 name/cache_key 会继续进入 project lookup、env_vars 加密、environment create/update 和 audit"
        in (environment_text_row)
    )
    assert "只证明空字符串被 Pydantic 拦住" in environment_text_row
    assert "`tests/unit/test_api/test_projects.py` 55 passed" in (project_core_text_row)
    assert "coverage unit 1182 passed" in project_core_text_row
    assert "空白 `name` / `git_url` / `default_branch` / `root_path`" in (
        project_core_text_row
    )
    assert "create 不查 slug、update 不查 project" in project_core_text_row
    assert "不查 credential、不创建/更新 project、不写 audit" in (project_core_text_row)
    assert (
        "空白 name/git_url/default_branch/root_path 会继续进入 slug 查重、credential 校验、project create/update 和 audit"
        in (project_core_text_row)
    )
    assert "只证明空字符串被 Pydantic 拦住" in project_core_text_row
    assert "`tests/unit/test_api/test_schedules.py` 10 passed" in (
        schedule_cron_expr_row
    )
    assert "coverage unit 1183 passed" in schedule_cron_expr_row
    assert "非法 `cron_expr`" in schedule_cron_expr_row
    assert "不查 project、不查 pipeline、不查/写 schedule" in (schedule_cron_expr_row)
    assert "不调用 `compute_next_run_at`、不写 audit" in schedule_cron_expr_row
    assert "update schema 只靠 `min_length=1`" in schedule_cron_expr_row
    assert "非法 cron 会继续进入 project lookup、权限、schedule lookup" in (
        schedule_cron_expr_row
    )
    assert "只证明 create happy path 和 timezone 边界" in schedule_cron_expr_row
    assert "`tests/unit/test_api/test_runs.py` 49 passed" in run_trigger_git_ref_row
    assert "coverage unit 1184 passed" in run_trigger_git_ref_row
    assert "空白 `git_ref`" in run_trigger_git_ref_row
    assert "不查 pipeline、不查 project、不查 environment" in (run_trigger_git_ref_row)
    assert "不创建 run、不写 retry group、不写 audit" in run_trigger_git_ref_row
    assert "通过 `min_length=1` 并作为真实 ref 写入 run" in (run_trigger_git_ref_row)
    assert "只证明明显空串能被 Pydantic 拦住" in run_trigger_git_ref_row
    assert "`tests/unit/test_api/test_p3.py` 50 passed" in webhook_git_ref_row
    assert "coverage unit 1185 passed" in webhook_git_ref_row
    assert "自定义 webhook 的空白 `git_ref`" in webhook_git_ref_row
    assert "不查 project、不查 pipeline、不查 environment" in webhook_git_ref_row
    assert "不查 dedup、不创建 run、不写 retry group、不写 audit" in (
        webhook_git_ref_row
    )
    assert "`git_ref` 只靠 `min_length=1`" in webhook_git_ref_row
    assert "进入 branch filter、dedup key 和 run 创建" in webhook_git_ref_row
    assert "只证明 SHA 边界能挡住" in webhook_git_ref_row
    assert "`tests/unit/test_api/test_p3.py` 51 passed" in webhook_git_sha_blank_row
    assert "coverage unit 1195 passed" in webhook_git_sha_blank_row
    assert "自定义 webhook 的空白 `git_sha`" in webhook_git_sha_blank_row
    assert "不查 project、不查 pipeline、不查 environment" in (
        webhook_git_sha_blank_row
    )
    assert "不查 dedup、不创建 run、不写 retry group、不写 audit" in (
        webhook_git_sha_blank_row
    )
    assert "空白 SHA 会继续进入 dedup key 和 Run 记录" in (webhook_git_sha_blank_row)
    assert "只证明空字符串能被 Pydantic 拦住" in webhook_git_sha_blank_row
    assert "`tests/unit/test_api/test_p3.py` 53 passed" in github_provider_ref_row
    assert "coverage unit 1197 passed" in github_provider_ref_row
    assert "GitHub provider push payload 的空白 `ref`" in github_provider_ref_row
    assert "400 `Missing GitHub ref`" in github_provider_ref_row
    assert "不查 repo URL、不查 pipeline/environment" in github_provider_ref_row
    assert "不查 dedup、不创建 run、不写 audit" in github_provider_ref_row
    assert "空白 ref 会落入 Pydantic ValidationError" in github_provider_ref_row
    assert "route 级 no-repo/no-run 断言" in github_provider_ref_row
    assert "`tests/unit/test_api/test_p3.py` 47 passed" in batch_run_ids_row
    assert "coverage unit 1132 passed" in batch_run_ids_row
    assert "batch cancel/retry 请求现在拒绝重复 run_id" in batch_run_ids_row
    assert (
        "不读取 run、不 cancel、不 create retry run、不入队、不发 Redis 取消/状态事件、不写 audit"
        in (batch_run_ids_row)
    )
    assert "`BatchRunRequest` 只限制 1-50 个 ID" in batch_run_ids_row
