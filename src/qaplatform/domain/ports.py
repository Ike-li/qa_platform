from __future__ import annotations

from typing import TYPE_CHECKING, Any, Collection, Protocol
from uuid import UUID

from qaplatform.domain.models.run import RunStatus

if TYPE_CHECKING:
    from qaplatform.domain.models.run import Run


class RunRepositoryProtocol(Protocol):
    """Unified run repository interface used by executor and execution services."""

    async def get(self, run_id: UUID | str) -> Run | None: ...
    async def mark_running(self, run_id: UUID | str) -> bool: ...
    async def mark_collecting(self, run_id: UUID | str) -> bool: ...
    async def finish_if_current(
        self,
        run_id: UUID | str,
        *,
        status: RunStatus,
        expected_in: Collection[RunStatus] | None = None,
        summary: dict[str, Any] | None = None,
    ) -> bool: ...
    async def fail_if_current(
        self,
        run_id: UUID | str,
        *,
        expected_in: Collection[RunStatus] | None = None,
        message: str = "",
    ) -> bool: ...
    async def cancel_if_current(
        self,
        run_id: UUID | str,
        *,
        expected_in: Collection[RunStatus] | None = None,
    ) -> bool: ...
    async def is_cancel_requested(self, run_id: UUID | str) -> bool: ...
    async def update_execution_id(self, run_id: UUID | str, execution_id: str) -> None: ...
    async def update_git_sha(self, run_id: UUID | str, sha: str) -> None: ...
    async def update_status(self, run_id: UUID | str, status: RunStatus, **kwargs) -> bool: ...
    async def commit(self) -> None: ...
