# T05: F-EX-02 静默窗口

> **来源**：feature-catalog.md §4.1（F-EX-02；设计见 feature-catalog.md §4.3）
> **必要性**：P1（PRD §3.3 验收项，当前已完成）
> **预计**：M（后端 + 前端）
> **当前状态**：已落地到 API、worker、前端、unit、required integration 与 E2E 证据；保留本文作为实现口径档案。

## 背景

PRD §3.3 F-EX-02 验收"支持时区；支持静默窗口（如发布冻结期不触发）"。timezone 与项目级静默窗口均已实现：项目设置写入 `Project.settings.silent_windows`，cron 命中时不触发 Run，手动触发与 webhook 不受影响。

实现口径见 catalog §4.3。本文不再是未完成任务包，而是防止后续把 `quiet_windows` 与 `silent_windows` 混用的维护说明。

## Schema（关键 — 注意嵌入既有 settings JSONB）

`Project.settings` 已是 JSONB（见 `infra/database/models.py`），现有用法包含 `webhook_secret`。**不要新增 alembic 列**，直接嵌入：

```python
class SilentWindow(BaseModel):
    start_at: datetime  # 必须 tz-aware
    end_at: datetime
    reason: str = Field(min_length=1, max_length=200)

# Project.settings 路径：
{
  "webhook_secret": "...",
  "silent_windows": [
    {"start_at": "2026-06-30T00:00:00+08:00", "end_at": "2026-07-05T23:59:59+08:00", "reason": "Release freeze Q2"}
  ]
}
```

## 实施起点

- **领域/API schema**：`src/qaplatform/domain/models/project.py` 加 `SilentWindow` 类型；API 的 `ProjectUpdate` 接受 `silent_windows` 后合并进 `Project.settings["silent_windows"]`。注意 worker 读取的是 ORM `Project`，当前没有 `.silent_windows` 属性；要从 `project.settings` 解析为 `list[SilentWindow]`
- **cron tick**：`src/qaplatform/worker/settings.py::check_schedules` 创建 Run 前判断
- **入队参考**：`src/qaplatform/worker/scheduler.py` 仅负责 enqueue-side fair scheduler，不是 cron tick 入口
- **项目解析**：cron worker 内部没有 `CurrentUser`，不要照抄 API 的 `get_for_tenant(user.tenant_id)` 形态；可通过 `schedule.project_id` 读取 `Project`（或显式 eager-load `Pipeline.project`）来读取 `settings.silent_windows`。当前 `Pipeline.project` 不是 eager-loaded 关系，若走 pipeline 路径要避免 async lazy-load。对外 API 路由仍必须使用租户隔离查询，跨租户返回 404
- **路由**：`src/qaplatform/api/v1/projects.py` 的 `PUT /api/v1/projects/{project_id}` body schema 加 `silent_windows`
- **前端**：`frontend/src/pages/projects/detail.tsx`（项目设置区块）

## 判定函数

```python
# src/qaplatform/domain/services/schedule.py
from datetime import datetime


def is_in_silent_window(windows: list[SilentWindow], now: datetime) -> SilentWindow | None:
    """Returns the matching window, or None."""
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    # 判定为闭区间：start_at <= now <= end_at。
    return next((w for w in windows if w.start_at <= now <= w.end_at), None)
```

## 既有 quiet_windows 注意事项

当前代码已经有 schedule 级 `quiet_windows`：

- `src/qaplatform/infra/database/models.py` 的 `Schedule.quiet_windows`
- `src/qaplatform/api/schemas/projects.py` 经 `qaplatform.api.schemas` re-export 的 `ScheduleCreate/Update/Response.quiet_windows`
- `src/qaplatform/domain/services/scheduling.py::should_fire`

当前已新增 project 级 `Project.settings.silent_windows`，用于发布冻结期等绝对时间窗口。实现时不要把两者混为一谈：`silent_windows` 命中时必须写 audit，且不更新 `schedule.last_run_at`；既有 `quiet_windows` 目前只是 schedule 级跳过逻辑。

## 调度行为（修改 `worker/settings.py::check_schedules`）

伪代码：

```python
async def trigger_schedule(schedule, now):
    # Worker cron 内部没有 CurrentUser；schedule 来源于数据库，不是外部传入的租户 ID。
    project = await repos.project.get_by_id(schedule.project_id)
    if project is None:
        return
    windows = parse_silent_windows((project.settings or {}).get("silent_windows", []))
    if w := is_in_silent_window(windows, now):
        # AuditEvent 当前没有 metadata 列；把非敏感详情写入 after_state。
        await repos.audit.create(
            tenant_id=project.tenant_id,
            user_id=None,
            action="schedule_skipped_silent_window",
            resource_type="schedule",
            resource_id=schedule.id,
            after_state={
                "schedule_id": str(schedule.id),
                "window": w.model_dump(mode="json"),
            },
        )
        return  # 不创建 Run，不更新 last_run_at
    # ... 正常创建 Run
```

## 验收标准

- [x] `PUT /api/v1/projects/{project_id}` 接受 silent_windows，校验 `end_at > start_at`、单项目 ≤ 20 条窗口
- [x] cron tick 命中窗口 → 不创建 Run + 写 audit `schedule_skipped_silent_window`
- [x] audit 的 `after_state` 包含 `schedule_id` 与命中的 `window`（当前 `AuditEvent` 无 `metadata` 列，不为 T05 新增 audit schema migration）
- [x] cron tick 命中窗口 → schedule 的 `last_run_at` 不更新
- [x] **手动触发 / Webhook 触发 完全忽略 silent_windows**
- [x] 时区敏感：start_at/end_at 必须 tz-aware，不接受 naive datetime
- [x] 前端项目设置页可添加/删除/编辑窗口
- [x] 单元测试：is_in_silent_window 边界（窗口起止时刻、跨夜、不同时区）
- [x] 集成测试：真实 API/DB 保存、window 内 cron tick、window 外 cron tick、手动触发与 webhook 不受影响

## 约束

- audit 写入必须使用不含 secret/PII 的 dict/schema；cron worker 没有 `CurrentUser`，不要调用依赖 user 的 API helper；当前 `AuditEvent` 没有 `metadata` 列，静默窗口跳过详情写入 `after_state`
- commit 拆分建议：
  1. `feat: 项目设置加 silent_windows schema 与 API 校验`
  2. `feat: worker 调度器在静默窗口内跳过 cron 触发`
  3. `feat: 项目设置页添加静默窗口编辑器`
  4. `test: 静默窗口边界与跳过审计的单元+集成测试`

## 不要做

- 不要做周期性窗口（如"每周末"），未来扩展 `cron_pattern` 字段时再加
- 不要 alembic 加新列（嵌入 `settings` JSONB）
- 不要让静默窗口影响手动触发（用户旅程明确只针对 cron）
