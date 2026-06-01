from __future__ import annotations

import asyncio
import ipaddress
import os
import re
import shlex
import socket
import tempfile
from pathlib import Path
from urllib.parse import urlparse

from qaplatform.engine.redact import redact_sensitive_text
from qaplatform.plugins.protocols import SourceRevision

_SHA_PATTERN = re.compile(r"^[0-9a-f]{40}$", re.IGNORECASE)


def _validate_git_url(url: str) -> None:
    """Reject URLs that could lead to SSRF attacks.

    Allowed formats:
    - https://github.com/org/repo.git
    - git@github.com:org/repo.git (SSH)
    """
    parsed = urlparse(url)
    if parsed.scheme:
        if parsed.scheme not in ("https",):
            raise ValueError(f"Git URL must use https:// or SSH format, got: {parsed.scheme}://")
        hostname = parsed.hostname
    else:
        # SSH scp-like format: git@hostname:path
        ssh_match = re.match(r"^[^/@:]+@([^/:]+):.+", url)
        if not ssh_match:
            raise ValueError("Git URL must use https:// or SSH format, got: ://")
        hostname = ssh_match.group(1)

    if not hostname:
        raise ValueError("Git URL has no hostname")
    try:
        infos = socket.getaddrinfo(hostname, None)
        for _, _, _, _, sockaddr in infos:
            ip = ipaddress.ip_address(sockaddr[0])
            if not ip.is_global or ip.is_multicast:
                raise ValueError(f"Git URL hostname resolves to non-public IP: {ip}")
    except socket.gaierror:
        raise ValueError(f"Cannot resolve hostname: {hostname}")


class GitSource:
    """Built-in SourceProtocol implementation using git CLI."""

    name: str = "git"

    async def clone(
        self,
        url: str,
        ref: str,
        dest: Path,
        auth: dict[str, str] | None = None,
    ) -> SourceRevision:
        _validate_git_url(url)
        with tempfile.TemporaryDirectory(prefix="qap-git-auth-") as tmp_dir:
            clone_url, env, secrets = self._prepare_auth(url, auth, Path(tmp_dir))
            if _SHA_PATTERN.match(ref):
                return await self._clone_by_sha(clone_url, ref, dest, env=env, secrets=secrets)
            return await self._clone_by_ref(clone_url, ref, dest, env=env, secrets=secrets)

    def _prepare_auth(
        self,
        url: str,
        auth: dict[str, str] | None,
        tmp_dir: Path,
    ) -> tuple[str, dict[str, str] | None, list[str]]:
        if not auth:
            return url, None, []

        method = auth.get("method", "none")
        secret = auth.get("secret", "")
        if method == "none" or not secret:
            return url, None, []
        if method == "token":
            return url, self._token_env(url, secret, tmp_dir), [secret]
        if method == "ssh_key":
            return url, self._ssh_key_env(url, secret, tmp_dir), [secret]
        raise ValueError(f"Unsupported Git auth method: {method}")

    def _token_env(self, url: str, token: str, tmp_dir: Path) -> dict[str, str]:
        parsed = urlparse(url)
        if parsed.scheme != "https":
            raise ValueError("Token Git credentials require an https:// git_url")
        askpass = tmp_dir / "askpass.sh"
        askpass.write_text(
            "#!/bin/sh\n"
            "case \"$1\" in\n"
            "*Username*) printf '%s\\n' \"${QAP_GIT_USERNAME:-x-access-token}\" ;;\n"
            "*Password*) printf '%s\\n' \"$QAP_GIT_TOKEN\" ;;\n"
            "*) printf '\\n' ;;\n"
            "esac\n"
        )
        askpass.chmod(0o700)
        return {
            "GIT_TERMINAL_PROMPT": "0",
            "GIT_ASKPASS": str(askpass),
            "QAP_GIT_USERNAME": "x-access-token",
            "QAP_GIT_TOKEN": token,
        }

    def _ssh_key_env(self, url: str, key: str, tmp_dir: Path) -> dict[str, str]:
        if not re.match(r"^[^@]+@[^:]+:", url):
            raise ValueError("SSH key Git credentials require an SSH git_url")
        key_path = tmp_dir / "identity"
        key_path.write_text(key if key.endswith("\n") else f"{key}\n")
        key_path.chmod(0o600)
        return {
            "GIT_TERMINAL_PROMPT": "0",
            "GIT_SSH_COMMAND": (
                f"ssh -i {shlex.quote(str(key_path))} "
                "-o IdentitiesOnly=yes -o StrictHostKeyChecking=accept-new"
            ),
        }

    async def _clone_by_ref(
        self,
        url: str,
        ref: str,
        dest: Path,
        env: dict[str, str] | None = None,
        secrets: list[str] | None = None,
    ) -> SourceRevision:
        cmd = ["git", "clone", "--depth", "1", "--branch", ref, url, str(dest)]
        await self._exec(cmd, env=env, secrets=secrets)
        sha = await self._resolve_sha(dest)
        return SourceRevision(path=dest, sha=sha, ref=ref)

    async def _clone_by_sha(
        self,
        url: str,
        sha: str,
        dest: Path,
        env: dict[str, str] | None = None,
        secrets: list[str] | None = None,
    ) -> SourceRevision:
        cmd = ["git", "clone", url, str(dest)]
        await self._exec(cmd, env=env, secrets=secrets)
        checkout_cmd = ["git", "-C", str(dest), "checkout", sha]
        await self._exec(checkout_cmd, env=env, secrets=secrets)
        return SourceRevision(path=dest, sha=sha, ref=sha)

    async def _resolve_sha(self, repo_path: Path) -> str:
        cmd = ["git", "-C", str(repo_path), "rev-parse", "HEAD"]
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await process.communicate()
        if process.returncode != 0:
            err_msg = stderr.decode(errors="replace").strip()
            raise RuntimeError(f"git rev-parse failed (exit {process.returncode}): {err_msg}")
        sha = stdout.decode().strip()
        if not sha:
            raise RuntimeError("git rev-parse failed: empty HEAD SHA")
        return sha

    async def _exec(
        self,
        cmd: list[str],
        env: dict[str, str] | None = None,
        secrets: list[str] | None = None,
    ) -> None:
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env={**os.environ, **env} if env else None,
        )
        _, stderr = await process.communicate()
        if process.returncode != 0:
            err_msg = stderr.decode(errors="replace").strip()
            err_msg = redact_sensitive_text(err_msg, secrets)
            raise RuntimeError(f"git clone failed (exit {process.returncode}): {err_msg}")
