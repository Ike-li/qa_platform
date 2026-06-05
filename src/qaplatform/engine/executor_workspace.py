"""Workspace directory helpers for run execution."""

from __future__ import annotations

import os
import tempfile
from contextlib import suppress
from pathlib import Path


def create_workspace_dir(run_id: str) -> Path:
    workspace_root = os.environ.get("QAP_RUN_WORKSPACE_DIR")
    if workspace_root:
        root = Path(workspace_root)
        root.mkdir(parents=True, exist_ok=True)
        with suppress(PermissionError):
            root.chmod(0o777)
        working_dir = Path(tempfile.mkdtemp(prefix=f"qap-{run_id[:8]}-", dir=root))
    else:
        working_dir = Path(tempfile.mkdtemp(prefix=f"qap-{run_id[:8]}-"))

    # Docker stage/setup containers run as a fixed non-root uid. GitHub
    # Linux runners create mkdtemp directories as 0700 for the host runner
    # user, so make this per-run sandbox writable by the mounted container.
    working_dir.chmod(0o777)
    return working_dir
