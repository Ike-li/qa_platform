from __future__ import annotations

import shutil
import stat
from pathlib import Path
from uuid import uuid4

from qaplatform.engine import executor as executor_module
from qaplatform.engine import executor_workspace as workspace
from qaplatform.engine.executor import RunExecutor


def test_create_workspace_dir_is_writable_by_fixed_container_uid(monkeypatch):
    monkeypatch.delenv("QAP_RUN_WORKSPACE_DIR", raising=False)
    run_id = str(uuid4())

    working_dir = workspace.create_workspace_dir(run_id)

    try:
        assert working_dir.name.startswith(f"qap-{run_id[:8]}-")
        assert stat.S_IMODE(working_dir.stat().st_mode) == 0o777
    finally:
        shutil.rmtree(working_dir, ignore_errors=True)


def test_create_workspace_dir_can_use_shared_docker_socket_root(
    tmp_path,
    monkeypatch,
):
    run_id = str(uuid4())
    shared_root = tmp_path / "qap-workspaces"
    monkeypatch.setenv("QAP_RUN_WORKSPACE_DIR", str(shared_root))

    working_dir = workspace.create_workspace_dir(run_id)

    try:
        assert working_dir.parent == shared_root
        assert working_dir.name.startswith(f"qap-{run_id[:8]}-")
        assert stat.S_IMODE(shared_root.stat().st_mode) == 0o777
        assert stat.S_IMODE(working_dir.stat().st_mode) == 0o777
    finally:
        shutil.rmtree(working_dir, ignore_errors=True)


def test_create_workspace_dir_tolerates_bind_root_chmod_denied(
    tmp_path,
    monkeypatch,
):
    run_id = str(uuid4())
    shared_root = tmp_path / "qap-workspaces"
    monkeypatch.setenv("QAP_RUN_WORKSPACE_DIR", str(shared_root))
    original_chmod = Path.chmod

    def chmod_with_bind_root_denied(path: Path, mode: int, *args, **kwargs):
        if path == shared_root:
            raise PermissionError("bind root is not owned by container user")
        return original_chmod(path, mode, *args, **kwargs)

    monkeypatch.setattr(Path, "chmod", chmod_with_bind_root_denied)

    working_dir = workspace.create_workspace_dir(run_id)

    try:
        assert working_dir.parent == shared_root
        assert working_dir.name.startswith(f"qap-{run_id[:8]}-")
        assert stat.S_IMODE(working_dir.stat().st_mode) == 0o777
    finally:
        shutil.rmtree(working_dir, ignore_errors=True)


def test_executor_module_keeps_workspace_helper_compatibility_exports(monkeypatch):
    monkeypatch.delenv("QAP_RUN_WORKSPACE_DIR", raising=False)

    assert executor_module._create_workspace_dir is workspace.create_workspace_dir
    working_dir = RunExecutor._create_workspace_dir(str(uuid4()))

    try:
        assert working_dir.exists()
    finally:
        shutil.rmtree(working_dir, ignore_errors=True)
