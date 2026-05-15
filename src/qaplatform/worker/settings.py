from __future__ import annotations

import os

from arq import cron, func

from qaplatform.worker.tasks import execute_run


async def reclaim_resources(ctx: dict) -> None:
    """Periodic task: reclaim orphan containers and timeout stale runs."""
    # TODO: implement ResourceReclaimer once infra layer is ready


async def dequeue_waiting(ctx: dict) -> None:
    """Periodic task: enqueue waiting runs when capacity is available."""
    # TODO: implement FairScheduler.try_dequeue_waiting()


async def retry_failed_archives(ctx: dict) -> None:
    """Periodic task: retry failed log archival."""
    # TODO: implement log archive retry


async def after_job_end(ctx: dict) -> None:
    """arq after_job_end hook: compensate failed jobs.

    If a job fails and the Run is still in a non-terminal state,
    mark it as failed. This is a safety net for uncaught exceptions.
    """
    if ctx.get("success"):
        return

    job_id = ctx.get("job_id", "")
    if not job_id.startswith("run:"):
        return

    from qaplatform.domain.models.run import TERMINAL_STATUSES, RunStatus

    run_id = job_id.removeprefix("run:")
    run_repo = ctx.get("run_repo")
    if run_repo is None:
        return

    run = await run_repo.get(run_id)
    if run and run.status not in TERMINAL_STATUSES:
        await run_repo.fail_if_current(
            run.id,
            message=f"arq job failed: {ctx.get('result', 'unknown error')}",
        )


class WorkerSettings:
    """arq WorkerSettings for the QA Platform.

    Each worker process listens to a queue specified by QAP_WORKER_QUEUE env var.
    Deployment starts multiple worker instances at different priority levels:
    - worker-high:   QAP_WORKER_QUEUE=queue:high   (replicas=2)
    - worker-medium: QAP_WORKER_QUEUE=queue:medium  (replicas=2)
    - worker-low:    QAP_WORKER_QUEUE=queue:low     (replicas=1)
    """

    queue_name: str = os.environ.get("QAP_WORKER_QUEUE", "queue:medium")
    functions = [func(execute_run, name="execute_run", max_tries=1)]
    on_job_end = after_job_end
    cron_jobs = [
        cron(reclaim_resources, second={0}),
        cron(dequeue_waiting, second={30}),
        cron(retry_failed_archives, second={45}),
    ]

    # Redis connection is injected via startup/shutdown hooks in the worker entrypoint
    redis_settings = None  # set at runtime from qaplatform.config.Settings
