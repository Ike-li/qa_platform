from __future__ import annotations

import shlex
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from qaplatform.plugins.builtin.git_source import GitSource, _validate_git_url
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

    @pytest.fixture(autouse=True)
    def _stub_url_validation(self):
        with patch("qaplatform.plugins.builtin.git_source._validate_git_url") as mock_validate:
            yield mock_validate

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

        clone_call = mock_exec.await_args_list[0]
        assert clone_call.args == (
            "git",
            "clone",
            "--depth",
            "1",
            "--branch",
            "main",
            "https://github.com/org/repo.git",
            str(dest),
        )
        assert token not in clone_call.args
        assert clone_call.kwargs["env"]["GIT_TERMINAL_PROMPT"] == "0"
        assert clone_call.kwargs["env"]["QAP_GIT_USERNAME"] == "x-access-token"
        assert clone_call.kwargs["env"]["QAP_GIT_TOKEN"] == token
        askpass = Path(clone_call.kwargs["env"]["GIT_ASKPASS"])
        assert askpass.name == "askpass.sh"
        assert askpass.parent.name.startswith("qap-git-auth-")

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

        clone_call = mock_exec.await_args_list[0]
        assert clone_call.args == (
            "git",
            "clone",
            "--depth",
            "1",
            "--branch",
            "main",
            "git@github.com:org/repo.git",
            str(dest),
        )
        assert key not in clone_call.args
        assert clone_call.kwargs["env"]["GIT_TERMINAL_PROMPT"] == "0"
        ssh_command = clone_call.kwargs["env"]["GIT_SSH_COMMAND"]
        ssh_argv = shlex.split(ssh_command)
        identity_path = Path(ssh_argv[2])
        assert ssh_argv == [
            "ssh",
            "-i",
            str(identity_path),
            "-o",
            "IdentitiesOnly=yes",
            "-o",
            "StrictHostKeyChecking=accept-new",
        ]
        assert identity_path.name == "identity"
        assert identity_path.parent.name.startswith("qap-git-auth-")
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

        message = str(exc_info.value)
        assert message == (
            "git clone failed (exit 128): fatal: Authentication failed for "
            "'https://***@github.com/org/repo.git'"
        )
        assert token not in message

    @pytest.mark.asyncio
    async def test_clone_failure_redacts_url_userinfo_without_explicit_secret(self, source, dest):
        url = "https://x-access-token:embedded-secret-token@github.com/org/repo.git"
        stderr = f"fatal: Authentication failed for '{url}'"
        with patch("asyncio.create_subprocess_exec") as mock_exec:
            process = AsyncMock()
            process.returncode = 128
            process.communicate.return_value = (b"", stderr.encode())
            mock_exec.return_value = process

            with pytest.raises(RuntimeError) as exc_info:
                await source.clone(url, "main", dest)

        message = str(exc_info.value)
        assert message == (
            "git clone failed (exit 128): fatal: Authentication failed for "
            "'https://***@github.com/org/repo.git'"
        )
        assert "embedded-secret-token" not in message
        assert "x-access-token" not in message

    @pytest.mark.asyncio
    async def test_clone_shallow_by_default(self, source, dest):
        with patch("asyncio.create_subprocess_exec") as mock_exec:
            process = AsyncMock()
            process.returncode = 0
            process.communicate.return_value = (b"", b"")
            mock_exec.return_value = process

            with patch.object(source, "_resolve_sha", return_value="abc123"):
                await source.clone("https://github.com/org/repo.git", "main", dest)

        mock_exec.assert_awaited_once()
        assert mock_exec.await_args.args == (
            "git",
            "clone",
            "--depth",
            "1",
            "--branch",
            "main",
            "https://github.com/org/repo.git",
            str(dest),
        )

    @pytest.mark.asyncio
    async def test_clone_with_branch_ref(self, source, dest):
        with patch("asyncio.create_subprocess_exec") as mock_exec:
            process = AsyncMock()
            process.returncode = 0
            process.communicate.return_value = (b"", b"")
            mock_exec.return_value = process

            with patch.object(source, "_resolve_sha", return_value="def456"):
                await source.clone("https://github.com/org/repo.git", "feature/x", dest)

        mock_exec.assert_awaited_once()
        assert mock_exec.await_args.args == (
            "git",
            "clone",
            "--depth",
            "1",
            "--branch",
            "feature/x",
            "https://github.com/org/repo.git",
            str(dest),
        )

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
        cmd_calls = mock_exec.await_args_list
        # For full SHA, should do unshallow clone + checkout
        assert [call.args[0:2] for call in cmd_calls] == [
            ("git", "clone"),
            ("git", "-C"),
        ]
        assert cmd_calls[-1].args == ("git", "-C", str(dest), "checkout", sha)

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
        checkout_call = mock_exec.await_args_list[-1].args
        assert checkout_call == ("git", "-C", str(dest), "checkout", sha)

    @pytest.mark.asyncio
    async def test_clone_failure_raises_runtime_error(self, source, dest):
        with patch("asyncio.create_subprocess_exec") as mock_exec:
            process = AsyncMock()
            process.returncode = 128
            process.communicate.return_value = (b"", b"fatal: repository not found")
            mock_exec.return_value = process

            with pytest.raises(RuntimeError) as exc_info:
                await source.clone("https://github.com/org/repo.git", "main", dest)

        assert str(exc_info.value) == (
            "git clone failed (exit 128): fatal: repository not found"
        )
        mock_exec.assert_awaited_once()
        assert mock_exec.await_args.args == (
            "git",
            "clone",
            "--depth",
            "1",
            "--branch",
            "main",
            "https://github.com/org/repo.git",
            str(dest),
        )
        assert mock_exec.await_args.kwargs["env"] is None

    @pytest.mark.asyncio
    async def test_clone_auth_failure_raises_runtime_error(self, source, dest):
        with patch("asyncio.create_subprocess_exec") as mock_exec:
            process = AsyncMock()
            process.returncode = 128
            process.communicate.return_value = (b"", b"fatal: Authentication failed")
            mock_exec.return_value = process

            with pytest.raises(RuntimeError) as exc_info:
                await source.clone("git@github.com:org/repo.git", "main", dest)

        assert str(exc_info.value) == (
            "git clone failed (exit 128): fatal: Authentication failed"
        )
        mock_exec.assert_awaited_once()
        assert mock_exec.await_args.args == (
            "git",
            "clone",
            "--depth",
            "1",
            "--branch",
            "main",
            "git@github.com:org/repo.git",
            str(dest),
        )
        assert mock_exec.await_args.kwargs["env"] is None

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

    @pytest.mark.asyncio
    async def test_clone_fails_when_resolving_head_sha_fails(self, source, dest):
        clone_process = AsyncMock()
        clone_process.returncode = 0
        clone_process.communicate.return_value = (b"", b"")
        rev_parse_process = AsyncMock()
        rev_parse_process.returncode = 128
        rev_parse_process.communicate.return_value = (b"", b"fatal: bad object HEAD")

        with patch(
            "asyncio.create_subprocess_exec",
            side_effect=[clone_process, rev_parse_process],
        ) as mock_exec:
            with pytest.raises(RuntimeError) as exc_info:
                await source.clone("https://github.com/org/repo.git", "main", dest)

        assert str(exc_info.value) == (
            "git rev-parse failed (exit 128): fatal: bad object HEAD"
        )
        assert mock_exec.await_args_list[1].args == (
            "git",
            "-C",
            str(dest),
            "rev-parse",
            "HEAD",
        )

    @pytest.mark.asyncio
    async def test_clone_fails_when_resolved_head_sha_is_empty(self, source, dest):
        clone_process = AsyncMock()
        clone_process.returncode = 0
        clone_process.communicate.return_value = (b"", b"")
        rev_parse_process = AsyncMock()
        rev_parse_process.returncode = 0
        rev_parse_process.communicate.return_value = (b"\n", b"")

        with patch(
            "asyncio.create_subprocess_exec",
            side_effect=[clone_process, rev_parse_process],
        ):
            with pytest.raises(RuntimeError) as exc_info:
                await source.clone("https://github.com/org/repo.git", "main", dest)

        assert str(exc_info.value) == "git rev-parse failed: empty HEAD SHA"


class TestGitSourceRegistration:
    """Test that GitSource is registered in builtins."""

    def test_register_builtins_includes_git_source(self):
        from qaplatform.plugins.registry import PluginRegistry

        registry = PluginRegistry()
        registry.register_builtins()
        assert "git" in registry.source_names


class TestGitUrlValidation:
    @pytest.mark.parametrize(
        "ip",
        [
            "127.0.0.1",
            "169.254.169.254",
            "0.0.0.0",
            "224.0.0.1",
            "2001:db8::1",
        ],
    )
    def test_rejects_https_hostname_that_resolves_to_non_global_ip(self, ip):
        with patch(
            "socket.getaddrinfo",
            return_value=[(None, None, None, None, (ip, 443))],
        ) as getaddrinfo:
            with pytest.raises(ValueError) as exc_info:
                _validate_git_url("https://github.example/repo.git")

        assert str(exc_info.value) == f"Git URL hostname resolves to non-public IP: {ip}"
        getaddrinfo.assert_called_once_with("github.example", None)

    def test_allows_https_hostname_that_resolves_to_public_ip(self):
        with patch(
            "socket.getaddrinfo",
            return_value=[(None, None, None, None, ("93.184.216.34", 443))],
        ) as getaddrinfo:
            _validate_git_url("https://github.example/repo.git")
        getaddrinfo.assert_called_once_with("github.example", None)

    def test_allows_ssh_format_after_hostname_validation(self):
        with patch(
            "socket.getaddrinfo",
            return_value=[(None, None, None, None, ("93.184.216.34", 22))],
        ) as getaddrinfo:
            _validate_git_url("git@github.example:org/repo.git")
        getaddrinfo.assert_called_once_with("github.example", None)

    @pytest.mark.parametrize(
        ("url", "expected_message"),
        [
            (
                "http://git@github.example:80/org/repo.git",
                "Git URL must use https:// or SSH format, got: http://",
            ),
            (
                "ftp://git@github.example:21/org/repo.git",
                "Git URL must use https:// or SSH format, got: ftp://",
            ),
        ],
    )
    def test_rejects_url_schemes_even_when_userinfo_port_looks_like_ssh(
        self,
        url,
        expected_message,
    ):
        with patch(
            "socket.getaddrinfo",
            return_value=[(None, None, None, None, ("93.184.216.34", 443))],
        ) as getaddrinfo:
            with pytest.raises(ValueError) as exc_info:
                _validate_git_url(url)

        assert exc_info.value.args == (expected_message,)
        getaddrinfo.assert_not_called()

    @pytest.mark.parametrize(
        ("url", "expected_message"),
        [
            (
                "http://github.example/repo.git",
                "Git URL must use https:// or SSH format, got: http://",
            ),
            ("https:///repo.git", "Git URL has no hostname"),
        ],
    )
    def test_rejects_unsupported_or_malformed_urls_without_dns_lookup(
        self,
        url,
        expected_message,
    ):
        with patch("socket.getaddrinfo") as getaddrinfo:
            with pytest.raises(ValueError) as exc_info:
                _validate_git_url(url)

        assert exc_info.value.args == (expected_message,)
        getaddrinfo.assert_not_called()
