from __future__ import annotations

import math
from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field

T = TypeVar("T")


class ResourceLimits(BaseModel):
    model_config = ConfigDict(frozen=True)

    memory_mb: int = 512
    cpu_cores: float = 1.0
    max_artifact_size_mb: int = 100
    max_artifacts_count: int = 50


class PaginationParams(BaseModel):
    model_config = ConfigDict(frozen=True)

    page: int = Field(default=1, ge=1)
    per_page: int = Field(default=20, ge=1, le=100)

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.per_page


class PaginatedResponse(BaseModel, Generic[T]):
    model_config = ConfigDict(frozen=True)

    data: list[T]
    page: int
    per_page: int
    total: int

    @property
    def pages(self) -> int:
        if self.total == 0:
            return 0
        return math.ceil(self.total / self.per_page)
