from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Iterable
from uuid import UUID

from qaplatform.domain.models.run import TERMINAL_STATUSES, Run, RunStatus
from qaplatform.domain.ports import RunRepositoryProtocol

# Valid status transitions
_TRANSITIONS: dict[RunStatus, set[RunStatus]] = {
    RunStatus.QUEUED: {RunStatus.PREPARING, RunStatus.CANCELLED},
    RunStatus.PREPARING: {RunStatus.RUNNING, RunStatus.FAILED, RunStatus.CANCELLED},
    RunStatus.RUNNING: {RunStatus.COLLECTING, RunStatus.FAILED, RunStatus.CANCELLED, RunStatus.TIMEOUT},
    RunStatus.COLLECTING: {RunStatus.DONE, RunStatus.FAILED, RunStatus.CANCELLED, RunStatus.TIMEOUT},
    # Terminal states have no outgoing transitions
    RunStatus.DONE: set(),
    RunStatus.FAILED: set(),
    RunStatus.CANCELLED: set(),
    RunStatus.TIMEOUT: set(),
}

# From any active state, cancellation/failure is allowed.
CANCELABLE_STATUSES = frozenset(
    {RunStatus.QUEUED, RunStatus.PREPARING, RunStatus.RUNNING, RunStatus.COLLECTING}
)
ACTIVE_STATUSES = CANCELABLE_STATUSES
IN_FLIGHT_STATUSES = frozenset(
    {RunStatus.PREPARING, RunStatus.RUNNING, RunStatus.COLLECTING}
)
RETRYABLE_STATUSES = frozenset(TERMINAL_STATUSES)
FINISHABLE_STATUSES = frozenset({RunStatus.RUNNING, RunStatus.COLLECTING})


def coerce_run_status(status: RunStatus | str | Enum) -> RunStatus:
    """Normalize API/infra status representations to the domain enum."""
    if isinstance(status, RunStatus):
        return status
    if isinstance(status, Enum):
        return RunStatus(status.value)
    return RunStatus(status)


def run_status_values(statuses: Iterable[RunStatus]) -> frozenset[str]:
    return frozenset(status.value for status in statuses)


def is_terminal_status(status: RunStatus | str | Enum) -> bool:
    return coerce_run_status(status) in TERMINAL_STATUSES


def is_cancelable_status(status: RunStatus | str | Enum) -> bool:
    return coerce_run_status(status) in CANCELABLE_STATUSES


def is_retryable_status(status: RunStatus | str | Enum) -> bool:
    return coerce_run_status(status) in RETRYABLE_STATUSES


def is_valid_transition(current: RunStatus, target: RunStatus) -> bool:
    """Check whether a status transition is valid."""
    if current in TERMINAL_STATUSES:
        return False
    return target in _TRANSITIONS.get(current, set())


# --------------------------------------------------------------------------- #
# Repository protocol for conditional updates
# --------------------------------------------------------------------------- #



# --------------------------------------------------------------------------- #
# Conditional state transitions (WHERE status = expected)
# --------------------------------------------------------------------------- #


async def claim_for_worker(
    repo: RunRepositoryProtocol,
    run_id: UUID | str,
    worker_id: str,
) -> Run | None:
    """Claim a run for a worker: queued -> preparing.

    Uses a conditional update (WHERE status = 'queued') to prevent
    double-claiming. Returns the run if claimed, None otherwise.
    """
    updated = await repo.update_status(
        run_id,
        RunStatus.PREPARING,
        worker_id=worker_id,
    )
    if not updated:
        return None
    return await repo.get(run_id)


async def start_execution(
    repo: RunRepositoryProtocol,
    run_id: UUID | str,
) -> bool:
    """Transition preparing -> running."""
    return await repo.update_status(run_id, RunStatus.RUNNING)


async def finish_if_current(
    repo: RunRepositoryProtocol,
    run_id: UUID | str,
    *,
    summary: dict | None = None,
) -> bool:
    """Transition collecting -> done (conditional: WHERE status = 'collecting').

    Returns True if the update was applied, False if another process
    already moved the run to a terminal state.
    """
    kwargs: dict = {}
    if summary is not None:
        kwargs["summary"] = summary
    return await repo.update_status(run_id, RunStatus.DONE, **kwargs)


async def fail_if_current(
    repo: RunRepositoryProtocol,
    run_id: UUID | str,
    *,
    expected: RunStatus | None = None,
    message: str = "",
) -> bool:
    """Transition any non-terminal state -> failed (conditional update).

    If ``expected`` is provided, only transitions from that specific status.
    Otherwise, allows transition from any non-terminal state.
    """
    return await repo.update_status(
        run_id,
        RunStatus.FAILED,
        error_message=message,
        expected=expected,
    )


async def cancel_if_current(
    repo: RunRepositoryProtocol,
    run_id: UUID | str,
) -> bool:
    """Transition any non-terminal state -> cancelled (conditional update).

    SQL: UPDATE run SET status = 'cancelled' WHERE id = :id
         AND status NOT IN ('done', 'failed', 'cancelled', 'timeout')
    """
    return await repo.update_status(run_id, RunStatus.CANCELLED)


async def timeout_if_current(
    repo: RunRepositoryProtocol,
    run_id: UUID | str,
) -> bool:
    """Transition running/collecting -> timeout (conditional update).

    Used by TimeoutGuard to preempt the executor when a pipeline deadline
    is exceeded.
    """
    return await repo.update_status(run_id, RunStatus.TIMEOUT)


class ExecutionService:
    """Domain service for run creation and lifecycle management."""

    def create_run(
        self,
        *,
        tenant_id: UUID,
        project_id: UUID,
        pipeline_id: UUID,
        environment_id: UUID,
        trigger_type: str,
        git_ref: str,
        triggered_by: UUID | None = None,
        git_sha: str | None = None,
        source_run_id: UUID | None = None,
        chain_depth: int = 0,
        dedup_key: str | None = None,
    ) -> Run:
        """Create a new Run in queued state."""
        now = datetime.now(timezone.utc)
        return Run(
            id=UUID(int=0),  # caller must assign a real id
            tenant_id=tenant_id,
            project_id=project_id,
            pipeline_id=pipeline_id,
            environment_id=environment_id,
            status=RunStatus.QUEUED,
            trigger_type=trigger_type,  # type: ignore[arg-type]
            git_ref=git_ref,
            git_sha=git_sha,
            triggered_by=triggered_by,
            source_run_id=source_run_id,
            chain_depth=chain_depth,
            dedup_key=dedup_key,
            created_at=now,
            updated_at=now,
            status_updated_at=now,
        )

    def transition_status(self, run: Run, target: RunStatus) -> bool:
        """Validate and return whether transition is allowed. Does not mutate."""
        return is_valid_transition(run.status, target)

    def is_cancelable(self, run: Run) -> bool:
        """Check if the run can be cancelled."""
        return is_cancelable_status(run.status)
