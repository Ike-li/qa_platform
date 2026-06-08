# Release Candidate Gate 检查清单

本文档用于发版前手动触发并验证 `release_candidate` gate，确保执行引擎核心、真实 Docker 环境、性能 SLO 等 PR CI 不覆盖的关键路径已验证。

---

## 背景

PR/push 触发的 `pr_like` CI 档**只跑轻量集成测试和一个 E2E**（`auth-flow.spec.ts`），以下测试**只在 nightly 和 release_candidate 档跑**：

- `heavy_docker` — 真实 Docker 镜像拉取、OOM 映射、容器启动失败路径
- `external_stack` — 真实 API + worker 栈（非 in-process ASGI）
- `performance` — 性能 SLO 基线与趋势监控
- `openapi_contract` — 完整 OpenAPI 契约冒烟
- 完整 Playwright E2E 套件（非仅 auth-flow）

**发版前必须手动触发 RC gate 并确认全绿**，否则执行引擎核心回归无人验证。

---

## 前置条件

- [ ] P1 修复已合并到 `main` 分支（commit `86b5bf8` 或更新）
- [ ] 本地所有门禁已通过：
  ```bash
  # 已在 P1 修复时验证通过
  .venv/bin/python -m pytest tests/unit -q                    # 1526 passed
  .venv/bin/ruff check src tests scripts                      # All checks passed
  .venv/bin/python scripts/check_tenant_isolation.py --self-test
  .venv/bin/python scripts/export_openapi.py
  ```
- [ ] Git 工作区干净（无未提交改动）

---

## 步骤 1：触发 release_candidate gate

### GitHub Actions 手动触发

1. 访问：https://github.com/YOUR_ORG/qa_platform/actions/workflows/ci.yml
2. 点击右上角 **"Run workflow"**
3. 选择分支：`main`
4. 选择 `gate` 参数：**`release_candidate`**
5. 点击 **"Run workflow"** 确认

### 预期运行时间

- 总耗时：**~15-25 分钟**（取决于 Docker 镜像缓存、testcontainers 启动）
- 关键阶段：
  - `backend-integration-test` (heavy_docker + external_stack)：~10-15 分钟
  - `e2e-test` (完整 Playwright)：~5-8 分钟
  - `performance-slo`：~2-3 分钟

---

## 步骤 2：监控运行并验证关键证据

### 2.1 后端集成测试（必看）

**Job**: `backend-integration-test`

检查点：
- [ ] `heavy_docker` 标记的测试已运行（非 deselected）
  - 包含：真实 Docker 镜像拉取、OOM 检测、容器启动失败路径
  - **重点**：验证记忆 [[project_platform_bugs_found]] #6 ExitResult 崩溃 bug 在真实 OOM 用例中**不复现**
- [ ] `external_stack` 标记的测试已运行
  - 真实 API + worker 栈（非 in-process），验证 arq 任务队列、真实 Redis/PG 交互
- [ ] 无 skip/xfail 假绿（evidence manifest 会拦截，但手动复查）
- [ ] 日志中无 `ExitResult.__init__() missing 2 required positional arguments` 错误

**验证命令**（在 Actions 日志中搜索）：
```
grep "heavy_docker" log
grep "external_stack" log
grep "ExitResult.*missing.*arguments" log  # 应无结果
```

### 2.2 E2E 测试（必看）

**Job**: `e2e-test`

检查点：
- [ ] 完整 Playwright 套件运行（非仅 auth-flow）
- [ ] 冒烟测试矩阵覆盖 6 页面 83 测试点（见 `scripts/smoke/` README）
- [ ] Evidence manifest 校验通过：
  - `actual_testcase_count >= expected_testcase_count`
  - 无 `result.status == "skipped"` 的必跑用例
- [ ] Artifact `playwright-report` 可下载（手动复查失败截图，如有）

**关键文件**（Actions artifacts）：
- `playwright-report/` — HTML 报告，失败有截图
- `e2e-manifest-*.json` — evidence 元数据

### 2.3 性能 SLO（建议看）

**Job**: `performance-slo`

检查点：
- [ ] SLO 基线测试通过（API 响应时间、列表查询延迟）
- [ ] 无性能退化警告（与历史基线对比）
- [ ] Artifact `performance-slo/` 可下载

**可接受阈值**（参考 `ci.yml` performance 段）：
- API 端点 p95 < 500ms
- 列表查询 (1000 条) p95 < 200ms

### 2.4 OpenAPI 契约（建议看）

**Job**: `frontend-api-contract`

检查点：
- [ ] `openapi-contract` 标记的冒烟测试通过
- [ ] `openapi.json` 导出成功且与前端 types 一致

---

## 步骤 3：evidence 汇总验证

**Job**: `release-gate-summary`

这个 job 汇总所有 evidence manifest 并生成 `release-evidence.md`。

检查点：
- [ ] Job 状态：✅ 绿色
- [ ] Artifact `release-gate-evidence/release-evidence.md` 内容示例：
  ```
  release_candidate_gate=passed
  required_jobs=lint-and-type-check,backend-test,frontend-api-contract,backend-integration-test,frontend-build,e2e-test
  evidence=frontend-api-contract,openapi-contract,api-test-quality,required-integration,heavy-docker,external-stack,performance-slo,full-playwright
  
  # Backend Integration Evidence
  mode=required,heavy_docker,external_stack
  testcase_count=565
  actual_testcase_count=565
  oom_candidate_tests=test_run_executor_oom_detection,test_docker_backend_memory_limit
  
  # E2E Evidence
  mode=full-playwright
  testcase_count=83
  actual_testcase_count=83
  ```
- [ ] 所有 `*_count` 匹配（actual >= expected）
- [ ] `oom_candidate_tests` 列表非空（确认 OOM 测试已跑）

---

## 步骤 4：关键 bug 确认（记忆遗留）

根据记忆 [[project_platform_bugs_found]]，以下 bug 在静态代码层已解决，需在 RC gate 运行态确认：

### ExitResult #6 崩溃 bug

**现象**（历史）：容器启动失败时 `ExitResult.__init__() missing 2 required positional arguments: 'started_at' and 'finished_at'`

**静态验证**（已完成）：
- 所有 5 处 `ExitResult(...)` 调用点已审查，均带 `started_at/finished_at`
- `docker_backend.py:199,216` + `executor.py:500,572,683`

**运行态验证**（本次 RC gate）：
- [ ] `backend-integration-test` 日志中**无** `ExitResult.*missing.*arguments` 错误
- [ ] `heavy_docker` 档的 OOM 测试通过（这是最易触发该 bug 的场景）
- [ ] 如有容器启动失败用例（镜像不存在/权限不足），终态正常写入 FAILED

**验证方法**：
```bash
# 下载 backend-integration-test 日志，本地搜索
grep -i "ExitResult" backend-integration-test.log
grep -i "missing.*arguments" backend-integration-test.log
# 应无匹配或仅有正常调用日志
```

---

## 步骤 5：最终 Go/No-Go 决策

### ✅ Go（可发版）条件

- [ ] 所有 jobs 绿色（lint、test、integration、e2e、performance、summary）
- [ ] Evidence manifest 校验通过（无 skip 假绿、计数匹配）
- [ ] ExitResult #6 bug 无复现（日志搜索干净）
- [ ] 无新的 P0/P1 问题（失败截图/日志中无安全/数据损坏风险）

### 🔴 No-Go（阻塞发版）条件

任一条件满足即阻塞：
- 任何 required job 失败（lint/test/integration/e2e/build）
- Evidence manifest 校验失败（skip 假绿、计数不足）
- ExitResult #6 bug 复现（容器失败路径崩溃）
- 发现新的安全/数据损坏风险

### ⚠️ 条件 Go（有风险但可接受）

- Performance SLO 轻微退化（<10%）但在可接受范围
- 非必跑的 E2E 用例偶发 flaky（可记录 issue 但不阻塞）

---

## 步骤 6：发版后验证（可选）

如果 RC gate 全绿并决定发版，建议在 staging/production 首次部署后验证：

- [ ] 启动时使用占位 JWT secret → **应拒绝启动**（P1-1 守护生效）
- [ ] 启动时 `ENVIRONMENT=production` + `DEBUG=true` → **应拒绝启动**
- [ ] `seed_admin.py` 未设 `ADMIN_PASSWORD` → **应拒绝**（P1-2 生效）
- [ ] 真实 run 执行一次完整链路（clone → setup → test → collect → 产物上传）
- [ ] SSE 实时日志流可正常订阅
- [ ] Webhook 触发（如有配置）可正常入队

---

## 附录：快速验证脚本

将以下脚本保存为 `scripts/verify_rc_gate.sh`，用于自动检查 Actions 日志（需 `gh` CLI）：

```bash
#!/usr/bin/env bash
set -euo pipefail

RUN_ID="${1:-}"
if [[ -z "$RUN_ID" ]]; then
  echo "Usage: $0 <workflow_run_id>"
  echo "Get run_id from: gh run list --workflow=ci.yml"
  exit 1
fi

echo "=== Downloading logs for run $RUN_ID ==="
gh run download "$RUN_ID" --name backend-integration-test-logs || true
gh run download "$RUN_ID" --name e2e-test-logs || true
gh run download "$RUN_ID" --name release-gate-evidence || true

echo ""
echo "=== Checking ExitResult bug (should be empty) ==="
grep -r "ExitResult.*missing.*arguments" . 2>/dev/null || echo "✅ No ExitResult crash"

echo ""
echo "=== Checking heavy_docker ran (should have matches) ==="
grep -r "heavy_docker" . 2>/dev/null | head -3 || echo "⚠️  No heavy_docker marker found"

echo ""
echo "=== Checking external_stack ran (should have matches) ==="
grep -r "external_stack" . 2>/dev/null | head -3 || echo "⚠️  No external_stack marker found"

echo ""
echo "=== Evidence summary ==="
cat release-gate-evidence/release-evidence.md 2>/dev/null || echo "⚠️  No evidence file"

echo ""
echo "✅ Manual review complete. Check above for warnings."
```

**用法**：
```bash
chmod +x scripts/verify_rc_gate.sh
gh run list --workflow=ci.yml --branch=main | grep release_candidate | head -1
# 获取 run_id（第一列）
./scripts/verify_rc_gate.sh <run_id>
```

---

## 更新记录

- 2026-06-08: 初版，基于上线审查报告生成
- 覆盖 P1 修复后的首次 RC gate 验证清单
