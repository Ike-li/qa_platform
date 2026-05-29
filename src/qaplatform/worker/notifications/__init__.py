"""Notification evaluation and sending for completed runs."""

from __future__ import annotations

import logging
import re
from typing import Any
from uuid import UUID

from qaplatform.infra.database.models import NotificationStatusEnum

log = logging.getLogger(__name__)

_TEMPLATE_VAR_RE = re.compile(r"{{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*}}")


def _evaluate_conditions(conditions: list[dict], run_summary: dict | None, status: str) -> bool:
    """Check whether a run matches all conditions of a notification rule.

    Conditions are dicts with ``field``, ``operator``, ``value`` keys.
    Supported fields: ``status``, ``pass_rate``, ``failed``.
    Supported operators: ``eq``, ``ne``, ``lt``, ``gt``, ``lte``, ``gte``.

    Returns True if all conditions match (or if conditions is empty).
    """
    if not conditions:
        return True

    for cond in conditions:
        field = cond.get("field")
        op = cond.get("operator", "eq")
        expected = cond.get("value")

        if field == "status":
            actual = status
        elif field == "pass_rate":
            actual = (run_summary or {}).get("pass_rate", 0.0)
            try:
                expected = float(expected)
            except (TypeError, ValueError):
                pass
        elif field == "failed":
            actual = (run_summary or {}).get("failed", 0)
            try:
                expected = int(expected)
            except (TypeError, ValueError):
                pass
        else:
            log.warning("unknown_condition_field", extra={"field": field})
            continue

        if not _compare(actual, op, expected):
            return False

    return True


def _compare(actual: Any, op: str, expected: Any) -> bool:
    try:
        if op == "eq":
            return actual == expected
        if op == "ne":
            return actual != expected
        if op == "lt":
            return actual < expected
        if op == "gt":
            return actual > expected
        if op == "lte":
            return actual <= expected
        if op == "gte":
            return actual >= expected
        return False
    except TypeError:
        return False


async def _send_channel(channel_type: str, channel_config: dict, message: str) -> None:
    """Send a notification to a single channel.

    Delegates to ChannelRouter for real delivery (email / webhook).
    Raises ``RuntimeError`` on failure so the caller can log it to
    ``NotificationLog``.
    """
    from qaplatform.worker.notifications.channels import route_channel

    log.info(
        "notification_send",
        extra={
            "channel_type": channel_type,
            "message_length": len(message),
        },
    )

    result = await route_channel(channel_type, channel_config, message)
    if not result.success:
        raise RuntimeError(result.error or "channel send failed")


def _render_message(
    template: str | None,
    *,
    run_id: UUID,
    status: str,
    summary: dict | None,
) -> str:
    values = {
        "run_id": str(run_id),
        "status": status,
        "passed": str((summary or {}).get("passed", 0)),
        "failed": str((summary or {}).get("failed", 0)),
        "total": str((summary or {}).get("total", 0)),
        "pass_rate": str((summary or {}).get("pass_rate", 0)),
    }

    if template:
        def replace(match: re.Match[str]) -> str:
            name = match.group(1)
            if name not in values:
                raise ValueError(f"unknown template variable: {name}")
            return values[name]

        return _TEMPLATE_VAR_RE.sub(replace, template)

    message = f"Run {run_id} completed with status: {status}"
    if summary:
        message += f" (passed: {summary.get('passed', 0)}, failed: {summary.get('failed', 0)})"
    return message


async def evaluate_and_notify(
    *,
    run_id: UUID,
    project_id: UUID,
    status: str,
    summary: dict | None,
    session_factory: Any,
) -> None:
    """Evaluate notification rules for a completed run and send notifications.

    Called from execute_run after the run reaches a terminal status.
    Each rule's channels are processed independently — a failure in one
    channel does not prevent others from being sent.
    """
    from qaplatform.infra.database.repositories.project_repo import (
        NotificationLogRepository,
        NotificationRuleRepository,
    )

    async with session_factory() as session:
        rule_repo = NotificationRuleRepository(session)
        log_repo = NotificationLogRepository(session)

        rules = await rule_repo.find_enabled_by_project(project_id)
        if not rules:
            return

        for rule in rules:
            if not _evaluate_conditions(rule.conditions, summary, status):
                continue

            template_error: Exception | None = None
            try:
                message = _render_message(
                    rule.template,
                    run_id=run_id,
                    status=status,
                    summary=summary,
                )
            except Exception as exc:
                message = ""
                template_error = exc

            for channel in rule.channels:
                channel_type = channel.get("type", "unknown")
                channel_config = channel.get("config", {})
                log_status = NotificationStatusEnum.SENT
                error_message = None

                existing = await log_repo.get_by_delivery(
                    run_id=run_id,
                    rule_id=rule.id,
                    channel_type=channel_type,
                )
                if existing is not None:
                    log.info(
                        "notification_log_already_exists",
                        extra={"run_id": str(run_id), "rule_id": str(rule.id)},
                    )
                    continue

                try:
                    if template_error is not None:
                        raise RuntimeError(str(template_error))
                    await _send_channel(channel_type, channel_config, message)
                except Exception as exc:
                    log_status = NotificationStatusEnum.FAILED
                    error_message = str(exc)[:500]
                    log.exception(
                        "notification_send_failed",
                        extra={
                            "run_id": str(run_id),
                            "rule_id": str(rule.id),
                            "channel_type": channel_type,
                        },
                    )

                try:
                    await log_repo.create(
                        project_id=project_id,
                        run_id=run_id,
                        rule_id=rule.id,
                        channel_type=channel_type,
                        status=log_status,
                        error_message=error_message,
                    )
                except Exception:
                    log.info(
                        "notification_log_already_exists",
                        extra={"run_id": str(run_id), "rule_id": str(rule.id)},
                    )

        await session.commit()
