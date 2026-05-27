# 后端测试审计与补强记录

审计日期：2026-05-27

## 结论

后端测试已有较好的单元测试基础，但原 CI 只运行 `pytest --cov=qaplatform`，没有显式覆盖率失败门槛，也没有开启分支覆盖；因此“测试是否完善”的口径不能只看通过数。

本轮按综合口径补强：

- 覆盖率指标：启用 coverage branch mode，CI 使用 `--cov-report=term-missing`，并设置 `fail_under = 83`。
- 关键业务路径：补齐 pipeline API CRUD/404/跨项目风险、调度服务、worker 队列调度、worker 周期任务、插件注册、日志配置。
- 安全风险路径：补齐 JWT/API token 鉴权中间件的缺失 Authorization、token 类型、过期/无效、撤销、平台管理员 DB 复核、API token 过期/撤销/secret 校验和 last-used best-effort 回滚。
- CI 稳定性：去掉生产 `Test*` 类型被 pytest 当成测试收集的警告；修正部分测试中同步 `session.add` 被 `AsyncMock` 化导致的 RuntimeWarning。

## 覆盖率基线

验证命令：

```bash
PYTHONDONTWRITEBYTECODE=1 COVERAGE_FILE=/tmp/qaplatform-final.coverage .venv/bin/python -m pytest tests/unit -q -p no:cacheprovider --cov=qaplatform --cov-report=term-missing --cov-report=json:/tmp/qaplatform-final-coverage.json
```

当前结果：

- 单元测试：729 passed
- 总覆盖率：83.24%
- 语句覆盖率：85.88%
- 分支覆盖率：69.16%
- warnings：23

关键补强模块：

| 模块 | 本轮后覆盖率 | 判断 |
| --- | ---: | --- |
| `qaplatform.api.auth.middleware` | 98% | 安全主干和失败分支已覆盖，分支覆盖 100% |
| `qaplatform.domain.services.scheduling` | 100% | 调度计算核心已覆盖 |
| `qaplatform.plugins.registry` | 100% | 插件注册/发现路径已覆盖 |
| `qaplatform.logging` | 100% | JSON/console logging 配置已覆盖 |
| `qaplatform.worker.scheduler` | 95% | 队列容量、优先级、去重入队路径已覆盖 |
| `qaplatform.worker.settings` | 89% | 周期任务、资源回收、失败补偿路径已覆盖 |
| `qaplatform.api.v1.pipelines` | 84% | Pipeline API 主路径和常见失败路径已覆盖 |

## 门禁说明

`fail_under = 83` 是当前有效补强后的可持续门槛，而不是为了数字最大化设定的目标。设置 84% 在当前代码形态下会失败；继续硬抬主要会落到数据库 repository CRUD、依赖注入 glue、外部 SDK 初始化等区域，容易变成重 mock 的覆盖率工程。

后续提升覆盖率应优先靠真实风险路径或集成测试补齐，而不是仅为全局百分比补空行。

## 残余缺口

- 数据库 repositories 覆盖偏低：更适合通过真实 Postgres 集成测试验证筛选、分页、事务和唯一约束，不建议用纯 mock 单测强刷。
- 分支覆盖率仍低于语句覆盖率：主要来自 API 路由的错误分支、通知 channel 网络异常矩阵和依赖初始化分支。
- warnings 剩余 23 个：主要是 testcontainers/HTTPX/PyJWT 外部弃用提示、SQLAlchemy relationship overlap 提示，以及 SSE 测试里的 Starlette/AsyncMock RuntimeWarning。

## 后续优先级

1. 为 repository 层建立更稳定的 Postgres 集成测试夹具，覆盖关键查询和事务边界。
2. 将 SSE 测试里的 AsyncMock session/redis 替换为更贴近真实协议的轻量 fake，减少 RuntimeWarning。
3. 扩展 webhook、notifications、runs/schedules 的错误分支测试，优先覆盖安全过滤、幂等去重和外部网络失败。
4. warnings 收敛到只剩明确接受的第三方弃用项后，再考虑把 `fail_under` 提升到 84+。
