from __future__ import annotations

from collections.abc import Collection, Mapping
from typing import Any
from uuid import UUID

from fastapi import HTTPException


RESERVED_RUN_METADATA_KEYS = frozenset(
    {
        "git_url",
        "git_auth_method",
        "credential_id",
        "shallow_clone",
        "default_branch",
    }
)


def build_project_run_metadata(
    project: Any,
    *,
    extra_metadata: Mapping[str, Any] | None = None,
    reserved_extra_keys: Collection[str] = RESERVED_RUN_METADATA_KEYS,
) -> dict[str, Any]:
    metadata: dict[str, Any] = {"git_url": project.git_url}
    if project.git_auth_method != "none" and project.credential_id:
        metadata["git_auth_method"] = project.git_auth_method
        metadata["credential_id"] = str(project.credential_id)
    if project.shallow_clone:
        metadata["shallow_clone"] = True
    if project.default_branch:
        metadata["default_branch"] = project.default_branch

    if extra_metadata:
        reserved = {key.lower() for key in reserved_extra_keys}
        metadata.update(
            {
                key: value
                for key, value in extra_metadata.items()
                if key.lower() not in reserved
            }
        )

    return metadata


async def resolve_project_run_environment_id(
    *,
    repos: Any,
    project: Any,
    requested_environment_id: UUID | None = None,
) -> UUID:
    if requested_environment_id is not None:
        environment = await repos.environment.get_for_project(requested_environment_id, project.id)
        if environment is None:
            raise HTTPException(status_code=404, detail="Environment not found")
        return requested_environment_id

    if project.default_env_id is not None:
        return project.default_env_id

    envs, _ = await repos.environment.list_by_project(project.id, limit=1)
    if envs:
        return envs[0].id

    raise HTTPException(status_code=409, detail="No environment configured for project")
