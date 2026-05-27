"""Notification delivery integration tests with real DB rules/logs."""

from __future__ import annotations

import os
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from qaplatform.infra.database.models import (
    NotificationLog,
    NotificationRule,
    NotificationStatusEnum,
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
    assert "failed=2" in mock_send.await_args.args[2]

    logs = await _logs_for_run(integration_db_session, run_id)
    assert len(logs) == 1
    assert logs[0].rule_id == matching.id
    assert logs[0].status == NotificationStatusEnum.SENT
    assert logs[0].error_message is None


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
    assert len(logs) == 1
    assert logs[0].rule_id == rule.id
    assert logs[0].status == NotificationStatusEnum.FAILED
    assert "unknown template variable" in (logs[0].error_message or "")


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
    assert len(logs) == 1
    assert logs[0].rule_id == rule.id
    assert logs[0].channel_type == "email"
    assert logs[0].status == NotificationStatusEnum.FAILED
    assert "smtp unavailable" in (logs[0].error_message or "")
