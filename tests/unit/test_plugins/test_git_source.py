from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from qaplatform.plugins.builtin.git_source import GitSource
from qaplatform.plugins.protocols import SourceProtocol, SourceRevision


class TestGitSourceProtocol:
    """Verify GitSource satisfies SourceProtocol."""

    def test_implements_protocol(self):
        source = GitSource()
        assert isinstance(source, SourceProtocol)

    def test_has_name(self):
        source = GitSource()
        assert source.name == "git"


class TestGitSourceClone:
    """Test clone behavior with mocked subprocess."""

    @pytest.fixture
    def source(self):
        return GitSource()

    @pytest.fixture
    def dest(self, tmp_path):
        return tmp_path / "repo"

    @pytest.mark.asyncio
    async def test_clone_https_success(self, source, dest):
        with patch("asyncio.create_subprocess_exec") as mock_exec:
            process = AsyncMock()
            process.returncode = 0
            process.communicate.return_value = (b"", b"")
            mock_exec.return_value = process

            with patch.object(source, "_resolve_sha", return_value="abc123"):
                result = await source.clone("https://github.com/org/repo.git", "main", dest)

        assert isinstance(result, SourceRevision)
        assert result.path == dest
        assert result.sha == "abc123"
        assert result.ref == "main"

    @pytest.mark.asyncio
    async def test_clone_https_token_uses_askpass_not_url_userinfo(self, source, dest):
        token = "ghp_secret_token_123"
        with patch("asyncio.create_subprocess_exec") as mock_exec:
            process = AsyncMock()
            process.returncode = 0
            process.communicate.return_value = (b"", b"")
            mock_exec.return_value = process

            with patch.object(source, "_resolve_sha", return_value="abc123"):
                await source.clone(
                    "https://github.com/org/repo.git",
                    "main",
                    dest,
                    {"method": "token", "secret": token},
                )

        clone_call = mock_exec.call_args_list[0]
        assert token not in clone_call.args
        assert clone_call.kwargs["env"]["GIT_TERMINAL_PROMPT"] == "0"
        assert clone_call.kwargs["env"]["QAP_GIT_TOKEN"] == token
        assert clone_call.kwargs["env"]["GIT_ASKPASS"].endswith("askpass.sh")

    @pytest.mark.asyncio
    async def test_clone_ssh_key_uses_temp_identity_file(self, source, dest):
        key = "-----BEGIN OPENSSH PRIVATE KEY-----\nsecret-key\n-----END OPENSSH PRIVATE KEY-----"
        with patch("asyncio.create_subprocess_exec") as mock_exec:
            process = AsyncMock()
            process.returncode = 0
            process.communicate.return_value = (b"", b"")
            mock_exec.return_value = process

            with patch.object(source, "_resolve_sha", return_value="abc123"):
                await source.clone(
                    "git@github.com:org/repo.git",
                    "main",
                    dest,
                    {"method": "ssh_key", "secret": key},
                )

        clone_call = mock_exec.call_args_list[0]
        assert key not in clone_call.args
        ssh_command = clone_call.kwargs["env"]["GIT_SSH_COMMAND"]
        assert "ssh -i" in ssh_command
        assert "secret-key" not in ssh_command

    @pytest.mark.asyncio
    async def test_clone_auth_failure_redacts_token_from_error(self, source, dest):
        token = "ghp_secret_token_123"
        stderr = (
            "fatal: Authentication failed for "
            f"'https://x-access-token:{token}@github.com/org/repo.git'"
        )
        with patch("asyncio.create_subprocess_exec") as mock_exec:
            process = AsyncMock()
            process.returncode = 128
            process.communicate.return_value = (b"", stderr.encode())
            mock_exec.return_value = process

            with pytest.raises(RuntimeError) as exc_info:
                await source.clone(
                    "https://github.com/org/repo.git",
                    "main",
                    dest,
                    {"method": "token", "secret": token},
                )

        assert token not in str(exc_info.value)
        assert "https://***@github.com/org/repo.git" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_clone_shallow_by_default(self, source, dest):
        with patch("asyncio.create_subprocess_exec") as mock_exec:
            process = AsyncMock()
            process.returncode = 0
            process.communicate.return_value = (b"", b"")
            mock_exec.return_value = process

            with patch.object(source, "_resolve_sha", return_value="abc123"):
                await source.clone("https://github.com/org/repo.git", "main", dest)

        cmd = mock_exec.call_args[0]
        assert "--depth" in cmd
        assert "1" in cmd

    @pytest.mark.asyncio
    async def test_clone_with_branch_ref(self, source, dest):
        with patch("asyncio.create_subprocess_exec") as mock_exec:
            process = AsyncMock()
            process.returncode = 0
            process.communicate.return_value = (b"", b"")
            mock_exec.return_value = process

            with patch.object(source, "_resolve_sha", return_value="def456"):
                await source.clone("https://github.com/org/repo.git", "feature/x", dest)

        cmd = mock_exec.call_args[0]
        assert "--branch" in cmd
        assert "feature/x" in cmd

    @pytest.mark.asyncio
    async def test_clone_with_commit_sha(self, source, dest):
        sha = "a" * 40
        with patch("asyncio.create_subprocess_exec") as mock_exec:
            process = AsyncMock()
            process.returncode = 0
            process.communicate.return_value = (b"", b"")
            mock_exec.return_value = process

            result = await source.clone("https://github.com/org/repo.git", sha, dest)

        assert result.sha == sha
        cmd_calls = mock_exec.call_args_list
        # For full SHA, should do unshallow clone + checkout
        assert len(cmd_calls) >= 1

    @pytest.mark.asyncio
    async def test_clone_with_uppercase_commit_sha(self, source, dest):
        sha = "A" * 40
        with patch("asyncio.create_subprocess_exec") as mock_exec:
            process = AsyncMock()
            process.returncode = 0
            process.communicate.return_value = (b"", b"")
            mock_exec.return_value = process

            result = await source.clone("https://github.com/org/repo.git", sha, dest)

        assert result.sha == sha
        checkout_call = mock_exec.call_args_list[-1][0]
        assert checkout_call == ("git", "-C", str(dest), "checkout", sha)

    @pytest.mark.asyncio
    async def test_clone_failure_raises_runtime_error(self, source, dest):
        with patch("asyncio.create_subprocess_exec") as mock_exec:
            process = AsyncMock()
            process.returncode = 128
            process.communicate.return_value = (b"", b"fatal: repository not found")
            mock_exec.return_value = process

            with pytest.raises(RuntimeError, match="git clone failed"):
                await source.clone("https://github.com/org/repo.git", "main", dest)

    @pytest.mark.asyncio
    async def test_clone_auth_failure_raises_runtime_error(self, source, dest):
        with patch("asyncio.create_subprocess_exec") as mock_exec:
            process = AsyncMock()
            process.returncode = 128
            process.communicate.return_value = (b"", b"fatal: Authentication failed")
            mock_exec.return_value = process

            with pytest.raises(RuntimeError, match="git clone failed"):
                await source.clone("git@github.com:org/repo.git", "main", dest)

    @pytest.mark.asyncio
    async def test_clone_returns_source_revision(self, source, dest):
        with patch("asyncio.create_subprocess_exec") as mock_exec:
            process = AsyncMock()
            process.returncode = 0
            process.communicate.return_value = (b"", b"")
            mock_exec.return_value = process

            with patch.object(source, "_resolve_sha", return_value="deadbeef"):
                result = await source.clone("https://github.com/org/repo.git", "v1.0", dest)

        assert result.path == dest
        assert result.sha == "deadbeef"
        assert result.ref == "v1.0"


class TestGitSourceRegistration:
    """Test that GitSource is registered in builtins."""

    def test_register_builtins_includes_git_source(self):
        from qaplatform.plugins.registry import PluginRegistry

        registry = PluginRegistry()
        registry.register_builtins()
        assert "git" in registry.source_names
