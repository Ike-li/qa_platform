# T05: F-EX-02 静默窗口

> **来源**：feature-catalog.md §4.1 #5（设计见 §4.3）
> **必要性**：P1（未达 PRD §3.3 验收）
> **预计**：M（后端 + 前端）

## 背景

PRD §3.3 F-EX-02 验收"支持时区；支持静默窗口（如发布冻结期不触发）"。timezone 已实现，**静默窗口未实现**。

设计已锁定（见 catalog §4.3），按规格实施即可，不要再做架构决策。

## Schema（关键 — 注意嵌入既有 settings JSONB）

`Project.settings` 已是 JSONB（line 186），现有用法包含 `webhook_secret`。**不要新增 alembic 列**，直接嵌入：

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

- **领域模型**：`src/qaplatform/domain/models/project.py` 加 `silent_windows: list[SilentWindow] = []`
- **scheduler**：`src/qaplatform/worker/scheduler.py` cron tick 创建 Run 前判断
- **路由**：`src/qaplatform/api/v1/projects.py` 的 `PUT /projects/{id}` body schema 加 `silent_windows`
- **前端**：`frontend/src/pages/projects/detail.tsx`（项目设置区块）

## 判定函数

```python
# 放 src/qaplatform/domain/services/schedule.py 或 schedule_service.py
def is_in_silent_window(windows: list[SilentWindow], now: datetime) -> SilentWindow | None:
    """Returns the matching window, or None."""
    if not windows:
        return None
    return next((w for w in windows if w.start_at <= now <= w.end_at), None)
```

## 调度行为（修改 `worker/scheduler.py`）

伪代码：

```python
async def trigger_schedule(schedule, now):
    project = await repos.project.get_for_tenant(...)
    if w := is_in_silent_window(project.silent_windows, now):
        await audit.write("schedule_skipped_silent_window",
                          actor=None, target=schedule.id,
                          metadata={"reason": w.reason, "window_end": w.end_at.isoformat()})
        return  # 不创建 Run，不更新 last_run_at
    # ... 正常创建 Run
```

## 验收标准

- [ ] `PUT /projects/{id}` 接受 silent_windows，校验 `end_at > start_at`、单项目 ≤ 20 条窗口
- [ ] cron tick 命中窗口 → 不创建 Run + 写 audit `schedule_skipped_silent_window`
- [ ] cron tick 命中窗口 → schedule 的 `last_run_at` 不更新
- [ ] **手动触发 / Webhook 触发 完全忽略 silent_windows**
- [ ] 时区敏感：start_at/end_at 必须 tz-aware，不接受 naive datetime
- [ ] 前端项目设置页可添加/删除/编辑窗口
- [ ] 单元测试：is_in_silent_window 边界（窗口起止时刻、跨夜、不同时区）
- [ ] 集成测试：window 内 cron tick + window 外 cron tick + 手动触发不受影响

## 约束

- audit 写入用 `_serialize(value.model_dump())` 脱敏
- commit 拆分建议：
  1. `feat: 项目设置加 silent_windows schema 与 API 校验`
  2. `feat: worker 调度器在静默窗口内跳过 cron 触发`
  3. `feat: 项目设置页添加静默窗口编辑器`
  4. `test: 静默窗口边界与跳过审计的单元+集成测试`

## 不要做

- 不要做周期性窗口（如"每周末"），未来扩展 `cron_pattern` 字段时再加
- 不要 alembic 加新列（嵌入 `settings` JSONB）
- 不要让静默窗口影响手动触发（用户旅程明确只针对 cron）
