"""Notification delivery integration tests with real DB rules/logs."""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from qaplatform.infra.database.models import (
    NotificationLog,
    NotificationRule,
    NotificationStatusEnum,
    Run,
    RunStatusEnum,
)
from qaplatform.worker.notifications import evaluate_and_notify

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_INTEGRATION_TESTS") != "1",
    reason="set RUN_INTEGRATION_TESTS=1 to run integration tests",
)


def _session_factory(engine):
    return async_sessionmaker(engine, expire_on_commit=False)


async def _logs_for_run(session, run_id):
    result = await session.execute(
        select(NotificationLog)
        .where(NotificationLog.run_id == run_id)
        .order_by(NotificationLog.sent_at.asc())
    )
    return list(result.scalars().all())


def _log_projection(log: NotificationLog) -> dict:
    return {
        "run_id": str(log.run_id),
        "rule_id": str(log.rule_id),
        "channel_type": log.channel_type,
        "status": log.status.value,
        "error_message": log.error_message,
    }


async def _add_rule(
    session,
    *,
    project_id,
    name: str,
    conditions: list[dict],
    channels: list[dict],
    template: str | None = None,
    enabled: bool = True,
):
    rule = NotificationRule(
        project_id=project_id,
        name=name,
        enabled=enabled,
        conditions=conditions,
        channels=channels,
        template=template,
    )
    session.add(rule)
    await session.flush()
    return rule


@pytest.mark.asyncio
async def test_api_created_notification_rule_uses_deliverable_channel_config(
    integration_client,
    integration_db_engine,
    integration_db_session,
    seed_run,
):
    project_id = seed_run["project"].id
    run_id = seed_run["run"].id
    webhook_url = f"https://example.com/api-created/{uuid4().hex}"

    create_resp = await integration_client.post(
        f"/api/v1/projects/{project_id}/notification-rules",
        json={
            "name": "api-created-legacy-webhook",
            "conditions": [{"field": "status", "operator": "eq", "value": "failed"}],
            "channels": [{"type": "webhook", "webhook_url": webhook_url}],
            "template": "Run {{run_id}}",
        },
    )
    assert create_resp.status_code == 201, create_resp.text
    created = create_resp.json()
    assert created["channels"] == [
        {"type": "webhook", "config": {"url": webhook_url}, "template": None}
    ]

    mock_send = AsyncMock()
    with patch("qaplatform.worker.notifications._send_channel", mock_send):
        await evaluate_and_notify(
            run_id=run_id,
            project_id=project_id,
            status="failed",
            summary={"passed": 7, "failed": 2, "total": 9, "pass_rate": 0.78},
            session_factory=_session_factory(integration_db_engine),
        )

    mock_send.assert_awaited_once_with("webhook", {"url": webhook_url}, f"Run {run_id}")
    logs = await _logs_for_run(integration_db_session, run_id)
    assert [_log_projection(log) for log in logs] == [
        {
            "run_id": str(run_id),
            "rule_id": created["id"],
            "channel_type": "webhook",
            "status": NotificationStatusEnum.SENT.value,
            "error_message": None,
        }
    ]


@pytest.mark.asyncio
async def test_notification_delivery_selects_real_db_rules_and_is_idempotent(
    integration_db_engine,
    integration_db_session,
    seed_run,
):
    project_id = seed_run["project"].id
    run_id = seed_run["run"].id
    matching = await _add_rule(
        integration_db_session,
        project_id=project_id,
        name="failed-runs",
        conditions=[{"field": "status", "operator": "eq", "value": "failed"}],
        channels=[{"type": "webhook", "config": {"url": "https://example.com/hook"}}],
        template="Run {{run_id}} failed={{failed}}",
    )
    await _add_rule(
        integration_db_session,
        project_id=project_id,
        name="done-runs",
        conditions=[{"field": "status", "operator": "eq", "value": "done"}],
        channels=[{"type": "webhook", "config": {"url": "https://example.com/skip"}}],
    )
    await _add_rule(
        integration_db_session,
        project_id=project_id,
        name="disabled",
        enabled=False,
        conditions=[],
        channels=[{"type": "webhook", "config": {"url": "https://example.com/off"}}],
    )
    await integration_db_session.commit()

    mock_send = AsyncMock()
    with patch("qaplatform.worker.notifications._send_channel", mock_send):
        await evaluate_and_notify(
            run_id=run_id,
            project_id=project_id,
            status="failed",
            summary={"passed": 7, "failed": 2, "total": 9, "pass_rate": 0.78},
            session_factory=_session_factory(integration_db_engine),
        )
        await evaluate_and_notify(
            run_id=run_id,
            project_id=project_id,
            status="failed",
            summary={"passed": 7, "failed": 2, "total": 9, "pass_rate": 0.78},
            session_factory=_session_factory(integration_db_engine),
        )

    mock_send.assert_awaited_once()
    sent_channel, sent_config, sent_message = mock_send.await_args.args
    assert sent_channel == "webhook"
    assert sent_config == {"url": "https://example.com/hook"}
    assert sent_message == f"Run {run_id} failed=2"

    logs = await _logs_for_run(integration_db_session, run_id)
    assert [_log_projection(log) for log in logs] == [
        {
            "run_id": str(run_id),
            "rule_id": str(matching.id),
            "channel_type": "webhook",
            "status": NotificationStatusEnum.SENT.value,
            "error_message": None,
        }
    ]


@pytest.mark.asyncio
async def test_notification_delivery_uses_channel_template_and_project_name(
    integration_db_engine,
    integration_db_session,
    seed_run,
):
    project_id = seed_run["project"].id
    run_id = seed_run["run"].id
    rule = await _add_rule(
        integration_db_session,
        project_id=project_id,
        name="channel-template",
        conditions=[],
        channels=[
            {
                "type": "webhook",
                "config": {"url": "https://example.com/hook"},
                "template": "Project {{project_name}} run {{run_id}} failed={{failed_tests}}",
            }
        ],
        template="Rule {{status}}",
    )
    await integration_db_session.commit()

    mock_send = AsyncMock()
    with patch("qaplatform.worker.notifications._send_channel", mock_send):
        await evaluate_and_notify(
            run_id=run_id,
            project_id=project_id,
            status="failed",
            summary={
                "passed": 7,
                "failed": 2,
                "failed_tests": [
                    "test_api",
                    {"suite": "ui", "name": "test_login"},
                ],
            },
            session_factory=_session_factory(integration_db_engine),
        )

    mock_send.assert_awaited_once_with(
        "webhook",
        {"url": "https://example.com/hook"},
        f"Project {seed_run['project'].name} run {run_id} failed=test_api, ui::test_login",
    )

    logs = await _logs_for_run(integration_db_session, run_id)
    assert [_log_projection(log) for log in logs] == [
        {
            "run_id": str(run_id),
            "rule_id": str(rule.id),
            "channel_type": "webhook",
            "status": NotificationStatusEnum.SENT.value,
            "error_message": None,
        }
    ]


@pytest.mark.asyncio
async def test_notification_delivery_supports_or_and_consecutive_failures(
    integration_db_engine,
    integration_db_session,
    seed_run,
):
    now = datetime.now(timezone.utc)
    project_id = seed_run["project"].id
    run_id = seed_run["run"].id

    older_done = Run(
        tenant_id=seed_run["tenant"].id,
        project_id=project_id,
        pipeline_id=seed_run["pipeline"].id,
        environment_id=seed_run["environment"].id,
        status=RunStatusEnum.DONE,
        trigger_type="manual",
        priority=1,
        triggered_by=seed_run["user"].id,
        git_ref="main",
        attempt=1,
        chain_depth=0,
        metadata_={},
        created_at=now - timedelta(minutes=3),
        finished_at=now - timedelta(minutes=3),
    )
    failed_runs = [
        Run(
            tenant_id=seed_run["tenant"].id,
            project_id=project_id,
            pipeline_id=seed_run["pipeline"].id,
            environment_id=seed_run["environment"].id,
            status=RunStatusEnum.FAILED,
            trigger_type="manual",
            priority=1,
            triggered_by=seed_run["user"].id,
            git_ref="main",
            attempt=1,
            chain_depth=0,
            metadata_={},
            created_at=now - timedelta(minutes=offset),
            finished_at=now - timedelta(minutes=offset),
        )
        for offset in (2, 1)
    ]
    current_run = seed_run["run"]
    current_run.status = RunStatusEnum.FAILED
    current_run.created_at = now
    current_run.finished_at = now
    integration_db_session.add_all([older_done, *failed_runs])

    matching = await _add_rule(
        integration_db_session,
        project_id=project_id,
        name="or-consecutive-failures",
        conditions=[
            {"field": "status", "operator": "eq", "value": "failed"},
            {
                "any": [
                    {"field": "pass_rate", "operator": "lt", "value": "0.5"},
                    {"field": "consecutive_failures", "operator": "gte", "value": "3"},
                ]
            },
        ],
        channels=[{"type": "webhook", "config": {"url": "https://example.com/hook"}}],
        template="Run {{run_id}}",
    )
    await _add_rule(
        integration_db_session,
        project_id=project_id,
        name="too-many-failures-required",
        conditions=[
            {"field": "status", "operator": "eq", "value": "failed"},
            {"field": "consecutive_failures", "operator": "gte", "value": "4"},
        ],
        channels=[{"type": "webhook", "config": {"url": "https://example.com/skip"}}],
    )
    await integration_db_session.commit()

    mock_send = AsyncMock()
    with patch("qaplatform.worker.notifications._send_channel", mock_send):
        await evaluate_and_notify(
            run_id=run_id,
            project_id=project_id,
            status="failed",
            summary={"passed": 9, "failed": 1, "total": 10, "pass_rate": 0.9},
            session_factory=_session_factory(integration_db_engine),
        )

    mock_send.assert_awaited_once_with(
        "webhook",
        {"url": "https://example.com/hook"},
        f"Run {run_id}",
    )
    logs = await _logs_for_run(integration_db_session, run_id)
    assert [_log_projection(log) for log in logs] == [
        {
            "run_id": str(run_id),
            "rule_id": str(matching.id),
            "channel_type": "webhook",
            "status": NotificationStatusEnum.SENT.value,
            "error_message": None,
        }
    ]


@pytest.mark.asyncio
async def test_notification_delivery_records_template_render_failure(
    integration_db_engine,
    integration_db_session,
    seed_run,
):
    project_id = seed_run["project"].id
    run_id = seed_run["run"].id
    rule = await _add_rule(
        integration_db_session,
        project_id=project_id,
        name="bad-template",
        conditions=[],
        channels=[{"type": "webhook", "config": {"url": "https://example.com/hook"}}],
        template="Run {{run_id}} missing={{unknown}}",
    )
    await integration_db_session.commit()

    mock_send = AsyncMock()
    with patch("qaplatform.worker.notifications._send_channel", mock_send):
        await evaluate_and_notify(
            run_id=run_id,
            project_id=project_id,
            status="done",
            summary={"passed": 1, "failed": 0},
            session_factory=_session_factory(integration_db_engine),
        )

    mock_send.assert_not_awaited()
    logs = await _logs_for_run(integration_db_session, run_id)
    assert [_log_projection(log) for log in logs] == [
        {
            "run_id": str(run_id),
            "rule_id": str(rule.id),
            "channel_type": "webhook",
            "status": NotificationStatusEnum.FAILED.value,
            "error_message": "unknown template variable: unknown",
        }
    ]


@pytest.mark.asyncio
async def test_notification_delivery_does_not_fire_invalid_historical_conditions(
    integration_db_engine,
    integration_db_session,
    seed_run,
):
    project_id = seed_run["project"].id
    run_id = seed_run["run"].id
    await _add_rule(
        integration_db_session,
        project_id=project_id,
        name="invalid-historical-condition",
        conditions=[{"field": "statuz", "operator": "eq", "value": "failed"}],
        channels=[{"type": "webhook", "config": {"url": "https://example.com/hook"}}],
    )
    await integration_db_session.commit()

    mock_send = AsyncMock()
    with patch("qaplatform.worker.notifications._send_channel", mock_send):
        await evaluate_and_notify(
            run_id=run_id,
            project_id=project_id,
            status="failed",
            summary={"passed": 0, "failed": 1},
            session_factory=_session_factory(integration_db_engine),
        )

    mock_send.assert_not_awaited()
    assert await _logs_for_run(integration_db_session, run_id) == []


@pytest.mark.asyncio
async def test_notification_delivery_records_channel_send_failure(
    integration_db_engine,
    integration_db_session,
    seed_run,
):
    project_id = seed_run["project"].id
    run_id = seed_run["run"].id
    rule = await _add_rule(
        integration_db_session,
        project_id=project_id,
        name="send-failure",
        conditions=[],
        channels=[{"type": "email", "config": {"to": "qa@example.com"}}],
    )
    await integration_db_session.commit()

    with patch(
        "qaplatform.worker.notifications._send_channel",
        AsyncMock(side_effect=RuntimeError("smtp unavailable")),
    ):
        await evaluate_and_notify(
            run_id=run_id,
            project_id=project_id,
            status="failed",
            summary={"passed": 0, "failed": 1},
            session_factory=_session_factory(integration_db_engine),
        )

    logs = await _logs_for_run(integration_db_session, run_id)
    assert [_log_projection(log) for log in logs] == [
        {
            "run_id": str(run_id),
            "rule_id": str(rule.id),
            "channel_type": "email",
            "status": NotificationStatusEnum.FAILED.value,
            "error_message": "smtp unavailable",
        }
    ]
