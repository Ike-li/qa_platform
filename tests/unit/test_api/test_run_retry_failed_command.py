"""retry_failed_run_command 单元测试。"""
from __future__ import annotations

from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest

from qaplatform.api.run_retry_failed_command import (
    MAX_FAILED_CASES_FOR_RETRY,
    RetryFailedError,
    retry_failed_run_command,
)


@pytest.mark.asyncio
async def test_retry_failed_rejects_non_retryable_status():
    """非终态 run 抛出 RetryFailedError。"""
    run_id = uuid4()
    repos = Mock()
    repos.run.get_for_tenant = AsyncMock(
        return_value=Mock(id=run_id, status="running", metadata_={})
    )

    user = Mock(tenant_id=uuid4(), user_id=uuid4())
    session = AsyncMock()

    with pytest.raises(RetryFailedError, match="terminal state"):
        await retry_failed_run_command(
            run_id=run_id,
            repos=repos,
            user=user,
            session=session,
            arq_pool=None,
            settings=None,
        )


@pytest.mark.asyncio
async def test_retry_failed_rejects_no_failures():
    """无失败用例抛出 RetryFailedError。"""
    run_id = uuid4()
    repos = Mock()
    repos.run.get_for_tenant = AsyncMock(
        return_value=Mock(id=run_id, status="done", metadata_={})
    )
    repos.test_result.list_failed_by_run = AsyncMock(return_value=[])

    user = Mock(tenant_id=uuid4(), user_id=uuid4())
    session = AsyncMock()

    with pytest.raises(RetryFailedError, match="No failed test cases"):
        await retry_failed_run_command(
            run_id=run_id,
            repos=repos,
            user=user,
            session=session,
            arq_pool=None,
            settings=None,
        )


@pytest.mark.asyncio
async def test_retry_failed_rejects_too_many_failures():
    """失败用例超过 200 个抛出 RetryFailedError。"""
    run_id = uuid4()
    repos = Mock()
    repos.run.get_for_tenant = AsyncMock(
        return_value=Mock(id=run_id, status="failed", metadata_={})
    )

    # 构造 201 个失败用例
    failed_results = [
        Mock(suite="tests.unit.test_x", name=f"test_case_{i}")
        for i in range(MAX_FAILED_CASES_FOR_RETRY + 1)
    ]
    repos.test_result.list_failed_by_run = AsyncMock(return_value=failed_results)

    user = Mock(tenant_id=uuid4(), user_id=uuid4())
    session = AsyncMock()

    with pytest.raises(RetryFailedError, match="Too many failed cases"):
        await retry_failed_run_command(
            run_id=run_id,
            repos=repos,
            user=user,
            session=session,
            arq_pool=None,
            settings=None,
        )


@pytest.mark.asyncio
async def test_retry_failed_rejects_non_pytest_runner():
    """非 pytest runner 的 pipeline 抛出 RetryFailedError。"""
    run_id = uuid4()
    pipeline_id = uuid4()
    env_id = uuid4()

    pipeline_mock = Mock(
        id=pipeline_id,
        stages=[{"plugin": "go-test", "config": {}}],
    )

    original_run = Mock(
        id=run_id,
        status="failed",
        metadata_={},
        pipeline_id=pipeline_id,
        environment_id=env_id,
        pipeline=pipeline_mock,
    )

    repos = Mock()
    repos.run.get_for_tenant = AsyncMock(return_value=original_run)
    repos.test_result.list_failed_by_run = AsyncMock(
        return_value=[
            Mock(suite="tests.unit.test_x", name="test_fail"),
        ]
    )

    user = Mock(tenant_id=uuid4(), user_id=uuid4())
    session = AsyncMock()
    session.refresh = AsyncMock()

    with pytest.raises(RetryFailedError, match="only supports pytest runner"):
        await retry_failed_run_command(
            run_id=run_id,
            repos=repos,
            user=user,
            session=session,
            arq_pool=None,
            settings=None,
        )


@pytest.mark.asyncio
async def test_retry_failed_creates_new_run_with_metadata():
    """成功路径：创建包含 retry_failed_cases 元数据的新 run。"""
    run_id = uuid4()
    pipeline_id = uuid4()
    env_id = uuid4()
    project_id = uuid4()
    tenant_id = uuid4()

    pipeline_mock = Mock(
        id=pipeline_id,
        stages=[{"plugin": "pytest", "config": {}}],
    )

    original_run = Mock(
        id=run_id,
        status="failed",
        metadata_={"existing": "value"},
        pipeline_id=pipeline_id,
        environment_id=env_id,
        project_id=project_id,
        tenant_id=tenant_id,
        git_ref="main",
        git_sha="abc123",
        priority=0,
        retry_group_id=None,
        chain_depth=0,
        pipeline=pipeline_mock,
        environment=Mock(),
    )

    failed_results = [
        Mock(suite="tests.unit.test_x", name="test_a"),
        Mock(suite="tests.unit.test_y.TestClass", name="test_b"),
    ]

    new_run_mock = Mock(id=uuid4())

    repos = Mock()
    repos.run.get_for_tenant = AsyncMock(return_value=original_run)
    repos.test_result.list_failed_by_run = AsyncMock(return_value=failed_results)
    repos.run.create = AsyncMock(return_value=new_run_mock)
    repos.run.set_retry_group_id = AsyncMock()
    repos.run.commit = AsyncMock()

    user = Mock(tenant_id=tenant_id, user_id=uuid4())
    session = AsyncMock()
    session.refresh = AsyncMock()

    from unittest.mock import patch

    with patch("qaplatform.api.run_retry_failed_command.to_run_response") as mock_presenter:
        with patch("qaplatform.api.run_retry_failed_command.write_audit") as mock_audit:
            mock_presenter.return_value = {"id": str(new_run_mock.id)}

            await retry_failed_run_command(
                run_id=run_id,
                repos=repos,
                user=user,
                session=session,
                arq_pool=None,
                settings=None,
            )

            # 验证创建了新 run
            repos.run.create.assert_called_once()
            call_kwargs = repos.run.create.call_args[1]

            assert call_kwargs["trigger_type"] == "retry_failed"
            assert call_kwargs["source_run_id"] == run_id
            assert "retry_failed_cases" in call_kwargs["metadata_"]
            assert len(call_kwargs["metadata_"]["retry_failed_cases"]) == 2
            assert call_kwargs["metadata_"]["retry_failed_cases"][0] == {
                "suite": "tests.unit.test_x",
                "name": "test_a",
            }

            # 验证设置了 retry_group_id
            repos.run.set_retry_group_id.assert_called_once()

            # 验证写入了审计
            mock_audit.assert_called_once()
            audit_call = mock_audit.call_args[1]
            assert audit_call["action"] == "run.retry_failed"
            assert "nodeids" in audit_call["after"]
