from __future__ import annotations

from pathlib import Path

from tests.unit.release_quality_contract_helpers import (
    _block_between,
    _quality_ops_row,
    _quality_ops_row_containing,
    _read,
)


ROOT = Path(__file__).resolve().parents[2]
GIT_SOURCE_TEST = ROOT / "tests" / "unit" / "test_plugins" / "test_git_source.py"
WORKER_NOTIFICATIONS_TEST = (
    ROOT / "tests" / "unit" / "test_worker" / "test_notifications.py"
)
WORKER_SETTINGS_TASKS_TEST = (
    ROOT / "tests" / "unit" / "test_worker" / "test_settings_tasks.py"
)
WORKER_TASKS_TEST = ROOT / "tests" / "unit" / "test_worker" / "test_tasks.py"


def test_quality_ops_capture_worker_git_raises_exact_exception_contract():
    row = _quality_ops_row_containing("Worker/Git raises exact exception 契约")
    worker_settings_tasks = _read(WORKER_SETTINGS_TASKS_TEST)
    worker_tasks = _read(WORKER_TASKS_TEST)
    worker_notifications = _read(WORKER_NOTIFICATIONS_TEST)
    git_source = _read(GIT_SOURCE_TEST)

    assert "Worker/Git raises exact exception 契约" in row
    assert "同一个 RuntimeError 对象或 exact args" in row
    assert "完整 ValueError args" in row
    assert "非法 URL 不触发 DNS lookup" in row
    assert "`pytest.raises(..., match=...)` 匹配错误片段" in row
    assert "重新包装异常" in row
    assert "抛出了相似错误文本" in row
    assert "assert exc_info.value is error" in worker_settings_tasks
    assert "assert exc_info.value is error" in worker_notifications
    assert (
        'assert exc_info.value.args == ("Project Git credential type mismatch",)'
        in worker_tasks
    )
    assert "Git URL must use https:// or SSH format, got: http://" in git_source
    assert "Git URL must use https:// or SSH format, got: ftp://" in git_source
    assert "Git URL has no hostname" in git_source
    assert 'with pytest.raises(RuntimeError, match="db close failed")' not in (
        worker_settings_tasks
    )
    assert 'with pytest.raises(RuntimeError, match="type mismatch")' not in (
        worker_tasks
    )
    assert 'pytest.raises(RuntimeError, match="database unavailable")' not in (
        worker_notifications
    )
    assert 'pytest.raises(ValueError, match="https:// or SSH")' not in git_source
    assert "pytest.raises(ValueError, match=message)" not in git_source


def test_quality_ops_capture_git_source_clone_failure_exact_redacted_message_contract():
    git_source_test = _read(GIT_SOURCE_TEST)

    row = _quality_ops_row("| 2026-05-31 | N/A（GitSource clone failure exact redacted message 契约）")
    assert (
        "`tests/unit/test_plugins/test_git_source.py::TestGitSourceClone::test_clone_auth_failure_redacts_token_from_error "
        "tests/unit/test_plugins/test_git_source.py::TestGitSourceClone::test_clone_failure_redacts_url_userinfo_without_explicit_secret` 2 passed"
    ) in row
    assert "release quality docs contract full 279 passed" in row
    assert "targeted ruff passed" in row
    assert "完整异常文本" in row
    assert "https://***@github.com/org/repo.git" in row
    assert "只证明“有一个脱敏片段”" in row

    explicit_block = _block_between(git_source_test, "async def test_clone_auth_failure_redacts_token_from_error", "\n\n    @pytest.mark.asyncio")
    embedded_block = _block_between(git_source_test, "async def test_clone_failure_redacts_url_userinfo_without_explicit_secret", "\n\n    @pytest.mark.asyncio")

    for block in [explicit_block, embedded_block]:
        assert "message = str(exc_info.value)" in block
        assert "assert message == (" in block
        assert "git clone failed (exit 128): fatal: Authentication failed for " in block
        assert "'https://***@github.com/org/repo.git'" in block
        assert '"https://***@github.com/org/repo.git" in' not in block
        assert "in str(exc_info.value)" not in block

    assert "assert token not in message" in explicit_block
    assert 'assert "embedded-secret-token" not in message' in embedded_block
    assert 'assert "x-access-token" not in message' in embedded_block


def test_quality_ops_capture_git_source_auth_env_path_ssh_argv_exact_contract():
    git_source_test = _read(GIT_SOURCE_TEST)

    row = _quality_ops_row("| 2026-05-31 | N/A（GitSource auth env path/ssh argv exact 契约）")
    assert (
        "`tests/unit/test_plugins/test_git_source.py::TestGitSourceClone::test_clone_https_token_uses_askpass_not_url_userinfo "
        "tests/unit/test_plugins/test_git_source.py::TestGitSourceClone::test_clone_ssh_key_uses_temp_identity_file` 2 passed"
    ) in row
    assert "release quality docs contract full 278 passed" in row
    assert "targeted ruff passed" in row
    assert "`GIT_ASKPASS` 解析成 `Path`" in row
    assert "`shlex.split(GIT_SSH_COMMAND)` 固定完整 argv" in row
    assert "字符串首尾看起来对" in row

    for expected in [
        "import shlex",
        "from pathlib import Path",
        'askpass = Path(clone_call.kwargs["env"]["GIT_ASKPASS"])',
        'assert askpass.name == "askpass.sh"',
        'assert askpass.parent.name.startswith("qap-git-auth-")',
        "ssh_argv = shlex.split(ssh_command)",
        "identity_path = Path(ssh_argv[2])",
        "assert ssh_argv == [",
        '"ssh",',
        '"-i",',
        '"IdentitiesOnly=yes"',
        '"StrictHostKeyChecking=accept-new"',
        'assert identity_path.name == "identity"',
        'assert identity_path.parent.name.startswith("qap-git-auth-")',
    ]:
        assert expected in git_source_test

    for weak in [
        'assert clone_call.kwargs["env"]["GIT_ASKPASS"].endswith("askpass.sh")',
        'assert ssh_command.startswith("ssh -i ")',
        'assert ssh_command.endswith("-o IdentitiesOnly=yes -o StrictHostKeyChecking=accept-new")',
    ]:
        assert weak not in git_source_test
