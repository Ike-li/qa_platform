# T06: F-EX-03 Webhook 分支过滤 + 同 commit 去重

> **来源**：feature-catalog.md §4.1（F-EX-03）
> **必要性**：P1（未达 PRD §3.3 验收）
> **预计**：S

## 背景

PRD §3.3 F-EX-03 验收"支持分支过滤；支持去重（同 commit 不重复触发）"。当前 `api/v1/webhooks.py` 仅做 HMAC-SHA256 签名验证，**两项过滤都缺**。

`Run.dedup_key` 字段已在 ORM（`infra/database/models.py`，包含 partial unique index），仅缺路由层接入。

## 实施起点

- **路由**：`src/qaplatform/api/v1/webhooks.py`（HMAC 验签后、创建 Run 前加过滤）
- **当前响应声明注意**：`webhook_trigger` 目前声明 `response_model=RunResponse`、`status_code=201`。`filtered` / `duplicate` 分支返回的不是 `RunResponse`，实现时必须用 `JSONResponse(status_code=200, content={...})` 或调整 response model/status code 以绕过 `RunResponse` 校验；不要照搬 Flask 风格 `return {...}, 200`
- **当前请求 schema 注意**：`WebhookTriggerRequest` 目前只有 `git_ref`、`git_sha`、`metadata`，没有完整 Git provider payload。分支过滤优先从 `body.git_ref` 解析 `refs/heads/main -> main`；repo/provider 可从 `body.metadata` 或 `project.git_url` 补足。`body.git_sha` 缺失时无法做“同 commit”去重，应保持兼容：跳过去重但仍可做分支过滤
- **Project 配置**：嵌入既有 `Project.settings` JSONB（与 `webhook_secret` 同源）：
  ```json
  {
    "webhook_secret": "...",
    "allowed_branches": ["main", "release/*"]
  }
  ```
- **配置校验**：当前 `ProjectCreate/Update.settings` 是自由 `dict`；实现 `allowed_branches` 时必须校验它是 `list[str]`，元素为非空字符串并限制数量/长度（例如 ≤ 50 条、每条 ≤ 200），避免字符串被当作字符序列参与 `fnmatch`
- **去重字段**：`Run.dedup_key` 已存在（`src/qaplatform/infra/database/models.py`），ORM 已有 partial unique index 仅对活跃状态去重

## 实现细节

### 分支过滤
```python
allowed = (project.settings or {}).get("allowed_branches", [])
if allowed:
    branch_name = parse_branch_from_ref(body.git_ref)  # e.g. refs/heads/main → main
    if not any(fnmatch(branch_name, pattern) for pattern in allowed):
        log.info("webhook_branch_filtered", branch=branch_name, allowed=allowed)
        return JSONResponse(
            status_code=200,
            content={"status": "filtered", "reason": "branch_not_allowed"},
        )
```

### 同 commit 去重
```python
dedup_key = None
if body.git_sha:
    dedup_key = f"{provider}:{repo_url}:{body.git_sha}:{branch_name}"
# 创建 Run 时传 dedup_key=dedup_key
# 数据库层 partial unique index 会防止重复（status IN queued/preparing/running/collecting）
# 如果 IntegrityError 捕获 → rollback 后返回 JSONResponse(status_code=200, content={"status": "duplicate"})
```

## 验收标准

- [ ] `Project.settings.allowed_branches` 空时不过滤（默认全部允许）
- [ ] `Project.settings.allowed_branches` 非空时必须是合法 `list[str]`，非法类型/空字符串在项目配置写入时被 422 拒绝
- [ ] 非空时按 fnmatch 通配符匹配；不匹配 → 200 OK 返回 `{"status": "filtered"}`，不创建 Run
- [ ] 同 commit 在活跃状态时再次 push → 200 OK 返回 `{"status": "duplicate"}`，不创建新 Run
- [ ] `filtered` / `duplicate` 响应不会被当前 `RunResponse` response model 校验拦截
- [ ] `git_sha` 缺失时不做 dedup，但仍按 `git_ref` 做分支过滤并保持既有 webhook 兼容
- [ ] 已完成（done/failed/cancelled）的同 commit 可以再次触发（partial unique index 不冲突）
- [ ] 单元测试：
  - allowed_branches 空 / 单分支 / 通配符 (`release/*`) / 全部不匹配 4 种用例
  - dedup IntegrityError → 200 不抛 500
- [ ] 集成测试：
  - 同 commit 双触发，第二次返回 duplicate
  - 不允许的分支返回 filtered

## 约束

- HTTP 状态码：过滤 / 重复 都返回 **200**（不是 4xx，避免 Git 平台标记为失败）
- commit 拆分：
  1. `feat: Project.settings.allowed_branches 字段支持 webhook 分支过滤`
  2. `feat: webhook 创建 Run 时传 dedup_key 实现同 commit 去重`
  3. `test: webhook 分支过滤与去重单元+集成测试`

## 不要做

- 不要新加 alembic 列（嵌入 settings JSONB）
- 不要支持正则（fnmatch 通配符够用）
- 不要对手动触发应用 allowed_branches（PRD 只针对 Webhook）
