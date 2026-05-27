# 测试质量运营台账

更新日期：2026-05-27

## Flaky 台账

当前无未关闭 flaky。新增 flaky 必须先登记再处理，不能直接靠重试掩盖。

| ID | 测试 | 失败环境 | 复现命令 | 最近证据 | Owner | 状态 | 截止条件 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| FLAKY-000 | 无活跃项 | - | - | 2026-05-27 本轮相关 unit/integration 均可重复通过 | 测试平台维护者 | closed | 出现首次非确定失败时新增条目 |

趋势记录：

| 日期 | required integration | unit | warning 摘要 | 处理结论 |
| --- | --- | --- | --- | --- |
| 2026-05-27 | `tests/integration/test_real_api_write_state.py` 7 passed | `tests/unit/test_api/test_notifications.py tests/unit/test_api/test_schedules.py` 10 passed | 无新增 warning；ruff targeted passed | 审计敏感值不落库和 delete before_state 进入真实 DB/API 证据，覆盖 credentials、environments、notification rules、schedules |
| 2026-05-27 | E2E targeted `special-regressions -g "archived logs"` 1 passed | frontend lint `--quiet` passed | 本地旧 Uvicorn/Vite 复用会造成归档接口路由级假阴性；验证时已用 `CI=1` 强制新进程 | 归档日志回看 + artifact 预览进入 nightly/manual 真实 E2E 证据；本地复现该链路时优先停旧服务或使用 `CI=1` |
| 2026-05-27 | required integration 94 passed / 18 deselected；完整 integration 102 passed / 10 skipped（未启动外部 API/worker 栈）；performance smoke 5 passed | unit + coverage 758 passed，coverage 83.37% | 已清理项目内 warning；第三方 testcontainers warning 精确过滤并登记；nightly/manual external-stack 主动启动 compose 后跑真实 worker smoke 与 worker_lost retry 黑盒 | 可继续作为 PR 门禁，nightly 承担重型/性能路径 |

## 缺陷回归流程

| 阶段 | 要求 |
| --- | --- |
| 发现 | 记录缺陷来源、影响租户/项目、失败日志、是否涉及安全/数据隔离 |
| 定位 | 先写能复现失败的自动化测试；跨租户、真实 DB、API 写入、worker 状态优先放 required integration |
| 修复 | 不为覆盖率添加无行为断言；外部 SMTP/S3/webhook 可 fake，但 DB/API/RBAC 链路必须真实 |
| 验证 | 本地跑新增测试、相关 suite、ruff；CI 失败摘要必须能指向具体测试和数据 |
| 关闭 | 在 PR/提交说明里写明回归测试路径；若只用 unit，说明为什么不需要 integration |

## 性能与非功能 Smoke

PR 不跑性能硬门禁，避免把环境抖动伪装成产品失败。nightly/manual 记录趋势，发现退化后再升格为专项性能测试。

| 项 | Nightly/Manual 入口 | 观察信号 | 升级条件 |
| --- | --- | --- | --- |
| API 与真实 DB smoke | `backend-integration-test` required + nightly/manual `tests/integration/test_performance_smoke.py` | pytest `--durations=20`、读/写 API p99 smoke、DB 写入/查询链路 | 同一测试连续 3 次进入慢榜前 5 且耗时翻倍，或 smoke 超过阈值 |
| Redis 日志 smoke | nightly/manual `tests/integration/test_performance_smoke.py` | Redis Stream 写入 + 读回 round trip | 连续 2 次超过阈值，转日志链路性能专项 |
| 归档日志回看 smoke | nightly/manual `tests/integration/test_performance_smoke.py` | `GET /runs/{run_id}/logs/archive` p99 smoke，失败摘要含 p50/p99/max | 连续 2 次超过阈值，转日志归档/对象存储专项 |
| Worker/container smoke | `heavy_docker` + `external_stack` integration | worker lost、cancel、state visibility、真实容器生命周期、真实 worker 后 artifact/download 与归档日志读回、worker_lost 后自动 retry 完成 | 同一 worker 路径连续 2 次超时、状态未收尾，或 artifact/log/retry 回看缺证据 |
| E2E 用户路径 | nightly 固定 real login / run trigger / special regressions，manual 全量 | 登录权限、创建项目到触发 run、结果/产物查看、归档日志回看、artifact 预览 | 任一路径 nightly 连续失败 2 次，转 P0 缺陷并补后端回归 |
| CI 稳定性 | 所有 job timeout + pytest durations + Docker pull retry | 超时、registry 前置失败、warning 摘要 | 非业务前置失败超过 1 周内 2 次，登记 flaky/infra 项 |
