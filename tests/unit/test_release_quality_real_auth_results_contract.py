from __future__ import annotations

from pathlib import Path

from tests.unit.release_quality_contract_helpers import (
    _block_between,
    _marked_block,
    _quality_ops_row,
    _quality_ops_row_containing,
    _read,
    _test_block,
)


ROOT = Path(__file__).resolve().parents[2]
AUTH_API_SOURCE = ROOT / "src" / "qaplatform" / "api" / "v1" / "auth.py"
AUTH_COMMAND_SOURCE = ROOT / "src" / "qaplatform" / "api" / "auth" / "commands.py"
AUTH_ROUTES_TEST = ROOT / "tests" / "unit" / "test_auth" / "test_auth_routes.py"
PERFORMANCE_SMOKE = ROOT / "tests" / "integration" / "test_performance_smoke.py"
REAL_AUTH_RESULTS_ARTIFACTS = (
    ROOT / "tests" / "integration" / "test_real_auth_results_artifacts.py"
)
WORKER_EXECUTE = ROOT / "tests" / "integration" / "test_worker_execute.py"


def test_quality_ops_capture_storage_unavailable_exact_body_contract():
    real_auth_results_artifacts = _read(REAL_AUTH_RESULTS_ARTIFACTS)
    performance_smoke = _read(PERFORMANCE_SMOKE)

    row = _quality_ops_row(
        "| 2026-05-31 | `RUN_INTEGRATION_TESTS=1 tests/integration/test_real_auth_results_artifacts.py::test_archived_logs_api_returns_503_when_storage_unconfigured_after_rbac tests/integration/test_real_auth_results_artifacts.py::test_artifact_download_url_uses_real_auth_rbac_and_db_row` 2 passed | `RUN_INTEGRATION_TESTS=1 RUN_PERFORMANCE_TESTS=1 tests/integration/test_performance_smoke.py::test_archived_log_storage_unavailable_p99_smoke tests/integration/test_performance_smoke.py::test_artifact_download_storage_unavailable_p99_smoke` 2 passed；release quality docs contract full 264 passed"
    )

    assert "storage-unavailable" in row
    assert "`{\"detail\": \"Archived logs are not available\"}`" in row
    assert "`{\"detail\": \"Artifact download is not available\"}`" in row
    assert "required integration" in row
    assert "performance smoke warmup/sample 循环" in row
    assert "真实 RBAC/PostgreSQL 后才在 S3 client 边界短路" in row
    assert '只断言 `json()["detail"]`' in row
    assert "bucket、storage path、artifact id、配置 hint 或 debug 字段" in row
    assert "storage-unavailable 503 exact body 契约" in row
    assert "只证明“返回了 503 且 detail 文案对”" in row

    real_archive_block = _block_between(real_auth_results_artifacts, "async def test_archived_logs_api_returns_503_when_storage_unconfigured_after_rbac", "async def test_artifact_download_url_uses_real_auth_rbac_and_db_row")
    real_download_block = _block_between(real_auth_results_artifacts, "async def test_artifact_download_url_uses_real_auth_rbac_and_db_row", "async def test_artifact_download_soft_deleted_row_returns_404_without_presign")
    perf_archive_block = _block_between(performance_smoke, "async def test_archived_log_storage_unavailable_p99_smoke", "async def test_archived_log_denied_no_s3_read_p99_smoke")
    perf_download_block = _block_between(performance_smoke, "async def test_artifact_download_storage_unavailable_p99_smoke", "async def test_artifact_download_denied_no_presign_p99_smoke")

    assert 'assert replay_resp.json() == {"detail": "Archived logs are not available"}' in (
        real_archive_block
    )
    assert (
        'assert download_resp.json() == {"detail": "Artifact download is not available"}'
        in real_download_block
    )
    assert (
        'assert response.json() == {"detail": "Archived logs are not available"}'
        in perf_archive_block
    )
    assert (
        'assert response.json() == {"detail": "Artifact download is not available"}'
        in perf_download_block
    )
    assert 'json()["detail"]' not in real_archive_block
    assert 'json()["detail"]' not in real_download_block
    assert 'json()["detail"]' not in perf_archive_block
    assert 'json()["detail"]' not in perf_download_block


def test_quality_ops_capture_real_auth_artifact_list_exact_response_contract():
    real_auth_results_artifacts = _read(REAL_AUTH_RESULTS_ARTIFACTS)

    row = _quality_ops_row(
        "| 2026-05-31 | `RUN_INTEGRATION_TESTS=1 .venv/bin/python -m pytest "
        "tests/integration/test_real_auth_results_artifacts.py::"
        "test_run_read_token_replays_logs_and_presigns_artifact_without_extra_s3_reads "
        "tests/integration/test_real_auth_results_artifacts.py::"
        "test_artifact_download_url_uses_real_auth_rbac_and_db_row -q` 2 passed"
    )
    bundle_block = _block_between(real_auth_results_artifacts, "async def test_run_read_token_replays_logs_and_presigns_artifact_without_extra_s3_reads", "async def test_log_archive_retry_worker_uses_real_redis_marker")
    download_block = _block_between(real_auth_results_artifacts, "async def test_artifact_download_url_uses_real_auth_rbac_and_db_row", "async def test_artifact_download_soft_deleted_row_returns_404_without_presign")

    assert "release quality docs contract full 325 passed" in row
    assert "targeted ruff passed" in row
    assert "完整 ArtifactResponse 分页体" in row
    assert "artifact list 不触发 S3 read/presign" in row
    assert "`total`、`data[0].id` 和 `data[0].storage_path`" in row
    assert "real auth artifact list exact response 契约" in row
    assert "能看到某个 artifact 的 id 和路径" in row

    for block, expected_name, expected_size, expected_per_page in [
        (bundle_block, "bundle-summary.html", 512, 10),
        (download_block, "summary.html", 128, 20),
    ]:
        for expected in [
            "assert list_resp.status_code == 200, list_resp.text",
            '"data": [',
            '"id": str(artifact.id)',
            '"run_id": str(run_id)',
            '"type": "html"',
            f'"name": "{expected_name}"',
            '"storage_path": storage_path',
            f'"size_bytes": {expected_size}',
            '"mime_type": "text/html"',
            '"expires_at": None',
            '"created_at": _json_datetime(artifact.created_at)',
            '"page": 1',
            f'"per_page": {expected_per_page}',
            '"total": 1',
        ]:
            assert expected in block
        for rejected in [
            'assert artifacts_body["total"] == 1',
            'assert artifacts_body["data"][0]["id"] == str(artifact.id)',
            'assert artifacts_body["data"][0]["storage_path"] == storage_path',
            'assert list_body["total"] == 1',
            'assert list_body["data"][0]["id"] == str(artifact.id)',
            'assert list_body["data"][0]["storage_path"] == storage_path',
        ]:
            assert rejected not in block


def test_quality_ops_capture_artifact_download_real_404_exact_envelope_contract():
    real_auth_results_artifacts = _read(REAL_AUTH_RESULTS_ARTIFACTS)

    row = _quality_ops_row(
        "| 2026-05-31 | `RUN_INTEGRATION_TESTS=1 tests/integration/test_real_auth_results_artifacts.py::test_artifact_download_soft_deleted_row_returns_404_without_presign tests/integration/test_real_auth_results_artifacts.py::test_artifact_download_api_token_cross_tenant_returns_same_404` 2 passed | release quality docs contract full 270 passed"
    )

    assert "真实 artifact download 的 soft-deleted 与跨租户 404" in row
    assert "与随机 UUID 响应一致" in row
    assert (
        '`{"error":{"code":"NOT_FOUND","message":"Artifact not found","details":[]}}`'
        in row
    )
    assert "no-presign/no-get" in row
    assert "artifact id/storage path 不回显" in row
    assert "只比较“目标 artifact 与随机 UUID 的响应相等”" in row
    assert "artifact_id、storage_path、tenant hint 或 debug details" in row
    assert "artifact download real 404 exact envelope 契约" in row
    assert "只证明“两边一样”" in row

    soft_deleted_block = _block_between(real_auth_results_artifacts, "async def test_artifact_download_soft_deleted_row_returns_404_without_presign", "async def test_artifact_download_api_token_cross_tenant_returns_same_404")
    cross_tenant_block = _block_between(real_auth_results_artifacts, "async def test_artifact_download_api_token_cross_tenant_returns_same_404", "async def test_artifact_upload_enforces_limits_before_real_db_rows")

    for block in (soft_deleted_block, cross_tenant_block):
        assert "expected_404 = {" in block
        assert '"code": "NOT_FOUND"' in block
        assert '"message": "Artifact not found"' in block
        assert '"details": []' in block
        assert "== random_resp.json() == expected_404" in block
        assert "assert s3.presign_calls == []" in block
        assert "assert s3.get_calls == []" in block

    assert "assert str(artifact_b.id) not in tenant_b_resp.text" in cross_tenant_block
    assert "assert artifact_b.storage_path not in tenant_b_resp.text" in (
        cross_tenant_block
    )


def test_quality_ops_capture_artifact_upload_limit_exact_log_sequence_contract():
    real_auth_results_artifacts = _read(REAL_AUTH_RESULTS_ARTIFACTS)

    row = _quality_ops_row("| 2026-05-31 | `RUN_INTEGRATION_TESTS=1 .venv/bin/python -m pytest "
            "tests/integration/test_real_auth_results_artifacts.py::"
            "test_artifact_upload_enforces_limits_before_real_db_rows -q` 1 passed")
    assert "artifact upload limit 集成用例" in row
    assert "真实 S3 object dict" in row
    assert "四条 `write_log` 序列" in row
    assert "run_id/line/stream 全部等值" in row
    assert "日志仍用 `assert any(...)` 找片段" in row
    assert "artifact upload limit exact log/S3 sequence 契约" in row
    assert "只证明“DB/S3 大致没写超限文件且日志里有几个词”" in row

    block = _block_between(real_auth_results_artifacts, "async def test_artifact_upload_enforces_limits_before_real_db_rows", "async def test_artifact_upload_s3_failure_leaves_no_real_db_rows")

    assert "assert s3.objects == {" in block
    assert '("qa-platform-test", f"reports/{run_id}/a.txt"): b"ok"' in block
    assert '("qa-platform-test", f"reports/{run_id}/c.txt"): b"ok"' in block
    assert "log_calls = [" in block
    assert '"line": "Uploaded artifact: a.txt"' in block
    assert (
        '"line": "Skipped artifact b.txt: size 9 exceeds limit 2 bytes"' in block
    )
    assert '"line": "Uploaded artifact: c.txt"' in block
    assert (
        '"line": "Skipped artifact d.txt: artifact count limit exceeded"' in block
    )
    assert block.count('"stream": "stderr"') == 2
    assert block.count('"stream": "stdout"') == 2
    assert 'assert any("exceeds limit"' not in block
    assert 'assert any("count limit exceeded"' not in block


def test_quality_ops_capture_real_auth_artifact_projection_exact_contract():
    real_auth_results_artifacts = _read(REAL_AUTH_RESULTS_ARTIFACTS)

    row = _quality_ops_row("| 2026-05-31 | `RUN_INTEGRATION_TESTS=1 "
            "tests/integration/test_real_auth_results_artifacts.py::"
            "test_artifact_list_api_token_requires_run_read_scope "
            "tests/integration/test_real_auth_results_artifacts.py::"
            "test_artifact_upload_recurses_allure_report_with_real_db_rows "
            "-q` 2 passed")
    assert "targeted docs contract passed" in row
    assert "targeted ruff/collect-only passed" in row
    assert "targeted integration passed" in row
    assert "完整 ArtifactResponse item 投影" in row
    assert "{id,run_id,type,name,storage_path,size_bytes,mime_type,expires_at,created_at}" in (
        row
    )
    assert "DB artifact row `{run_id,type,name,storage_path,size_bytes,mime_type}`" in (
        row
    )
    assert "S3 object bytes 完整等值" in row
    assert "`assert set(artifacts_by_id)` / `assert set(by_name)`" in row
    assert "real auth artifact projection exact contract" in row
    assert "artifact 集成测试为了覆盖率而只数名字" in row

    artifact_list_block = _block_between(real_auth_results_artifacts, "async def test_artifact_list_api_token_requires_run_read_scope", "async def test_run_artifacts_list_paginates_real_db_without_s3_side_effects")
    allure_block = _block_between(real_auth_results_artifacts, "async def test_artifact_upload_recurses_allure_report_with_real_db_rows", "async def test_api_token_scope_matrix_enforced_by_real_routes")

    for expected in [
        "artifact_created_at = datetime(2026, 1, 1, tzinfo=timezone.utc)",
        "created_at=artifact_created_at,",
        "created_at=artifact_created_at + timedelta(seconds=1),",
        "expected_body = {",
        '"page": 1',
        '"per_page": 10',
        '"total": 2',
        "for artifact in (second, first)",
        '"id": str(artifact.id)',
        '"run_id": run_id',
        '"type": artifact.type',
        '"name": artifact.name',
        '"storage_path": artifact.storage_path',
        '"size_bytes": artifact.size_bytes',
        '"mime_type": artifact.mime_type',
        '"created_at": _json_datetime(artifact.created_at)',
        "assert body == expected_body",
    ]:
        assert expected in artifact_list_block
    for rejected in [
        "artifacts_by_id =",
        "assert set(artifacts_by_id)",
        "first_body =",
        "second_body =",
        'assert body["total"] == 2',
        '"data": body["data"]',
        'artifact_items = sorted(body["data"], key=lambda item: item["id"])',
        "expected_artifact_items = sorted(",
        "assert artifact_items == expected_artifact_items",
    ]:
        assert rejected not in artifact_list_block

    for expected in [
        "artifact_rows = sorted(",
        '"run_id": str(row.run_id)',
        '"type": row.type',
        '"name": row.name',
        '"storage_path": row.storage_path',
        '"size_bytes": row.size_bytes',
        '"mime_type": row.mime_type',
        "assert artifact_rows == [",
        '"name": "allure-report/assets/app.js"',
        '"storage_path": f"reports/{run_id}/allure-report/assets/app.js"',
        '"size_bytes": len("ok")',
        '"mime_type": "text/javascript"',
        '"name": "allure-report/index.html"',
        '"storage_path": f"reports/{run_id}/allure-report/index.html"',
        '"size_bytes": len("<html/>")',
        '"mime_type": "text/html"',
        "assert s3.objects == {",
        '"qa-platform-test",',
        '): b"ok"',
        '): b"<html/>"',
    ]:
        assert expected in allure_block
    for rejected in [
        "by_name =",
        "assert set(by_name)",
        'by_name["allure-report/index.html"]',
        "{\n        key for _bucket, key in s3.objects",
    ]:
        assert rejected not in allure_block


def test_quality_ops_capture_api_token_project_read_exact_list_contract():
    row = _quality_ops_row_containing("API token scope matrix 中 `project.read` token")
    real_auth_results_artifacts = _read(REAL_AUTH_RESULTS_ARTIFACTS)

    assert "API token scope matrix 中 `project.read` token" in row
    assert "固定 total=1 且 data id 列表只含当前 project" in row
    assert 'assert read_body["total"] == 1' in real_auth_results_artifacts
    assert (
        '[item["id"] for item in read_body["data"]] == [stack["project_id"]]'
        in real_auth_results_artifacts
    )
    assert 'stack["project_id"] in {item["id"] for item in read_resp.json()["data"]}' not in (
        real_auth_results_artifacts
    )


def test_quality_ops_capture_real_auth_token_pagination_exact_response_contract():
    row = _quality_ops_row_containing(
        "真实 auth API token 分页测试现在固定第二页完整列表项"
    )
    real_auth_results_artifacts = _read(REAL_AUTH_RESULTS_ARTIFACTS)

    assert "真实 auth API token 分页测试现在固定第二页完整列表项" in row
    assert "用完整 body 等值排除一次性 token 明文" in row
    assert "删除完整 body 后的重复字段集合守门" in row
    assert "避免 token 列表测试只证明“有一个熟悉名字且没看到 token”" in (
        row
    )
    assert "assert page_body == {" in real_auth_results_artifacts
    assert '"data": [created_tokens[0]]' in real_auth_results_artifacts
    assert '"last_used_at": None' in real_auth_results_artifacts
    assert '"is_revoked": False' in real_auth_results_artifacts
    assert 'assert set(page_body["data"][0]) == {' not in real_auth_results_artifacts
    assert 'assert len(page_body["data"]) == 1' not in real_auth_results_artifacts
    assert 'page_body["data"][0]["name"] in token_names' not in (
        real_auth_results_artifacts
    )
    assert 'assert "token" not in page_body["data"][0]' not in (
        real_auth_results_artifacts
    )


def test_quality_ops_capture_real_auth_token_empty_pagination_exact_response_contract():
    row = _quality_ops_row_containing(
        "真实 auth API token 空分页现在固定完整"
    )
    real_auth_results_artifacts = _read(REAL_AUTH_RESULTS_ARTIFACTS)
    test_block = _block_between(real_auth_results_artifacts, "async def test_auth_tokens_list_is_paginated", "async def test_audit_events_api_token_requires_audit_read_scope_without_self_audit_on_denial")

    assert "真实 auth API token 空分页现在固定完整" in row
    assert "release quality docs contract full 246 passed" in row
    assert "避免 token 空分页测试只证明“空列表且总数对”" in row
    assert "empty_body = empty_resp.json()" in test_block
    assert "assert empty_body == {" in test_block
    assert '"data": []' in test_block
    assert '"page": 99' in test_block
    assert '"per_page": 2' in test_block
    assert '"total": 3' in test_block
    assert 'empty_resp.json()["data"]' not in test_block
    assert 'empty_resp.json()["total"]' not in test_block


def test_quality_ops_capture_real_auth_audit_events_exact_response_contract():
    row = _quality_ops_row_containing(
        "真实 auth API token 访问 audit-events 正向路径"
    )
    real_auth_results_artifacts = _read(REAL_AUTH_RESULTS_ARTIFACTS)
    test_block = _block_between(real_auth_results_artifacts, "async def test_audit_events_api_token_requires_audit_read_scope_without_self_audit_on_denial", "async def test_auth_refresh_logout_audits_do_not_store_tokens_or_passwords")

    assert "真实 auth API token 访问 audit-events 正向路径" in row
    assert "AuditEventResponse body" in row
    assert "删除完整 body 后的重复字段集合守门" in row
    assert "避免权限正向测试只证明“能看到那条审计”" in row
    assert "audit_event = AuditEvent(" in test_block
    assert "await integration_db_session.refresh(audit_event)" in test_block
    assert "assert body == {" in test_block
    assert '"id": str(audit_event.id)' in test_block
    assert '"before_state": None' in test_block
    assert '"after_state": {"marker": action}' in test_block
    assert '"ip_address": None' in test_block
    assert '"user_agent": None' in test_block
    assert '"created_at": audit_event.created_at.isoformat().replace(' in test_block
    assert "assert self_audit.after_state == {" in test_block
    assert '"actor_id": None' in test_block
    assert '"resource_id": str(resource_id)' in test_block
    assert '"total": 1' in test_block
    assert 'assert set(body["data"][0]) == {' not in test_block
    assert "assert set(self_audit.after_state)" not in test_block
    assert 'assert "data" not in self_audit.after_state' not in test_block
    assert (
        'assert body["total"] == 1\n'
        '    assert [item["action"] for item in body["data"]] == [action]\n'
        '    assert body["data"][0]["resource_id"] == str(resource_id)'
    ) not in test_block


def test_quality_ops_capture_real_auth_scope_denial_exact_body_contract():
    real_auth_results_artifacts = _read(REAL_AUTH_RESULTS_ARTIFACTS)
    row = _quality_ops_row(
        "| 2026-05-31 | `RUN_INTEGRATION_TESTS=1 "
        "tests/integration/test_real_auth_results_artifacts.py::test_audit_events_api_token_requires_audit_read_scope_without_self_audit_on_denial"
    )
    audit_block = _block_between(real_auth_results_artifacts, "async def test_audit_events_api_token_requires_audit_read_scope_without_self_audit_on_denial", "\n\n@pytest.mark.asyncio")
    archived_logs_block = _block_between(real_auth_results_artifacts, "async def test_archived_logs_api_token_requires_run_read_scope", "\n\n@pytest.mark.asyncio")
    artifact_list_block = _block_between(real_auth_results_artifacts, "async def test_artifact_list_api_token_requires_run_read_scope", "\n\n@pytest.mark.asyncio")
    artifact_download_block = _block_between(real_auth_results_artifacts, "async def test_artifact_download_api_token_requires_run_read_scope", "\n\n@pytest.mark.asyncio")

    assert "real auth API token scope denial exact body 契约" in row
    assert "release quality docs contract full 256 passed" in row
    assert "targeted ruff passed" in row
    assert "`{\"detail\": \"Insufficient permissions\"}`" in row
    assert "no self-audit、no-S3 get/presign" in row
    assert "只证明“拒绝了且没碰 S3/没写自审计”" in row

    for block in [
        audit_block,
        archived_logs_block,
        artifact_list_block,
        artifact_download_block,
    ]:
        assert (
            block.count(
                'assert denied_resp.json() == {"detail": "Insufficient permissions"}'
            )
            == 1
        )

    assert "assert await count_self_audits() == before_self_audits" in audit_block
    assert "assert action not in denied_resp.text" in audit_block
    assert "assert str(resource_id) not in denied_resp.text" in audit_block
    assert (
        "assert denied_resp.status_code == 403, f\"{label}: {denied_resp.text}\"\n"
        "        assert action not in denied_resp.text"
        not in audit_block
    )

    assert 'assert f"logs/{run_id}.jsonl" not in denied_resp.text' in (
        archived_logs_block
    )
    assert 'assert "scope-line-" not in denied_resp.text' in archived_logs_block
    assert "assert s3.get_calls == []" in archived_logs_block
    assert "assert s3.presign_calls == []" in archived_logs_block

    assert 'assert "summary.html" not in denied_resp.text' in artifact_list_block
    assert 'assert "results.xml" not in denied_resp.text' in artifact_list_block
    assert 'assert f"reports/{run_id}/" not in denied_resp.text' in (
        artifact_list_block
    )
    assert "assert s3.presign_calls == []" in artifact_list_block
    assert "assert s3.get_calls == []" in artifact_list_block

    assert "assert artifact.name not in denied_resp.text" in artifact_download_block
    assert "assert artifact.storage_path not in denied_resp.text" in (
        artifact_download_block
    )
    assert "assert s3.presign_calls == []" in artifact_download_block
    assert "assert s3.get_calls == []" in artifact_download_block


def test_quality_ops_capture_api_token_scope_matrix_exact_denial_body_contract():
    real_auth_results_artifacts = _read(REAL_AUTH_RESULTS_ARTIFACTS)
    row = _quality_ops_row(
        "| 2026-05-31 | `RUN_INTEGRATION_TESTS=1 "
        "tests/integration/test_real_auth_results_artifacts.py::test_api_token_scope_matrix_enforced_by_real_routes"
    )
    test_block = _block_between(real_auth_results_artifacts, "async def test_api_token_scope_matrix_enforced_by_real_routes", "\n\n@pytest.mark.asyncio")

    assert "API token scope matrix exact denial body 契约" in row
    assert "release quality docs contract full 257 passed" in row
    assert "targeted ruff passed" in row
    assert "`{\"detail\": \"Insufficient permissions\"}`" in row
    assert "project 未落库、schedule count 不变、run.trigger 正向 Run 行匹配证据" in (
        row
    )
    assert "只证明“这些分支都 403”" in row

    for expected in [
        'assert denied_write.json() == {"detail": "Insufficient permissions"}',
        'assert denied_schedule.json() == {"detail": "Insufficient permissions"}',
        'assert wrong_scope_resp.json() == {"detail": "Insufficient permissions"}',
        'assert empty_scope_resp.json() == {"detail": "Insufficient permissions"}',
        "assert denied_project_count == 0",
        "assert schedule_count_after == schedule_count_before",
        "assert triggered[\"project_id\"] == stack[\"project_id\"]",
        "assert run.status == RunStatusEnum.QUEUED",
    ]:
        assert expected in test_block
    assert test_block.count('{"detail": "Insufficient permissions"}') == 4
    for weak_fragment in [
        "assert denied_write.status_code == 403, denied_write.text\n"
        "    denied_project_count",
        "assert denied_schedule.status_code == 403, denied_schedule.text\n"
        "    schedule_count_after",
        "assert wrong_scope_resp.status_code == 403, wrong_scope_resp.text\n\n",
        "assert empty_scope_resp.status_code == 403, empty_scope_resp.text\n\n",
    ]:
        assert weak_fragment not in test_block


def test_quality_ops_capture_real_api_token_revoke_exact_rejection_contract():
    real_auth_results_artifacts = _read(REAL_AUTH_RESULTS_ARTIFACTS)
    row = _quality_ops_row(
        "| 2026-05-31 | `RUN_INTEGRATION_TESTS=1 "
        "tests/integration/test_real_auth_results_artifacts.py::test_real_jwt_created_api_token_authenticates_updates_last_used_and_revokes"
    )
    test_block = _block_between(real_auth_results_artifacts, "async def test_real_jwt_created_api_token_authenticates_updates_last_used_and_revokes", "\n\n@pytest.mark.asyncio")

    assert "real API token revoke rejection exact body 契约" in row
    assert "release quality docs contract full 258 passed" in row
    assert "targeted ruff passed" in row
    assert "`{\"detail\": \"Invalid or revoked API token\"}`" in row
    assert "token secret 不落库、last_used 更新、revoke 204 空 body" in row
    assert "只证明“撤销后不能访问”" in row

    for expected in [
        'assert rejected_resp.json() == {"detail": "Invalid or revoked API token"}',
        "assert record.secret_hash != secret",
        "assert TokenService.verify_token(secret, record.secret_hash)",
        "assert record.last_used_at is not None",
        "assert revoke_resp.content == b\"\"",
        "assert record.is_revoked is True",
        "assert create_audit.after_state == {\"name\": \"ci-smoke\", \"scopes\": [\"project.read\"]}",
        "assert revoke_audit.before_state == {\"name\": \"ci-smoke\"}",
        "assert full_api_token not in serialized_audit",
        "assert secret not in serialized_audit",
        "assert record.secret_hash not in serialized_audit",
    ]:
        assert expected in test_block
    assert (
        "assert rejected_resp.status_code == 401, rejected_resp.text\n\n"
        not in test_block
    )


def test_quality_ops_capture_real_auth_results_and_artifacts_exact_response_contract():
    row = _quality_ops_row_containing(
        "真实 run results/artifacts API 现在固定过滤结果完整 TestResultResponse"
    )
    real_auth_results_artifacts = _read(REAL_AUTH_RESULTS_ARTIFACTS)

    assert "真实 run results/artifacts API 现在固定过滤结果完整 TestResultResponse" in (
        row
    )
    assert "rollback 后完整可见结果集" in row
    assert "artifact soft-delete 后完整 ArtifactResponse" in row
    assert "删除完整 body 等值后的冗余字段集合守门" in row
    assert "避免 run results/artifacts 测试只证明“目标行大概出现”" in (
        row
    )
    assert "def _json_datetime(value: datetime) -> str:" in (
        real_auth_results_artifacts
    )
    assert "expected_results_by_name = {" in real_auth_results_artifacts
    assert '"data": [expected_results_by_name["test_payment_decline"]]' in (
        real_auth_results_artifacts
    )
    assert '"data": [' in real_auth_results_artifacts
    assert 'expected_results_by_name["test_payment_decline"]' in (
        real_auth_results_artifacts
    )
    assert 'expected_results_by_name["test_cart_total"]' in (
        real_auth_results_artifacts
    )
    assert '"metadata": {"node": "gw0"}' in real_auth_results_artifacts
    assert '"metadata": {"node": "gw1"}' in real_auth_results_artifacts
    assert '"storage_path": f"runs/{run_id}/summary.html"' in (
        real_auth_results_artifacts
    )
    assert '"mime_type": "text/html"' in real_auth_results_artifacts
    assert '"created_at": _json_datetime(visible.created_at)' in (
        real_auth_results_artifacts
    )
    assert 'assert set(body["data"][0]) == {' not in real_auth_results_artifacts
    assert "expected_result_fields = {" not in real_auth_results_artifacts
    assert (
        'assert [set(item) for item in after_rollback_body["data"]]'
        not in real_auth_results_artifacts
    )
    assert 'assert body["data"][0]["name"] == "test_payment_decline"' not in (
        real_auth_results_artifacts
    )
    assert 'assert body["data"][0]["status"] == "failed"' not in (
        real_auth_results_artifacts
    )
    assert (
        'assert {\n'
        '        item["name"] for item in after_rollback_body["data"]\n'
        '    } == {"test_cart_total", "test_payment_decline"}'
    ) not in real_auth_results_artifacts
    assert 'assert body["data"][0]["id"] == str(visible.id)' not in (
        real_auth_results_artifacts
    )
    assert 'assert body["data"][0]["name"] == "summary.html"' not in (
        real_auth_results_artifacts
    )
    assert "assert all(\n        set(item)\n        == {\n            \"id\",\n            \"run_id\",\n            \"suite\"," not in (
        real_auth_results_artifacts
    )


def test_quality_ops_capture_real_auth_field_set_direct_projection_contract():
    real_auth_results_artifacts = _read(REAL_AUTH_RESULTS_ARTIFACTS)
    row = _quality_ops_row("| 2026-05-31 | `RUN_INTEGRATION_TESTS=1 "
            "tests/integration/test_real_auth_results_artifacts.py --collect-only` "
            "30 tests collected")

    assert "targeted docs contract passed" in row
    assert "targeted ruff/py_compile passed" in row
    assert "不再藏在 `assert all(...)` generator" in row
    assert "archived logs 大分页投影为 100 个" in row
    assert "artifact page two 投影为两组完整 ArtifactResponse 字段" in row
    assert "rollback 后 results 投影为两组完整 TestResultResponse 字段" in row
    assert "real auth field-set direct projection 契约" in row
    assert "避免字段集合检查为了覆盖率而存在" in row

    for expected in [
        '"data": entries[1400:1500]',
        '"data": [',
        'expected_results_by_name["test_payment_decline"]',
        'expected_results_by_name["test_cart_total"]',
    ]:
        assert expected in real_auth_results_artifacts
    for removed in [
        'expected_log_fields = {"stream", "line"}',
        'assert [set(item) for item in body["data"]]',
        "expected_artifact_fields = {",
        'assert [set(item) for item in page_two["data"]]',
        "expected_result_fields = {",
        'assert [set(item) for item in after_rollback_body["data"]]',
        'assert all(set(item) == {"stream", "line"} for item in body["data"])',
        "assert all(\n        set(item)\n        == {\n            \"id\",\n            \"run_id\",\n            \"type\",",
        "assert all(\n        set(item)\n        == {\n            \"id\",\n            \"run_id\",\n            \"suite\",",
    ]:
        assert removed not in real_auth_results_artifacts


def test_quality_ops_capture_real_auth_artifact_list_pagination_exact_response_contract():
    row = _quality_ops_row_containing(
        "真实 run artifacts 分页 required integration 现在固定"
    )
    real_auth_results_artifacts = _read(REAL_AUTH_RESULTS_ARTIFACTS)
    test_block = _block_between(real_auth_results_artifacts, "async def test_run_artifacts_list_paginates_real_db_without_s3_side_effects", "async def test_artifact_download_api_token_requires_run_read_scope")

    assert "真实 run artifacts 分页 required integration 现在固定" in row
    assert "release quality docs contract full 248 passed" in row
    assert "避免 artifact list required integration 只证明“分页窗口几个字段看起来对”" in (
        row
    )
    assert "assert page_two == {" in test_block
    assert '"run_id": run_id' in test_block
    assert '"type": "report"' in test_block
    assert '"mime_type": "text/html"' in test_block
    assert '"expires_at": None' in test_block
    assert '"created_at": _json_datetime(artifact.created_at)' in test_block
    assert "expected_artifact_fields = {" not in test_block
    assert "assert [set(item) for item in page_two[\"data\"]]" not in test_block
    assert "assert all(" not in test_block
    assert "assert empty_page == {" in test_block
    assert '"data": []' in test_block
    assert "assert s3.presign_calls == []" in test_block
    assert "assert s3.get_calls == []" in test_block
    assert 'assert page_two["page"] == 2' not in test_block
    assert 'assert [item["id"] for item in page_two["data"]]' not in test_block
    assert 'assert [item["name"] for item in page_two["data"]]' not in test_block
    assert 'assert [item["storage_path"] for item in page_two["data"]]' not in (
        test_block
    )
    assert 'assert empty_page["data"] == []' not in test_block


def test_quality_ops_capture_real_auth_archived_log_large_page_exact_window_contract():
    row = _quality_ops_row_containing(
        "真实 archived logs API 大分页现在固定"
    )
    real_auth_results_artifacts = _read(REAL_AUTH_RESULTS_ARTIFACTS)

    assert "真实 archived logs API 大分页现在固定" in row
    assert "完整 100 条 data 必须精确等于归档 JSONL 源切片" in row
    assert "避免 archived logs 大分页测试只证明“首尾看起来对”" in (
        row
    )
    assert '"data": entries[1400:1500]' in real_auth_results_artifacts
    assert '"page": 15' in real_auth_results_artifacts
    assert '"per_page": 100' in real_auth_results_artifacts
    assert '"total": 1500' in real_auth_results_artifacts
    assert 'expected_log_fields = {"stream", "line"}' not in (
        real_auth_results_artifacts
    )
    assert 'assert [set(item) for item in body["data"]]' not in (
        real_auth_results_artifacts
    )
    assert 'assert all(set(item) == {"stream", "line"} for item in body["data"])' not in (
        real_auth_results_artifacts
    )
    assert 'assert len(body["data"]) == 100' not in (
        real_auth_results_artifacts
    )
    assert 'assert body["data"][0] == {\n        "stream": "stdout",' not in (
        real_auth_results_artifacts
    )
    assert 'assert body["data"][-1] == {\n        "stream": "stdout",' not in (
        real_auth_results_artifacts
    )


def test_quality_ops_capture_refresh_token_revoke_outage_exact_warning_contract():
    real_auth_results_artifacts = _read(REAL_AUTH_RESULTS_ARTIFACTS)

    row = _quality_ops_row("| 2026-05-31 | `RUN_INTEGRATION_TESTS=1 "
            "tests/integration/test_real_auth_results_artifacts.py::"
            "test_refresh_survives_refresh_token_revoke_outage")

    assert "` 1 passed" in row
    assert "release quality docs contract full 335 passed" in row
    assert "targeted ruff/py_compile passed" in row
    assert "`redis.set` 只按旧 refresh token jti 写 `jwt:revoked:{jti}`" in row
    assert "TTL `ex` 落在有效范围内" in row
    assert "WARNING 投影为唯一 `{message,jti,exc_type,exc_message}`" in row
    assert "message 为 `token_revoke_failed`" in row
    assert "`record.jti` 等于旧 refresh token jti" in row
    assert "exc_info 保留原始 `RuntimeError(\"redis revoke unavailable\")`" in row
    assert "此前只用 `caplog.text` 包含式断言" in row
    assert "后来仍靠 `len(records) == 1` 和 `records[0]`" in row
    assert "Redis 写入参数漂移" in row
    assert "日志里出现过 token_revoke_failed" in row
    assert "direct projection 契约" in row

    helper_block = _marked_block(
        real_auth_results_artifacts,
        "def _assert_token_revoke_warning",
        "@pytest_asyncio.fixture",
    )

    assert 'record.name == "qaplatform.api.v1.auth"' in helper_block
    assert "record.levelno == logging.WARNING" in helper_block
    assert 'getattr(record, "jti", None) == jti' in helper_block
    assert '"message": record.getMessage()' in helper_block
    assert '"jti": getattr(record, "jti", None)' in helper_block
    assert '"exc_type": type(record.exc_info[1]) if record.exc_info else None' in (
        helper_block
    )
    assert '"exc_message": str(record.exc_info[1]) if record.exc_info else None' in (
        helper_block
    )
    assert '"message": "token_revoke_failed"' in helper_block
    assert '"jti": jti' in helper_block
    assert '"exc_type": RuntimeError' in helper_block
    assert '"exc_message": "redis revoke unavailable"' in helper_block
    assert "assert len(records) == 1" not in helper_block
    assert "assert records[0]" not in helper_block

    block = _marked_block(
        real_auth_results_artifacts,
        "async def test_refresh_survives_refresh_token_revoke_outage",
        "async def test_real_sse_logs_resume_after_last_event_id",
    )

    assert "old_jti = old_refresh_payload[\"jti\"]" in block
    assert "revoke_spy = AsyncMock(side_effect=RuntimeError" in block
    assert "revoke_spy.assert_awaited_once()" in block
    assert (
        'assert revoke_spy.await_args.args == (f"jwt:revoked:{old_jti}", "1")'
        in block
    )
    assert "(revoke_expires_in,) = revoke_spy.await_args.kwargs.values()" in block
    assert (
        'assert revoke_spy.await_args.kwargs == {"ex": revoke_expires_in}'
        in block
    )
    assert 'assert set(revoke_spy.await_args.kwargs) == {"ex"}' not in block
    assert "_assert_token_revoke_warning(caplog, old_jti)" in block
    assert 'assert "token_revoke_failed" in caplog.text' not in block


def test_quality_ops_capture_auth_refresh_audit_new_jti_trace_contract():
    row = _quality_ops_row_containing("Auth refresh audit new_jti 真实追踪契约")
    auth_command_source = _read(AUTH_COMMAND_SOURCE)
    auth_routes_test = _read(AUTH_ROUTES_TEST)
    real_auth_results_artifacts = _read(REAL_AUTH_RESULTS_ARTIFACTS)

    assert "Auth refresh audit new_jti 真实追踪契约" in row
    assert (
        "`tests/unit/test_auth/test_auth_routes.py::TestRefreshRevokesOldToken::test_refresh_revokes_old_refresh_token tests/unit/test_auth/test_auth_routes.py::TestAuditRefresh::test_refresh_success_emits_audit_with_jti` 2 passed"
        in row
    )
    assert "auth routes full 57 passed" in row
    assert "真实非空 `new_jti`" in row
    assert "真实新 refresh cookie 的 jti" in row
    assert "把 `new_jti` 固定写成 `None`" in row
    assert "只能证明字段名存在" in row

    refresh_source_block = _marked_block(
        auth_command_source,
        "async def refresh_tokens_command(",
        "async def _revoke_payload_token",
    )

    assert "access_token = jwt_svc.create_access_token(" in refresh_source_block
    assert (
        "new_refresh_token = jwt_svc.create_refresh_token(user_id=str(user.id))"
        in refresh_source_block
    )
    assert (
        'new_jti = jwt_svc.decode_token(new_refresh_token).get("jti")'
        in refresh_source_block
    )
    assert 'after_state={"new_jti": new_jti}' in refresh_source_block
    assert "new_jti_placeholder" not in refresh_source_block

    rotation_block = _marked_block(
        auth_routes_test,
        "async def test_refresh_revokes_old_refresh_token",
        "async def test_refresh_with_revoked_token_returns_401",
    )
    audit_block = _marked_block(
        auth_routes_test,
        "async def test_refresh_success_emits_audit_with_jti",
        "async def test_refresh_failed_emits_audit",
    )

    for block in [rotation_block, audit_block]:
        assert (
            'new_refresh_payload = jwt_svc.decode_token(resp.cookies["refresh_token"])'
            in block
        )
        assert 'new_jti = new_refresh_payload["jti"]' in block
        assert "assert new_jti != old_jti" in block
        assert '{"new_jti": None}' not in block

    assert 'audit_kwargs["after_state"] == {"new_jti": new_jti}' in rotation_block
    assert '"after_state": {"new_jti": new_jti}' in audit_block

    integration_block = _block_between(real_auth_results_artifacts, "async def test_auth_refresh_logout_audits_do_not_store_tokens_or_passwords", "async def test_real_sse_ticket_writes_audit_without_storing_ticket")
    assert 'old_refresh_jti = refresh_audit.before_state.get("old_jti")' in (
        integration_block
    )
    assert (
        'assert refresh_audit.before_state == {"old_jti": old_refresh_jti}'
        in integration_block
    )
    assert 'new_refresh_jti = refresh_audit.after_state.get("new_jti")' in (
        integration_block
    )
    assert (
        'assert refresh_audit.after_state == {"new_jti": new_refresh_jti}'
        in integration_block
    )
    assert "assert new_refresh_jti != old_refresh_jti" in integration_block
    assert "Counter(audit.action for audit in audits)" in integration_block
    assert "assert set(refresh_audit.before_state)" not in integration_block
    assert "assert set(refresh_audit.after_state)" not in integration_block


def test_quality_ops_capture_auth_token_missing_authorization_integration_exact_response_contract():
    row = _quality_ops_row_containing(
        "Auth token missing Authorization integration exact response 契约"
    )
    real_auth_results_artifacts = _read(REAL_AUTH_RESULTS_ARTIFACTS)

    assert "Auth token missing Authorization integration exact response 契约" in (
        row
    )
    assert (
        "`RUN_INTEGRATION_TESTS=1 tests/integration/test_real_auth_results_artifacts.py::test_auth_token_routes_require_authorization_without_side_effects` 1 passed"
        in row
    )
    assert "三条完整响应投影 `[{status_code, body}]`" in row
    assert '{"detail": "Missing Authorization header"}' in row
    assert "ApiToken 数量和 create/revoke audit 数量不变" in row
    assert 'all("Missing Authorization header" in response.text ...)' in row
    assert "三个响应文本里都有某句话" in row

    test_block = _marked_block(
        real_auth_results_artifacts,
        "async def test_auth_token_routes_require_authorization_without_side_effects",
        "async def test_auth_tokens_list_is_paginated",
    )

    assert (
        'assert [\n        {"status_code": response.status_code, "body": response.json()}'
        in test_block
    )
    assert test_block.count('"status_code": 401') == 3
    assert test_block.count('"body": {"detail": "Missing Authorization header"}') == 3
    assert "token_count_after == token_count_before" in test_block
    assert "audit_count_after == audit_count_before" in test_block
    assert '"Missing Authorization header" in response.text' not in test_block


def test_quality_ops_capture_sse_events_real_resume_exact_frame_contract():
    row = _quality_ops_row_containing("SSE events real resume exact frame 契约")
    projection_row = _quality_ops_row_containing("SSE resume projection exact 契约")
    real_auth_results_artifacts = _read(REAL_AUTH_RESULTS_ARTIFACTS)

    assert "SSE events real resume exact frame 契约" in row
    assert (
        "`RUN_INTEGRATION_TESTS=1 tests/integration/test_real_auth_results_artifacts.py::test_real_sse_events_resume_after_last_event_id_uses_ticket_rbac_and_redis` 1 passed"
        in row
    )
    assert "targeted SSE unit passed" in row
    assert "真实 `/runs/{id}/events` SSE Last-Event-ID 集成用例" in row
    assert "只回放第二条 `status_change`" in row
    assert "随后 `done` sentinel" in row
    assert "ticket 复用固定 401 `Invalid or expired SSE ticket`" in row
    assert "`expected_log_frames` / `expected_sse_frames` 完整 frame projection" in (
        projection_row
    )
    assert "done sentinel、id、data、status/previous/timestamp 都按列表等值" in (
        projection_row
    )
    assert "集合负断言证明首个事件未回放" in projection_row

    assert "def _parse_sse_events(text: str) -> list[dict[str, str]]:" in (
        real_auth_results_artifacts
    )
    assert "def _decode_redis_entry(data: dict) -> dict:" in (
        real_auth_results_artifacts
    )

    test_block = _marked_block(
        real_auth_results_artifacts,
        "async def test_real_sse_events_resume_after_last_event_id_uses_ticket_rbac_and_redis",
        "async def test_archived_logs_api_replays_s3_jsonl_after_real_rbac",
    )

    assert "event_payloads = [_decode_redis_entry(data) for _event_id, data in events]" in (
        test_block
    )
    assert '"status": "running"' in test_block
    assert '"previous": "preparing"' in test_block
    assert '"status": "done"' in test_block
    assert '"previous": "running"' in test_block
    assert "sse_events = _parse_sse_events(resume_resp.text)" in test_block
    assert "expected_sse_frames = [" in test_block
    assert '"event": "status_change"' in test_block
    assert '"id": second_event_id' in test_block
    assert '"timestamp": event_payloads[1]["timestamp"]' in test_block
    assert '{"event": "done", "id": None, "data": {"status": "done"}}' in test_block
    assert "for event in sse_events" in test_block
    assert "] == expected_sse_frames" in test_block
    assert 'assert reuse_resp.json() == {"detail": "Invalid or expired SSE ticket"}' in (
        test_block
    )
    assert "assert len(events) == 2" not in test_block
    assert 'assert [event["event"] for event in sse_events] == ["status_change", "done"]' not in (
        test_block
    )
    assert '"timestamp_present": bool(status_data["timestamp"])' not in test_block
    assert 'assert json.loads(sse_events[1]["data"]) == {"status": "done"}' not in (
        test_block
    )
    assert 'assert first_event_id not in {event.get("id") for event in sse_events}' not in (
        test_block
    )
    assert '"event: status_change" in resume_resp.text' not in test_block
    assert '"event: done" in resume_resp.text' not in test_block


def test_quality_ops_capture_sse_logs_real_resume_exact_frame_contract():
    row = _quality_ops_row_containing("SSE logs real resume exact frame 契约")
    projection_row = _quality_ops_row_containing("SSE resume projection exact 契约")
    real_auth_results_artifacts = _read(REAL_AUTH_RESULTS_ARTIFACTS)

    assert "SSE logs real resume exact frame 契约" in row
    assert (
        "`RUN_INTEGRATION_TESTS=1 tests/integration/test_real_auth_results_artifacts.py::test_real_sse_logs_resume_after_last_event_id_uses_ticket_rbac_and_redis` 1 passed"
        in row
    )
    assert "targeted SSE unit passed" in row
    assert "真实 `/runs/{id}/logs` SSE Last-Event-ID 集成用例" in row
    assert "只回放第二条 stderr log" in row
    assert "owner ticket 复用 401 `Invalid or expired SSE ticket`" in row
    assert "`run.read` API token 可续读同一帧" in row
    assert "空 scope ticket 返回 403 `Insufficient permissions`" in row
    assert "`expected_log_frames` / `expected_sse_frames` 完整 frame projection" in (
        projection_row
    )
    assert "owner/run.read/status-stream 回放" in projection_row
    assert "集合负断言证明首个事件未回放" in projection_row

    test_block = _marked_block(
        real_auth_results_artifacts,
        "async def test_real_sse_logs_resume_after_last_event_id_uses_ticket_rbac_and_redis",
        "async def test_real_sse_events_resume_after_last_event_id_uses_ticket_rbac_and_redis",
    )

    assert "log_events = _parse_sse_events(resume_resp.text)" in test_block
    assert "expected_log_frames = [" in test_block
    assert '"event": "log"' in test_block
    assert '"id": entries[1]["id"]' in test_block
    assert '"stream": "stderr"' in test_block
    assert '"line": second_line' in test_block
    assert '{"event": "done", "id": None, "data": {"status": "done"}}' in test_block
    assert "for event in log_events" in test_block
    assert test_block.count("] == expected_log_frames") == 2
    assert 'assert reuse_resp.json() == {"detail": "Invalid or expired SSE ticket"}' in (
        test_block
    )
    assert "run_read_events = _parse_sse_events(run_read_resp.text)" in test_block
    assert "for event in run_read_events" in test_block
    assert (
        'assert empty_resp.json() == {"detail": "Insufficient permissions"}'
        in test_block
    )
    assert 'assert [event["event"] for event in log_events] == ["log", "done"]' not in (
        test_block
    )
    assert 'assert json.loads(log_events[1]["data"]) == {"status": "done"}' not in (
        test_block
    )
    assert 'assert entries[0]["id"] not in {event.get("id") for event in log_events}' not in (
        test_block
    )
    assert 'assert first_line not in {log_data["line"]}' not in test_block
    assert 'assert [event["event"] for event in run_read_events] == ["log", "done"]' not in (
        test_block
    )
    assert "second_line in resume_resp.text" not in test_block
    assert '"event: done" in resume_resp.text' not in test_block
    assert "second_line in run_read_resp.text" not in test_block
    assert "second_line not in empty_resp.text" not in test_block


def test_quality_ops_capture_real_auth_sse_resume_projection_followup_contract():
    real_auth_results_artifacts = _read(REAL_AUTH_RESULTS_ARTIFACTS)

    row = _quality_ops_row(
        "| 2026-06-01 | `RUN_INTEGRATION_TESTS=1 tests/integration/test_real_auth_results_artifacts.py::test_real_sse_logs_resume_after_last_event_id_uses_ticket_rbac_and_redis tests/integration/test_real_auth_results_artifacts.py::test_real_sse_events_resume_after_last_event_id_uses_ticket_rbac_and_redis -q` 2 passed；real_auth full 30 passed"
    )

    assert "release quality docs contract targeted 3 passed" in row
    assert "release quality docs contract full 358 passed" in row
    assert "targeted ruff/py_compile passed" in row
    assert "git diff --check passed" in row
    assert "owner/run.read/status-stream 回放" in row
    assert "`expected_log_frames` / `expected_sse_frames` 完整 frame projection" in row
    assert "done sentinel、id、data、status/previous/timestamp 都按列表等值" in row
    assert "集合负断言证明首个事件未回放" in row
    assert "外部 token reuse/empty-scope exact body 保留" in row
    assert "SSE resume projection exact 契约" in row

    assert "expected_log_frames = [" in real_auth_results_artifacts
    assert "expected_sse_frames = [" in real_auth_results_artifacts
    assert 'assert entries[0]["id"] not in {event.get("id") for event in log_events}' not in (
        real_auth_results_artifacts
    )
    assert 'assert first_event_id not in {event.get("id") for event in sse_events}' not in (
        real_auth_results_artifacts
    )
    assert '"timestamp_present": bool(status_data["timestamp"])' not in (
        real_auth_results_artifacts
    )


def test_quality_ops_capture_real_sse_logs_missing_ticket_exact_body_contract():
    real_auth_results_artifacts = _read(REAL_AUTH_RESULTS_ARTIFACTS)

    row = _quality_ops_row(
        "| 2026-05-31 | `RUN_INTEGRATION_TESTS=1 tests/integration/test_real_auth_results_artifacts.py::test_real_sse_logs_resume_after_last_event_id_uses_ticket_rbac_and_redis` 1 passed | release quality docs contract full 262 passed"
    )

    assert "真实 logs SSE 缺 ticket 401" in row
    assert "`{\"detail\": \"Invalid or expired SSE ticket\"}`" in row
    assert "Last-Event-ID 只回放第二条 stderr frame" in row
    assert "owner ticket 复用 401" in row
    assert "`run.read` API token 续读" in row
    assert "empty-scope 403" in row
    assert '只断言 `json()["detail"]`' in row
    assert "错误体夹带 ticket、run_id、内部 reason" in row
    assert "真实 logs SSE missing ticket exact body 契约" in row
    assert "只证明“缺票会 401 且 detail 文案对”" in row

    test_block = _marked_block(
        real_auth_results_artifacts,
        "async def test_real_sse_logs_resume_after_last_event_id_uses_ticket_rbac_and_redis",
        "async def test_real_sse_events_resume_after_last_event_id_uses_ticket_rbac_and_redis",
    )

    assert (
        'assert missing_ticket_resp.json() == {"detail": "Invalid or expired SSE ticket"}'
        in test_block
    )
    assert 'assert missing_ticket_resp.json()["detail"]' not in test_block
    assert 'assert reuse_resp.json() == {"detail": "Invalid or expired SSE ticket"}' in (
        test_block
    )
    assert (
        'assert empty_resp.json() == {"detail": "Insufficient permissions"}'
        in test_block
    )


def test_quality_ops_capture_archived_logs_missing_object_exact_envelope_alias_gate():
    real_auth = _read(REAL_AUTH_RESULTS_ARTIFACTS)
    performance = _read(PERFORMANCE_SMOKE)
    quality_gate = _read(ROOT / "tests" / "unit" / "test_test_quality_contracts.py")

    row = _quality_ops_row("| 2026-05-31 | `RUN_INTEGRATION_TESTS=1 .venv/bin/python -m pytest tests/integration/test_real_auth_results_artifacts.py::test_archived_logs_api_returns_404_when_s3_object_missing -q` 1 passed")
    assert (
        "`RUN_INTEGRATION_TESTS=1 RUN_PERFORMANCE_TESTS=1 .venv/bin/python -m pytest "
        "tests/integration/test_performance_smoke.py::test_archived_log_missing_object_p99_smoke -q` 1 passed"
    ) in row
    assert "test quality contracts 5 passed" in row
    assert "release quality docs contract full 276 passed" in row
    assert "targeted ruff passed" in row
    assert "Archived logs missing object exact envelope/alias gate 契约" in row
    assert '`error = response.json()["error"]`' in row

    real_block = _block_between(real_auth, "async def test_archived_logs_api_returns_404_when_s3_object_missing", "\n\n@pytest.mark.asyncio")
    performance_block = _block_between(performance, "async def test_archived_log_missing_object_p99_smoke", "\n\n@pytest.mark.asyncio")

    for source in [real_block, performance_block]:
        assert '"code": "NOT_FOUND"' in source
        assert '"message": "Archived logs not found"' in source
        assert '"details": []' in source
        assert "assert str(run_id) not in" in source
        assert 'json()["error"]' not in source
        assert 'error["code"]' not in source
        assert 'error["message"]' not in source

    for expected in [
        "def _json_alias_target",
        "def _json_alias_subfield",
        "def _json_nested_subfield",
        "json_alias_subfield",
        "aliases[alias[0]] = alias[1]",
    ]:
        assert expected in quality_gate


def test_quality_ops_capture_integration_field_set_residual_cleanup_contract():
    performance_smoke = _read(PERFORMANCE_SMOKE)
    real_auth_results_artifacts = _read(REAL_AUTH_RESULTS_ARTIFACTS)
    worker_execute = _read(WORKER_EXECUTE)
    row = _quality_ops_row(
        "| 2026-06-01 | `RUN_INTEGRATION_TESTS=1 RUN_PERFORMANCE_TESTS=1 "
        "tests/integration/test_performance_smoke.py::"
        "test_archived_log_replay_large_page_p99_smoke"
    )

    assert "integration field-set residual cleanup" not in row
    assert "performance 31、real_auth 30、worker_execute 8" in row
    assert "performance 31 passed" in row
    assert "real_auth 30 passed" in row
    assert "worker_execute 8 skipped" in row
    assert "release quality docs contract full 352 passed" in row
    assert "targeted ruff/py_compile" in row
    assert "git diff --check" in row
    assert "pending" not in row
    assert "`expected_*_fields` 与 `[set(item) ...]` 冗余守门" in row
    assert "`_audit_event_response` 完整 DTO 分页 body 等值" in row
    assert "log stream roundtrip 固定完整 `{id,stream,line}` entry" in row
    assert "execution summary 纳入 `failed_tests/failed_tests_omitted`" in row
    assert "live SSE client 固定 `trust_env=False`" in row
    assert "rollback results 通过显式 `created_at` 固定结果顺序" in row
    assert "唯一 attempt=2" in row
    assert "`_has_exact_artifact_names`、`_archive_contains_all` 等保留为异步轮询 readiness" in row
    assert "direct response/projection/exact-once retry 契约" in row
    assert "performance full 31 passed" in row

    for removed in [
        "expected_log_fields",
        "expected_artifact_fields",
        "expected_audit_fields",
        'assert [set(item) for item in body["data"]]',
    ]:
        assert removed not in performance_smoke
    for expected in [
        "def _audit_event_response(event) -> dict:",
        '"data": [_audit_event_response(event) for event in target_events[:50]]',
        "for index in range(199, 99, -1)",
        "expected_audit_body = {",
        "assert response.json() == expected_audit_body",
        'entry_ids = [entry["id"] for entry in entries]',
        '"failed_tests_omitted": counts["failed"] + counts["error"] - 20',
    ]:
        assert expected in performance_smoke
    sse_client_lines = [
        line.strip()
        for line in performance_smoke.splitlines()
        if "trust_env=False" in line
    ]
    assert sse_client_lines == [
        "async with httpx.AsyncClient(timeout=timeout, trust_env=False) as client:",
        "async with httpx.AsyncClient(timeout=timeout, trust_env=False) as client:",
    ]

    for removed in [
        "expected_log_fields",
        "expected_artifact_fields",
        "expected_result_fields",
        'assert [set(item) for item in body["data"]]',
        'assert [set(item) for item in page_two["data"]]',
        'assert [set(item) for item in after_rollback_body["data"]]',
    ]:
        assert removed not in real_auth_results_artifacts
    for expected in [
        "result_created_at = datetime(2026, 1, 1, tzinfo=timezone.utc)",
        'assert after_rollback_body == {',
        'expected_results_by_name["test_payment_decline"]',
        'expected_results_by_name["test_cart_total"]',
    ]:
        assert expected in real_auth_results_artifacts

    worker_lost_block = _test_block(
        worker_execute,
        "test_worker_lost_retry_completes_with_artifacts_and_archived_logs",
    )
    for expected in [
        'run["attempt"] for run in body["data"] if run["attempt"] == 2',
        "== [2]",
        "(retry_run,) = [",
        '"project_id": retry_run["project_id"]',
        '"summary": retry_run["summary"]',
        '"error_message": retry_run["error_message"]',
        '"attempt": 2',
    ]:
        assert expected in worker_lost_block
    assert 'any(run["attempt"] == 2 for run in body["data"])' not in (
        worker_lost_block
    )
    assert "next(\n            run for run in retry_runs_body" not in worker_lost_block


def test_quality_ops_capture_artifact_response_body_followup_contract():
    performance_smoke = _read(PERFORMANCE_SMOKE)
    real_auth_results_artifacts = _read(REAL_AUTH_RESULTS_ARTIFACTS)
    worker_execute = _read(WORKER_EXECUTE)
    row = _quality_ops_row(
        "| 2026-06-01 | `RUN_INTEGRATION_TESTS=1 RUN_PERFORMANCE_TESTS=1 "
        "tests/integration/test_performance_smoke.py::test_artifact_list_api_p99_smoke"
    )

    assert "performance full 31 passed" in row
    assert "real_auth full 30 passed" in row
    assert "release quality docs contract full 353 passed" in row
    assert "targeted ruff/py_compile passed" in row
    assert "git diff --check passed" in row
    assert "pending" not in row
    assert "`expected_body` 完整等值" in row
    assert "`expected_artifact_body` 完整分页体" in row
    assert "`total == 2` + `{row.name}` 升级为 `{total, rows}` 投影等值" in (
        row
    )
    assert "`_has_exact_artifact_names` 与 `_archive_contains_all` 本批判定为合理保留的异步 readiness" in (
        row
    )
    assert "exact response/projection 契约" in row

    artifact_list_block = _test_block(
        performance_smoke,
        "test_artifact_list_api_p99_smoke",
    )
    concurrent_block = _test_block(
        performance_smoke,
        "test_real_api_token_concurrent_read_paths_p99_smoke",
    )
    real_auth_archive_block = _test_block(
        real_auth_results_artifacts,
        "test_archived_logs_api_replays_s3_jsonl_after_real_rbac",
    )
    real_auth_upload_block = _test_block(
        real_auth_results_artifacts,
        "test_artifact_upload_enforces_limits_before_real_db_rows",
    )

    for expected in [
        "artifact_created_at = datetime(2026, 1, 1, tzinfo=timezone.utc)",
        "expected_body = {",
        "assert body == expected_body",
        "key=lambda item: item.created_at",
        '"total": 80',
    ]:
        assert expected in artifact_list_block
    for rejected in [
        "expected_artifacts_by_name = {",
        'item["name"]: item for item in body["data"]',
        'assert body["total"] == len(expected_artifacts_by_name)',
    ]:
        assert rejected not in artifact_list_block

    for expected in [
        "expected_artifact_body = {",
        "assert body == expected_artifact_body",
        "key=lambda artifact_item: artifact_item.created_at",
        '"total": 3',
    ]:
        assert expected in concurrent_block
    for rejected in [
        '"data": body["data"]',
        '"total": len(artifacts)',
        'artifact_items = sorted(body["data"], key=lambda item: item["id"])',
        "expected_artifact_items = sorted(",
        "assert artifact_items == expected_artifact_items",
    ]:
        assert rejected not in concurrent_block

    for expected in [
        "assert body == {",
        '"per_page": 100',
        "assert page_body == {",
        '"per_page": 2',
    ]:
        assert expected in real_auth_archive_block
    for rejected in [
        'assert body["total"] == 5',
        'assert body["data"][:2]',
        'assert page_body["total"] == 5',
        'assert page_body["page"] == 2',
    ]:
        assert rejected not in real_auth_archive_block

    for expected in [
        "artifact_rows = sorted(",
        'assert {"total": total, "rows": artifact_rows} == {',
        '"type": "log"',
        '"mime_type": "text/plain"',
    ]:
        assert expected in real_auth_upload_block
    for rejected in [
        "assert total == 2",
        "assert {row.name for row in rows}",
    ]:
        assert rejected not in real_auth_upload_block

    assert "def _has_exact_artifact_names(*expected_names: str):" in worker_execute
    assert "def _archive_contains_all(*fragments: str):" in worker_execute
    assert "def _artifact_page_projection(body: dict) -> dict:" in worker_execute
    assert "assert _artifact_page_projection(artifacts_body) == expected_artifact_page" in (
        worker_execute
    )


def test_quality_ops_capture_real_auth_artifact_list_body_order_followup_contract():
    real_auth_results_artifacts = _read(REAL_AUTH_RESULTS_ARTIFACTS)
    worker_execute = _read(WORKER_EXECUTE)
    row = _quality_ops_row(
        "| 2026-06-01 | `RUN_INTEGRATION_TESTS=1 "
        "tests/integration/test_real_auth_results_artifacts.py::"
        "test_artifact_list_api_token_requires_run_read_scope -q` 1 passed"
    )

    assert "real_auth full 30 passed" in row
    assert "worker_execute full 8 skipped" in row
    assert "release quality docs contract targeted 2 passed" in row
    assert "release quality docs contract full 354 passed" in row
    assert "targeted ruff/py_compile passed" in row
    assert "git diff --check passed" in row
    assert "pending" not in row
    assert "`expected_body` 完整等值" in row
    assert '`data: body["data"]` 响应壳自填充' in row
    assert "exact body/order 契约" in row
    assert "外部栈异步 readiness" in row

    artifact_list_block = _block_between(
        real_auth_results_artifacts,
        "async def test_artifact_list_api_token_requires_run_read_scope",
        "async def test_run_artifacts_list_paginates_real_db_without_s3_side_effects",
    )
    for expected in [
        "artifact_created_at = datetime(2026, 1, 1, tzinfo=timezone.utc)",
        "created_at=artifact_created_at,",
        "created_at=artifact_created_at + timedelta(seconds=1),",
        "expected_body = {",
        "for artifact in (second, first)",
        '"id": str(artifact.id)',
        '"run_id": run_id',
        '"type": artifact.type',
        '"name": artifact.name',
        '"storage_path": artifact.storage_path',
        '"size_bytes": artifact.size_bytes',
        '"mime_type": artifact.mime_type',
        '"expires_at": None',
        '"created_at": _json_datetime(artifact.created_at)',
        '"page": 1',
        '"per_page": 10',
        '"total": 2',
        "assert body == expected_body",
    ]:
        assert expected in artifact_list_block
    for rejected in [
        '"data": body["data"]',
        'artifact_items = sorted(body["data"], key=lambda item: item["id"])',
        "expected_artifact_items = sorted(",
        "assert artifact_items == expected_artifact_items",
        'assert body["total"] == 2',
    ]:
        assert rejected not in artifact_list_block

    assert "def _has_exact_artifact_names(*expected_names: str):" in worker_execute
    assert "def _archive_contains_all(*fragments: str):" in worker_execute
    assert "collect_bulk_indexes(lines) == list(range(bulk_log_count))" in (
        worker_execute
    )
