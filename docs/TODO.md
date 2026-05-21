# QA 平台开发 TODO

> 基于 [prd.md](prd.md) 逐项核对，2026-05-19 更新

---

## Phase 1: MVP（核心执行循环） ✅ 全部完成

| ID | 功能 | 状态 | Commit |
|----|------|------|--------|
| F-PM-01 | 创建项目 | ✅ | — |
| F-PM-02 | 凭证管理 | ✅ | — |
| F-PM-03 | 项目归档 | ✅ | P0 |
| F-PL-01 | 定义管道 | ✅ | — |
| F-PL-02 | 环境配置 | ✅ | — |
| F-PL-03 | 资源限制 | ✅ | — |
| F-EX-01 | 手动触发 | ✅ | — |
| F-EX-04 | 执行隔离 | ✅ | — |
| F-EX-05 | 实时日志 | ✅ | — |
| F-EX-06 | 取消执行 | ✅ | — |
| F-RE-01 | 结构化结果 | ✅ | — |
| F-RE-02 | 执行摘要 | ✅ | — |
| F-RE-03 | 失败详情 | ✅ | — |
| F-RE-04 | 产物管理 | ✅ | — |
| F-AU-01 | 用户认证 | ✅ | — |
| F-AU-03 | 角色权限 | ✅ | — |
| F-LS-01 | 执行列表过滤 | ✅ | — |
| F-LS-02 | 分页 | ✅ | — |
| F-LS-03 | 项目搜索 | ✅ | — |
| F-LS-04 | 测试结果过滤 | ✅ | — |

---

## Phase 2: 自动化与通知 — 差 3 项

| ID | 功能 | 状态 | Commit |
|----|------|------|--------|
| F-EX-02 | Cron 定时触发 | ✅ | `3c947f7` |
| F-EX-03 | Webhook 触发 + 签名验证 | ✅ | `b1d4b3a` |
| F-NT-01 | 条件通知 | ✅ | `7f4abc0` |
| F-NT-02 | 多渠道通知 | ⚠️ | `1978228` |
| F-NT-03 | 通知模板 | ✅ | `08fdf90` |
| F-EX-07 | 自动重试 | ✅ | `bf49efd` |
| **F-EX-08** | **优先级队列** | ❌ | — |
| **F-AU-02** | **API Token** | ✅ | `55228e8` |
| F-AU-04 | 租户隔离 | ✅ | — |
| — | 批量操作 | ✅ | `b2d4a95` |

### F-NT-02 多渠道通知 — 已实现 vs PRD 要求

| 渠道 | 状态 | 说明 |
|------|------|------|
| Email (SMTP) | ✅ | smtplib + asyncio |
| Webhook (HTTP) | ✅ | httpx |
| **钉钉** | ❌ | PRD 约束：需支持中国大陆网络 |
| **企业微信** | ❌ | PRD 约束：需支持中国大陆网络 |
| **Slack** | ❌ | Slack Incoming Webhook |

### F-EX-08 优先级队列

PRD 描述：高优先级任务插队；同优先级 FIFO。

当前状态：Run 模型有 `priority` 字段，但 worker 调度未实现优先级排序。

实现要点：
- worker 取任务时按 `priority DESC, created_at ASC` 排序
- API 触发时可指定 priority（默认 0，高优先级 > 0）

### F-AU-02 API Token

PRD 描述：支持生成长期 API Token，可配置 scope 和过期时间，支持吊销。

实现要点：
- 新增 `api_tokens` 表（id, user_id, name, token_hash, scopes, expires_at, revoked_at）
- API 端点：POST /tokens（创建）、GET /tokens（列表）、DELETE /tokens/{id}（吊销）
- 认证中间件支持 Bearer Token（除 JWT 外）

---

## Phase 3: 洞察与报告 — 差 5 项

| ID | 功能 | 状态 | Commit |
|----|------|------|--------|
| — | 项目质量仪表盘 | ✅ | `1c081f1` |
| F-RE-05 | 用例级历史趋势 | ✅ | `1c081f1` |
| — | Flaky test 检测 | ✅ | `b2d4a95` |
| **—** | **跨分支/跨环境对比** | ❌ | — |
| **—** | **Allure 报告集成** | ❌ | — |
| **—** | **日志搜索** | ❌ | — |
| **—** | **数据导出（CSV）** | ❌ | — |
| **—** | **系统状态页** | ❌ | — |

### 跨分支/跨环境对比

PRD 用户旅程 5.3：测试经理需要对比 release 分支和 main 分支的质量。

实现要点：
- analytics API 支持 `branch` 参数过滤
- 前端对比视图：选择两个分支，展示通过率趋势对比

### Allure 报告集成

PRD 提及：HTML 报告在线预览（Phase 1 延至此处）。

实现要点：
- 产物存储中识别 Allure 报告（index.html）
- iframe 预览 + 预签名 URL 下载

### 日志搜索

PRD 用户旅程 5.4：需要定位卡住位置。

实现要点：
- SSE 日志流支持关键字过滤参数
- 历史日志支持全文搜索

### 数据导出

PRD：测试结果 CSV、执行历史。

实现要点：
- GET /runs/{id}/results/export?format=csv
- GET /projects/{id}/runs/export?format=csv

### 系统状态页

PRD：Worker 数量、队列深度、成功率。

实现要点：
- GET /admin/status 端点
- 前端状态页展示 worker 数、队列深度、最近 1h 成功率

---

## Phase 4: 规模化 — 未开始

| 功能 | 状态 | 说明 |
|------|------|------|
| Kubernetes Job 执行后端 | ❌ | 替代当前 Docker 直连 |
| 多 Worker 节点管理 | ❌ | Worker 注册 + 心跳 |
| 历史数据归档与分区 | ❌ | 按月分区，冷数据归档 |
| 更多运行器插件 | ❌ | Go test、Jest、Playwright |
| 开放插件市场 | ❌ | 远期目标 |

---

## 非功能需求检查

| 维度 | 指标 | 目标 | 当前状态 |
|------|------|------|----------|
| 响应时间 | 读 API p99 | < 100ms | 未测量 |
| 响应时间 | 写 API p99 | < 300ms | 未测量 |
| 日志延迟 | 实时推送 | < 2s | SSE 实现，未测量 |
| 安全 | 凭证加密 | AES-256-GCM | ✅ 已实现 |
| 安全 | API 防护 | Rate limit | ❌ 未实现 |
| 安全 | Webhook 签名 | HMAC-SHA256 | ✅ 已实现 |

---

## 建议优先级（下一步）

1. **API Token** (F-AU-02) — 外部系统集成必需，Phase 2 遗留
2. **优先级队列** (F-EX-08) — Phase 2 遗留，实现成本低
3. **钉钉/企业微信通知** (F-NT-02) — PRD 约束：中国大陆网络
4. **日志搜索** — 用户旅程 5.4 需要
5. **数据导出** — 测试经理需要 CSV 报告
6. **CI/CD 集成** — 防止回归（GitHub Actions）
7. **部署准备** — Docker Compose + migration 管理
