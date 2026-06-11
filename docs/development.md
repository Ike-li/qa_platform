# 开发环境搭建

## 前置条件

- Python 3.12+
- Node.js 22.13+（或 20.19+；前端 Vite 8 / ESLint 10 需要）
- Docker & Docker Compose
- Homebrew (macOS)

## 快速启动

```bash
# 1. 复制环境变量
cp .env.example .env

# 2. 启动基础设施
make infra-up

# 3. 创建虚拟环境并安装依赖
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"

# 4. 执行数据库迁移
.venv/bin/alembic upgrade head

# 5. 创建默认 admin 用户
.venv/bin/python scripts/seed_admin.py

# 6. 启动 API
.venv/bin/uvicorn qaplatform.main:create_app --factory --reload
```

## 常用命令

以下 Makefile 目标默认在已激活虚拟环境，或 `PATH` 已包含 `.venv/bin` 时运行。

| 命令 | 说明 |
|------|------|
| `make infra-up` | 启动 PostgreSQL、Redis、MinIO |
| `make up` | 启动完整 Docker Compose 服务 |
| `make down` | 停止所有容器 |
| `make logs` | 查看容器日志 |
| `make migrate` | 执行 Alembic 迁移 |
| `make migrate-create msg="描述"` | 创建新迁移 |
| `make test` | 运行测试 |
| `make lint` | Ruff 静态检查 |
| `make format` | Ruff 格式化 |
| `make seed` | 创建默认 admin 用户 |

## 服务端口

| 服务 | 端口 |
|------|------|
| API | 8000 |
| PostgreSQL | 5432 |
| Redis | 6379 |
| MinIO API | 9000 |
| MinIO Console | 9001 |

## 测试

单元测试建议直接限定 `tests/unit`：

```bash
.venv/bin/pytest tests/unit -q
```

`make test` 会执行仓库 pytest 默认集合；目前 `tests/integration/test_auth_audit_failure_paths.py` 这类 testcontainers 用例未被 `RUN_INTEGRATION_TESTS` gate 掉，因此本地只想跑单元测试时不要用 `make test` 代替 `pytest tests/unit -q`。

集成测试位于 `tests/integration/`，单元测试位于 `tests/unit/`。集成测试分两类：部分用例会自启 testcontainers；多数重型 worker / Docker / API 栈用例需要 `RUN_INTEGRATION_TESTS=1` 才会运行，并可能需要完整 API / Worker / 基础设施栈；以后者为准时按下方步骤运行。

E2E 测试脚本定义在仓库根目录 `package.json`，不要在 `frontend/` 目录运行。运行前需要安装根目录 Playwright 依赖、`frontend/` 依赖，并按快速启动步骤创建 `.venv`，因为 Playwright 配置会用 `.venv/bin/python` 启动后端并执行迁移 / seed：

```bash
# 首次运行前
npm ci
npm ci --prefix frontend

# 稳定冒烟用例
npm run test:e2e -- tests/e2e/auth-flow.spec.ts

# 交互式 smoke 默认把 skip 当失败；探索性排查才显式允许 skip
# 可用 RESULTS_DIR=... 固定父级产物目录；子脚本证据会落在 <script-name>/ 下
./scripts/smoke/run-all.sh
SMOKE_ADMIN_PASSWORD="$E2E_ADMIN_PASSWORD" ./scripts/smoke/run-all.sh
SMOKE_ALLOW_SKIPS=1 ./scripts/smoke/run-all.sh

# 全量 E2E
E2E_ADMIN_PASSWORD=admin123 npm run test:e2e

# 本地真实 worker-backed E2E；脚本默认导出 QAP_E2E_WORKER=1，
# 因此 real-run-trigger 不会被环境门控跳过
E2E_ADMIN_PASSWORD=admin123 ./scripts/run-e2e.sh
```

### 运行集成测试

运行完整集成测试需要 Docker daemon 以及数据库等基础设施服务，且需要手动启动 API 和 Worker。未设置 `RUN_INTEGRATION_TESTS=1` 时多数重型集成测试会跳过，但少数 testcontainers 回归测试仍会运行。

```bash
# 1. 启动基础设施
docker compose up -d postgres redis minio

# 2. 数据库迁移和 Seed
.venv/bin/python -m alembic upgrade head
.venv/bin/python scripts/seed_admin.py

# 3. 后台启动后端 API 和 Worker
.venv/bin/python -m uvicorn qaplatform.main:create_app --factory --port 8000 --app-dir src &
.venv/bin/python -m arq qaplatform.worker.settings.WorkerSettings &

# 4. 执行集成测试
RUN_INTEGRATION_TESTS=1 .venv/bin/python -m pytest tests/integration/ -v -s

# 5. 完成后清理后台进程 (可用 jobs 命令查看然后 kill，或关闭终端)
kill %1 %2
```

## Dogfooding：导入本仓库 CI 测试结果（T14）

让本仓库自己的 CI 测试结果每天进入本地平台实例，平台从此有第一个真实数据流。
原理：`scripts/import_ci_results.sh`（pull 模式）用 `gh` 拉取 main 分支最近完成的
CI run 的 JUnit artifact，逐份调用 T11 导入接口
`POST /api/v1/projects/{project_id}/runs/import`。

### 1. 起本地实例

```bash
make infra-up
.venv/bin/python -m alembic upgrade head
.venv/bin/python -m uvicorn qaplatform.main:create_app --factory --port 8000 --app-dir src &
```

不需要 Worker——导入的 Run 直接以终态落库，不经过执行管线。

### 2. 建项目和 API token（一次性）

```bash
# 注册账号（已有账号跳过；登录需要 username + password + tenant_id）
curl -s -X POST http://localhost:8000/api/v1/auth/register \
  -H "Content-Type: application/json" \
  -d '{"username":"dogfood","email":"dogfood@qaplatform.dev","password":"<密码>"}'
# 响应里的 access_token 用于下面两步，user.tenant_id 留作以后登录用

# 建项目（记下响应里的 id → QAP_IMPORT_PROJECT_ID）
curl -s -X POST http://localhost:8000/api/v1/projects \
  -H "Authorization: Bearer <access_token>" -H "Content-Type: application/json" \
  -d '{"name":"qa-platform-ci","slug":"qa-platform-ci","git_url":"https://github.com/Ike-li/qa_platform.git","default_branch":"main"}'

# 签发 API token（记下响应里的 token → QAP_IMPORT_TOKEN；只需 run.trigger scope）
curl -s -X POST http://localhost:8000/api/v1/auth/tokens \
  -H "Authorization: Bearer <access_token>" -H "Content-Type: application/json" \
  -d '{"name":"ci-import","scopes":["run.trigger"]}'
```

### 3. 运行导入脚本

```bash
# 预览（不写入、不更新状态文件）
QAP_IMPORT_TOKEN=qap_xxx QAP_IMPORT_PROJECT_ID=<uuid> \
  ./scripts/import_ci_results.sh --dry-run --limit 5

# 真实导入
QAP_IMPORT_TOKEN=qap_xxx QAP_IMPORT_PROJECT_ID=<uuid> \
  ./scripts/import_ci_results.sh --limit 5
```

行为说明：

- 已处理的 CI run id 记录在 `.qap-import-state.json`（已 gitignore），重复运行不重复导入
- artifact 缺失或不含 JUnit XML 的 run 打印原因后跳过，不中断
- 每份 JUnit XML 生成一条独立 import Run；pipeline 按 artifact 区分：
  `ci-backend-unit` / `ci-backend-integration` / `ci-e2e` / `ci-frontend-unit`
- `QAP_IMPORT_URL` 可覆盖平台地址（默认 `http://localhost:8000`）

### 4. 每日定时（可选）

手动方式：每天跑一次第 3 步即可。

macOS launchd 方式——写入 `~/Library/LaunchAgents/dev.qaplatform.ci-import.plist`：

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>dev.qaplatform.ci-import</string>
  <key>ProgramArguments</key><array>
    <string>/bin/bash</string><string>-lc</string>
    <string>cd <仓库绝对路径> && QAP_IMPORT_TOKEN=qap_xxx QAP_IMPORT_PROJECT_ID=<uuid> ./scripts/import_ci_results.sh --limit 10</string>
  </array>
  <key>StartCalendarInterval</key><dict>
    <key>Hour</key><integer>9</integer><key>Minute</key><integer>30</integer>
  </dict>
  <key>StandardOutPath</key><string>/tmp/qap-ci-import.log</string>
  <key>StandardErrorPath</key><string>/tmp/qap-ci-import.log</string>
</dict></plist>
```

```bash
launchctl load ~/Library/LaunchAgents/dev.qaplatform.ci-import.plist
# 验证：launchctl list | grep qaplatform；日志在 /tmp/qap-ci-import.log
```
