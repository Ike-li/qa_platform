from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

from qaplatform.api.run_presenters import (
    is_allure_report_index,
    to_artifact_response,
    to_notification_log_response,
    to_result_response,
    to_run_response,
)
from qaplatform.infra.database.models import (
    RunStatusEnum,
)
from qaplatform.infra.database.models import (
    TestResultStatusEnum as ResultStatusEnum,
)


def test_to_run_response_normalizes_status_and_pipeline_name():
    now = datetime(2026, 6, 1, tzinfo=timezone.utc)
    run = SimpleNamespace(
        id=uuid4(),
        tenant_id=uuid4(),
        project_id=uuid4(),
        pipeline_id=uuid4(),
        pipeline=SimpleNamespace(name="smoke"),
        environment_id=uuid4(),
        status=RunStatusEnum.RUNNING,
        trigger_type="manual",
        priority=1,
        triggered_by=uuid4(),
        git_ref="main",
        git_sha="a" * 40,
        attempt=2,
        started_at=now,
        finished_at=None,
        duration_ms=None,
        summary={"passed": 3},
        error_message=None,
        created_at=now,
        updated_at=now,
    )

    response = to_run_response(run)

    assert response.status == "running"
    assert response.pipeline_name == "smoke"
    assert response.summary == {"passed": 3}


def test_to_result_response_defaults_optional_collections():
    result = SimpleNamespace(
        id=uuid4(),
        run_id=uuid4(),
        suite="api",
        name="test_health",
        status=ResultStatusEnum.PASSED,
        duration_ms=12,
        error_message=None,
        stack_trace=None,
        tags=None,
        metadata_=None,
    )

    response = to_result_response(result)

    assert response.status == "passed"
    assert response.tags == []
    assert response.metadata == {}


def test_to_artifact_response_and_allure_index_detection():
    now = datetime(2026, 6, 1, tzinfo=timezone.utc)
    artifact = SimpleNamespace(
        id=uuid4(),
        run_id=uuid4(),
        type="allure-report",
        name="reports/ALLURE-REPORT/index.html",
        storage_path="s3://bucket/reports/index.html",
        size_bytes=123,
        mime_type="text/html",
        expires_at=None,
        created_at=now,
    )

    response = to_artifact_response(artifact)

    assert is_allure_report_index(artifact) is True
    assert response.name == artifact.name
    assert response.mime_type == "text/html"


def test_to_notification_log_response_normalizes_enum_like_status():
    now = datetime(2026, 6, 1, tzinfo=timezone.utc)
    notification = SimpleNamespace(
        id=uuid4(),
        project_id=uuid4(),
        run_id=uuid4(),
        rule_id=uuid4(),
        channel_type="slack",
        status=SimpleNamespace(value="sent"),
        error_message=None,
        sent_at=now,
    )

    response = to_notification_log_response(notification)

    assert response.status == "sent"
    assert response.channel_type == "slack"
