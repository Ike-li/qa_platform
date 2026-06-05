from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from fastapi import HTTPException

from qaplatform.api.run_commands import (
    build_project_run_metadata,
    resolve_project_run_environment_id,
)


def _project(**overrides):
    defaults = {
        "id": uuid4(),
        "git_url": "https://github.com/example/repo.git",
        "git_auth_method": "none",
        "credential_id": None,
        "shallow_clone": True,
        "default_branch": "main",
        "default_env_id": uuid4(),
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def test_build_project_run_metadata_preserves_reserved_project_fields():
    credential_id = uuid4()
    project = _project(git_auth_method="token", credential_id=credential_id)

    metadata = build_project_run_metadata(
        project,
        extra_metadata={
            "git_url": "https://attacker.example/repo.git",
            "credential_id": "not-the-project-credential",
            "provider": "github",
        },
    )

    assert metadata == {
        "git_url": "https://github.com/example/repo.git",
        "git_auth_method": "token",
        "credential_id": str(credential_id),
        "shallow_clone": True,
        "default_branch": "main",
        "provider": "github",
    }


@pytest.mark.asyncio
async def test_resolve_project_run_environment_id_uses_default_without_lookup():
    project = _project()
    repos = MagicMock()

    environment_id = await resolve_project_run_environment_id(
        repos=repos,
        project=project,
    )

    assert environment_id == project.default_env_id
    repos.environment.get_by_id.assert_not_called()
    repos.environment.list_by_project.assert_not_called()


@pytest.mark.asyncio
async def test_resolve_project_run_environment_id_validates_requested_environment():
    project = _project()
    requested_environment_id = uuid4()
    environment = SimpleNamespace(id=requested_environment_id, project_id=project.id)
    repos = MagicMock()
    repos.environment.get_by_id = AsyncMock(return_value=environment)

    environment_id = await resolve_project_run_environment_id(
        repos=repos,
        project=project,
        requested_environment_id=requested_environment_id,
    )

    assert environment_id == requested_environment_id
    repos.environment.get_by_id.assert_awaited_once_with(requested_environment_id)


@pytest.mark.asyncio
async def test_resolve_project_run_environment_id_rejects_missing_environment():
    project = _project(default_env_id=None)
    repos = MagicMock()
    repos.environment.list_by_project = AsyncMock(return_value=([], 0))

    with pytest.raises(HTTPException) as exc_info:
        await resolve_project_run_environment_id(repos=repos, project=project)

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail == "No environment configured for project"
