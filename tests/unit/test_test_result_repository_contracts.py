"""TestResultRepository 新增方法（T12）的契约单测。

mock session：验证 SQL 编译形态（过滤、窗口限行、行序比较）与
Python 侧的分组/计数逻辑；真实查询行为由集成测试覆盖。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from sqlalchemy.dialects import postgresql

# 经模块引用而非顶层 import：TestResultRepository 以 Test 开头，
# 直接 import 会触发 PytestCollectionWarning。
from qaplatform.infra.database.repositories import test_result_repo

NOW = datetime(2026, 6, 10, 12, 0, 0, tzinfo=timezone.utc)


def _make_repo(session):
    return test_result_repo.TestResultRepository(session)


def _postgres_sql(statement) -> str:
    return str(statement.compile(dialect=postgresql.dialect()))


@pytest.mark.asyncio
async def test_list_failed_by_run_filters_failed_and_error():
    session = MagicMock()
    result = MagicMock()
    rows = [SimpleNamespace(name="a"), SimpleNamespace(name="b")]
    result.scalars.return_value.all.return_value = rows
    session.execute = AsyncMock(return_value=result)
    repo = _make_repo(session)

    run_id = uuid4()
    returned = await repo.list_failed_by_run(run_id)

    assert returned == rows
    stmt = session.execute.await_args.args[0]
    sql = _postgres_sql(stmt)
    assert "test_result.run_id =" in sql
    assert "test_result.status IN" in sql
    assert "ORDER BY test_result.suite ASC, test_result.name ASC" in sql


@pytest.mark.asyncio
async def test_list_prior_observations_groups_rows_and_counts():
    session = MagicMock()
    result = MagicMock()
    # 查询按 (suite, name, rn) 排序返回；prior_count 为每用例窗口内总观测数。
    result.all.return_value = [
        SimpleNamespace(
            suite="s", name="a", status="failed", run_id=uuid4(),
            run_created_at=NOW - timedelta(hours=1), rn=1, prior_count=12,
        ),
        SimpleNamespace(
            suite="s", name="a", status="passed", run_id=uuid4(),
            run_created_at=NOW - timedelta(hours=2), rn=2, prior_count=12,
        ),
        SimpleNamespace(
            suite="s", name="b", status="error", run_id=uuid4(),
            run_created_at=NOW - timedelta(hours=1), rn=1, prior_count=1,
        ),
    ]
    session.execute = AsyncMock(return_value=result)
    repo = _make_repo(session)

    history, counts = await repo.list_prior_observations_for_failed_cases(
        run_id=uuid4(),
        project_id=uuid4(),
        cutoff=NOW - timedelta(days=30),
        before_created_at=NOW,
        before_run_id=uuid4(),
        per_case_limit=9,
    )

    assert counts == {("s", "a"): 12, ("s", "b"): 1}
    assert [row.status for row in history[("s", "a")]] == ["failed", "passed"]
    assert [row.status for row in history[("s", "b")]] == ["error"]

    stmt = session.execute.await_args.args[0]
    sql = _postgres_sql(stmt)
    # 窗口函数限行 + "本 run 之前" 的行序比较 + 自连接本 run 的失败行。
    assert "row_number() OVER (PARTITION BY" in sql
    assert "count(*) OVER (PARTITION BY" in sql
    assert ".rn <=" in sql
    assert "(run.created_at, run.id) <" in sql
    assert "test_result_1.run_id =" in sql
    assert "test_result_1.status IN" in sql
