"""Tests for notification evaluation and sending logic."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, call, patch
from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError

from qaplatform.worker.notifications import (
    _compare,
    _evaluate_conditions,
    evaluate_and_notify,
)


# --------------------------------------------------------------------------- #
# _compare unit tests
# --------------------------------------------------------------------------- #


class TestCompare:
    def test_eq(self):
        assert _compare("failed", "eq", "failed") is True
        assert _compare("failed", "eq", "done") is False

    def test_ne(self):
        assert _compare("failed", "ne", "done") is True
        assert _compare("failed", "ne", "failed") is False

    def test_lt(self):
        assert _compare(0.5, "lt", 0.8) is True
        assert _compare(0.8, "lt", 0.5) is False

    def test_gt(self):
        assert _compare(0.8, "gt", 0.5) is True
        assert _compare(0.5, "gt", 0.8) is False

    def test_lte(self):
        assert _compare(0.5, "lte", 0.5) is True
        assert _compare(0.5, "lte", 0.8) is True
        assert _compare(0.8, "lte", 0.5) is False

    def test_gte(self):
        assert _compare(0.5, "gte", 0.5) is True
        assert _compare(0.8, "gte", 0.5) is True
        assert _compare(0.5, "gte", 0.8) is False

    def test_unknown_operator(self):
        assert _compare("x", "like", "x") is False


# --------------------------------------------------------------------------- #
# _evaluate_conditions unit tests
# --------------------------------------------------------------------------- #


class TestEvaluateConditions:
    def test_empty_conditions_always_match(self):
        assert _evaluate_conditions([], {}, "done") is True

    def test_status_eq_match(self):
        conditions = [{"field": "status", "operator": "eq", "value": "failed"}]
        assert _evaluate_conditions(conditions, {}, "failed") is True

    def test_status_eq_no_match(self):
        conditions = [{"field": "status", "operator": "eq", "value": "failed"}]
        assert _evaluate_conditions(conditions, {}, "done") is False

    def test_pass_rate_gte(self):
        conditions = [{"field": "pass_rate", "operator": "gte", "value": 0.8}]
        assert _evaluate_conditions(conditions, {"pass_rate": 0.9}, "done") is True
        assert _evaluate_conditions(conditions, {"pass_rate": 0.5}, "done") is False

    def test_failed_gt(self):
        conditions = [{"field": "failed", "operator": "gt", "value": 0}]
        assert _evaluate_conditions(conditions, {"failed": 3}, "done") is True
        assert _evaluate_conditions(conditions, {"failed": 0}, "done") is False

    def test_multiple_conditions_all_must_match(self):
        conditions = [
            {"field": "status", "operator": "eq", "value": "failed"},
            {"field": "failed", "operator": "gt", "value": 5},
        ]
        assert _evaluate_conditions(conditions, {"failed": 10}, "failed") is True
        assert _evaluate_conditions(conditions, {"failed": 3}, "failed") is False
        assert _evaluate_conditions(conditions, {"failed": 10}, "done") is False

    def test_any_condition_group_matches_when_one_child_matches(self):
        conditions = [
            {"field": "status", "operator": "eq", "value": "failed"},
            {
                "any": [
                    {"field": "pass_rate", "operator": "lt", "value": 0.5},
                    {"field": "failed", "operator": "gte", "value": 3},
                ]
            },
        ]
        assert _evaluate_conditions(conditions, {"pass_rate": 0.8, "failed": 3}, "failed") is True
        assert _evaluate_conditions(conditions, {"pass_rate": 0.8, "failed": 1}, "failed") is False

    def test_nested_all_condition_group_requires_every_child(self):
        conditions = [
            {
                "all": [
                    {"field": "status", "operator": "eq", "value": "failed"},
                    {"field": "pass_rate", "operator": "lt", "value": "0.8"},
                ]
            }
        ]
        assert _evaluate_conditions(conditions, {"pass_rate": 0.5}, "failed") is True
        assert _evaluate_conditions(conditions, {"pass_rate": 0.9}, "failed") is False

    def test_consecutive_failures_condition_uses_context(self):
        conditions = [
            {"field": "consecutive_failures", "operator": "gte", "value": "3"}
        ]
        assert (
            _evaluate_conditions(
                conditions,
                {"consecutive_failures": 1},
                "failed",
                {"consecutive_failures": 3},
            )
            is True
        )
        assert (
            _evaluate_conditions(
                conditions,
                {"consecutive_failures": 3},
                "failed",
                {"consecutive_failures": 2},
            )
            is False
        )

    def test_consecutive_failed_runs_alias_keeps_historical_rules_working(self):
        conditions = [
            {"field": "consecutive_failed_runs", "operator": "gte", "value": "3"}
        ]

        assert (
            _evaluate_conditions(
                conditions,
                {},
                "failed",
                {"consecutive_failures": 3, "consecutive_failed_runs": 3},
            )
            is True
        )

    def test_unknown_field_does_not_match(self):
        conditions = [{"field": "unknown", "operator": "eq", "value": "x"}]
        assert _evaluate_conditions(conditions, {}, "done") is False

    def test_invalid_condition_shapes_do_not_match(self):
        invalid_conditions = [
            ["not-an-object"],
            [{"all": []}],
            [{"all": [{"field": "status", "operator": "eq", "value": "failed"}], "field": "status"}],
            [{"field": "status", "operator": "like", "value": "fail%"}],
        ]
        for conditions in invalid_conditions:
            assert _evaluate_conditions(conditions, {}, "failed") is False

    def test_none_summary_uses_defaults(self):
        conditions = [{"field": "pass_rate", "operator": "eq", "value": 0.0}]
        assert _evaluate_conditions(conditions, None, "done") is True


# --------------------------------------------------------------------------- #
# evaluate_and_notify integration tests
# --------------------------------------------------------------------------- #


class TestEvaluateAndNotify:
    def _assert_delivery_log(self, log_repo, expected):
        log_repo.create.assert_awaited_once()
        call_kwargs = log_repo.create.await_args.kwargs
        status = call_kwargs["status"]
        assert call_kwargs == {**expected, "status": status}
        assert status.value == expected["status"]
        return call_kwargs

    @pytest.mark.asyncio
    async def test_no_rules_no_notifications(self):
        project_id = uuid4()
        session = AsyncMock()
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock(return_value=False)
        sf = MagicMock(return_value=session)

        rule_repo = AsyncMock()
        rule_repo.find_enabled_by_project = AsyncMock(return_value=[])
        log_repo = AsyncMock()
        log_repo.get_by_delivery = AsyncMock(return_value=None)

        with (
            patch("qaplatform.infra.database.repositories.project_repo.NotificationRuleRepository", return_value=rule_repo),
            patch("qaplatform.infra.database.repositories.project_repo.NotificationLogRepository", return_value=log_repo),
        ):
            await evaluate_and_notify(
                run_id=uuid4(),
                project_id=project_id,
                status="done",
                summary={},
                session_factory=sf,
            )

        rule_repo.find_enabled_by_project.assert_awaited_once_with(project_id)
        log_repo.get_by_delivery.assert_not_awaited()
        log_repo.create.assert_not_awaited()
        session.commit.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_matching_rule_sends_notification(self):
        run_id = uuid4()
        project_id = uuid4()
        rule = MagicMock()
        rule.id = uuid4()
        rule.conditions = [{"field": "status", "operator": "eq", "value": "failed"}]
        rule.channels = [{"type": "webhook", "webhook_url": "https://example.com"}]
        rule.template = None

        session = AsyncMock()
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock(return_value=False)
        sf = MagicMock(return_value=session)

        rule_repo = AsyncMock()
        rule_repo.find_enabled_by_project = AsyncMock(return_value=[rule])
        log_repo = AsyncMock()
        log_repo.get_by_delivery = AsyncMock(return_value=None)

        mock_send = AsyncMock()
        with (
            patch("qaplatform.infra.database.repositories.project_repo.NotificationRuleRepository", return_value=rule_repo),
            patch("qaplatform.infra.database.repositories.project_repo.NotificationLogRepository", return_value=log_repo),
            patch("qaplatform.worker.notifications._send_channel", mock_send),
        ):
            await evaluate_and_notify(
                run_id=run_id,
                project_id=project_id,
                status="failed",
                summary={"passed": 5, "failed": 3},
                session_factory=sf,
            )

        expected_message = f"Run {run_id} completed with status: failed (passed: 5, failed: 3)"
        rule_repo.find_enabled_by_project.assert_awaited_once_with(project_id)
        log_repo.get_by_delivery.assert_awaited_once_with(
            run_id=run_id,
            rule_id=rule.id,
            channel_type="webhook",
        )
        mock_send.assert_awaited_once_with(
            "webhook",
            {"url": "https://example.com"},
            expected_message,
        )
        self._assert_delivery_log(
            log_repo,
            {
                "project_id": project_id,
                "run_id": run_id,
                "rule_id": rule.id,
                "channel_type": "webhook",
                "status": "sent",
                "error_message": None,
            },
        )
        session.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_template_rendering(self):
        run_id = uuid4()
        project_id = uuid4()
        rule = MagicMock()
        rule.id = uuid4()
        rule.conditions = []
        rule.template = "Run {{run_id}} status={{status}} passed={{passed}} failed={{failed}}"
        rule.channels = [{"type": "webhook", "config": {"url": "https://example.com"}}]

        session = AsyncMock()
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock(return_value=False)
        sf = MagicMock(return_value=session)

        rule_repo = AsyncMock()
        rule_repo.find_enabled_by_project = AsyncMock(return_value=[rule])
        log_repo = AsyncMock()
        log_repo.get_by_delivery = AsyncMock(return_value=None)

        mock_send = AsyncMock()
        with (
            patch("qaplatform.infra.database.repositories.project_repo.NotificationRuleRepository", return_value=rule_repo),
            patch("qaplatform.infra.database.repositories.project_repo.NotificationLogRepository", return_value=log_repo),
            patch("qaplatform.worker.notifications._send_channel", mock_send),
        ):
            await evaluate_and_notify(
                run_id=run_id,
                project_id=project_id,
                status="failed",
                summary={"passed": 5, "failed": 3},
                session_factory=sf,
            )

        expected_message = f"Run {run_id} status=failed passed=5 failed=3"
        rule_repo.find_enabled_by_project.assert_awaited_once_with(project_id)
        log_repo.get_by_delivery.assert_awaited_once_with(
            run_id=run_id,
            rule_id=rule.id,
            channel_type="webhook",
        )
        mock_send.assert_awaited_once_with(
            "webhook",
            {"url": "https://example.com"},
            expected_message,
        )
        self._assert_delivery_log(
            log_repo,
            {
                "project_id": project_id,
                "run_id": run_id,
                "rule_id": rule.id,
                "channel_type": "webhook",
                "status": "sent",
                "error_message": None,
            },
        )
        session.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_channel_template_overrides_rule_template_and_loads_project_name(self):
        run_id = uuid4()
        project_id = uuid4()
        rule = MagicMock()
        rule.id = uuid4()
        rule.conditions = []
        rule.template = "Rule {{project_name}} status={{status}}"
        rule.channels = [
            {
                "type": "webhook",
                "config": {"url": "https://example.com"},
                "template": "Webhook {{project_name}} failed={{failed_tests}}",
            },
            {"type": "email", "config": {"to": "qa@example.com"}},
        ]

        session = AsyncMock()
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock(return_value=False)
        sf = MagicMock(return_value=session)

        rule_repo = AsyncMock()
        rule_repo.find_enabled_by_project = AsyncMock(return_value=[rule])
        log_repo = AsyncMock()
        log_repo.get_by_delivery = AsyncMock(return_value=None)
        project = MagicMock()
        project.name = "QA Platform"
        project_repo = AsyncMock()
        project_repo.get_by_id = AsyncMock(return_value=project)
        mock_send = AsyncMock()

        with (
            patch("qaplatform.infra.database.repositories.project_repo.NotificationRuleRepository", return_value=rule_repo),
            patch("qaplatform.infra.database.repositories.project_repo.NotificationLogRepository", return_value=log_repo),
            patch("qaplatform.infra.database.repositories.project_repo.ProjectRepository", return_value=project_repo),
            patch("qaplatform.worker.notifications._send_channel", mock_send),
        ):
            await evaluate_and_notify(
                run_id=run_id,
                project_id=project_id,
                status="failed",
                summary={
                    "passed": 5,
                    "failed": 2,
                    "failed_tests": [
                        {"suite": "api", "name": "test_login"},
                        "test_checkout",
                    ],
                },
                session_factory=sf,
            )

        project_repo.get_by_id.assert_awaited_once_with(project_id)
        assert mock_send.await_args_list == [
            call(
                "webhook",
                {"url": "https://example.com"},
                "Webhook QA Platform failed=api::test_login, test_checkout",
            ),
            call(
                "email",
                {"to_addresses": ["qa@example.com"]},
                "Rule QA Platform status=failed",
            ),
        ]
        assert [
            {
                "project_id": create_call.kwargs["project_id"],
                "run_id": create_call.kwargs["run_id"],
                "rule_id": create_call.kwargs["rule_id"],
                "channel_type": create_call.kwargs["channel_type"],
                "status": create_call.kwargs["status"].value,
                "error_message": create_call.kwargs["error_message"],
            }
            for create_call in log_repo.create.await_args_list
        ] == [
            {
                "project_id": project_id,
                "run_id": run_id,
                "rule_id": rule.id,
                "channel_type": "webhook",
                "status": "sent",
                "error_message": None,
            },
            {
                "project_id": project_id,
                "run_id": run_id,
                "rule_id": rule.id,
                "channel_type": "email",
                "status": "sent",
                "error_message": None,
            },
        ]

    @pytest.mark.asyncio
    async def test_project_name_is_not_loaded_when_templates_do_not_reference_it(self):
        run_id = uuid4()
        project_id = uuid4()
        rule = MagicMock()
        rule.id = uuid4()
        rule.conditions = []
        rule.template = "Run {{run_id}} status={{status}}"
        rule.channels = [
            {
                "type": "webhook",
                "config": {"url": "https://example.com"},
                "template": "Webhook failed={{failed}}",
            },
            {"type": "email", "config": {"to": "qa@example.com"}},
        ]

        session = AsyncMock()
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock(return_value=False)
        sf = MagicMock(return_value=session)

        rule_repo = AsyncMock()
        rule_repo.find_enabled_by_project = AsyncMock(return_value=[rule])
        log_repo = AsyncMock()
        log_repo.get_by_delivery = AsyncMock(return_value=None)
        project_repo = AsyncMock()
        project_repo.get_by_id = AsyncMock(
            side_effect=AssertionError("project lookup should stay lazy")
        )
        mock_send = AsyncMock()

        with (
            patch("qaplatform.infra.database.repositories.project_repo.NotificationRuleRepository", return_value=rule_repo),
            patch("qaplatform.infra.database.repositories.project_repo.NotificationLogRepository", return_value=log_repo),
            patch("qaplatform.infra.database.repositories.project_repo.ProjectRepository", return_value=project_repo),
            patch("qaplatform.worker.notifications._send_channel", mock_send),
        ):
            await evaluate_and_notify(
                run_id=run_id,
                project_id=project_id,
                status="failed",
                summary={"passed": 5, "failed": 2},
                session_factory=sf,
            )

        project_repo.get_by_id.assert_not_awaited()
        assert mock_send.await_args_list == [
            call(
                "webhook",
                {"url": "https://example.com"},
                "Webhook failed=2",
            ),
            call(
                "email",
                {"to_addresses": ["qa@example.com"]},
                f"Run {run_id} status=failed",
            ),
        ]
        assert [
            {
                "project_id": create_call.kwargs["project_id"],
                "run_id": create_call.kwargs["run_id"],
                "rule_id": create_call.kwargs["rule_id"],
                "channel_type": create_call.kwargs["channel_type"],
                "status": create_call.kwargs["status"].value,
                "error_message": create_call.kwargs["error_message"],
            }
            for create_call in log_repo.create.await_args_list
        ] == [
            {
                "project_id": project_id,
                "run_id": run_id,
                "rule_id": rule.id,
                "channel_type": "webhook",
                "status": "sent",
                "error_message": None,
            },
            {
                "project_id": project_id,
                "run_id": run_id,
                "rule_id": rule.id,
                "channel_type": "email",
                "status": "sent",
                "error_message": None,
            },
        ]
        session.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_numeric_coercion_in_conditions(self):
        project_id = uuid4()
        rule = MagicMock()
        rule.id = uuid4()
        rule.conditions = [
            {"field": "pass_rate", "operator": "gte", "value": "0.8"},
            {"field": "failed", "operator": "gt", "value": "0"},
        ]
        rule.channels = [{"type": "webhook", "config": {}}]
        rule.template = None

        session = AsyncMock()
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock(return_value=False)
        sf = MagicMock(return_value=session)

        rule_repo = AsyncMock()
        rule_repo.find_enabled_by_project = AsyncMock(return_value=[rule])
        log_repo = AsyncMock()
        log_repo.get_by_delivery = AsyncMock(return_value=None)

        mock_send = AsyncMock()
        with (
            patch("qaplatform.infra.database.repositories.project_repo.NotificationRuleRepository", return_value=rule_repo),
            patch("qaplatform.infra.database.repositories.project_repo.NotificationLogRepository", return_value=log_repo),
            patch("qaplatform.worker.notifications._send_channel", mock_send),
        ):
            await evaluate_and_notify(
                run_id=uuid4(),
                project_id=project_id,
                status="failed",
                summary={"passed": 2, "failed": 8, "pass_rate": 0.2},
                session_factory=sf,
            )

        # pass_rate 0.2 < 0.8 and failed 8 > 0 → first condition fails, notification skipped
        rule_repo.find_enabled_by_project.assert_awaited_once_with(project_id)
        log_repo.get_by_delivery.assert_not_awaited()
        mock_send.assert_not_awaited()
        log_repo.create.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_or_group_with_consecutive_failures_sends_notification(self):
        run_id = uuid4()
        project_id = uuid4()
        rule = MagicMock()
        rule.id = uuid4()
        rule.conditions = [
            {"field": "status", "operator": "eq", "value": "failed"},
            {
                "any": [
                    {"field": "pass_rate", "operator": "lt", "value": "0.5"},
                    {"field": "consecutive_failures", "operator": "gte", "value": "3"},
                ]
            },
        ]
        rule.channels = [{"type": "webhook", "config": {"url": "https://example.com"}}]
        rule.template = "Run {{run_id}}"

        session = AsyncMock()
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock(return_value=False)
        sf = MagicMock(return_value=session)

        rule_repo = AsyncMock()
        rule_repo.find_enabled_by_project = AsyncMock(return_value=[rule])
        log_repo = AsyncMock()
        log_repo.get_by_delivery = AsyncMock(return_value=None)
        run_repo = MagicMock()
        mock_send = AsyncMock()
        load_consecutive = AsyncMock(return_value=3)

        with (
            patch("qaplatform.infra.database.repositories.project_repo.NotificationRuleRepository", return_value=rule_repo),
            patch("qaplatform.infra.database.repositories.project_repo.NotificationLogRepository", return_value=log_repo),
            patch("qaplatform.infra.database.repositories.run_repo.RunRepository", return_value=run_repo),
            patch("qaplatform.worker.notifications._load_consecutive_failures", load_consecutive),
            patch("qaplatform.worker.notifications._send_channel", mock_send),
        ):
            await evaluate_and_notify(
                run_id=run_id,
                project_id=project_id,
                status="failed",
                summary={"pass_rate": 0.9, "failed": 1},
                session_factory=sf,
            )

        load_consecutive.assert_awaited_once_with(run_repo, project_id, run_id)
        log_repo.get_by_delivery.assert_awaited_once_with(
            run_id=run_id,
            rule_id=rule.id,
            channel_type="webhook",
        )
        mock_send.assert_awaited_once_with(
            "webhook",
            {"url": "https://example.com"},
            f"Run {run_id}",
        )
        self._assert_delivery_log(
            log_repo,
            {
                "project_id": project_id,
                "run_id": run_id,
                "rule_id": rule.id,
                "channel_type": "webhook",
                "status": "sent",
                "error_message": None,
            },
        )
        session.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_non_matching_rule_skipped(self):
        project_id = uuid4()
        rule = MagicMock()
        rule.id = uuid4()
        rule.conditions = [{"field": "status", "operator": "eq", "value": "failed"}]
        rule.channels = [{"type": "webhook", "config": {}}]
        rule.template = None

        session = AsyncMock()
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock(return_value=False)
        sf = MagicMock(return_value=session)

        rule_repo = AsyncMock()
        rule_repo.find_enabled_by_project = AsyncMock(return_value=[rule])
        log_repo = AsyncMock()
        log_repo.get_by_delivery = AsyncMock(return_value=None)
        mock_send = AsyncMock()

        with (
            patch("qaplatform.infra.database.repositories.project_repo.NotificationRuleRepository", return_value=rule_repo),
            patch("qaplatform.infra.database.repositories.project_repo.NotificationLogRepository", return_value=log_repo),
            patch("qaplatform.worker.notifications._send_channel", mock_send),
        ):
            await evaluate_and_notify(
                run_id=uuid4(),
                project_id=project_id,
                status="done",
                summary={},
                session_factory=sf,
            )

        rule_repo.find_enabled_by_project.assert_awaited_once_with(project_id)
        log_repo.get_by_delivery.assert_not_awaited()
        mock_send.assert_not_awaited()
        log_repo.create.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_send_failure_logged(self):
        run_id = uuid4()
        project_id = uuid4()
        rule = MagicMock()
        rule.id = uuid4()
        rule.conditions = []
        secret_url = "https://bot:webhook-secret-123@example.com/hook"
        header_token = "header-token-123"
        rule.channels = [
            {
                "type": "webhook",
                "config": {
                    "url": secret_url,
                    "headers": {"Authorization": f"Bearer {header_token}"},
                },
            }
        ]
        rule.template = None

        session = AsyncMock()
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock(return_value=False)
        sf = MagicMock(return_value=session)

        rule_repo = AsyncMock()
        rule_repo.find_enabled_by_project = AsyncMock(return_value=[rule])
        log_repo = AsyncMock()
        log_repo.get_by_delivery = AsyncMock(return_value=None)

        with (
            patch("qaplatform.infra.database.repositories.project_repo.NotificationRuleRepository", return_value=rule_repo),
            patch("qaplatform.infra.database.repositories.project_repo.NotificationLogRepository", return_value=log_repo),
            patch(
                "qaplatform.worker.notifications._send_channel",
                side_effect=RuntimeError(
                    f"send failed for {secret_url} with Bearer {header_token}"
                ),
            ),
        ):
            await evaluate_and_notify(
                run_id=run_id,
                project_id=project_id,
                status="done",
                summary={},
                session_factory=sf,
            )

        log_repo.get_by_delivery.assert_awaited_once_with(
            run_id=run_id,
            rule_id=rule.id,
            channel_type="webhook",
        )
        call_kwargs = self._assert_delivery_log(
            log_repo,
            {
                "project_id": project_id,
                "run_id": run_id,
                "rule_id": rule.id,
                "channel_type": "webhook",
                "status": "failed",
                "error_message": "send failed for [REDACTED] with [REDACTED]",
            },
        )
        assert secret_url not in call_kwargs["error_message"]
        assert "webhook-secret-123" not in call_kwargs["error_message"]
        assert header_token not in call_kwargs["error_message"]
        assert "[REDACTED]" in call_kwargs["error_message"]
        session.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_template_render_failure_logged_without_sending(self):
        run_id = uuid4()
        project_id = uuid4()
        rule = MagicMock()
        rule.id = uuid4()
        rule.conditions = []
        rule.channels = [{"type": "webhook", "config": {}}]
        rule.template = "Run {{run_id}} missing={{unknown}}"

        session = AsyncMock()
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock(return_value=False)
        sf = MagicMock(return_value=session)

        rule_repo = AsyncMock()
        rule_repo.find_enabled_by_project = AsyncMock(return_value=[rule])
        log_repo = AsyncMock()
        log_repo.get_by_delivery = AsyncMock(return_value=None)
        mock_send = AsyncMock()

        with (
            patch("qaplatform.infra.database.repositories.project_repo.NotificationRuleRepository", return_value=rule_repo),
            patch("qaplatform.infra.database.repositories.project_repo.NotificationLogRepository", return_value=log_repo),
            patch("qaplatform.worker.notifications._send_channel", mock_send),
        ):
            await evaluate_and_notify(
                run_id=run_id,
                project_id=project_id,
                status="done",
                summary={},
                session_factory=sf,
            )

        log_repo.get_by_delivery.assert_awaited_once_with(
            run_id=run_id,
            rule_id=rule.id,
            channel_type="webhook",
        )
        mock_send.assert_not_awaited()
        self._assert_delivery_log(
            log_repo,
            {
                "project_id": project_id,
                "run_id": run_id,
                "rule_id": rule.id,
                "channel_type": "webhook",
                "status": "failed",
                "error_message": "unknown template variable: unknown",
            },
        )
        session.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_existing_delivery_log_skips_duplicate_send(self):
        run_id = uuid4()
        project_id = uuid4()
        rule = MagicMock()
        rule.id = uuid4()
        rule.conditions = []
        rule.channels = [{"type": "webhook", "config": {}}]
        rule.template = "Run {{project_name}} status={{status}}"

        session = AsyncMock()
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock(return_value=False)
        sf = MagicMock(return_value=session)

        rule_repo = AsyncMock()
        rule_repo.find_enabled_by_project = AsyncMock(return_value=[rule])
        log_repo = AsyncMock()
        log_repo.get_by_delivery = AsyncMock(return_value=MagicMock())
        project_repo = AsyncMock()
        project_repo.get_by_id = AsyncMock(
            side_effect=AssertionError(
                "duplicate delivery must short-circuit before project lookup"
            )
        )
        mock_send = AsyncMock()

        with (
            patch("qaplatform.infra.database.repositories.project_repo.NotificationRuleRepository", return_value=rule_repo),
            patch("qaplatform.infra.database.repositories.project_repo.NotificationLogRepository", return_value=log_repo),
            patch("qaplatform.infra.database.repositories.project_repo.ProjectRepository", return_value=project_repo),
            patch("qaplatform.worker.notifications._send_channel", mock_send),
        ):
            await evaluate_and_notify(
                run_id=run_id,
                project_id=project_id,
                status="done",
                summary={},
                session_factory=sf,
            )

        rule_repo.find_enabled_by_project.assert_awaited_once_with(project_id)
        log_repo.get_by_delivery.assert_awaited_once_with(
            run_id=run_id,
            rule_id=rule.id,
            channel_type="webhook",
        )
        project_repo.get_by_id.assert_not_awaited()
        mock_send.assert_not_awaited()
        log_repo.create.assert_not_awaited()
        session.commit.assert_awaited_once_with()

    @pytest.mark.asyncio
    async def test_duplicate_log_integrity_error_after_send_is_treated_as_existing_delivery(self):
        run_id = uuid4()
        project_id = uuid4()
        rule = MagicMock()
        rule.id = uuid4()
        rule.conditions = []
        rule.channels = [{"type": "webhook", "config": {"url": "https://example.com"}}]
        rule.template = None

        session = AsyncMock()
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock(return_value=False)
        sf = MagicMock(return_value=session)

        duplicate_error = IntegrityError(
            "insert notification_log",
            {},
            Exception(
                'duplicate key value violates unique constraint '
                '"uq_notification_log_run_rule_channel"'
            ),
        )
        rule_repo = AsyncMock()
        rule_repo.find_enabled_by_project = AsyncMock(return_value=[rule])
        log_repo = AsyncMock()
        log_repo.get_by_delivery = AsyncMock(return_value=None)
        log_repo.create = AsyncMock(side_effect=duplicate_error)
        mock_send = AsyncMock()

        with (
            patch("qaplatform.infra.database.repositories.project_repo.NotificationRuleRepository", return_value=rule_repo),
            patch("qaplatform.infra.database.repositories.project_repo.NotificationLogRepository", return_value=log_repo),
            patch("qaplatform.worker.notifications._send_channel", mock_send),
        ):
            await evaluate_and_notify(
                run_id=run_id,
                project_id=project_id,
                status="done",
                summary={},
                session_factory=sf,
            )

        expected_message = f"Run {run_id} completed with status: done"
        mock_send.assert_awaited_once_with(
            "webhook",
            {"url": "https://example.com"},
            expected_message,
        )
        log_repo.get_by_delivery.assert_awaited_once_with(
            run_id=run_id,
            rule_id=rule.id,
            channel_type="webhook",
        )
        self._assert_delivery_log(
            log_repo,
            {
                "project_id": project_id,
                "run_id": run_id,
                "rule_id": rule.id,
                "channel_type": "webhook",
                "status": "sent",
                "error_message": None,
            },
        )
        session.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_non_duplicate_log_integrity_error_propagates_after_send(self):
        run_id = uuid4()
        project_id = uuid4()
        rule = MagicMock()
        rule.id = uuid4()
        rule.conditions = []
        rule.channels = [{"type": "webhook", "config": {"url": "https://example.com"}}]
        rule.template = None

        session = AsyncMock()
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock(return_value=False)
        sf = MagicMock(return_value=session)

        integrity_error = IntegrityError(
            "insert notification_log",
            {},
            Exception('violates foreign key constraint "fk_notification_log_run"'),
        )
        rule_repo = AsyncMock()
        rule_repo.find_enabled_by_project = AsyncMock(return_value=[rule])
        log_repo = AsyncMock()
        log_repo.get_by_delivery = AsyncMock(return_value=None)
        log_repo.create = AsyncMock(side_effect=integrity_error)
        mock_send = AsyncMock()

        with (
            patch("qaplatform.infra.database.repositories.project_repo.NotificationRuleRepository", return_value=rule_repo),
            patch("qaplatform.infra.database.repositories.project_repo.NotificationLogRepository", return_value=log_repo),
            patch("qaplatform.worker.notifications._send_channel", mock_send),
            pytest.raises(IntegrityError),
        ):
            await evaluate_and_notify(
                run_id=run_id,
                project_id=project_id,
                status="done",
                summary={},
                session_factory=sf,
            )

        expected_message = f"Run {run_id} completed with status: done"
        mock_send.assert_awaited_once_with(
            "webhook",
            {"url": "https://example.com"},
            expected_message,
        )
        log_repo.get_by_delivery.assert_awaited_once_with(
            run_id=run_id,
            rule_id=rule.id,
            channel_type="webhook",
        )
        self._assert_delivery_log(
            log_repo,
            {
                "project_id": project_id,
                "run_id": run_id,
                "rule_id": rule.id,
                "channel_type": "webhook",
                "status": "sent",
                "error_message": None,
            },
        )
        session.commit.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_unexpected_log_write_failure_propagates_after_send(self):
        run_id = uuid4()
        project_id = uuid4()
        rule = MagicMock()
        rule.id = uuid4()
        rule.conditions = []
        rule.channels = [{"type": "webhook", "config": {"url": "https://example.com"}}]
        rule.template = None

        session = AsyncMock()
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock(return_value=False)
        sf = MagicMock(return_value=session)

        rule_repo = AsyncMock()
        rule_repo.find_enabled_by_project = AsyncMock(return_value=[rule])
        log_repo = AsyncMock()
        log_repo.get_by_delivery = AsyncMock(return_value=None)
        error = RuntimeError("database unavailable")
        log_repo.create = AsyncMock(side_effect=error)
        mock_send = AsyncMock()

        with (
            patch("qaplatform.infra.database.repositories.project_repo.NotificationRuleRepository", return_value=rule_repo),
            patch("qaplatform.infra.database.repositories.project_repo.NotificationLogRepository", return_value=log_repo),
            patch("qaplatform.worker.notifications._send_channel", mock_send),
            pytest.raises(RuntimeError) as exc_info,
        ):
            await evaluate_and_notify(
                run_id=run_id,
                project_id=project_id,
                status="done",
                summary={},
                session_factory=sf,
            )

        assert exc_info.value is error
        expected_message = f"Run {run_id} completed with status: done"
        mock_send.assert_awaited_once_with(
            "webhook",
            {"url": "https://example.com"},
            expected_message,
        )
        log_repo.get_by_delivery.assert_awaited_once_with(
            run_id=run_id,
            rule_id=rule.id,
            channel_type="webhook",
        )
        self._assert_delivery_log(
            log_repo,
            {
                "project_id": project_id,
                "run_id": run_id,
                "rule_id": rule.id,
                "channel_type": "webhook",
                "status": "sent",
                "error_message": None,
            },
        )
        session.commit.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_multiple_channels_per_rule(self):
        run_id = uuid4()
        project_id = uuid4()
        rule = MagicMock()
        rule.id = uuid4()
        rule.conditions = []
        rule.channels = [
            {"type": "email", "config": {"to_addresses": ["qa@example.com"]}},
            {"type": "webhook", "config": {"url": "https://example.com"}},
        ]
        rule.template = None

        session = AsyncMock()
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock(return_value=False)
        sf = MagicMock(return_value=session)

        rule_repo = AsyncMock()
        rule_repo.find_enabled_by_project = AsyncMock(return_value=[rule])
        log_repo = AsyncMock()
        log_repo.get_by_delivery = AsyncMock(return_value=None)
        mock_send = AsyncMock()

        with (
            patch("qaplatform.infra.database.repositories.project_repo.NotificationRuleRepository", return_value=rule_repo),
            patch("qaplatform.infra.database.repositories.project_repo.NotificationLogRepository", return_value=log_repo),
            patch("qaplatform.worker.notifications._send_channel", mock_send),
        ):
            await evaluate_and_notify(
                run_id=run_id,
                project_id=project_id,
                status="done",
                summary={},
                session_factory=sf,
            )

        expected_message = f"Run {run_id} completed with status: done"
        assert log_repo.get_by_delivery.await_args_list == [
            call(run_id=run_id, rule_id=rule.id, channel_type="email"),
            call(run_id=run_id, rule_id=rule.id, channel_type="webhook"),
        ]
        assert mock_send.await_args_list == [
            call("email", {"to_addresses": ["qa@example.com"]}, expected_message),
            call("webhook", {"url": "https://example.com"}, expected_message),
        ]
        assert [
            {
                "project_id": create_call.kwargs["project_id"],
                "run_id": create_call.kwargs["run_id"],
                "rule_id": create_call.kwargs["rule_id"],
                "channel_type": create_call.kwargs["channel_type"],
                "status": create_call.kwargs["status"].value,
                "error_message": create_call.kwargs["error_message"],
            }
            for create_call in log_repo.create.await_args_list
        ] == [
            {
                "project_id": project_id,
                "run_id": run_id,
                "rule_id": rule.id,
                "channel_type": "email",
                "status": "sent",
                "error_message": None,
            },
            {
                "project_id": project_id,
                "run_id": run_id,
                "rule_id": rule.id,
                "channel_type": "webhook",
                "status": "sent",
                "error_message": None,
            },
        ]
        session.commit.assert_awaited_once()


# --------------------------------------------------------------------------- #
# T15: new_failed and recovered condition fields
# --------------------------------------------------------------------------- #


class TestNewFailedAndRecoveredConditions:
    """T15: 测试 new_failed 和 recovered 通知条件字段。"""

    def test_new_failed_condition_evaluation(self):
        """new_failed 条件评估正确。"""
        conditions = [{"field": "new_failed", "operator": "gt", "value": 0}]
        context = {"new_failed": 3}
        assert _evaluate_conditions(conditions, {}, "failed", context) is True

        context = {"new_failed": 0}
        assert _evaluate_conditions(conditions, {}, "failed", context) is False

    def test_recovered_condition_evaluation(self):
        """recovered 条件评估正确。"""
        conditions = [{"field": "recovered", "operator": "gt", "value": 0}]
        context = {"recovered": 2}
        assert _evaluate_conditions(conditions, {}, "done", context) is True

        context = {"recovered": 0}
        assert _evaluate_conditions(conditions, {}, "done", context) is False

    def test_new_failed_zero_does_not_notify(self):
        """连续两次相同失败集合，new_failed=0 不触发通知。"""
        conditions = [{"field": "new_failed", "operator": "gt", "value": 0}]
        context = {"new_failed": 0}
        assert _evaluate_conditions(conditions, {"failed": 5}, "failed", context) is False

    def test_new_failed_with_legacy_failed_condition(self):
        """new_failed 与旧 failed 条件共存时向后兼容。"""
        conditions = [{"field": "failed", "operator": "gt", "value": 0}]
        # 旧条件只看 summary.failed，不依赖 context
        assert _evaluate_conditions(conditions, {"failed": 5}, "failed", {}) is True
        assert _evaluate_conditions(conditions, {"failed": 0}, "failed", {}) is False
