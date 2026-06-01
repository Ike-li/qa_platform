from __future__ import annotations

from pathlib import Path

from tests.unit.release_quality_contract_helpers import (
    _after,
    _block_between,
    _marked_block,
    _marked_block_or_tail,
    _quality_ops_row,
    _quality_ops_row_containing,
    _quality_ops_rows_containing,
    _read,
)


ROOT = Path(__file__).resolve().parents[2]
CANCEL_E2E = ROOT / "tests" / "integration" / "test_cancel_e2e.py"
CREDENTIALS_TEST = ROOT / "tests" / "unit" / "test_api" / "test_credentials.py"
ENVIRONMENTS_TEST = ROOT / "tests" / "unit" / "test_api" / "test_environments.py"
NOTIFICATIONS_TEST = ROOT / "tests" / "unit" / "test_api" / "test_notifications.py"
P3_TEST = ROOT / "tests" / "unit" / "test_api" / "test_p3.py"
PIPELINES_TEST = ROOT / "tests" / "unit" / "test_api" / "test_pipelines.py"
PROJECT_MEMBERS_TEST = ROOT / "tests" / "unit" / "test_api" / "test_project_members.py"
PROJECTS_SOURCE = ROOT / "src" / "qaplatform" / "api" / "v1" / "projects.py"
PROJECTS_TEST = ROOT / "tests" / "unit" / "test_api" / "test_projects.py"
SCHEDULES_TEST = ROOT / "tests" / "unit" / "test_api" / "test_schedules.py"
SILENT_WINDOWS_INTEGRATION = ROOT / "tests" / "integration" / "test_silent_windows.py"
WEBHOOK_BRANCH_DEDUP = ROOT / "tests" / "integration" / "test_webhook_branch_dedup.py"


def test_quality_ops_capture_webhook_rejection_response_contracts():
    row = _quality_ops_row_containing("Webhook 拒绝响应脱敏契约")
    webhook_tests = _read(WEBHOOK_BRANCH_DEDUP)

    assert "Webhook 拒绝响应脱敏契约" in row
    assert "provider 签名错误、项目级签名缺失、archived project、跨租户 project" in (
        row
    )
    assert "不回显 webhook secret、project/git URL、project/tenant/user 探测 ID" in (
        row
    )
    assert 'resp.json() == {"detail": "Invalid webhook signature"}' in webhook_tests
    assert 'resp.json() == {"detail": "Missing X-Webhook-Signature header"}' in (
        webhook_tests
    )
    assert '"detail": "Project is archived; new runs cannot be triggered"' in (
        webhook_tests
    )
    assert '"code": "NOT_FOUND"' in webhook_tests
    assert '"message": "Project not found"' in webhook_tests
    assert '"github-provider-secret" not in resp.text' in webhook_tests
    assert '"signed-webhook-secret" not in resp.text' in webhook_tests


def test_quality_ops_capture_webhook_filtered_duplicate_exact_audit_ownership_contract():
    webhook_tests = _read(WEBHOOK_BRANCH_DEDUP)

    row = _quality_ops_row("| 2026-05-31 | `RUN_INTEGRATION_TESTS=1 "
            "tests/integration/test_webhook_branch_dedup.py::"
            "test_provider_github_push_filtered_branch_uses_api_v1_alias_and_system_audit")

    assert (
        "tests/integration/test_webhook_branch_dedup.py::"
        "test_webhook_same_commit_second_trigger_returns_duplicate"
        in row
    )
    assert "` 2 passed" in row
    assert "release quality docs contract full 234 passed" in row
    assert "targeted ruff passed" in row
    assert "filtered response 与 duplicate response" in row
    assert "no-run / single-run 副作用边界" in row
    assert "`webhook.filtered` / `webhook.duplicate` AuditEvent" in row
    assert "tenant/user/resource/before_state/after_state 完整等值" in row
    assert "审计 payload 不含 repo URL、secret 或 dedup_key" in row
    assert "filtered 只证明 response/no-run/after_state" in row
    assert "duplicate 只证明 200/单 run/部分 audit" in row
    assert "audit 归属写错 tenant/resource" in row
    assert "before_state 被误填" in row
    assert "duplicate dedup_key 泄露" in row
    assert "secret/repo URL 进入审计" in row
    assert "webhook 分支过滤/去重测试只证明“不建或少建了 run”" in row

    filtered_block = _marked_block(
        webhook_tests,
        "async def test_provider_github_push_filtered_branch_uses_api_v1_alias_and_system_audit",
        "async def test_webhook_same_commit_second_trigger_returns_duplicate",
    )

    for expected in [
        'assert resp.json() == {"status": "filtered", "reason": "branch_not_allowed"}',
        "assert await _webhook_run_count(integration_db_session, project.id) == before",
        'AuditEvent.action == "webhook.filtered"',
        "assert audit.user_id is None",
        "assert audit.tenant_id == project.tenant_id",
        'assert audit.resource_type == "project"',
        "assert audit.resource_id == project.id",
        "assert audit.before_state is None",
        "assert audit.after_state == {",
        '"delivery_id": f"provider-filtered-{project.id}"',
        "assert project.git_url not in repr(audit.after_state)",
        "assert secret not in repr(audit.after_state)",
    ]:
        assert expected in filtered_block

    duplicate_block = _marked_block(
        webhook_tests,
        "async def test_webhook_same_commit_second_trigger_returns_duplicate",
        "async def test_webhook_archived_project_returns_409_and_creates_no_run",
    )

    for expected in [
        'assert second.json() == {"status": "duplicate"}',
        "await _webhook_run_count(",
        "== 1",
        'AuditEvent.action == "webhook.duplicate"',
        "assert audit.user_id == user.id",
        "assert audit.tenant_id == tenant.id",
        'assert audit.resource_type == "project"',
        "assert audit.resource_id == project.id",
        "assert audit.before_state is None",
        "assert audit.after_state == {",
        '"reason": "dedup_key_conflict"',
        "assert project.git_url not in repr(audit.after_state)",
        "assert dedup_key not in repr(audit.after_state)",
    ]:
        assert expected in duplicate_block


def test_quality_ops_capture_project_webhook_filtered_unit_exact_response_audit_contract():
    p3_test = _read(P3_TEST)

    row = _quality_ops_row("| 2026-05-31 | N/A（Project webhook filtered unit exact response/audit 契约）")

    assert (
        "`tests/unit/test_api/test_p3.py::TestWebhookTrigger::"
        "test_webhook_trigger_filtered_branch_returns_200_without_run` 1 passed"
        in row
    )
    assert "targeted docs contract passed" in row
    assert "targeted ruff passed" in row
    assert '完整响应 `{"status":"filtered","reason":"branch_not_allowed"}`' in row
    assert "pipeline/environment/dedup/run create/retry group 全部短路" in row
    assert "`webhook.filtered` audit after_state 精确等值" in row
    assert "不含项目 git_url、攻击者 git_url 或 dedup_key" in row
    assert '只断言 `resp.json()["status"]`' in row
    assert "继续查 pipeline/env/dedup" in row
    assert "项目 webhook filtered 单测只证明“返回了 filtered”" in row

    block = _block_between(p3_test, "async def test_webhook_trigger_filtered_branch_returns_200_without_run", "async def test_webhook_trigger_invalid_signature_stops_before_rbac_or_run_creation")

    for expected in [
        'assert resp.json() == {"status": "filtered", "reason": "branch_not_allowed"}',
        "mock_repos.pipeline.list_by_project.assert_not_awaited()",
        "mock_repos.environment.list_by_project.assert_not_awaited()",
        "mock_repos.run.get_active_by_dedup.assert_not_awaited()",
        "mock_repos.run.create.assert_not_awaited()",
        "mock_repos.run.set_retry_group_id.assert_not_awaited()",
        'assert audit_kwargs["action"] == "webhook.filtered"',
        'assert audit_kwargs["resource_type"] == "project"',
        'assert audit_kwargs["resource_id"] == mock_project.id',
        'assert audit_kwargs["after_state"] == {',
        '"project_id": str(mock_project.id)',
        '"status": "filtered"',
        '"reason": "branch_not_allowed"',
        '"git_ref": "refs/heads/feature/foo"',
        '"git_sha": "abc123"',
        '"branch_name": "feature/foo"',
        '"provider": "github"',
        '"delivery_id": "delivery-filtered-123"',
        'assert mock_project.git_url not in repr(audit_kwargs["after_state"])',
        'assert "attacker.example" not in repr(audit_kwargs["after_state"])',
        'assert "should-not-leak" not in repr(audit_kwargs["after_state"])',
    ]:
        assert expected in block
    assert 'resp.json()["status"]' not in block


def test_quality_ops_capture_project_webhook_reserved_metadata_integration_exact_audit_contract():
    webhook_tests = _read(WEBHOOK_BRANCH_DEDUP)

    row = _quality_ops_row("| 2026-05-31 | `RUN_INTEGRATION_TESTS=1 "
            "tests/integration/test_webhook_branch_dedup.py::"
            "test_signed_webhook_success_audits_and_protects_reserved_metadata")

    assert (
        "tests/integration/test_webhook_branch_dedup.py::"
        "test_webhook_filtered_branch_returns_200_and_creates_no_run"
        in row
    )
    assert "` 2 passed" in row
    assert "release quality docs contract full 235 passed" in row
    assert "targeted ruff passed" in row
    assert "Run tenant/project/pipeline/environment/triggered_by/git_ref/git_sha/dedup_key" in row
    assert "reserved metadata 不可覆盖" in row
    assert "`run.trigger` 审计完整匹配 tenant/user/resource/before_state/after_state" in row
    assert "精确 filtered response" in row
    assert "`webhook.filtered` 审计归属" in row
    assert "审计 payload 不含项目 repo URL、攻击者 URL、credential 或 default_branch" in row
    assert "只抽查 run trigger_type/git_sha/metadata 和 audit user/after_state" in row
    assert 'filtered 分支只断言 `resp.json()["status"]`' in row
    assert "payload 污染 pipeline/environment/triggered_by" in row
    assert "audit 归属写错" in row
    assert "错误体夹带额外字段" in row
    assert "攻击者 metadata 进入审计" in row
    assert "webhook 安全测试只证明“创建了 run 或返回 filtered”" in row

    signed_block = _marked_block(
        webhook_tests,
        "async def test_signed_webhook_success_audits_and_protects_reserved_metadata",
        "async def test_webhook_filtered_branch_returns_200_and_creates_no_run",
    )

    for expected in [
        "assert run.tenant_id == tenant.id",
        "assert run.project_id == project.id",
        'assert run.pipeline_id == seed_run["pipeline"].id',
        'assert run.environment_id == seed_run["environment"].id',
        "assert run.triggered_by == user.id",
        'assert run.git_ref == "refs/heads/release/2026.05"',
        "assert run.dedup_key == f\"github:{project.git_url}:signed-webhook-sha:release/2026.05\"",
        'assert run.metadata_["git_url"] == project.git_url',
        'assert run.metadata_["shallow_clone"] is True',
        'assert run.metadata_["default_branch"] == project.default_branch',
        "assert attacker_url not in serialized_metadata",
        "assert attacker_credential not in serialized_metadata",
        'assert "evil" not in serialized_metadata',
        "assert audit.tenant_id == tenant.id",
        "assert audit.user_id == user.id",
        'assert audit.resource_type == "run"',
        "assert audit.resource_id == run.id",
        "assert audit.before_state is None",
        "assert audit.after_state == response_body",
        "assert attacker_url not in repr(audit.after_state)",
        "assert attacker_credential not in repr(audit.after_state)",
        'assert "evil" not in repr(audit.after_state)',
    ]:
        assert expected in signed_block
    assert 'audit.after_state["trigger_type"]' in signed_block

    filtered_block = _marked_block(
        webhook_tests,
        "async def test_webhook_filtered_branch_returns_200_and_creates_no_run",
        "async def test_webhook_terminal_same_commit_can_trigger_again",
    )

    for expected in [
        'assert resp.json() == {"status": "filtered", "reason": "branch_not_allowed"}',
        "assert await _webhook_run_count(integration_db_session, project.id) == before",
        'AuditEvent.action == "webhook.filtered"',
        "assert audit.tenant_id == tenant.id",
        "assert audit.user_id == user.id",
        'assert audit.resource_type == "project"',
        "assert audit.resource_id == project.id",
        "assert audit.before_state is None",
        "assert audit.after_state == {",
        '"provider": "github"',
        '"delivery_id": f"filtered-{project.id}"',
        "assert project.git_url not in serialized_audit",
        'assert "attacker.example" not in serialized_audit',
        'assert "should-not-be-audited" not in serialized_audit',
    ]:
        assert expected in filtered_block
    assert 'resp.json()["status"]' not in filtered_block


def test_quality_ops_capture_webhook_terminal_same_commit_exact_response_db_contract():
    webhook_tests = _read(WEBHOOK_BRANCH_DEDUP)

    row = _quality_ops_row("| 2026-05-31 | `RUN_INTEGRATION_TESTS=1 .venv/bin/python -m pytest "
            "tests/integration/test_webhook_branch_dedup.py::"
            "test_webhook_terminal_same_commit_can_trigger_again -q` 1 passed")

    assert "targeted docs contract passed" in row
    assert "targeted ruff passed" in row
    assert "第一次与第二次 201 的完整 RunResponse" in row
    assert "同一 dedup_key 下的 done/queued 两条 run 投影" in row
    assert "retry_group_id 完整等值" in row
    assert "只抽查两次响应的 git_ref/git_sha/status" in row
    assert "用 `all(...)` 证明两条 DB run" in row
    assert "terminal same-commit exact response/DB projection 契约" in row
    assert "去重回归测试只证明“同 commit 能再建一条 run”" in row

    block = _marked_block(
        webhook_tests,
        "async def test_webhook_terminal_same_commit_can_trigger_again",
        "@pytest.mark.asyncio",
    )

    for expected in [
        "def _expected_run_response(run, *, pipeline_name: str) -> dict:",
        "def _run_dedup_projection(run) -> dict:",
        'assert first_body == _expected_run_response(',
        'assert second_body == _expected_run_response(',
        "assert [_run_dedup_projection(run) for run in runs] == [",
        '"tenant_id": tenant.id',
        '"project_id": project.id',
        '"pipeline_id": seed_run["pipeline"].id',
        '"environment_id": seed_run["environment"].id',
        '"status": RunStatusEnum.DONE',
        '"status": RunStatusEnum.QUEUED',
        '"trigger_type": "webhook"',
        '"git_ref": "refs/heads/release/2026.05"',
        '"git_sha": "done-sha"',
        '"triggered_by": user.id',
        '"attempt": 1',
        '"dedup_key": dedup_key',
        '"retry_group_id": first_run_id',
        '"retry_group_id": second_run_id',
    ]:
        assert expected in webhook_tests if expected.startswith("def ") else expected in block
    assert 'first.json()["git_ref"]' not in block
    assert 'second_body["git_ref"]' not in block
    assert "assert all(" not in block


def test_quality_ops_capture_github_repo_url_candidates_exact_contract():
    row = _quality_ops_row_containing("GitHub repo URL candidates 精确匹配契约")
    p3_test = _read(P3_TEST)

    assert "GitHub repo URL candidates 精确匹配契约" in row
    assert "固定为 clone/html/ssh/git/full_name 推导出的 4 个精确候选" in (
        row
    )
    assert "不允许额外 URL 混入" in row
    assert "candidates == {" in p3_test
    assert "}.issubset(candidates)" not in p3_test
    assert '"https://github.com/acme/widget"' in p3_test
    assert '"https://github.com/acme/widget.git"' in p3_test
    assert '"git@github.com:acme/widget.git"' in p3_test
    assert '"git://github.com/acme/widget.git"' in p3_test


def test_quality_ops_capture_project_list_exact_response_contract():
    ops_row = _quality_ops_row_containing("Project list 精确响应契约")
    projects_test = _read(PROJECTS_TEST)
    row = _quality_ops_row(
        "| 2026-05-31 | N/A（Project list redundant field-set guard removed）"
    )

    assert "Project list redundant field-set guard removed" in row
    assert (
        "`tests/unit/test_api/test_projects.py::test_list_projects` 1 passed"
        in row
    )
    assert "release quality docs contract full 335 passed" in row
    assert "完整 `body == {...}` 固定分页 body" in row
    assert "完整 ProjectResponse item" in row
    assert "tenant filter、offset/limit 和 name order" in row
    assert "删除重复的 `assert set(body[\"data\"][0]) == {...}`" in row
    assert "它不能发现完整 body 已发现不了的问题" in row
    assert "project list no redundant field-set guard 契约" in row

    assert "Project list 精确响应契约" in ops_row
    assert "固定完整 ProjectResponse 列表项" in ops_row
    assert "包含 silent_windows、created_at、updated_at" in ops_row
    assert 'assert body == {' in projects_test
    assert '"silent_windows": []' in projects_test
    assert '"updated_at": project.updated_at.isoformat().replace("+00:00", "Z")' in (
        projects_test
    )
    assert 'assert set(body["data"][0]) == {' not in projects_test
    assert 'assert body["data"][0]["slug"] == "test-project"' not in projects_test


def test_quality_ops_capture_project_silent_windows_update_success_exact_contract():
    projects_test = _read(PROJECTS_TEST)
    row = _quality_ops_row(
        "| 2026-05-31 | N/A（Project silent_windows update success exact settings/audit 契约）"
    )

    assert "Project silent_windows update success exact settings/audit 契约" in row
    assert (
        "`tests/unit/test_api/test_projects.py::test_update_project_serializes_silent_windows_into_settings` 1 passed"
        in row
    )
    assert "projects full 59 passed" in row
    assert "release quality docs contract full 188 passed" in row
    assert "固定保留既有 settings" in row
    assert "序列化后的完整 silent window 对象" in row
    assert "完整 ProjectResponse" in row
    assert "`project.update(project, settings=...)` exact 参数" in row
    assert "credential lookup 零触达" in row
    assert "`project.update` audit before/after 完整脱敏 payload" in row
    assert "`webhook_secret` 原值不进入 audit before/after" in row
    assert "此前只抽查 settings/response 中的 `reason`" in row
    assert "webhook_secret 原值进审计" in row
    assert "success exact settings/audit/no-secret 契约" in row
    assert "项目静默窗口成功测试只证明“reason 被放进某个地方”" in row

    assert "def _expected_project_settings_audit_state(value):" in projects_test
    block = _marked_block(
        projects_test,
        "async def test_update_project_serializes_silent_windows_into_settings",
        "async def test_delete_project",
    )
    for expected in [
        "mock_repos,",
        "mock_user,",
        "before_state = _expected_project_audit_state(project)",
        "expected_silent_windows = [",
        '"start_at": "2026-06-01T09:00:00+08:00"',
        '"end_at": "2026-06-01T10:00:00+08:00"',
        '"reason": "Release freeze"',
        "expected_settings = {",
        '"allowed_branches": ["main"]',
        '"webhook_secret": "project-webhook-secret"',
        '"silent_windows": expected_silent_windows',
        "json={\"silent_windows\": expected_silent_windows}",
        "assert resp.json() == _expected_project_response(project)",
        "mock_project_repo.get_for_tenant.assert_awaited_once_with(project.id, tenant_id)",
        "mock_project_repo.update.assert_awaited_once_with(",
        "settings=expected_settings",
        "mock_repos.credential.get_by_project_tenant.assert_not_awaited()",
        "audit_kwargs = mock_repos.audit.create.await_args.kwargs",
        "assert audit_kwargs == {",
        '"tenant_id": tenant_id',
        '"user_id": mock_user.user_id',
        '"action": "project.update"',
        '"resource_type": "project"',
        '"resource_id": project.id',
        '"before_state": before_state',
        '"after_state": _expected_project_audit_state(project)',
        'audit_kwargs["before_state"]["settings"]["webhook_secret"] == {',
        'audit_kwargs["after_state"]["settings"]["webhook_secret"] == {',
        '"project-webhook-secret" not in repr(',
    ]:
        assert expected in block
    assert 'settings = mock_project_repo.update.await_args.kwargs["settings"]' not in block
    assert 'settings["silent_windows"][0]["reason"]' not in block
    assert 'resp.json()["silent_windows"][0]["reason"]' not in block


def test_quality_ops_capture_project_duplicate_slug_exact_short_circuit_contract():
    projects_test = _read(PROJECTS_TEST)
    row = _quality_ops_row(
        "| 2026-05-31 | N/A（Project duplicate slug exact short-circuit 契约）"
    )

    assert "Project duplicate slug exact short-circuit 契约" in row
    assert (
        "`tests/unit/test_api/test_projects.py::test_create_project_duplicate_slug` 1 passed"
        in row
    )
    assert "projects full 59 passed" in row
    assert "release quality docs contract full 192 passed" in row
    assert "完整 409 body" in row
    assert 'tenant-scoped `project.get_by_slug(tenant_id, "dup-slug")`' in row
    assert "credential lookup、project create 和 audit 均在查重命中后短路" in row
    assert "此前只断言 `get_by_slug` 被 await 一次和 `detail` 子字段" in row
    assert "重复 slug 测试只证明“返回 409 且大概查过 slug”" in row

    block = _marked_block(
        projects_test,
        "async def test_create_project_duplicate_slug",
        "async def test_create_project_rejects_credential_before_project_exists",
    )
    for expected in [
        "mock_repos, tenant_id",
        "mock_project_repo.get_by_slug.return_value = _make_orm_project(",
        "tenant_id=tenant_id",
        'slug="dup-slug"',
        'assert resp.json() == {"detail": "Slug already exists"}',
        'mock_project_repo.get_by_slug.assert_awaited_once_with(tenant_id, "dup-slug")',
        "mock_repos.credential.get_by_project_tenant.assert_not_awaited()",
        "mock_project_repo.create.assert_not_awaited()",
        "mock_repos.audit.create.assert_not_awaited()",
    ]:
        assert expected in block
    assert 'assert resp.json()["detail"]' not in block
    assert "mock_project_repo.get_by_slug.assert_awaited_once()" not in block


def test_quality_ops_capture_project_credential_binding_update_exact_response_audit_contract():
    projects_test = _read(PROJECTS_TEST)
    row = _quality_ops_row(
        "| 2026-05-31 | N/A（Project credential binding update exact response/audit 契约）"
    )

    assert "Project credential binding update exact response/audit 契约" in row
    assert (
        "`tests/unit/test_api/test_projects.py::test_update_project_validates_git_credential_binding` 1 passed"
        in row
    )
    assert "projects full 59 passed" in row
    assert "release quality docs contract full 194 passed" in row
    assert "固定完整 ProjectResponse" in row
    assert "tenant-scoped project lookup" in row
    assert "credential lookup exact 参数" in row
    assert '`project.update(project, git_auth_method="token", credential_id=...)`' in row
    assert "`project.update` audit before/after 完整 payload" in row
    assert '此前只抽查 `update.await_args.kwargs["credential_id"]`' in row
    assert "凭据绑定成功测试只证明“credential_id 被更新”" in row

    block = _marked_block(
        projects_test,
        "async def test_update_project_validates_git_credential_binding",
        "async def test_update_project_rejects_git_credential_type_mismatch",
    )
    for expected in [
        "mock_user,",
        "assert resp.json() == _expected_project_response(updated)",
        "mock_project_repo.get_for_tenant.assert_awaited_once_with(project.id, tenant_id)",
        "mock_repos.credential.get_by_project_tenant.assert_awaited_once_with(",
        "credential.id,",
        "project.id,",
        "tenant_id,",
        "mock_project_repo.update.assert_awaited_once_with(",
        "git_auth_method=\"token\"",
        "credential_id=credential.id",
        "mock_repos.audit.create.assert_awaited_once()",
        "assert mock_repos.audit.create.await_args.kwargs == {",
        '"tenant_id": tenant_id',
        '"user_id": mock_user.user_id',
        '"action": "project.update"',
        '"resource_type": "project"',
        '"resource_id": project.id',
        '"before_state": _expected_project_audit_state(project)',
        '"after_state": _expected_project_audit_state(updated)',
    ]:
        assert expected in block
    assert 'mock_project_repo.update.await_args.kwargs["credential_id"]' not in block


def test_quality_ops_capture_project_crud_exact_response_audit_contract():
    projects_test = _read(PROJECTS_TEST)
    row = _quality_ops_row(
        "| 2026-05-31 | N/A（Project CRUD exact response/audit 契约）"
    )

    assert "Project CRUD exact response/audit 契约" in row
    assert (
        "`tests/unit/test_api/test_projects.py::test_create_project "
        "tests/unit/test_api/test_projects.py::test_get_project "
        "tests/unit/test_api/test_projects.py::test_update_project "
        "tests/unit/test_api/test_projects.py::test_delete_project` 4 passed"
        in row
    )
    assert "projects full 59 passed" in row
    assert "release quality docs contract full 174 passed" in row
    assert "固定完整 ProjectResponse" in row
    assert "tenant-scoped lookup" in row
    assert "create/update/delete 仓储 exact kwargs" in row
    assert "create/update/delete audit 的 tenant/user/action/resource/before_state/after_state" in row
    assert "git URL userinfo 脱敏" in row
    assert "此前只抽查响应 id/name 或 audit action/resource/name/git_url" in row
    assert "Projects 正向测试只证明“路由成功且几个字段看起来对”" in row

    assert "def _expected_project_response(project) -> dict:" in projects_test
    assert "def _expected_project_audit_state(project, *, git_url: str | None = None) -> dict:" in projects_test

    create_block = _marked_block(
        projects_test,
        "async def test_create_project(",
        "async def test_create_project_duplicate_slug",
    )
    for expected in [
        "assert body == _expected_project_response(project)",
        "assert mock_project_repo.create.await_args.kwargs == {",
        '"description": None',
        '"git_auth_method": "none"',
        '"default_branch": "main"',
        '"root_path": "."',
        '"settings": {}',
        "assert audit_kwargs == {",
        '"tenant_id": tenant_id',
        '"user_id": mock_user.user_id',
        '"action": "project.create"',
        '"before_state": None',
        '"after_state": _expected_project_audit_state(',
        '"https://***@github.com/example/repo.git"',
        'assert "secret-token" not in repr(audit_kwargs)',
    ]:
        assert expected in create_block
    assert 'assert resp.json()["name"]' not in create_block
    assert 'audit_kwargs["after_state"]["name"]' not in create_block

    get_block = _marked_block(
        projects_test,
        "async def test_get_project(",
        "async def test_get_project_not_found",
    )
    assert "assert resp.json() == _expected_project_response(project)" in get_block
    assert "mock_project_repo.get_for_tenant.assert_awaited_once_with(project.id, tenant_id)" in get_block
    assert 'assert resp.json()["id"]' not in get_block

    update_block = _marked_block(
        projects_test,
        "async def test_update_project(",
        "async def test_update_project_validates_git_credential_binding",
    )
    for expected in [
        "mock_user, tenant_id",
        "assert resp.json() == _expected_project_response(updated)",
        'mock_project_repo.update.assert_awaited_once_with(project, name="updated-name")',
        "assert audit_kwargs == {",
        '"action": "project.update"',
        '"before_state": _expected_project_audit_state(project)',
        '"after_state": _expected_project_audit_state(updated)',
    ]:
        assert expected in update_block
    assert 'assert resp.json()["name"]' not in update_block
    assert 'audit_kwargs["before_state"]["name"]' not in update_block

    delete_block = _marked_block(
        projects_test,
        "async def test_delete_project(",
        "async def test_delete_project_not_found",
    )
    for expected in [
        "mock_user, tenant_id",
        "mock_project_repo.get_for_tenant.assert_awaited_once_with(project.id, tenant_id)",
        "mock_project_repo.delete.assert_awaited_once_with(project)",
        "assert audit_kwargs == {",
        '"action": "project.delete"',
        '"before_state": _expected_project_audit_state(project)',
        '"after_state": None',
    ]:
        assert expected in delete_block
    assert 'audit_kwargs["before_state"]["git_url"]' not in delete_block


def test_quality_ops_capture_project_silent_windows_integration_exact_audit_no_secret_contract():
    silent_windows = _read(SILENT_WINDOWS_INTEGRATION)
    projects_source = _read(PROJECTS_SOURCE)

    row = _quality_ops_row("| 2026-05-31 | `RUN_INTEGRATION_TESTS=1 "
            "tests/integration/test_silent_windows.py::"
            "test_project_update_api_persists_silent_windows_in_settings")

    assert "` 1 passed" in row
    assert "`tests/unit/test_api/test_projects.py::test_update_project_serializes_silent_windows_into_settings` 1 passed" in row
    assert "release quality docs contract full 232 passed" in row
    assert "targeted ruff passed" in row
    assert "递归脱敏 `settings` 中的敏感 key" in row
    assert "完整 ProjectResponse" in row
    assert "DB settings 完整保留 allowed_branches/webhook_secret/silent_windows" in row
    assert "`project.update` AuditEvent tenant/user/resource 完整匹配" in row
    assert "before/after_state 精确等于脱敏后的 ProjectResponse" in row
    assert "webhook_secret 原值不进 audit" in row
    assert "此前只脱敏 git_url userinfo" in row
    assert "只抽查 response/settings/audit 中的 reason 与 allowed_branches" in row
    assert "`Project.settings.webhook_secret` 被写入 audit" in row
    assert "silent_windows integration exact response/settings/audit/no-secret" in row

    for expected in [
        "_SENSITIVE_PROJECT_SETTINGS_RE = re.compile(",
        "_REDACTED = {\"redacted\": True}",
        'data["settings"] = _redact_project_settings_audit_value(',
        "def _redact_project_settings_audit_value(value: Any) -> Any:",
        "dict(_REDACTED)",
        "def _is_sensitive_project_settings_key(key: Any) -> bool:",
        "redact_url_userinfo(value)",
    ]:
        assert expected in projects_source

    block = _marked_block(
        silent_windows,
        "async def test_project_update_api_persists_silent_windows_in_settings",
        "async def test_cron_tick_in_silent_window_skips_run_writes_audit_and_preserves_last_run_at",
    )

    for expected in [
        '"webhook_secret": "existing-webhook-secret"',
        "before_updated_at = _json_datetime(project.updated_at)",
        "expected_settings = {",
        '"allowed_branches": ["main"]',
        '"silent_windows": [window]',
        "assert body == {",
        '"settings": expected_settings',
        '"silent_windows": [window]',
        "assert project.settings == expected_settings",
        'assert _json_datetime(project.updated_at) == body["updated_at"]',
        "assert event.resource_type == \"project\"",
        "assert event.before_state == {",
        "assert event.after_state == {",
        '"webhook_secret": {"redacted": True}',
        '"updated_at": before_updated_at',
        '"existing-webhook-secret" not in repr(',
    ]:
        assert expected in block
    assert 'body["silent_windows"][0]["reason"]' not in block
    assert 'project.settings["silent_windows"][0]["reason"]' not in block
    assert 'event.after_state["silent_windows"][0]["reason"]' not in block
    assert 'event.after_state["settings"]["allowed_branches"]' not in block


def test_quality_ops_capture_project_members_list_exact_response_contract():
    ops_row = _quality_ops_row_containing("Project members list 精确响应契约")
    created_at_row = _quality_ops_row_containing(
        "Project members created_at 精确响应契约"
    )
    project_members_test = _read(PROJECT_MEMBERS_TEST)
    row = _quality_ops_row(
        "| 2026-05-31 | N/A（Project members list exact pagination body 契约）"
    )
    list_block = _marked_block(
        project_members_test,
        "async def test_list_project_members_returns_rows",
        "\n\n@pytest.mark.asyncio",
    )

    assert "Project members list exact pagination body 契约" in row
    assert (
        "`tests/unit/test_api/test_project_members.py::test_list_project_members_returns_rows` 1 passed"
        in row
    )
    assert "release quality docs contract full 334 passed" in row
    assert "完整分页 body" in row
    assert "`page=2`、`per_page=1`、`total=2`" in row
    assert "两个完整 ProjectMemberResponse item 必须整体等值" in row
    assert "tenant-scoped project lookup" in row
    assert "`list_by_project_tenant` offset/limit" in row
    assert 'body["page"]` / `body["per_page"]` / `body["total"]' in row
    assert "project members list exact pagination body 契约" in row
    assert "data 和几个分页数字分别看起来对" in row

    assert "Project members list 精确响应契约" in ops_row
    assert "按顺序固定 project_id、user_id、username、email、role 两条响应" in (
        ops_row
    )
    assert "Project members created_at 精确响应契约" in created_at_row
    assert "包含每个 member 对应的 created_at ISO 时间串" in created_at_row
    assert "created_at 仍只证明“非空”" in created_at_row
    assert "assert body == {" in list_block
    assert "member1_created_at.isoformat().replace" in list_block
    assert "member2_created_at.isoformat().replace" in list_block
    assert '"page": 2' in list_block
    assert '"per_page": 1' in list_block
    assert '"total": 2' in list_block
    assert "{key: value for key, value in item.items() if key != \"created_at\"}" not in (
        list_block
    )
    for rejected in [
        'assert body["page"] == 2',
        'assert body["per_page"] == 1',
        'assert body["total"] == 2',
        'assert body["data"] == [',
        'assert all(item["created_at"] for item in body["data"])',
        'assert {m["role"] for m in body["data"]} == {"admin", "viewer"}',
    ]:
        assert rejected not in list_block
    assert '"user_id": str(member1.user_id)' in list_block
    assert '"username": member2.user.username' in list_block


def test_quality_ops_capture_project_member_crud_exact_response_audit_contract():
    project_members_test = _read(PROJECT_MEMBERS_TEST)
    row = _quality_ops_row(
        "| 2026-05-31 | N/A（Project member CRUD exact response/audit 契约）"
    )

    assert "Project member CRUD exact response/audit 契约" in row
    assert (
        "`tests/unit/test_api/test_project_members.py::test_add_member_happy_path tests/unit/test_api/test_project_members.py::test_update_member_role tests/unit/test_api/test_project_members.py::test_remove_member` 3 passed"
        in row
    )
    assert "project members full 10 passed" in row
    assert "release quality docs contract full 186 passed" in row
    assert "完整 ProjectMemberResponse" in row
    assert "tenant-scoped project/user/member lookup" in row
    assert "完整 audit tenant/user/action/resource/before_state/after_state" in row
    assert "此前只抽查响应 `role`、audit `action` 与少量 state 字段" in row
    assert "delete after_state 不是 None" in row
    assert "项目成员正向测试只证明“成员角色变了且审计大概写过”" in row

    assert "def _expected_member_response(" in project_members_test
    assert '"created_at": _json_datetime(member.created_at)' in project_members_test

    add_block = _marked_block(
        project_members_test,
        "async def test_add_member_happy_path",
        "async def test_add_member_rejects_cross_tenant_user",
    )
    for expected in [
        "created_at = datetime(2026, 5, 31, 7, 8, 9, tzinfo=timezone.utc)",
        "created_member.user = target_user",
        "expected = _expected_member_response(created_member)",
        "assert resp.json() == expected",
        "mock_repos.project.get_for_tenant.assert_awaited_once_with(project_id, tenant_id)",
        "mock_repos.user.get_by_id.assert_awaited_once_with(target_user.id)",
        "mock_repos.project_member.get_existing.assert_awaited_once_with(",
        "mock_repos.project_member.create.assert_awaited_once_with(",
        "assert mock_repos.audit.create.await_args.kwargs == {",
        '"tenant_id": mock_user.tenant_id',
        '"user_id": mock_user.user_id',
        '"action": "project_member.add"',
        '"resource_type": "project_member"',
        '"resource_id": project_id',
        '"before_state": None',
        '"after_state": expected',
    ]:
        assert expected in add_block
    assert 'resp.json()["role"]' not in add_block
    assert 'audit_kwargs["action"]' not in add_block

    update_block = _marked_block(
        project_members_test,
        "async def test_update_member_role",
        "async def test_update_nonexistent_member_returns_404_without_side_effects",
    )
    for expected in [
        "created_at = datetime(2026, 5, 31, 8, 9, 10, tzinfo=timezone.utc)",
        "expected = _expected_member_response(member)",
        "assert resp.json() == expected",
        "mock_repos.project.get_for_tenant.assert_awaited_once_with(project_id, tenant_id)",
        "mock_repos.project_member.get_by_project_user.assert_awaited_once_with(",
        "mock_repos.project_member.update.assert_awaited_once_with(member, role=\"admin\")",
        "assert mock_repos.audit.create.await_args.kwargs == {",
        '"tenant_id": mock_user.tenant_id',
        '"user_id": mock_user.user_id',
        '"action": "project_member.update"',
        '"resource_type": "project_member"',
        '"resource_id": project_id',
        '"before_state": {"user_id": str(target_uid), "role": "developer"}',
        '"after_state": expected',
    ]:
        assert expected in update_block
    assert 'resp.json()["role"]' not in update_block
    assert 'audit_kwargs["after_state"]["role"]' not in update_block

    remove_block = _marked_block(
        project_members_test,
        "async def test_remove_member(",
        "async def test_remove_nonexistent_member_returns_404",
    )
    for expected in [
        "created_at=datetime(2026, 5, 31, 9, 10, 11, tzinfo=timezone.utc)",
        "mock_repos.project.get_for_tenant.assert_awaited_once_with(project_id, tenant_id)",
        "mock_repos.project_member.get_existing.assert_awaited_once_with(",
        "mock_repos.project_member.delete.assert_awaited_once_with(member)",
        "assert mock_repos.audit.create.await_args.kwargs == {",
        '"tenant_id": mock_user.tenant_id',
        '"user_id": mock_user.user_id',
        '"action": "project_member.remove"',
        '"resource_type": "project_member"',
        '"resource_id": project_id',
        '"before_state": {"user_id": str(target_uid), "role": "developer"}',
        '"after_state": None',
    ]:
        assert expected in remove_block
    assert 'audit_kwargs["action"]' not in remove_block
    assert 'audit_kwargs["before_state"]' not in remove_block


def test_quality_ops_capture_webhook_trigger_run_create_exact_identity_enqueue_contract():
    row = _quality_ops_row_containing(
        "Webhook trigger run create exact identity/enqueue 契约"
    )
    p3_test = _read(P3_TEST)

    assert "Webhook trigger run create exact identity/enqueue 契约" in row
    assert (
        "`tests/unit/test_api/test_p3.py::TestWebhookTrigger::test_webhook_trigger_creates_run` 1 passed"
        in row
    )
    assert "P3 full 60 passed" in row
    assert "固定 dedup 预查 kwargs、`run.create` kwargs 完整等值" in row
    assert (
        "{tenant_id,project_id,pipeline_id,environment_id,git_ref,git_sha,triggered_by,trigger_type,metadata_,dedup_key}"
        in row
    )
    assert "`enqueue_run` 五个位置参数与空 kwargs" in row
    assert "此前只逐字段抽查部分 create kwargs" in row
    assert "后来完整等值后仍保留字段集合守门" in row
    assert "失败信号停在字段集合噪音" in row
    assert "webhook 创建 run 测试只证明“run.create 被调用且几个字段看起来对”" in (
        row
    )

    create_block = _marked_block(
        p3_test,
        "async def test_webhook_trigger_creates_run",
        "async def test_webhook_trigger_preserves_project_git_auth_metadata",
    )

    assert "mock_project," in create_block
    assert "mock_user," in create_block
    assert "expected_dedup_key = " in create_block
    assert "mock_repos.run.get_active_by_dedup.assert_awaited_once_with(" in (
        create_block
    )
    assert "pipeline_id=mock_pipeline.id" in create_block
    assert "dedup_key=expected_dedup_key" in create_block
    assert "assert call_kwargs == {" in create_block
    assert "assert set(call_kwargs)" not in create_block
    for key in [
        '"tenant_id"',
        '"project_id"',
        '"pipeline_id"',
        '"environment_id"',
        '"git_ref"',
        '"git_sha"',
        '"triggered_by"',
        '"trigger_type"',
        '"metadata_"',
        '"dedup_key"',
    ]:
        assert key in create_block
    assert '"tenant_id": mock_project.tenant_id' in create_block
    assert '"project_id": project_id' in create_block
    assert '"pipeline_id": mock_pipeline.id' in create_block
    assert '"environment_id": mock_project.default_env_id' in create_block
    assert '"git_ref": "refs/heads/main"' in create_block
    assert '"git_sha": "abc123"' in create_block
    assert '"triggered_by": mock_user.user_id' in create_block
    assert '"trigger_type": "webhook"' in create_block
    assert '"git_url": "https://github.com/org/repo.git"' in create_block
    assert '"default_branch": "main"' in create_block
    assert '"dedup_key": expected_dedup_key' in create_block
    assert "assert enqueue_run.await_args.args == (" in create_block
    assert "app.state.container.arq_pool" in create_block
    assert "app.state.container.settings" in create_block
    assert "assert enqueue_run.await_args.kwargs == {}" in create_block

    assert 'assert call_kwargs["project_id"] == project_id' not in create_block
    assert 'assert call_kwargs["environment_id"] is not None' not in create_block
    assert "assert enqueue_run.await_args.args[:4] == (" not in create_block


def test_quality_ops_capture_webhook_metadata_reserved_key_exact_merge_contract():
    row = _quality_ops_row_containing(
        "Webhook metadata reserved-key exact merge 契约"
    )
    p3_test = _read(P3_TEST)

    assert "Webhook metadata reserved-key exact merge 契约" in row
    assert (
        "`tests/unit/test_api/test_p3.py::TestWebhookTrigger::test_webhook_trigger_preserves_project_git_auth_metadata` 1 passed"
        in row
    )
    assert "P3 full 60 passed" in row
    assert "`GIT_URL/git_auth_method/Credential_ID/default_branch/shallow_clone`" in (
        row
    )
    assert "固定 `run.create` 完整 kwargs、dedup 预查参数" in row
    assert "metadata 精确等于项目 Git 配置加允许的 `delivery_id/trace_id`" in (
        row
    )
    assert "此前只抽查 `metadata[\"git_auth_method\"]`" in row
    assert "reserved key 大小写绕过" in row
    assert "webhook Git 凭据测试只证明“三个 metadata 字段看起来对”" in (
        row
    )

    metadata_block = _marked_block(
        p3_test,
        "async def test_webhook_trigger_preserves_project_git_auth_metadata",
        "@pytest.mark.parametrize",
    )

    assert "attacker_credential_id = uuid.uuid4()" in metadata_block
    assert "mock_project.git_auth_method = \"token\"" in metadata_block
    assert "mock_project.credential_id = credential_id" in metadata_block
    assert "mock_project.shallow_clone = True" in metadata_block
    assert (
        'expected_dedup_key = "webhook:https://github.com/org/repo.git:abc123:main"'
        in metadata_block
    )
    assert "expected_metadata = {" in metadata_block
    for expected_value in [
        '"git_url": "https://github.com/org/repo.git"',
        '"git_auth_method": "token"',
        '"credential_id": str(credential_id)',
        '"shallow_clone": True',
        '"default_branch": "main"',
        '"delivery_id": "delivery-1"',
        '"trace_id": "trace-123"',
    ]:
        assert expected_value in metadata_block
    for attacker_value in [
        '"GIT_URL": "https://evil.example/repo.git"',
        '"git_auth_method": "ssh_key"',
        '"Credential_ID": str(attacker_credential_id)',
        '"default_branch": "evil-main"',
        '"shallow_clone": False',
    ]:
        assert attacker_value in metadata_block

    assert "mock_repos.run.get_active_by_dedup.assert_awaited_once_with(" in (
        metadata_block
    )
    assert "dedup_key=expected_dedup_key" in metadata_block
    assert "assert create_kwargs == {" in metadata_block
    assert "assert set(create_kwargs)" not in metadata_block
    assert '"metadata_": expected_metadata' in metadata_block
    assert '"dedup_key": expected_dedup_key' in metadata_block
    assert '"triggered_by": mock_user.user_id' in metadata_block
    assert "rendered_create = repr(create_kwargs)" in metadata_block
    assert "assert str(attacker_credential_id) not in rendered_create" in (
        metadata_block
    )
    assert 'assert "https://evil.example/repo.git" not in rendered_create' in (
        metadata_block
    )
    assert 'assert "evil-main" not in rendered_create' in metadata_block

    assert 'metadata = mock_repos.run.create.await_args.kwargs["metadata_"]' not in (
        metadata_block
    )
    assert 'assert metadata["git_auth_method"] == "token"' not in metadata_block
    assert 'assert metadata["delivery_id"] == "delivery-1"' not in metadata_block


def test_quality_ops_capture_github_provider_webhook_success_exact_route_contract():
    row = _quality_ops_row_containing(
        "GitHub provider webhook success exact route 契约"
    )
    p3_test = _read(P3_TEST)
    provider_block = _marked_block(
        p3_test,
        "async def test_provider_webhook_success_uses_system_identity_and_metadata",
        "async def test_provider_webhook_missing_signature_stops_before_run_creation",
    )

    assert "GitHub provider webhook success exact route 契约" in row
    assert (
        "`tests/unit/test_api/test_p3.py::TestProviderWebhookTrigger::test_provider_webhook_success_uses_system_identity_and_metadata` 1 passed"
        in row
    )
    assert "P3 full 60 passed" in row
    assert "release quality docs contract full 217 passed" in row
    assert "repository URL 候选精确集合" in row
    assert "`run.create` 完整 kwargs" in row
    assert "`enqueue_run` 五个位置参数与空 kwargs" in row
    assert "系统身份 `run.trigger` audit 的完整 payload" in row
    assert "此前只抽查一个 repo URL 候选" in row
    assert "provider URL 匹配面扩大" in row
    assert "audit after_state 不等于响应体" in row
    assert "GitHub provider webhook 成功测试只证明“201 且几个字段看起来对”" in (
        row
    )

    assert "body = resp.json()" in provider_block
    assert "assert body == _expected_run_response(run)" in provider_block
    assert "assert repo_urls == {" in provider_block
    for candidate in [
        '"https://github.com/acme/widget"',
        '"https://github.com/acme/widget.git"',
        '"git@github.com:acme/widget.git"',
    ]:
        assert candidate in provider_block
    assert "expected_dedup_key = f\"github:{mock_project.git_url}" in provider_block
    assert "mock_repos.run.get_active_by_dedup.assert_awaited_once_with(" in (
        provider_block
    )
    assert "expected_metadata = {" in provider_block
    for metadata_value in [
        '"git_url": mock_project.git_url',
        '"default_branch": "main"',
        '"provider": "github"',
        '"event": "push"',
        '"delivery_id": "delivery-123"',
        '"repository": "acme/widget"',
    ]:
        assert metadata_value in provider_block
    assert "mock_repos.run.create.assert_awaited_once_with(" in provider_block
    for create_arg in [
        "tenant_id=mock_project.tenant_id",
        "project_id=mock_project.id",
        "pipeline_id=mock_pipeline.id",
        "environment_id=mock_project.default_env_id",
        'git_ref="refs/heads/main"',
        'git_sha="a" * 40',
        "triggered_by=None",
        'trigger_type="webhook"',
        "metadata_=expected_metadata",
        "dedup_key=expected_dedup_key",
    ]:
        assert create_arg in provider_block
    assert "mock_repos.run.set_retry_group_id.assert_awaited_once_with(run.id, run.id)" in (
        provider_block
    )
    assert "assert enqueue_run.await_args.args == (" in provider_block
    assert "app.state.container.arq_pool" in provider_block
    assert "app.state.container.settings" in provider_block
    assert "assert enqueue_run.await_args.kwargs == {}" in provider_block
    assert "assert mock_repos.audit.create.await_args.kwargs == {" in provider_block
    assert '"user_id": None' in provider_block
    assert '"before_state": None' in provider_block
    assert '"after_state": body' in provider_block

    assert 'assert "https://github.com/acme/widget.git" in repo_urls' not in (
        provider_block
    )
    assert 'assert create_kwargs["tenant_id"] == mock_project.tenant_id' not in (
        provider_block
    )
    assert 'assert audit_kwargs["action"] == "run.trigger"' not in provider_block


def test_quality_ops_capture_analytics_repository_query_exact_kwargs_cutoff_contract():
    row = _quality_ops_row_containing(
        "Analytics repository query exact kwargs/cutoff 契约"
    )
    p3_test = _read(P3_TEST)

    assert "Analytics repository query exact kwargs/cutoff 契约" in row
    assert (
        "`tests/unit/test_api/test_p3.py::TestAnalytics::test_trends_returns_paginated_response tests/unit/test_api/test_p3.py::TestAnalytics::test_flaky_returns_paginated_response tests/unit/test_api/test_p3.py::TestAnalytics::test_test_history_returns_repository_rows` 3 passed"
        in row
    )
    assert "P3 full 60 passed" in row
    assert "固定仓储查询 kwargs 完整等值" in row
    assert "默认 `days=30` 的 timezone-aware cutoff" in row
    assert "完整响应体与不走 `session.execute`" in row
    assert "此前只逐字段抽查 project/offset/limit" in row
    assert "`cutoff.tzinfo is not None`" in row
    assert "cutoff 没减 days、min_runs/suite/name 漂移" in row
    assert "analytics 成功测试只证明“响应体来自 mock 行且仓储大概被调用”" in (
        row
    )

    assert "from datetime import datetime, timedelta, timezone" in p3_test
    assert "def _assert_cutoff_within_request_window(" in p3_test
    assert "assert cutoff.tzinfo is timezone.utc" in p3_test
    assert "started_at - timedelta(days=days) <= cutoff <= finished_at - timedelta(" in (
        p3_test
    )

    p3_analytics = _marked_block_or_tail(
        p3_test,
        "class TestAnalytics:",
        "\n\nclass ",
    )
    for test_name in [
        "async def test_trends_returns_paginated_response",
        "async def test_flaky_returns_paginated_response",
        "async def test_test_history_returns_repository_rows",
    ]:
        assert test_name in p3_analytics

    assert p3_analytics.count("request_started = datetime.now(timezone.utc)") >= 3
    assert p3_analytics.count("request_finished = datetime.now(timezone.utc)") >= 3
    assert p3_analytics.count("assert call_kwargs == {") >= 3
    assert p3_analytics.count("cutoff = call_kwargs[\"cutoff\"]") >= 3
    assert p3_analytics.count("_assert_cutoff_within_request_window(") >= 3
    assert p3_analytics.count("days=30,") >= 3
    assert p3_analytics.count("started_at=request_started,") >= 3
    assert p3_analytics.count("finished_at=request_finished,") >= 3
    assert "assert set(call_kwargs)" not in p3_analytics
    assert (
        'assert {key: value for key, value in call_kwargs.items() if key != "cutoff"} == {'
        not in p3_analytics
    )
    for expected in [
        '"project_id": project_id',
        '"offset": 0',
        '"limit": 365',
        '"min_runs": 3',
        '"limit": 50',
        '"suite": "checkout"',
        '"name": "test_login"',
    ]:
        assert expected in p3_analytics
    assert "mock_session.execute.assert_not_awaited()" in p3_analytics
    assert 'assert call_kwargs["project_id"] == project_id' not in p3_analytics
    assert 'assert call_kwargs["cutoff"].tzinfo is not None' not in p3_analytics


def test_quality_ops_capture_p3_analytics_custom_pagination_exact_empty_response_contract():
    p3_test = _read(P3_TEST)

    row = _quality_ops_row(
        "| 2026-05-31 | N/A（P3 analytics custom pagination exact empty response 契约）"
    )
    analytics_block = _after(p3_test, "class TestAnalytics:")
    trends_block = _block_between(analytics_block, "async def test_trends_with_custom_pagination", "async def test_trends_rejects_invalid_pagination")
    flaky_block = _block_between(analytics_block, "async def test_flaky_with_offset", "async def test_flaky_rejects_invalid_pagination")

    assert (
        "`tests/unit/test_api/test_p3.py::TestAnalytics::test_trends_with_custom_pagination "
        "tests/unit/test_api/test_p3.py::TestAnalytics::test_flaky_with_offset` 2 passed"
        in row
    )
    assert "P3 full 60 passed" in row
    assert "release quality docs contract full 322 passed" in row
    assert "targeted ruff passed" in row
    assert "空页完整响应体" in row
    assert "repository kwargs 精确字段集合" in row
    assert "默认 `days=30` cutoff 时间窗口" in row
    assert "pagination 子字段看起来对" in row

    for expected in [
        "request_started = datetime.now(timezone.utc)",
        "request_finished = datetime.now(timezone.utc)",
        "assert resp.json() == {",
        '"data": []',
        '"pagination": {"offset": 5, "limit": 3, "total": 10}',
        "mock_repos.run.list_trend_points.assert_awaited_once()",
        "call_kwargs = dict(mock_repos.run.list_trend_points.await_args.kwargs)",
        'assert call_kwargs == {"project_id": project_id, "offset": 5, "limit": 3}',
        "_assert_cutoff_within_request_window(",
        "days=30,",
    ]:
        assert expected in trends_block
    for rejected in [
        'body = resp.json()',
        'assert body["pagination"]["offset"] == 5',
        'assert body["pagination"]["limit"] == 3',
        'assert body["pagination"]["total"] == 10',
        'await_args.kwargs["offset"] == 5',
        'await_args.kwargs["limit"] == 3',
    ]:
        assert rejected not in trends_block

    for expected in [
        "request_started = datetime.now(timezone.utc)",
        "request_finished = datetime.now(timezone.utc)",
        "assert resp.json() == {",
        '"data": []',
        '"pagination": {"offset": 10, "limit": 20, "total": 100}',
        "mock_repos.test_result.list_flaky_tests.assert_awaited_once()",
        "call_kwargs = dict(mock_repos.test_result.list_flaky_tests.await_args.kwargs)",
        '"project_id": project_id',
        '"min_runs": 3',
        '"offset": 10',
        '"limit": 20',
        "_assert_cutoff_within_request_window(",
        "days=30,",
    ]:
        assert expected in flaky_block
    for rejected in [
        'body = resp.json()',
        'assert body["pagination"]["offset"] == 10',
        'assert body["pagination"]["limit"] == 20',
        'assert body["pagination"]["total"] == 100',
        'await_args.kwargs["offset"] == 10',
        'await_args.kwargs["limit"] == 20',
    ]:
        assert rejected not in flaky_block


def test_quality_ops_capture_missing_project_route_matrix_direct_error_lists():
    row = _quality_ops_row_containing(
        "Missing project route matrix ErrorResponse 直接列表契约"
    )
    credentials_test = _read(CREDENTIALS_TEST)
    project_members_test = _read(PROJECT_MEMBERS_TEST)
    notifications_test = _read(NOTIFICATIONS_TEST)
    environments_test = _read(ENVIRONMENTS_TEST)

    assert "Missing project route matrix ErrorResponse 直接列表契约" in row
    assert (
        "`tests/unit/test_api/test_credentials.py::test_credential_routes_hide_missing_project_without_side_effects tests/unit/test_api/test_project_members.py::test_project_member_routes_hide_missing_project_without_side_effects tests/unit/test_api/test_notifications.py::test_notification_rule_routes_hide_missing_project_without_side_effects tests/unit/test_api/test_environments.py::test_update_delete_environment_return_same_404_without_side_effects tests/unit/test_api/test_environments.py::test_environment_routes_hide_missing_project_without_side_effects` 5 passed"
        in row
    )
    assert "直接断言完整 `NOT_FOUND` ErrorResponse 列表" in row
    assert "每个入口的 `{code,message,details}`" in row
    assert "`assert all(body == bodies[0] for body in bodies)` 加首个 body 精确检查" in (
        row
    )
    assert "`bodies == [expected_body] * N` 的直接契约" in row
    assert "只证明“所有路由返回同一个东西”" in row

    for path_text, multiplier, message in [
        (credentials_test, 5, "Project not found"),
        (project_members_test, 4, "Project not found"),
        (notifications_test, 5, "Project not found"),
        (environments_test, 4, "Environment not found"),
        (environments_test, 5, "Project not found"),
    ]:
        assert "expected_body = {" in path_text
        assert '"code": "NOT_FOUND"' in path_text
        assert f'"message": "{message}"' in path_text
        assert '"details": []' in path_text
        assert f"assert bodies == [expected_body] * {multiplier}" in path_text
        assert "assert all(body == bodies[0] for body in bodies)" not in path_text


def test_quality_ops_capture_batch_internal_failure_exact_body_contract():
    row = _quality_ops_row_containing("Batch internal failure exact response body 契约")
    p3_test = _read(P3_TEST)

    assert "Batch internal failure exact response body 契约" in row
    assert (
        "`tests/unit/test_api/test_p3.py::TestBatchCancel::test_batch_cancel_internal_failure_redacts_exception_without_side_effects tests/unit/test_api/test_p3.py::TestBatchRetry::test_batch_retry_internal_failure_redacts_exception_without_side_effects` 2 passed"
        in row
    )
    assert "完整响应体只包含 `processed=0`、`failed=1`" in row
    assert "`errors=[<run_id>: operation failed]`" in row
    assert "SQL/token/底层异常文本不回显" in row
    assert "无 Redis/audit/retry 副作用" in row
    assert 'data["processed"]` / `data["failed"]` / `data["errors"]' in row
    assert "响应夹带 `details`、`trace_id`、异常类型或原始错误上下文" in (
        row
    )
    assert "只证明“核心三字段看起来对”" in row

    cancel_block = _marked_block(
        p3_test,
        "async def test_batch_cancel_internal_failure_redacts_exception_without_side_effects",
        "async def test_batch_cancel_rejects_duplicate_run_ids_without_side_effects"
    )
    retry_block = _marked_block(
        p3_test,
        "async def test_batch_retry_internal_failure_redacts_exception_without_side_effects",
        "async def test_batch_retry_rejects_duplicate_run_ids_without_side_effects"
    )

    for block, secret in [
        (cancel_block, "batch-cancel-secret"),
        (retry_block, "batch-retry-secret"),
    ]:
        assert "assert resp.json() == {" in block
        assert '"processed": 0' in block
        assert '"failed": 1' in block
        assert "operation failed" in block
        assert "secret_error not in resp.text" in block
        assert f'"{secret}" not in resp.text' in block
        assert 'data["processed"]' not in block
        assert 'data["failed"]' not in block
        assert 'data["errors"]' not in block


def test_quality_ops_capture_batch_business_outcome_exact_body_contract():
    row = _quality_ops_row_containing("Batch business outcome exact response body 契约")
    p3_test = _read(P3_TEST)

    assert "Batch business outcome exact response body 契约" in row
    assert (
        "`tests/unit/test_api/test_p3.py::TestBatchCancel::test_batch_cancel_success tests/unit/test_api/test_p3.py::TestBatchCancel::test_batch_cancel_not_found tests/unit/test_api/test_p3.py::TestBatchRetry::test_batch_retry_success tests/unit/test_api/test_p3.py::TestBatchRetry::test_batch_retry_not_terminal` 4 passed"
        in row
    )
    assert "success、not-found、not-terminal" in row
    assert "完整响应体 `{processed, failed, errors}`" in row
    assert "cancel/status publish、retry create/enqueue、audit" in row
    assert 'data["processed"]` / `data["failed"]` / `data["errors"]' in row
    assert "成功分支 `errors` 缺失/漂移" in row
    assert "只证明“关键计数字段看起来对”" in row

    blocks = [
        _marked_block(
            p3_test,
            "async def test_batch_cancel_success",
            "async def test_batch_cancel_not_found",
        ),
        _marked_block(
            p3_test,
            "async def test_batch_cancel_not_found",
            "async def test_batch_cancel_internal_failure_redacts_exception_without_side_effects",
        ),
        _marked_block(
            p3_test,
            "async def test_batch_retry_success",
            "async def test_batch_retry_not_terminal",
        ),
        _marked_block(
            p3_test,
            "async def test_batch_retry_not_terminal",
            "async def test_batch_retry_internal_failure_redacts_exception_without_side_effects",
        ),
    ]

    for block in blocks:
        assert "assert resp.json() == {" in block
        assert '"processed": ' in block
        assert '"failed": ' in block
        assert '"errors": ' in block
        assert 'data["processed"]' not in block
        assert 'data["failed"]' not in block
        assert 'data["errors"]' not in block

    assert '"errors": []' in blocks[0]
    assert '"errors": []' in blocks[2]
    assert "not found" in blocks[1]
    assert "not terminal" in blocks[3]


def test_quality_ops_capture_remaining_rejection_exact_body_contract():
    cancel_e2e = _read(CANCEL_E2E)
    webhook_branch_dedup = _read(WEBHOOK_BRANCH_DEDUP)
    notifications_test = _read(NOTIFICATIONS_TEST)
    project_members_test = _read(PROJECT_MEMBERS_TEST)

    row = _quality_ops_row(
        "| 2026-05-31 | `RUN_INTEGRATION_TESTS=1 tests/integration/test_webhook_branch_dedup.py::test_webhook_without_pipeline_returns_409_and_creates_no_run tests/integration/test_webhook_branch_dedup.py::test_webhook_without_environment_returns_409_and_creates_no_run` 2 passed；`RUN_INTEGRATION_TESTS=1 tests/integration/test_cancel_e2e.py::test_repeated_http_cancel_is_idempotent --collect-only` 1 test collected；cancel e2e py_compile passed | `tests/unit/test_api/test_notifications.py::test_get_rule_not_found tests/unit/test_api/test_notifications.py::test_notification_rule_item_routes_hide_other_project_rule_without_side_effects tests/unit/test_api/test_project_members.py::test_update_nonexistent_member_returns_404_without_side_effects tests/unit/test_api/test_project_members.py::test_remove_nonexistent_member_returns_404` 4 passed；release quality docs contract full 268 passed"
    )

    assert "剩余字段级错误体断言已收敛" in row
    assert "webhook 缺 pipeline/environment 409" in row
    assert "重复 cancel 第二次 409" in row
    assert "notification rule 404、project member 404" in row
    assert "完整 body/envelope" in row
    assert "no-run/no-side-effect/no-leak 证据" in row
    assert '`json()["detail"]` 或 `json()["error"]`' in row
    assert "project/member/rule/run 标识、配置 hint 或 debug 字段" in row
    assert "remaining rejection exact body 契约" in row
    assert "只证明“子字段文案正确”" in row

    cancel_block = _after(
        cancel_e2e,
        "async def test_repeated_http_cancel_is_idempotent",
    )
    no_pipeline_block = _block_between(webhook_branch_dedup, "async def test_webhook_without_pipeline_returns_409_and_creates_no_run", "async def test_webhook_without_environment_returns_409_and_creates_no_run")
    no_environment_block = _block_between(webhook_branch_dedup, "async def test_webhook_without_environment_returns_409_and_creates_no_run", "async def test_webhook_enqueue_conflict_keeps_run_waiting_and_audited")
    notification_missing_block = _block_between(notifications_test, "async def test_get_rule_not_found", "async def test_notification_rule_item_routes_hide_other_project_rule_without_side_effects")
    notification_cross_project_block = _block_between(notifications_test, "async def test_notification_rule_item_routes_hide_other_project_rule_without_side_effects", "async def test_update_rule")
    member_update_block = _block_between(project_members_test, "async def test_update_nonexistent_member_returns_404_without_side_effects", "async def test_remove_member")
    member_remove_block = _block_between(project_members_test, "async def test_remove_nonexistent_member_returns_404", "async def test_project_member_routes_hide_missing_project_without_side_effects")

    assert (
        'assert second.json() == {"detail": "Run already in terminal status: cancelled"}'
        in cancel_block
    )
    assert (
        'assert resp.json() == {"detail": "No pipeline configured for project"}'
        in no_pipeline_block
    )
    assert (
        'assert resp.json() == {"detail": "No environment configured for project"}'
        in no_environment_block
    )
    for block in (
        notification_missing_block,
        notification_cross_project_block,
        member_update_block,
        member_remove_block,
    ):
        assert "assert resp.json() == {" in block
        assert '"error": {' in block
        assert 'resp.json()["error"]' not in block

    for block in (cancel_block, no_pipeline_block, no_environment_block):
        assert 'json()["detail"]' not in block

    assert "Run already in terminal status: cancelled" in cancel_block
    assert "assert await _webhook_run_count" in no_pipeline_block
    assert "assert await _webhook_run_count" in no_environment_block
    assert "mock_repos.audit.create.assert_not_awaited()" in (
        notification_missing_block
    )
    assert "assert str(rule.project_id) not in resp.text" in (
        notification_cross_project_block
    )
    assert "mock_repos.audit.create.assert_not_awaited()" in member_update_block
    assert "mock_repos.project_member.delete.assert_not_awaited()" in member_remove_block


def test_quality_ops_capture_p3_analytics_exact_response_contracts():
    quality_ops = _quality_ops_rows_containing(
        "P3 analytics exact response 契约",
        "P3 analytics test-history 精确响应契约",
    )
    p3_test = _read(P3_TEST)

    assert "P3 analytics exact response 契约" in quality_ops
    assert "trends/flaky 单测固定完整 response body" in quality_ops
    assert "P3 analytics test-history 精确响应契约" in quality_ops
    assert "passed_runs/failed_runs/pass_rate" in quality_ops
    assert "name/total_runs/passed_count/failed_count/flaky_rate" in quality_ops
    assert "run_id/run_created_at/run_status/status/duration_ms/error_message/git_ref" in (
        quality_ops
    )
    assert '"pass_rate": 0.8' in p3_test
    assert '"failed_runs": 2' in p3_test
    assert '"name": "test_login"' in p3_test
    assert '"passed_count": 7' in p3_test
    assert '"flaky_rate": 0.3' in p3_test
    assert '"run_created_at": run_created_at.isoformat().replace(' in p3_test
    assert '"git_ref": "main"' in p3_test
    assert 'assert "data" in body' not in p3_test
    assert 'body["data"][0]["error_message"] == "boom"' not in p3_test


def test_quality_ops_capture_api_delete_204_empty_body_contract():
    test_sources = {
        "test_delete_credential_happy_path": _read(CREDENTIALS_TEST),
        "test_delete_environment_removes_existing_environment_and_audits": _read(ENVIRONMENTS_TEST),
        "test_delete_rule": _read(NOTIFICATIONS_TEST),
        "test_delete_pipeline_removes_existing_pipeline_and_audits": _read(PIPELINES_TEST),
        "test_remove_member": _read(PROJECT_MEMBERS_TEST),
        "test_delete_project": _read(PROJECTS_TEST),
        "test_delete_schedule": _read(SCHEDULES_TEST),
    }

    row = _quality_ops_row("| 2026-05-31 | N/A（API delete/remove 204 空 body 契约）")
    assert "` 7 passed" in row
    assert "release quality docs contract full 250 passed" in row
    assert "targeted ruff passed" in row
    assert "固定 204 且 `resp.content == b\"\"`" in row
    assert "避免 delete/remove 单测只证明“状态码和副作用看起来对”" in row

    for test_name, source in test_sources.items():
        block = _block_between(source, f"async def {test_name}", "\n\n@pytest.mark.asyncio")
        assert "assert resp.status_code == 204" in block
        assert 'assert resp.content == b""' in block


def test_quality_ops_capture_project_creator_membership_exact_session_contract():
    projects_test = _read(PROJECTS_TEST)
    row = _quality_ops_row(
        "| 2026-05-31 | N/A（Project creator membership exact session add/flush 契约）"
    )

    assert "Project creator membership exact session add/flush 契约" in row
    assert (
        "`tests/unit/test_api/test_projects.py::test_create_project_adds_creator_as_project_admin` 1 passed"
        in row
    )
    assert "projects full 59 passed" in row
    assert "release quality docs contract full 195 passed" in row
    assert "只 `add` 一个 `ProjectMemberORM`" in row
    assert "随后立刻 `flush`" in row
    assert "role/user_id/project_id/tenant_id/deleted_at" in row
    assert "`len(members) == 1`" in row
    assert "额外 add 其他对象" in row
    assert "漏掉 flush" in row
    assert "某处出现过一个成员对象" in row

    test_block = _marked_block(
        projects_test,
        "async def test_create_project_adds_creator_as_project_admin",
        "async def test_get_project",
    )

    for expected in [
        "captured_added = []",
        "operations = []",
        'operations.append(("add", instance))',
        'operations.append(("flush", None))',
        "member = captured_added[0]",
        "assert captured_added == [member]",
        "assert isinstance(member, ProjectMemberORM)",
        'assert operations == [("add", member), ("flush", None)]',
        'assert member.role == "admin"',
        "assert member.user_id == mock_user.user_id",
        "assert member.project_id == project.id",
        "assert member.tenant_id == tenant_id",
        "assert member.deleted_at is None",
    ]:
        assert expected in test_block
    assert "assert len(members) == 1" not in test_block
    assert "str(m.role)" not in test_block
