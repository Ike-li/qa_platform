"""Tests for the execution service state machine and conditional transitions."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from qaplatform.domain.models.run import RunStatus, TERMINAL_STATUSES
from qaplatform.domain.services.execution import (
    ExecutionService,
    cancel_if_current,
    claim_for_worker,
    fail_if_current,
    finish_if_current,
    is_valid_transition,
    start_execution,
    timeout_if_current,
)


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


# --------------------------------------------------------------------------- #
# ExecutionService
# --------------------------------------------------------------------------- #


class TestExecutionService:
    def setup_method(self):
        self.svc = ExecutionService()

    def test_create_run_returns_queued(self):
        run = self.svc.create_run(
            tenant_id=uuid4(),
            project_id=uuid4(),
            pipeline_id=uuid4(),
            environment_id=uuid4(),
            trigger_type="manual",
            git_ref="main",
        )
        assert run.status == RunStatus.QUEUED

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

        result = await claim_for_worker(self.repo, fake_run.id, "worker-1")
        assert result is not None
        self.repo.update_status.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_claim_for_worker_already_claimed(self):
        self.repo.update_status.return_value = False

        result = await claim_for_worker(self.repo, uuid4(), "worker-1")
        assert result is None

    @pytest.mark.asyncio
    async def test_start_execution(self):
        self.repo.update_status.return_value = True
        result = await start_execution(self.repo, uuid4())
        assert result is True

    @pytest.mark.asyncio
    async def test_finish_if_current_success(self):
        self.repo.update_status.return_value = True
        summary = {"total": 5, "passed": 5, "failed": 0}
        result = await finish_if_current(self.repo, uuid4(), summary=summary)
        assert result is True

    @pytest.mark.asyncio
    async def test_finish_if_current_already_terminated(self):
        self.repo.update_status.return_value = False
        result = await finish_if_current(self.repo, uuid4())
        assert result is False

    @pytest.mark.asyncio
    async def test_fail_if_current_with_message(self):
        self.repo.update_status.return_value = True
        result = await fail_if_current(self.repo, uuid4(), message="container OOM")
        assert result is True

    @pytest.mark.asyncio
    async def test_cancel_if_current(self):
        self.repo.update_status.return_value = True
        result = await cancel_if_current(self.repo, uuid4())
        assert result is True

    @pytest.mark.asyncio
    async def test_timeout_if_current(self):
        self.repo.update_status.return_value = True
        result = await timeout_if_current(self.repo, uuid4())
        assert result is True
