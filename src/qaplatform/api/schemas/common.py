from __future__ import annotations

import re

from pydantic import BaseModel, ConfigDict, Field

from qaplatform.domain.models.common import (
    PaginatedResponse as PaginatedResponse,
    PaginationParams as PaginationParams,
)

_IMAGE_TAG_RE = re.compile(r"^[a-zA-Z0-9._/\-]+:[a-zA-Z0-9._\-]+$")
_BLOCKED_IMAGE_TAGS = {"latest", "stable", "edge"}


def validate_pinned_base_image(image: str) -> str:
    if not _IMAGE_TAG_RE.match(image):
        raise ValueError("Image must use format 'registry/name:tag'")
    tag = image.rsplit(":", 1)[-1]
    if tag.lower() in _BLOCKED_IMAGE_TAGS:
        raise ValueError(f"Tag ':{tag}' is not allowed; pin a specific version")
    return image


def validate_credential_name(name: str) -> str:
    if name.strip() == "":
        raise ValueError("credential name must not be blank")
    return name


def validate_environment_text(field_name: str, value: str | None) -> str | None:
    if value is not None and value.strip() == "":
        raise ValueError(f"environment {field_name} must not be blank")
    return value


def validate_project_text(field_name: str, value: str | None) -> str | None:
    if value is not None and value.strip() == "":
        raise ValueError(f"project {field_name} must not be blank")
    return value


def validate_run_git_ref(git_ref: str | None) -> str | None:
    if git_ref is not None and git_ref.strip() == "":
        raise ValueError("run git_ref must not be blank")
    return git_ref


def validate_webhook_git_ref(git_ref: str) -> str:
    if git_ref.strip() == "":
        raise ValueError("webhook git_ref must not be blank")
    return git_ref


def validate_webhook_git_sha(git_sha: str | None) -> str | None:
    if git_sha is not None and git_sha.strip() == "":
        raise ValueError("webhook git_sha must not be blank")
    return git_sha


def validate_pipeline_text(field_name: str, value: str | None) -> str | None:
    if value is not None and value.strip() == "":
        raise ValueError(f"pipeline {field_name} must not be blank")
    return value


def validate_pipeline_text_list(field_name: str, values: list[str]) -> list[str]:
    for index, value in enumerate(values):
        if value.strip() == "":
            raise ValueError(f"pipeline {field_name}[{index}] must not be blank")
    return values


class ErrorDetail(BaseModel):
    model_config = ConfigDict(frozen=True, from_attributes=True)

    code: str
    message: str
    details: list[str] = Field(default_factory=list)


class ErrorResponse(BaseModel):
    model_config = ConfigDict(frozen=True, from_attributes=True)

    error: ErrorDetail


__all__ = [
    "ErrorDetail",
    "ErrorResponse",
    "PaginatedResponse",
    "PaginationParams",
    "validate_credential_name",
    "validate_environment_text",
    "validate_pinned_base_image",
    "validate_pipeline_text",
    "validate_pipeline_text_list",
    "validate_project_text",
    "validate_run_git_ref",
    "validate_webhook_git_ref",
    "validate_webhook_git_sha",
]
