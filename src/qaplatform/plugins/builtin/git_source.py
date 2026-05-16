from __future__ import annotations

import asyncio
import re
from pathlib import Path

from qaplatform.plugins.protocols import SourceRevision

_SHA_PATTERN = re.compile(r"^[0-9a-f]{40}$")


class GitSource:
    """Built-in SourceProtocol implementation using git CLI."""

    name: str = "git"

    async def clone(self, url: str, ref: str, dest: Path) -> SourceRevision:
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
