"""Notification evaluation and sending for completed runs."""

from __future__ import annotations

import logging
import re
from collections.abc import Mapping
from typing import Any
from uuid import UUID

from sqlalchemy.exc import IntegrityError

from qaplatform.domain.services.redact import redact_sensitive_text
from qaplatform.domain.models.notification import (
    NOTIFICATION_CONDITION_FIELDS,
    NOTIFICATION_CONDITION_OPERATORS,
    normalize_notification_channel,
)
from qaplatform.infra.database.models import NotificationStatusEnum

log = logging.getLogger(__name__)

_TEMPLATE_VAR_RE = re.compile(r"{{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*}}")
_CONSECUTIVE_FAILURE_FIELDS = frozenset({"consecutive_failures", "consecutive_failed_runs"})
_NEW_FAILED_RECOVERED_FIELDS = frozenset({"new_failed", "recovered"})
_NOTIFICATION_LOG_UNIQUE_CONSTRAINT = "uq_notification_log_run_rule_channel"


def _evaluate_conditions(
    conditions: list[dict],
    run_summary: dict | None,
    status: str,
    condition_context: dict | None = None,
) -> bool:
    """Check whether a run matches the notification rule conditions.

    Conditions are dicts with ``field``, ``operator``, ``value`` keys.
    Supported fields: ``status``, ``pass_rate``, ``failed``, ``consecutive_failures``.
    Supported operators: ``eq``, ``ne``, ``lt``, ``gt``, ``lte``, ``gte``.
    A condition may also be a group: ``{"all": [...]}`` or ``{"any": [...]}``.

    Returns True if all top-level conditions match (or if conditions is empty).
    """
    if not conditions:
        return True

    return all(
        _evaluate_condition(cond, run_summary, status, condition_context or {})
        for cond in conditions
    )


def _evaluate_condition(
    cond: dict,
    run_summary: dict | None,
    status: str,
    condition_context: dict,
) -> bool:
    if not isinstance(cond, dict):
        log.warning("invalid_condition", extra={"condition": cond})
        return False

    group_keys = [key for key in ("all", "any") if key in cond]
    if len(group_keys) > 1:
        log.warning("invalid_condition_group", extra={"condition": cond})
        return False
    if group_keys:
        group_key = group_keys[0]
        children = cond.get(group_key)
        if not isinstance(children, list) or not children:
            log.warning("invalid_condition_group", extra={"condition": cond})
            return False
        if any(key not in group_keys for key in cond):
            log.warning("invalid_condition_group", extra={"condition": cond})
            return False
        if group_key == "all":
            return all(
                _evaluate_condition(child, run_summary, status, condition_context)
                for child in children
            )
        return any(
            _evaluate_condition(child, run_summary, status, condition_context)
            for child in children
        )

    field = cond.get("field")
    op = cond.get("operator", "eq")
    expected = cond.get("value")

    if field not in NOTIFICATION_CONDITION_FIELDS:
        log.warning("unknown_condition_field", extra={"field": field})
        return False
    if op not in NOTIFICATION_CONDITION_OPERATORS:
        log.warning("unknown_condition_operator", extra={"operator": op})
        return False

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
    elif field in _CONSECUTIVE_FAILURE_FIELDS:
        actual = condition_context.get("consecutive_failures")
        if actual is None:
            actual = (run_summary or {}).get("consecutive_failures", 0)
        try:
            actual = int(actual)
            expected = int(expected)
        except (TypeError, ValueError):
            pass
    elif field == "new_failed":
        actual = condition_context.get("new_failed", 0)
        try:
            actual = int(actual)
            expected = int(expected)
        except (TypeError, ValueError):
            pass
    elif field == "recovered":
        actual = condition_context.get("recovered", 0)
        try:
            actual = int(actual)
            expected = int(expected)
        except (TypeError, ValueError):
            pass
    return _compare(actual, op, expected)


def _conditions_include_fields(conditions: list[dict], fields: frozenset[str]) -> bool:
    for cond in conditions:
        if not isinstance(cond, dict):
            continue
        if cond.get("field") in fields:
            return True
        for group_key in ("all", "any"):
            children = cond.get(group_key)
            if isinstance(children, list) and _conditions_include_fields(children, fields):
                return True
    return False


async def _load_consecutive_failures(run_repo: Any, project_id: UUID, run_id: UUID) -> int:
    return await run_repo.count_consecutive_failures(
        project_id=project_id,
        run_id=run_id,
    )


async def _load_new_failed_and_recovered(
    *,
    run_repo: Any,
    test_result_repo: Any,
    project_id: UUID,
    run_id: UUID,
    pipeline_id: UUID,
) -> tuple[int, int]:
    """计算 new_failed 和 recovered 数量。

    new_failed: 本次相对同 project + 同 pipeline 上一终态 run 的新增失败数（已知 flaky 不计入）
    recovered: 上次失败本次通过的用例数
    """
    from qaplatform.infra.database.models import Run, RunStatusEnum, TestResult, TestResultStatusEnum
    from datetime import timedelta
    from sqlalchemy import select

    current_stmt = select(Run).where(
        Run.id == run_id,
        Run.project_id == project_id,
        Run.deleted_at.is_(None),
    )
    current_result = await run_repo.session.execute(current_stmt)
    current = current_result.scalar_one_or_none()
    if current is None:
        return 0, 0

    terminal_statuses = (
        RunStatusEnum.DONE,
        RunStatusEnum.FAILED,
        RunStatusEnum.CANCELLED,
        RunStatusEnum.TIMEOUT,
    )
    prior_stmt = (
        select(Run.id)
        .where(
            Run.project_id == project_id,
            Run.pipeline_id == pipeline_id,
            Run.deleted_at.is_(None),
            Run.status.in_(terminal_statuses),
            Run.created_at < current.created_at,
        )
        .order_by(Run.created_at.desc(), Run.id.desc())
        .limit(1)
    )
    prior_result = await run_repo.session.execute(prior_stmt)
    prior_run_id = prior_result.scalar_one_or_none()
    if prior_run_id is None:
        return 0, 0

    failed_statuses = (TestResultStatusEnum.FAILED, TestResultStatusEnum.ERROR)
    current_failed_stmt = select(TestResult.suite, TestResult.name).where(
        TestResult.run_id == run_id,
        TestResult.status.in_(failed_statuses),
    )
    current_failed_result = await test_result_repo.session.execute(current_failed_stmt)
    current_failed_set = set(current_failed_result.all())

    prior_failed_stmt = select(TestResult.suite, TestResult.name).where(
        TestResult.run_id == prior_run_id,
        TestResult.status.in_(failed_statuses),
    )
    prior_failed_result = await test_result_repo.session.execute(prior_failed_stmt)
    prior_failed_set = set(prior_failed_result.all())

    cutoff = current.created_at - timedelta(days=30)
    flaky_rows, _ = await test_result_repo.list_flaky_tests(
        project_id=project_id,
        cutoff=cutoff,
        min_runs=3,
        offset=0,
        limit=100_000,
    )
    flaky_keys = {(row.suite, row.name) for row in flaky_rows}

    new_failed_raw = current_failed_set - prior_failed_set
    new_failed = len(new_failed_raw - flaky_keys)

    recovered = len(prior_failed_set - current_failed_set)

    return new_failed, recovered


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
    project_name: str | None = None,
) -> str:
    values = {
        "run_id": str(run_id),
        "status": status,
        "project_name": project_name or "",
        "passed": str((summary or {}).get("passed", 0)),
        "failed": str((summary or {}).get("failed", 0)),
        "total": str((summary or {}).get("total", 0)),
        "pass_rate": str((summary or {}).get("pass_rate", 0)),
        "failed_tests": _format_failed_tests(summary),
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


def _format_failed_tests(summary: dict | None) -> str:
    failed_tests = (summary or {}).get("failed_tests") or []
    if isinstance(failed_tests, str):
        return failed_tests
    if not isinstance(failed_tests, list):
        return str(failed_tests)

    formatted: list[str] = []
    for item in failed_tests:
        if isinstance(item, dict):
            name = item.get("name") or item.get("test_name") or item.get("nodeid")
            suite = item.get("suite")
            if suite and name:
                formatted.append(f"{suite}::{name}")
            elif name:
                formatted.append(str(name))
            elif item:
                formatted.append(str(item))
        elif item is not None:
            formatted.append(str(item))
    return ", ".join(formatted)


def _uses_template_variable(template: str | None, variable: str) -> bool:
    if not template:
        return False
    return variable in _TEMPLATE_VAR_RE.findall(template)


def _iter_config_values(value: Any):
    if isinstance(value, Mapping):
        for nested in value.values():
            yield from _iter_config_values(nested)
        return
    if isinstance(value, (list, tuple, set, frozenset)):
        for nested in value:
            yield from _iter_config_values(nested)
        return
    yield value


def _notification_error_message(exc: Exception, channel_config: dict) -> str:
    return redact_sensitive_text(str(exc), _iter_config_values(channel_config))[:500]


def _is_duplicate_notification_log_error(exc: IntegrityError) -> bool:
    orig = getattr(exc, "orig", None)
    diag = getattr(orig, "diag", None)
    if getattr(diag, "constraint_name", None) == _NOTIFICATION_LOG_UNIQUE_CONSTRAINT:
        return True
    return _NOTIFICATION_LOG_UNIQUE_CONSTRAINT in str(exc)


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
        ProjectRepository,
    )
    from qaplatform.infra.database.repositories.run_repo import RunRepository
    from qaplatform.infra.database.repositories.test_result_repo import TestResultRepository

    async with session_factory() as session:
        rule_repo = NotificationRuleRepository(session)
        log_repo = NotificationLogRepository(session)
        project_repo = ProjectRepository(session)
        run_repo = RunRepository(session)
        test_result_repo = TestResultRepository(session)
        project_loaded = False
        project_name = ""

        rules = await rule_repo.find_enabled_by_project(project_id)
        if not rules:
            return
        condition_context: dict[str, int] = {}
        if any(
            _conditions_include_fields(rule.conditions, _CONSECUTIVE_FAILURE_FIELDS)
            for rule in rules
        ):
            consecutive_failures = await _load_consecutive_failures(
                run_repo, project_id, run_id
            )
            condition_context["consecutive_failures"] = consecutive_failures
            condition_context["consecutive_failed_runs"] = consecutive_failures

        if any(
            _conditions_include_fields(rule.conditions, _NEW_FAILED_RECOVERED_FIELDS)
            for rule in rules
        ):
            from qaplatform.infra.database.models import Run
            from sqlalchemy import select

            run_stmt = select(Run.pipeline_id).where(Run.id == run_id)
            run_result = await session.execute(run_stmt)
            pipeline_id = run_result.scalar_one_or_none()
            if pipeline_id is not None:
                new_failed, recovered = await _load_new_failed_and_recovered(
                    run_repo=run_repo,
                    test_result_repo=test_result_repo,
                    project_id=project_id,
                    run_id=run_id,
                    pipeline_id=pipeline_id,
                )
                condition_context["new_failed"] = new_failed
                condition_context["recovered"] = recovered

        async def load_project_name() -> str:
            nonlocal project_loaded, project_name
            if not project_loaded:
                project = await project_repo.get_by_id(project_id)
                project_name = getattr(project, "name", "") if project is not None else ""
                project_loaded = True
            return project_name

        for rule in rules:
            if not _evaluate_conditions(rule.conditions, summary, status, condition_context):
                continue

            for channel in rule.channels:
                normalized_channel = normalize_notification_channel(channel)
                channel_type = normalized_channel["type"]
                channel_config = normalized_channel["config"]
                template = normalized_channel.get("template", rule.template)
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
                    render_project_name = ""
                    if _uses_template_variable(template, "project_name"):
                        render_project_name = await load_project_name()
                    message = _render_message(
                        template,
                        run_id=run_id,
                        status=status,
                        summary=summary,
                        project_name=render_project_name,
                    )
                    await _send_channel(channel_type, channel_config, message)
                except Exception as exc:
                    log_status = NotificationStatusEnum.FAILED
                    error_message = _notification_error_message(exc, channel_config)
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
                except IntegrityError as exc:
                    if not _is_duplicate_notification_log_error(exc):
                        raise
                    log.info(
                        "notification_log_already_exists",
                        extra={"run_id": str(run_id), "rule_id": str(rule.id)},
                    )

        await session.commit()
