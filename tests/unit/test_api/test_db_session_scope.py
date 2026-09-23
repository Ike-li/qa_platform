"""请求级 DB session 必须在响应发出之前提交。

FastAPI 的 yield 依赖默认是 request scope：退出代码在 `await response(...)`
之后才执行（见 fastapi/routing.py 的 request_stack）。对 `_get_db_session`
来说，这意味着客户端先收到 201、事务后提交——

- 客户端紧接着发的下一个请求可能读不到刚创建的数据。2026-09-22 的
  release_candidate gate 里，创建 pipeline 拿到 201 后 6ms 触发 run，
  得到 404 "Pipeline not found"；
- commit 本身失败时，客户端已经拿到了成功响应，数据却回滚了。

`scope="function"` 让退出代码在端点返回后、响应发出前执行。

同一请求内所有声明必须一致：依赖缓存键包含 scope，混用两种 scope 会让
同一个请求拿到两个不同的 session，写入分散在两个事务里。
"""

from __future__ import annotations

from fastapi.routing import APIRoute

from qaplatform.api.deps import _get_db_session
from qaplatform.dependencies import get_db_session

SESSION_DEPENDENCIES = {_get_db_session, get_db_session}


def _session_dependants(dependant, path=()):
    for sub in dependant.dependencies:
        trail = (*path, getattr(sub.call, "__name__", repr(sub.call)))
        if sub.call in SESSION_DEPENDENCIES:
            yield trail, sub
        yield from _session_dependants(sub, trail)


def _api_routes(routes):
    # FastAPI 0.141 起 include_router 不再把子路由展开进 app.routes，
    # 而是包成 _IncludedRouter，原路由挂在 original_router 上
    for route in routes:
        if isinstance(route, APIRoute):
            yield route
        elif (inner := getattr(route, "original_router", None)) is not None:
            yield from _api_routes(inner.routes)


def test_every_db_session_dependency_commits_before_the_response_is_sent():
    from qaplatform.main import create_app

    app = create_app()
    offenders = []
    checked = 0
    for route in _api_routes(app.routes):
        for trail, sub in _session_dependants(route.dependant):
            checked += 1
            if sub.scope != "function":
                offenders.append(f"{route.path} via {' -> '.join(trail)}")

    # 防止遍历方式失效后变成空断言
    assert checked > 0
    assert offenders == []
