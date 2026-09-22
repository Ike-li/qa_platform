from __future__ import annotations

from collections.abc import Sequence
from typing import Any
from uuid import UUID

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from qaplatform.api.audit import write_audit
from qaplatform.api.deps import UserIdentity
from qaplatform.api.run_presenters import to_run_response
from qaplatform.api.schemas import BatchRunResponse
from qaplatform.domain.services.execution import (
    CANCELABLE_STATUSES,
    is_cancelable_status,
    is_retryable_status,
)
from qaplatform.infra.database.models import Run as RunORM
from qaplatform.infra.database.models import RunStatusEnum

_BATCH_OPERATION_FAILED = "operation failed"
_CANCELABLE = frozenset(RunStatusEnum(status.value) for status in CANCELABLE_STATUSES)


def _status_value(status: object) -> str:
    return status.value if isinstance(status, RunStatusEnum) else str(status)


async def batch_cancel_run_command(
    *,
    run_ids: Sequence[UUID],
    repos: Any,
    user: UserIdentity,
    redis: Any,
) -> BatchRunResponse:
    processed = 0
    failed = 0
    errors: list[str] = []

    cancelable_runs: list[RunORM] = []
    for run_id in run_ids:
        try:
            run = await repos.run.get_for_tenant(run_id, user.tenant_id)
            if run is None:
                errors.append(f"{run_id}: not found")
                failed += 1
                continue

            if not is_cancelable_status(run.status):
                errors.append(f"{run_id}: already terminal ({run.status})")
                failed += 1
                continue

            cancelable_runs.append(run)
        except (SQLAlchemyError, ValueError):
            errors.append(f"{run_id}: {_BATCH_OPERATION_FAILED}")
            failed += 1

    for run in cancelable_runs:
        run_id = run.id
        try:
            before_response = to_run_response(run)
            previous = _status_value(run.status)
            cancelled = await repos.run.cancel_if_current(run_id, expected_in=_CANCELABLE)
            if not cancelled:
                errors.append(f"{run_id}: status changed concurrently")
                failed += 1
                continue

            if redis is not None:
                from qaplatform.engine.cancel import publish_cancel
                from qaplatform.engine.events import publish_status_event

                await publish_cancel(redis, run_id)
                await publish_status_event(redis, run_id, "cancelled", previous=previous)

            run_after = await repos.run.get_for_tenant(run_id, user.tenant_id)
            after_response = (
                to_run_response(run_after)
                if run_after is not None
                else {"status": "cancelled"}
            )
            await write_audit(
                repos,
                user,
                action="run.batch_cancel",
                resource_type="run",
                resource_id=run_id,
                before=before_response,
                after=after_response,
            )
            processed += 1
        except (SQLAlchemyError, ValueError):
            errors.append(f"{run_id}: {_BATCH_OPERATION_FAILED}")
            failed += 1

    return BatchRunResponse(processed=processed, failed=failed, errors=errors)


async def batch_retry_run_command(
    *,
    run_ids: Sequence[UUID],
    repos: Any,
    user: UserIdentity,
    session: AsyncSession,
    arq_pool: Any,
    settings: Any,
) -> BatchRunResponse:
    processed = 0
    failed = 0
    errors: list[str] = []

    retryable_runs: list[RunORM] = []
    for run_id in run_ids:
        try:
            original = await repos.run.get_for_tenant(run_id, user.tenant_id)
            if original is None:
                errors.append(f"{run_id}: not found")
                failed += 1
                continue

            if not is_retryable_status(original.status):
                errors.append(f"{run_id}: not terminal ({original.status})")
                failed += 1
                continue

            retryable_runs.append(original)
        except (SQLAlchemyError, ValueError):
            errors.append(f"{run_id}: {_BATCH_OPERATION_FAILED}")
            failed += 1

    for original in retryable_runs:
        run_id = original.id
        try:
            before_response = to_run_response(original)
            await session.refresh(original, ["pipeline", "environment"])

            new_run = await repos.run.create(
                tenant_id=original.tenant_id,
                project_id=original.project_id,
                pipeline_id=original.pipeline_id,
                environment_id=original.environment_id,
                git_ref=original.git_ref,
                git_sha=original.git_sha,
                priority=original.priority,
                triggered_by=user.user_id,
                trigger_type="manual",
                metadata_=dict(original.metadata_ or {}),
                source_run_id=original.id,
                chain_depth=(original.chain_depth or 0) + 1,
            )
            await repos.run.set_retry_group_id(new_run.id, new_run.id)

            if arq_pool is not None:
                await repos.run.commit()
                from qaplatform.infra.queue.scheduler import enqueue_run

                await enqueue_run(arq_pool, repos.run, new_run, "manual", settings)

            await write_audit(
                repos,
                user,
                action="run.batch_retry",
                resource_type="run",
                resource_id=original.id,
                before=before_response,
                after={
                    "retry_run_id": str(new_run.id),
                    "source_run_id": str(original.id),
                    "status": "queued",
                    "attempt": getattr(new_run, "attempt", None),
                },
            )
            processed += 1
        except (SQLAlchemyError, ValueError):
            errors.append(f"{run_id}: {_BATCH_OPERATION_FAILED}")
            failed += 1

    return BatchRunResponse(processed=processed, failed=failed, errors=errors)
