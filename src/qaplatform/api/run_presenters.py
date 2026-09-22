from __future__ import annotations

from qaplatform.api.schemas import (
    ArtifactResponse,
    NotificationLogResponse,
    RunResponse,
    TestResultResponse,
)
from qaplatform.infra.database.models import (
    Artifact as ArtifactORM,
)
from qaplatform.infra.database.models import (
    NotificationLog as NotificationLogORM,
)
from qaplatform.infra.database.models import (
    Run as RunORM,
)
from qaplatform.infra.database.models import (
    RunStatusEnum,
)
from qaplatform.infra.database.models import (
    TestResult as TestResultORM,
)


def to_run_response(orm: RunORM) -> RunResponse:
    return RunResponse(
        id=orm.id,
        tenant_id=orm.tenant_id,
        project_id=orm.project_id,
        pipeline_id=orm.pipeline_id,
        pipeline_name=orm.pipeline.name if orm.pipeline is not None else "",
        environment_id=orm.environment_id,
        status=orm.status.value if isinstance(orm.status, RunStatusEnum) else orm.status,
        trigger_type=orm.trigger_type,
        priority=orm.priority,
        triggered_by=orm.triggered_by,
        git_ref=orm.git_ref,
        git_sha=orm.git_sha,
        attempt=orm.attempt,
        started_at=orm.started_at,
        finished_at=orm.finished_at,
        duration_ms=orm.duration_ms,
        summary=orm.summary,
        error_message=orm.error_message,
        created_at=orm.created_at,
        updated_at=orm.updated_at,
    )


def to_result_response(orm: TestResultORM) -> TestResultResponse:
    return TestResultResponse(
        id=orm.id,
        run_id=orm.run_id,
        suite=orm.suite,
        name=orm.name,
        status=orm.status.value if hasattr(orm.status, "value") else orm.status,
        duration_ms=orm.duration_ms,
        error_message=orm.error_message,
        stack_trace=orm.stack_trace,
        tags=orm.tags or [],
        metadata=orm.metadata_ or {},
    )


def to_artifact_response(orm: ArtifactORM) -> ArtifactResponse:
    return ArtifactResponse.model_validate(orm)


def is_allure_report_index(artifact: ArtifactORM) -> bool:
    return (
        artifact.type == "allure-report"
        and artifact.name.lower().endswith("allure-report/index.html")
    )


def to_notification_log_response(orm: NotificationLogORM) -> NotificationLogResponse:
    return NotificationLogResponse(
        id=orm.id,
        project_id=orm.project_id,
        run_id=orm.run_id,
        rule_id=orm.rule_id,
        channel_type=orm.channel_type,
        status=orm.status.value if hasattr(orm.status, "value") else orm.status,
        error_message=orm.error_message,
        sent_at=orm.sent_at,
    )
