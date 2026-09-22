"""Tests for the execution service state machine and conditional transitions."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from qaplatform.domain.models.run import RunStatus
from qaplatform.domain.services.execution import (
    ACTIVE_STATUSES,
    CANCELABLE_STATUSES,
    IN_FLIGHT_STATUSES,
    RETRYABLE_STATUSES,
    ExecutionService,
    cancel_if_current,
    claim_for_worker,
    fail_if_current,
    finish_if_current,
    is_cancelable_status,
    is_retryable_status,
    is_terminal_status,
    is_valid_transition,
    run_status_values,
    start_execution,
    timeout_if_current,
)
from qaplatform.infra.database.models import RunStatusEnum

# --------------------------------------------------------------------------- #
# is_valid_transition
# --------------------------------------------------------------------------- #


class TestIsValidTransition:
    def test_queued_to_preparing(self):
        assert is_valid_transition(RunStatus.QUEUED, RunStatus.PREPARING) is True

    def test_queued_to_cancelled(self):
        assert is_valid_transition(RunStatus.QUEUED, RunStatus.CANCELLED) is True

    def test_queued_to_running_rejected(self):
        assert is_valid_transition(RunStatus.QUEUED, RunStatus.RUNNING) is False

    def test_preparing_to_running(self):
        assert is_valid_transition(RunStatus.PREPARING, RunStatus.RUNNING) is True

    def test_preparing_to_failed(self):
        assert is_valid_transition(RunStatus.PREPARING, RunStatus.FAILED) is True

    def test_running_to_collecting(self):
        assert is_valid_transition(RunStatus.RUNNING, RunStatus.COLLECTING) is True

    def test_running_to_timeout(self):
        assert is_valid_transition(RunStatus.RUNNING, RunStatus.TIMEOUT) is True

    def test_collecting_to_done(self):
        assert is_valid_transition(RunStatus.COLLECTING, RunStatus.DONE) is True

    def test_done_is_terminal(self):
        for target in RunStatus:
            assert is_valid_transition(RunStatus.DONE, target) is False

    def test_failed_is_terminal(self):
        for target in RunStatus:
            assert is_valid_transition(RunStatus.FAILED, target) is False

    def test_cancelled_is_terminal(self):
        for target in RunStatus:
            assert is_valid_transition(RunStatus.CANCELLED, target) is False

    def test_timeout_is_terminal(self):
        for target in RunStatus:
            assert is_valid_transition(RunStatus.TIMEOUT, target) is False


class TestStatusSets:
    def test_active_and_cancelable_statuses_are_the_same_domain_set(self):
        assert ACTIVE_STATUSES == CANCELABLE_STATUSES
        assert run_status_values(CANCELABLE_STATUSES) == frozenset(
            {"queued", "preparing", "running", "collecting"}
        )

    def test_in_flight_statuses_exclude_waiting_queued_runs(self):
        assert run_status_values(IN_FLIGHT_STATUSES) == frozenset(
            {"preparing", "running", "collecting"}
        )
        assert RunStatus.QUEUED not in IN_FLIGHT_STATUSES

    def test_terminal_status_helper_accepts_infra_enum_and_strings(self):
        assert is_terminal_status(RunStatusEnum.DONE) is True
        assert is_terminal_status("failed") is True
        assert is_terminal_status(RunStatus.RUNNING) is False

    def test_cancelable_status_helper_accepts_infra_enum_and_strings(self):
        assert is_cancelable_status(RunStatusEnum.RUNNING) is True
        assert is_cancelable_status("collecting") is True
        assert is_cancelable_status(RunStatusEnum.CANCELLED) is False

    def test_retryable_statuses_are_terminal_statuses(self):
        assert RETRYABLE_STATUSES == {
            RunStatus.DONE,
            RunStatus.FAILED,
            RunStatus.CANCELLED,
            RunStatus.TIMEOUT,
        }
        assert is_retryable_status(RunStatusEnum.TIMEOUT) is True
        assert is_retryable_status(RunStatusEnum.PREPARING) is False


# --------------------------------------------------------------------------- #
# ExecutionService
# --------------------------------------------------------------------------- #


class TestExecutionService:
    def setup_method(self):
        self.svc = ExecutionService()

    def test_create_run_returns_queued(self):
        tenant_id = uuid4()
        project_id = uuid4()
        pipeline_id = uuid4()
        environment_id = uuid4()
        triggered_by = uuid4()
        source_run_id = uuid4()

        run = self.svc.create_run(
            tenant_id=tenant_id,
            project_id=project_id,
            pipeline_id=pipeline_id,
            environment_id=environment_id,
            trigger_type="manual",
            git_ref="main",
            triggered_by=triggered_by,
            git_sha="abc123",
            source_run_id=source_run_id,
            chain_depth=2,
            dedup_key="manual:abc123",
        )
        assert run.id.int == 0
        assert run.tenant_id == tenant_id
        assert run.project_id == project_id
        assert run.pipeline_id == pipeline_id
        assert run.environment_id == environment_id
        assert run.status == RunStatus.QUEUED
        assert run.trigger_type == "manual"
        assert run.git_ref == "main"
        assert run.git_sha == "abc123"
        assert run.triggered_by == triggered_by
        assert run.source_run_id == source_run_id
        assert run.chain_depth == 2
        assert run.dedup_key == "manual:abc123"
        assert run.priority == 1
        assert run.attempt == 1
        assert run.retry_group_id is None
        assert run.created_at == run.updated_at == run.status_updated_at
        assert run.created_at.tzinfo is not None
        assert run.created_at.utcoffset() is not None

    def test_transition_status_valid(self):
        run = MagicMock()
        run.status = RunStatus.QUEUED
        assert self.svc.transition_status(run, RunStatus.PREPARING) is True

    def test_transition_status_invalid(self):
        run = MagicMock()
        run.status = RunStatus.QUEUED
        assert self.svc.transition_status(run, RunStatus.DONE) is False

    def test_is_cancelable_queued(self):
        run = MagicMock()
        run.status = RunStatus.QUEUED
        assert self.svc.is_cancelable(run) is True

    def test_is_cancelable_running(self):
        run = MagicMock()
        run.status = RunStatus.RUNNING
        assert self.svc.is_cancelable(run) is True

    def test_not_cancelable_done(self):
        run = MagicMock()
        run.status = RunStatus.DONE
        assert self.svc.is_cancelable(run) is False


# --------------------------------------------------------------------------- #
# Conditional state transitions
# --------------------------------------------------------------------------- #


class _FakeRun:
    """Minimal fake run object."""

    def __init__(self, status: RunStatus):
        self.id = uuid4()
        self.status = status


class TestConditionalTransitions:
    def setup_method(self):
        self.repo = AsyncMock()

    @pytest.mark.asyncio
    async def test_claim_for_worker_success(self):
        self.repo.update_status.return_value = True
        fake_run = _FakeRun(RunStatus.PREPARING)
        self.repo.get.return_value = fake_run
        run_id = fake_run.id

        result = await claim_for_worker(self.repo, run_id, "worker-1")

        assert result is fake_run
        self.repo.update_status.assert_awaited_once_with(
            run_id,
            RunStatus.PREPARING,
            worker_id="worker-1",
        )
        self.repo.get.assert_awaited_once_with(run_id)

    @pytest.mark.asyncio
    async def test_claim_for_worker_already_claimed(self):
        self.repo.update_status.return_value = False
        run_id = uuid4()

        result = await claim_for_worker(self.repo, run_id, "worker-1")

        assert result is None
        self.repo.update_status.assert_awaited_once_with(
            run_id,
            RunStatus.PREPARING,
            worker_id="worker-1",
        )
        self.repo.get.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_start_execution(self):
        self.repo.update_status.return_value = True
        run_id = uuid4()

        result = await start_execution(self.repo, run_id)

        assert result is True
        self.repo.update_status.assert_awaited_once_with(run_id, RunStatus.RUNNING)

    @pytest.mark.asyncio
    async def test_finish_if_current_success(self):
        self.repo.update_status.return_value = True
        summary = {"total": 5, "passed": 5, "failed": 0}
        run_id = uuid4()

        result = await finish_if_current(self.repo, run_id, summary=summary)

        assert result is True
        self.repo.update_status.assert_awaited_once_with(
            run_id,
            RunStatus.DONE,
            summary=summary,
        )

    @pytest.mark.asyncio
    async def test_finish_if_current_already_terminated(self):
        self.repo.update_status.return_value = False
        run_id = uuid4()

        result = await finish_if_current(self.repo, run_id)

        assert result is False
        self.repo.update_status.assert_awaited_once_with(run_id, RunStatus.DONE)

    @pytest.mark.asyncio
    async def test_fail_if_current_with_message(self):
        self.repo.update_status.return_value = True
        run_id = uuid4()

        result = await fail_if_current(
            self.repo,
            run_id,
            expected=RunStatus.RUNNING,
            message="container OOM",
        )

        assert result is True
        self.repo.update_status.assert_awaited_once_with(
            run_id,
            RunStatus.FAILED,
            error_message="container OOM",
            expected=RunStatus.RUNNING,
        )

    @pytest.mark.asyncio
    async def test_cancel_if_current(self):
        self.repo.update_status.return_value = True
        run_id = uuid4()

        result = await cancel_if_current(self.repo, run_id)

        assert result is True
        self.repo.update_status.assert_awaited_once_with(run_id, RunStatus.CANCELLED)

    @pytest.mark.asyncio
    async def test_timeout_if_current(self):
        self.repo.update_status.return_value = True
        run_id = uuid4()

        result = await timeout_if_current(self.repo, run_id)

        assert result is True
        self.repo.update_status.assert_awaited_once_with(run_id, RunStatus.TIMEOUT)
