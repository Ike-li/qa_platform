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
| 2026-05-27 | P0/P1 相关 integration targeted 通过 | P0/P1 相关 unit targeted 通过 | 已清理项目内 warning；第三方 testcontainers warning 精确过滤并登记 | 可继续作为 PR 门禁，nightly 承担重型路径 |

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
| API 与真实 DB smoke | `backend-integration-test` required + heavy/manual lane | pytest `--durations=20`、失败摘要、DB 写入/查询链路 | 同一测试连续 3 次进入慢榜前 5 且耗时翻倍 |
| Worker/container smoke | `heavy_docker` + `external_stack` integration | worker lost、cancel、state visibility、真实容器生命周期 | 同一 worker 路径连续 2 次超时或状态未收尾 |
| E2E 用户路径 | nightly 固定 real login / run trigger / special regressions，manual 全量 | 登录权限、创建项目到触发 run、结果/产物查看 | 任一路径 nightly 连续失败 2 次，转 P0 缺陷并补后端回归 |
| CI 稳定性 | 所有 job timeout + pytest durations + Docker pull retry | 超时、registry 前置失败、warning 摘要 | 非业务前置失败超过 1 周内 2 次，登记 flaky/infra 项 |
