from __future__ import annotations

from tests.unit.release_quality_contract_helpers import _quality_ops_row


def test_quality_ops_records_current_gate_source_evidence():
    git_source_url_scheme_row = _quality_ops_row(
        "| 2026-05-30 | N/A（GitSource URL scheme/SSH 判定顺序契约）"
    )
    git_source_rev_parse_row = _quality_ops_row(
        "| 2026-05-30 | N/A（GitSource rev-parse HEAD 解析契约）"
    )
    git_source_non_public_dns_row = _quality_ops_row(
        "| 2026-05-30 | N/A（GitSource non-public DNS 防 SSRF 契约）"
    )
    worker_git_credential_type_row = _quality_ops_row(
        "| 2026-05-30 | N/A（Worker Git credential type mismatch 解密短路）"
    )
    builtin_runner_path_error_row = _quality_ops_row(
        "| 2026-05-30 | N/A（内置 runner 越界路径错误契约）"
    )
    git_source_clone_private_ip_row = _quality_ops_row(
        "| 2026-05-30 | N/A（GitSource clone/private-IP 弱断言契约）"
    )
    plugin_registry_missing_row = _quality_ops_row(
        "| 2026-05-30 | N/A（PluginRegistry missing plugin 错误契约）"
    )
    assert "`tests/unit/test_plugins/test_git_source.py` 28 passed" in (
        git_source_url_scheme_row
    )
    assert "coverage unit 1297 passed" in git_source_url_scheme_row
    assert "先处理显式 URL scheme" in git_source_url_scheme_row
    assert "只有无 scheme 时才按 scp-like SSH 解析" in git_source_url_scheme_row
    assert "`http://git@host:80/...` 与 `ftp://git@host:21/...`" in (
        git_source_url_scheme_row
    )
    assert "SSH 正则跑在 `urlparse` 前" in git_source_url_scheme_row
    assert "不再被 SSH 正则绕过" in git_source_url_scheme_row
    assert "避免 Git URL scheme 测试只覆盖朴素非法 URL" in (git_source_url_scheme_row)
    assert "`tests/unit/test_plugins/test_git_source.py` 26 passed" in (
        git_source_rev_parse_row
    )
    assert "coverage unit 1295 passed" in git_source_rev_parse_row
    assert "`git rev-parse HEAD` 非零退出或返回空 SHA" in (git_source_rev_parse_row)
    assert "不再把空 revision 写进 SourceRevision" in git_source_rev_parse_row
    assert "既有 clone happy path 大多 mock `_resolve_sha()`" in (
        git_source_rev_parse_row
    )
    assert "clone 成功后 rev-parse 失败/空输出两条红灯" in (git_source_rev_parse_row)
    assert "避免 GitSource 测试只证明 clone 命令 happy path" in (
        git_source_rev_parse_row
    )
    assert "`tests/unit/test_plugins/test_git_source.py` 24 passed" in (
        git_source_non_public_dns_row
    )
    assert "coverage unit 1293 passed" in git_source_non_public_dns_row
    assert "loopback/link-local/unspecified/multicast/reserved" in (
        git_source_non_public_dns_row
    )
    assert "`non-public IP`" in git_source_non_public_dns_row
    assert "`0.0.0.0`、`224.0.0.1`、`2001:db8::1` 被放行" in (
        git_source_non_public_dns_row
    )
    assert "不完整 CIDR 清单不再形成假绿" in git_source_non_public_dns_row
    assert "避免 Git URL SSRF 测试只证明一类私网地址" in (git_source_non_public_dns_row)
    assert (
        "`tests/unit/test_worker/test_tasks.py::test_build_source_auth_rejects_type_mismatch` 1 passed"
        in (worker_git_credential_type_row)
    )
    assert "Git 凭据类型不匹配用例从 raises-only 补成 no-decrypt 契约" in (
        worker_git_credential_type_row
    )
    assert "只证明会抛 `RuntimeError`" in worker_git_credential_type_row
    assert "先解密 `credential.encrypted_value` 再发现类型不匹配" in (
        worker_git_credential_type_row
    )
    assert "credential lookup 发生一次" in worker_git_credential_type_row
    assert "`crypto.decrypt` 不被调用" in worker_git_credential_type_row
    assert "worker source auth 测试只为异常覆盖率服务" in (
        worker_git_credential_type_row
    )
    assert (
        "`tests/unit/test_plugins/test_pytest_runner.py::TestPytestBuildCommandInternal::test_rejects_junit_xml_outside_workspace tests/unit/test_plugins/test_jest_runner.py::TestJestBuildCommand::test_rejects_junit_xml_outside_workspace tests/unit/test_plugins/test_playwright_runner.py::TestPlaywrightBuildCommand::test_rejects_junit_xml_outside_workspace tests/unit/test_plugins/test_go_test_runner.py::TestGoTestBuildCommand::test_rejects_output_paths_outside_workspace` 16 passed"
        in (builtin_runner_path_error_row)
    )
    assert "四个 runner 越界报告路径用例从 raises-only 补成精确错误契约" in (
        builtin_runner_path_error_row
    )
    assert "只匹配 `must be a relative path` 片段" in (builtin_runner_path_error_row)
    assert "Jest/Playwright 漏掉 `reports/../report.xml` 与 Windows 绝对路径" in (
        builtin_runner_path_error_row
    )
    assert "`must be a relative path inside the workspace`" in (
        builtin_runner_path_error_row
    )
    assert "错误不回显原始越界路径" in builtin_runner_path_error_row
    assert "runner 工作区边界测试只为异常覆盖率服务" in (builtin_runner_path_error_row)
    assert (
        "`tests/unit/test_plugins/test_git_source.py::TestGitSourceClone::test_clone_failure_raises_runtime_error tests/unit/test_plugins/test_git_source.py::TestGitSourceClone::test_clone_auth_failure_raises_runtime_error tests/unit/test_plugins/test_git_source.py::TestGitUrlValidation::test_rejects_https_hostname_that_resolves_to_private_ip` 3 passed"
        in (git_source_clone_private_ip_row)
    )
    assert (
        "GitSource clone/private-IP 用例从 raises-only 补成命令参数与拒绝来源契约"
        in (git_source_clone_private_ip_row)
    )
    assert "只匹配 `git clone failed`" in git_source_clone_private_ip_row
    assert "clone 命令少了 `--depth 1 --branch main`" in (
        git_source_clone_private_ip_row
    )
    assert "无 auth 场景误带环境变量" in git_source_clone_private_ip_row
    assert "只匹配 `private IP`" in git_source_clone_private_ip_row
    assert '`getaddrinfo("github.example", None)`' in git_source_clone_private_ip_row
    assert "GitSource 失败路径测试只为异常覆盖率服务" in (
        git_source_clone_private_ip_row
    )
    assert (
        "`tests/unit/test_plugins/test_registry.py::test_missing_plugins_raise_actionable_key_errors` 3 passed"
        in (plugin_registry_missing_row)
    )
    assert "missing plugin 用例从 raises-only 补成错误参数与 registry 状态不变契约" in (
        plugin_registry_missing_row
    )
    assert "只匹配 `Runner/Collector/Source plugin not found` 片段" in (
        plugin_registry_missing_row
    )
    assert "KeyError args 丢失插件名" in plugin_registry_missing_row
    assert "miss 后污染已注册插件表" in plugin_registry_missing_row
    assert "`KeyError.args` 精确包含类型和 missing name" in (
        plugin_registry_missing_row
    )
    assert "三类 names 列表不变且已注册插件仍可取回" in plugin_registry_missing_row
    assert "插件查找测试只为异常覆盖率服务" in plugin_registry_missing_row
