"""Source checkout helpers for run execution."""

from __future__ import annotations

import re
from typing import Any

FULL_GIT_SHA_RE = re.compile(r"^[0-9a-fA-F]{40}$")


def run_metadata(run: Any) -> dict[str, Any]:
    metadata = getattr(run, "metadata_", None)
    if metadata is None:
        metadata = getattr(run, "metadata", None) or {}
    if not isinstance(metadata, dict):
        return {}
    return metadata


def git_url_for_run(run: Any) -> Any:
    return run_metadata(run).get("git_url", "") or ""


def clone_ref_for_run(run: Any) -> str:
    git_sha = getattr(run, "git_sha", None)
    if git_sha and FULL_GIT_SHA_RE.match(git_sha):
        return git_sha
    return run.git_ref
