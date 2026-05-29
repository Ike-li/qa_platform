"""Tests for notification evaluation and sending logic."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

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

    def test_unknown_field_skipped(self):
        conditions = [{"field": "unknown", "operator": "eq", "value": "x"}]
        assert _evaluate_conditions(conditions, {}, "done") is True

    def test_none_summary_uses_defaults(self):
        conditions = [{"field": "pass_rate", "operator": "eq", "value": 0.0}]
        assert _evaluate_conditions(conditions, None, "done") is True


# --------------------------------------------------------------------------- #
# evaluate_and_notify integration tests
# --------------------------------------------------------------------------- #


class TestEvaluateAndNotify:
    @pytest.mark.asyncio
    async def test_no_rules_no_notifications(self):
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
                project_id=uuid4(),
                status="done",
                summary={},
                session_factory=sf,
            )

        log_repo.create.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_matching_rule_sends_notification(self):
        rule = MagicMock()
        rule.id = uuid4()
        rule.conditions = [{"field": "status", "operator": "eq", "value": "failed"}]
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

        with (
            patch("qaplatform.infra.database.repositories.project_repo.NotificationRuleRepository", return_value=rule_repo),
            patch("qaplatform.infra.database.repositories.project_repo.NotificationLogRepository", return_value=log_repo),
            patch("qaplatform.worker.notifications._send_channel", new_callable=AsyncMock),
        ):
            await evaluate_and_notify(
                run_id=uuid4(),
                project_id=uuid4(),
                status="failed",
                summary={"passed": 5, "failed": 3},
                session_factory=sf,
            )

        log_repo.create.assert_awaited_once()
        call_kwargs = log_repo.create.call_args.kwargs
        assert call_kwargs["channel_type"] == "webhook"
        assert call_kwargs["status"].value == "sent"

    @pytest.mark.asyncio
    async def test_template_rendering(self):
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
            run_id = uuid4()
            await evaluate_and_notify(
                run_id=run_id,
                project_id=uuid4(),
                status="failed",
                summary={"passed": 5, "failed": 3},
                session_factory=sf,
            )

        mock_send.assert_awaited_once()
        sent_message = mock_send.call_args.args[2]
        assert str(run_id) in sent_message
        assert "status=failed" in sent_message
        assert "passed=5" in sent_message
        assert "failed=3" in sent_message

    @pytest.mark.asyncio
    async def test_numeric_coercion_in_conditions(self):
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

        with (
            patch("qaplatform.infra.database.repositories.project_repo.NotificationRuleRepository", return_value=rule_repo),
            patch("qaplatform.infra.database.repositories.project_repo.NotificationLogRepository", return_value=log_repo),
            patch("qaplatform.worker.notifications._send_channel", new_callable=AsyncMock),
        ):
            await evaluate_and_notify(
                run_id=uuid4(),
                project_id=uuid4(),
                status="failed",
                summary={"passed": 2, "failed": 8, "pass_rate": 0.2},
                session_factory=sf,
            )

        # pass_rate 0.2 < 0.8 and failed 8 > 0 → first condition fails, notification skipped
        log_repo.create.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_non_matching_rule_skipped(self):
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

        with (
            patch("qaplatform.infra.database.repositories.project_repo.NotificationRuleRepository", return_value=rule_repo),
            patch("qaplatform.infra.database.repositories.project_repo.NotificationLogRepository", return_value=log_repo),
        ):
            await evaluate_and_notify(
                run_id=uuid4(),
                project_id=uuid4(),
                status="done",
                summary={},
                session_factory=sf,
            )

        log_repo.create.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_send_failure_logged(self):
        rule = MagicMock()
        rule.id = uuid4()
        rule.conditions = []
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

        with (
            patch("qaplatform.infra.database.repositories.project_repo.NotificationRuleRepository", return_value=rule_repo),
            patch("qaplatform.infra.database.repositories.project_repo.NotificationLogRepository", return_value=log_repo),
            patch("qaplatform.worker.notifications._send_channel", side_effect=RuntimeError("send failed")),
        ):
            await evaluate_and_notify(
                run_id=uuid4(),
                project_id=uuid4(),
                status="done",
                summary={},
                session_factory=sf,
            )

        log_repo.create.assert_awaited_once()
        call_kwargs = log_repo.create.call_args.kwargs
        assert call_kwargs["status"].value == "failed"
        assert "send failed" in call_kwargs["error_message"]

    @pytest.mark.asyncio
    async def test_template_render_failure_logged_without_sending(self):
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
                run_id=uuid4(),
                project_id=uuid4(),
                status="done",
                summary={},
                session_factory=sf,
            )

        mock_send.assert_not_awaited()
        log_repo.create.assert_awaited_once()
        call_kwargs = log_repo.create.call_args.kwargs
        assert call_kwargs["status"].value == "failed"
        assert "unknown template variable" in call_kwargs["error_message"]

    @pytest.mark.asyncio
    async def test_existing_delivery_log_skips_duplicate_send(self):
        rule = MagicMock()
        rule.id = uuid4()
        rule.conditions = []
        rule.channels = [{"type": "webhook", "config": {}}]
        rule.template = None

        session = AsyncMock()
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock(return_value=False)
        sf = MagicMock(return_value=session)

        rule_repo = AsyncMock()
        rule_repo.find_enabled_by_project = AsyncMock(return_value=[rule])
        log_repo = AsyncMock()
        log_repo.get_by_delivery = AsyncMock(return_value=MagicMock())
        mock_send = AsyncMock()

        with (
            patch("qaplatform.infra.database.repositories.project_repo.NotificationRuleRepository", return_value=rule_repo),
            patch("qaplatform.infra.database.repositories.project_repo.NotificationLogRepository", return_value=log_repo),
            patch("qaplatform.worker.notifications._send_channel", mock_send),
        ):
            await evaluate_and_notify(
                run_id=uuid4(),
                project_id=uuid4(),
                status="done",
                summary={},
                session_factory=sf,
            )

        mock_send.assert_not_awaited()
        log_repo.create.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_multiple_channels_per_rule(self):
        rule = MagicMock()
        rule.id = uuid4()
        rule.conditions = []
        rule.channels = [
            {"type": "email", "config": {}},
            {"type": "webhook", "config": {}},
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
        ):
            await evaluate_and_notify(
                run_id=uuid4(),
                project_id=uuid4(),
                status="done",
                summary={},
                session_factory=sf,
            )

        assert log_repo.create.await_count == 2
