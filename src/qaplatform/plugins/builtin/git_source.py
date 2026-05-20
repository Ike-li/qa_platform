from __future__ import annotations

import asyncio
import ipaddress
import re
import socket
from pathlib import Path
from urllib.parse import urlparse

from qaplatform.plugins.protocols import SourceRevision

_SHA_PATTERN = re.compile(r"^[0-9a-f]{40}$")

_PRIVATE_CIDRS = [
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
]


def _validate_git_url(url: str) -> None:
    """Reject URLs that could lead to SSRF attacks.

    Allowed formats:
    - https://github.com/org/repo.git
    - git@github.com:org/repo.git (SSH)
    """
    # SSH format: git@hostname:path
    ssh_match = re.match(r"^[^@]+@([^:]+):", url)
    if ssh_match:
        hostname = ssh_match.group(1)
    else:
        parsed = urlparse(url)
        if parsed.scheme not in ("https",):
            raise ValueError(f"Git URL must use https:// or SSH format, got: {parsed.scheme}://")
        hostname = parsed.hostname

    if not hostname:
        raise ValueError("Git URL has no hostname")
    try:
        infos = socket.getaddrinfo(hostname, None)
        for family, _, _, _, sockaddr in infos:
            ip = ipaddress.ip_address(sockaddr[0])
            for cidr in _PRIVATE_CIDRS:
                if ip in cidr:
                    raise ValueError(f"Git URL hostname resolves to private IP: {ip}")
    except socket.gaierror:
        raise ValueError(f"Cannot resolve hostname: {hostname}")


class GitSource:
    """Built-in SourceProtocol implementation using git CLI."""

    name: str = "git"

    async def clone(self, url: str, ref: str, dest: Path) -> SourceRevision:
        _validate_git_url(url)
        if _SHA_PATTERN.match(ref):
            return await self._clone_by_sha(url, ref, dest)
        return await self._clone_by_ref(url, ref, dest)

    async def _clone_by_ref(self, url: str, ref: str, dest: Path) -> SourceRevision:
        cmd = ["git", "clone", "--depth", "1", "--branch", ref, url, str(dest)]
        await self._exec(cmd)
        sha = await self._resolve_sha(dest)
        return SourceRevision(path=dest, sha=sha, ref=ref)

    async def _clone_by_sha(self, url: str, sha: str, dest: Path) -> SourceRevision:
        cmd = ["git", "clone", url, str(dest)]
        await self._exec(cmd)
        checkout_cmd = ["git", "-C", str(dest), "checkout", sha]
        await self._exec(checkout_cmd)
        return SourceRevision(path=dest, sha=sha, ref=sha)

    async def _resolve_sha(self, repo_path: Path) -> str:
        cmd = ["git", "-C", str(repo_path), "rev-parse", "HEAD"]
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await process.communicate()
        return stdout.decode().strip()

    async def _exec(self, cmd: list[str]) -> None:
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await process.communicate()
        if process.returncode != 0:
            err_msg = stderr.decode(errors="replace").strip()
            raise RuntimeError(f"git clone failed (exit {process.returncode}): {err_msg}")
