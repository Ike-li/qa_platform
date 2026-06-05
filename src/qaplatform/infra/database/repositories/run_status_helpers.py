from __future__ import annotations

from enum import Enum as PyEnum
from typing import Collection

from qaplatform.infra.database.models import RunStatusEnum


def coerce_run_status_enum(status: RunStatusEnum | str | PyEnum) -> RunStatusEnum:
    if isinstance(status, RunStatusEnum):
        return status
    if isinstance(status, PyEnum):
        return RunStatusEnum(status.value)
    return RunStatusEnum(status)


def run_status_enums(
    statuses: Collection[RunStatusEnum | str | PyEnum],
) -> frozenset[RunStatusEnum]:
    return frozenset(coerce_run_status_enum(status) for status in statuses)
