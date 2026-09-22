"""失败子集重跑命令。"""
from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from qaplatform.api.audit import write_audit
from qaplatform.api.deps import UserIdentity
from qaplatform.api.run_presenters import to_run_response
from qaplatform.api.schemas import RunResponse
from qaplatform.domain.services.execution import is_retryable_status
from qaplatform.domain.services.pytest_nodeid import reconstruct_nodeid

MAX_FAILED_CASES_FOR_RETRY = 200


class RetryFailedError(Exception):
    """重跑失败用例错误。"""

    def __init__(self, message: str, status_code: int = 409):
        self.message = message
        self.status_code = status_code
        super().__init__(message)


async def retry_failed_run_command(
    *,
    run_id: UUID,
    repos: Any,
    user: UserIdentity,
    session: AsyncSession,
    arq_pool: Any,
    settings: Any,
) -> RunResponse:
    """创建只重跑失败用例的新 Run。

    Args:
        run_id: 原 run ID
        repos: 仓库集合
        user: 当前用户
        session: 数据库会话
        arq_pool: ARQ 队列池
        settings: 应用配置

    Returns:
        新创建的 Run 响应

    Raises:
        RetryFailedError: 原 run 非终态、无失败用例、非 pytest pipeline、失败用例过多等
    """
    try:
        original = await repos.run.get_for_tenant(run_id, user.tenant_id)
        if original is None:
            raise RetryFailedError("Run not found", status_code=404)

        if not is_retryable_status(original.status):
            raise RetryFailedError(
                f"Run must be in terminal state, current: {original.status}"
            )

        # 查询失败用例
        failed_results = await repos.test_result.list_failed_by_run(run_id)
        if not failed_results:
            raise RetryFailedError("No failed test cases to retry")

        if len(failed_results) > MAX_FAILED_CASES_FOR_RETRY:
            raise RetryFailedError(
                f"Too many failed cases ({len(failed_results)} > {MAX_FAILED_CASES_FOR_RETRY}), "
                "please run the entire pipeline instead"
            )

        # 加载关联对象
        await session.refresh(original, ["pipeline", "environment"])

        # 检查 runner 类型
        pipeline_stages = original.pipeline.stages or []
        if not pipeline_stages:
            raise RetryFailedError("Pipeline has no stages")

        # v1 仅支持 pytest runner
        for stage in pipeline_stages:
            if stage.get("plugin") != "pytest":
                raise RetryFailedError(
                    f"Retry-failed only supports pytest runner, found: {stage.get('plugin')}"
                )

        # 重构 nodeid 列表
        retry_failed_cases = [
            {"suite": r.suite, "name": r.name} for r in failed_results
        ]
        nodeids = [
            reconstruct_nodeid(r.suite, r.name) for r in failed_results
        ]

        # 创建新 Run
        new_metadata = dict(original.metadata_ or {})
        new_metadata["retry_failed_cases"] = retry_failed_cases

        new_run = await repos.run.create(
            tenant_id=original.tenant_id,
            project_id=original.project_id,
            pipeline_id=original.pipeline_id,
            environment_id=original.environment_id,
            git_ref=original.git_ref,
            git_sha=original.git_sha,
            priority=original.priority,
            triggered_by=user.user_id,
            trigger_type="retry_failed",
            metadata_=new_metadata,
            source_run_id=original.id,
            chain_depth=(original.chain_depth or 0) + 1,
        )

        # 设置 retry_group_id（沿用原值或新建）
        if original.retry_group_id:
            await repos.run.set_retry_group_id(new_run.id, original.retry_group_id)
        else:
            await repos.run.set_retry_group_id(new_run.id, new_run.id)

        # 入队
        if arq_pool is not None:
            await repos.run.commit()
            from qaplatform.infra.queue.scheduler import enqueue_run

            await enqueue_run(arq_pool, repos.run, new_run, "retry_failed", settings)

        # 审计
        await write_audit(
            repos,
            user,
            action="run.retry_failed",
            resource_type="run",
            resource_id=original.id,
            before=to_run_response(original),
            after={
                "retry_run_id": str(new_run.id),
                "source_run_id": str(original.id),
                "failed_case_count": len(failed_results),
                "nodeids": nodeids,
            },
        )

        return to_run_response(new_run)

    except RetryFailedError:
        raise
    except (SQLAlchemyError, ValueError) as e:
        raise RetryFailedError(f"Operation failed: {e}", status_code=500) from e
