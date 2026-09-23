# QA Platform

[English](README.md) | 简体中文

自托管的 QA 自动化执行与回归分析平台：在隔离的 Docker 容器里运行 pytest / Jest / Playwright / Go test，或从现有 CI 导入 JUnit XML，然后做失败分诊、只重跑失败用例、识别并隔离 flaky 测试，回答「这个版本能不能发」。

[![CI](https://github.com/Ike-li/qa_platform/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/Ike-li/qa_platform/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.12](https://img.shields.io/badge/python-3.12-blue.svg)](pyproject.toml)

> 📖 [架构](docs/architecture.md) · [功能清单](docs/feature-catalog.md) · [开发指南](docs/development.md) · [技术改进](docs/BACKLOG.md)

## 架构概览

```
┌──────────────┐     ┌──────────────┐     ┌──────────────┐
│   Frontend   │────▶│   FastAPI    │────▶│  arq Worker  │
│  React/Vite  │  80 │   API  :8000 │     │  (async job) │
└──────────────┘     └──────┬───────┘     └──────┬───────┘
                            │                     │
              ┌─────────────┼─────────────┐       │
              ▼             ▼             ▼       ▼
        ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌────────┐
        │PostgreSQL│ │  Redis   │ │  MinIO   │ │ Docker │
        │   :5432  │ │  :6379   │ │:9000/9001│ │  sock  │
        └──────────┘ └──────────┘ └──────────┘ └────────┘
```

| 层 | 技术栈 |
|---|---|
| 前端 | React 19 · Vite 8 · TailwindCSS 4 · TanStack Query · Radix UI · Recharts |
| 后端 API | FastAPI · Pydantic v2 · SQLAlchemy 2 (async) · Alembic |
| 任务队列 | arq (Redis-backed) |
| 执行引擎 | Docker (aiodocker) 容器化执行测试 |
| 存储 | PostgreSQL 16 · Redis 7 · MinIO (S3 兼容) |
| 可观测性 | structlog · Prometheus；OpenTelemetry 基础追踪装配已落地，OTLP HTTP exporter 依赖/部署验证待 T10 收口 |

## 核心功能

回归闭环：

- **外部结果导入** — 把任意 CI 产出的 JUnit XML 通过 API 导入为一次 Run，不必改造现有流水线
- **失败分诊** — 每个失败用例自动归入「新增失败 / 已知 flaky / 持续失败」，并按错误签名聚类
- **一键重跑失败** — 只重跑上次失败的用例（当前支持 pytest）
- **Flaky 检测与隔离** — 识别时好时坏的用例；隔离后仍照常执行，但不再计入发版判断和「新增失败」通知，可设过期时间
- **发版判断** — 对比目标分支与基线的通过率（含剔除 flaky 后的通过率）、新增失败与恢复用例
- **条件通知** — 按状态、通过率、连续失败、新增失败、恢复等条件推送到 Email / Webhook / 钉钉 / 企业微信

平台能力：

- **多租户 RBAC** — 租户级 (Owner/Admin/Member/Viewer) + 项目级 (Admin/Developer/Viewer) 双层权限
- **流水线管理** — 定义测试流水线，配置运行环境与凭据存储；私有 HTTPS token / SSH key 可在执行时安全注入 Git clone
- **容器化执行** — 测试在隔离 Docker 容器中运行，支持超时、取消与 Docker OOMKilled 状态识别
- **实时日志** — SSE 推送执行日志，终态 Run 可从 S3 归档日志回看
- **插件系统** — Runner / Collector / Source 三类插件协议，内置 pytest、Jest、Playwright、Go test、JUnit、Git
- **产物管理** — 递归上传 `results/` 到 S3，支持数量/大小限制、预签名下载与 HTML/Allure 预览
- **审计日志** — 关键操作审计，提供 `/api/v1/audit-events` 查询；API 写路径审计基线由架构契约锁住，新增写接口必须同步审计与脱敏回归
- **定时调度** — Cron 风格定时触发测试流水线

## 快速开始

### 前置依赖

- Docker & Docker Compose
- Python >= 3.12
- Node.js >= 22.13（与 `frontend/package.json` 的 `engines` 一致）

### 1. 克隆与配置

```bash
git clone https://github.com/Ike-li/qa_platform.git && cd qa_platform
cp .env.example .env
# 按需修改 .env 中的配置
```

### 2. 启动基础设施

```bash
make infra-up   # 仅启动 PostgreSQL、Redis、MinIO
```

### 3. 初始化数据库

```bash
# 创建虚拟环境并安装后端依赖
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"

# 执行迁移
.venv/bin/alembic upgrade head

# (可选) 导入种子数据。ADMIN_PASSWORD 是必填项，脚本不提供默认密码
ADMIN_PASSWORD='<your-strong-password>' .venv/bin/python scripts/seed_admin.py
```

> **依赖版本与 CI 保持一致**
>
> CI 从 `uv.lock` 安装精确版本（`uv export --frozen` + `pip install -r`），
> 上面的 `pip install -e ".[dev]"` 装的是当前可得的最新版，两者可能不同。
> 需要完全对齐时用 `uv sync --frozen`，或先 `uv pip install -e '.[dev]' --upgrade`。
>
> **改动 `pyproject.toml` 的依赖后必须运行 `uv lock` 并提交 `uv.lock`**，
> 否则 CI 的 `uv lock --check` 会失败。

> 登录账号为 `admin`，密码即上面设置的 `ADMIN_PASSWORD`。

### 4. 启动后端

```bash
.venv/bin/uvicorn qaplatform.main:create_app --factory --reload --port 8000
```

### 5. 启动前端

```bash
cd frontend
npm ci
npm run dev   # 默认 http://localhost:5173
```

### 6. 启动 Worker（可选，执行测试需要）

```bash
.venv/bin/arq qaplatform.worker.settings.WorkerSettings
```

### Docker 一键部署

```bash
cp .env.example .env
make up   # 构建并启动完整服务（postgres, redis, minio, api, frontend, workers）

# API 容器起来后：建表并创建管理员
docker compose exec api python -m alembic upgrade head
docker compose exec -e ADMIN_PASSWORD='<your-strong-password>' api python scripts/seed_admin.py
```

打开 http://localhost:3001，用 `admin` 登录。API 发布在 http://localhost:8001。`make up` 本身不会执行迁移，也不会创建用户。

> **安全提示**: Worker 容器挂载 `/var/run/docker.sock` 以执行测试容器。这意味着 Worker 被攻陷可获取宿主 root 权限。生产环境建议使用 `tecnativa/docker-socket-proxy` 限制 API 暴露范围，或迁移到 K8s Job 后端。

## 项目结构

```
qa_platform/
├── src/qaplatform/
│   ├── api/                  # FastAPI 路由 & 中间件
│   │   ├── auth/             #   JWT / 权限 / Token
│   │   ├── middleware/       #   CORS / 限流 / 请求ID / 安全头
│   │   └── v1/              #   v1 路由 (projects, runs, pipelines, ...)
│   ├── domain/               # 领域模型 & 服务
│   │   ├── models/           #   Pydantic 模型 (run, project, user, ...)
│   │   └── services/         #   业务逻辑 (execution, scheduling, discovery)
│   ├── engine/               # 执行引擎
│   │   ├── executor.py       #   核心执行器
│   │   ├── docker_backend.py #   Docker 容器管理
│   │   ├── cancel.py         #   取消逻辑
│   │   └── log_stream.py     #   日志流
│   ├── infra/                # 基础设施层
│   │   ├── database/         #   SQLAlchemy 模型 & Repository
│   │   └── storage/          #   S3 存储
│   ├── plugins/              # 插件系统
│   │   ├── protocols.py      #   Runner / Collector / Source 协议
│   │   └── builtin/          #   内置插件 (pytest, Jest, Playwright, Go, JUnit, Git)
│   ├── worker/               # arq 异步任务
│   ├── config.py             # 配置 (Pydantic Settings)
│   └── main.py               # FastAPI 应用工厂
├── frontend/                 # React SPA
│   └── src/
│       ├── components/       #   UI 组件
│       ├── pages/            #   页面 (login, projects, runs, settings)
│       ├── hooks/            #   自定义 Hooks (auth, projects, runs, SSE)
│       └── lib/              #   API 客户端 & 工具函数
├── tests/
│   ├── unit/                 # 单元测试
│   ├── integration/          # 集成测试
│   └── e2e/                  # 端到端测试
├── alembic/                  # 数据库迁移
├── docker-compose.yml
├── Dockerfile
├── Makefile
└── pyproject.toml
```

## API 文档

启动后端后访问：

- Swagger UI: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc

主要端点：

| 路径 | 说明 |
|---|---|
| `POST /api/v1/auth/login` | 登录 |
| `GET /api/v1/projects` | 项目列表 |
| `POST /api/v1/projects/{project_id}/pipelines` | 创建流水线 |
| `POST /api/v1/runs` | 触发测试运行 |
| `POST /api/v1/projects/{project_id}/runs/import` | 导入 JUnit XML 为一次 Run |
| `GET /api/v1/runs/{id}` | 运行详情 |
| `GET /api/v1/runs/{id}/results` | 测试结果过滤查询 |
| `GET /api/v1/runs/{run_id}/triage` | Run 的失败分诊 |
| `POST /api/v1/runs/{run_id}/retry-failed` | 只重跑失败用例 |
| `GET /api/v1/projects/{project_id}/analytics/release-summary` | 对比基线的发版判断 |
| `GET /api/v1/runs/{id}/artifacts` | 产物列表 |
| `GET /api/v1/artifacts/{id}/download` | 产物预签名下载 |
| `GET /api/v1/runs/{id}/logs?ticket=...` | SSE 实时日志 |
| `GET /api/v1/runs/{id}/logs/archive` | 归档日志分页回看 |
| `GET /api/v1/runs/{id}/events?ticket=...` | SSE 状态事件 |
| `GET /api/v1/audit-events` | 审计事件查询 |

## 文档入口

文档总目录见 [docs/README.md](docs/README.md)。维护时按用途分流：

- 当前实现与边界：`architecture.md`、`feature-catalog.md`、`product.md`、`TODO.md`、`development.md`、`runbook.md`、`testing-strategy.md`
- 任务包：`docs/tasks/`

## 常用命令

以下 Makefile 目标默认在已激活虚拟环境，或 `PATH` 已包含 `.venv/bin` 时运行。

```bash
make infra-up    # 仅启动 PostgreSQL、Redis、MinIO
make up          # 启动完整 Docker Compose 服务
make down        # 停止 Docker 服务
make logs        # 查看容器日志
make migrate     # 执行数据库迁移
make test        # 运行测试
make lint        # 代码检查 (ruff)
make format      # 代码格式化 (ruff)
make seed        # 导入种子数据
```

## 环境变量

所有环境变量以 `QAP_` 为前缀，完整列表见 [.env.example](.env.example)。关键配置：

| 变量 | 说明 | 默认值 |
|---|---|---|
| `QAP_DATABASE_URL` | PostgreSQL 连接串 | — |
| `QAP_REDIS_URL` | Redis 连接串 | — |
| `QAP_S3_ENDPOINT` | MinIO/S3 端点 | — |
| `QAP_JWT_SECRET` | JWT 签名密钥 | — |
| `QAP_ENCRYPTION_KEY` | 凭据加密密钥 (64 hex chars) | — |
| `QAP_MAX_CONCURRENT_RUNS` | 最大并发执行数 | 5 |
| `QAP_LOG_FORMAT` | 日志格式 (json / console) | json |

## 测试

```bash
# 单元测试
.venv/bin/pytest tests/unit -q

# 集成测试（多数重型用例需 RUN_INTEGRATION_TESTS=1；部分用例会自启 testcontainers）
RUN_INTEGRATION_TESTS=1 .venv/bin/pytest tests/integration -q

# E2E 冒烟（从仓库根目录运行；需已安装根目录和 frontend 的 npm 依赖，
# 且已按快速开始创建 .venv；Playwright 会按配置启动 API 与前端）
npm run test:e2e -- tests/e2e/auth-flow.spec.ts

# 本地真实 worker-backed E2E；脚本默认导出 QAP_E2E_WORKER=1，
# real-run-trigger 会启动受控 worker 而不是被 skip
E2E_ADMIN_PASSWORD=admin123 ./scripts/run-e2e.sh

# 交互式 smoke 默认把 skip 当失败；探索性排查才显式允许 skip
# 可用 RESULTS_DIR=... 固定父级产物目录；子脚本证据会落在 <script-name>/ 下
./scripts/smoke/run-all.sh
SMOKE_ADMIN_PASSWORD="$E2E_ADMIN_PASSWORD" ./scripts/smoke/run-all.sh
SMOKE_ALLOW_SKIPS=1 ./scripts/smoke/run-all.sh

# 覆盖率
.venv/bin/pytest --cov=qaplatform --cov-report=html
```

## 插件开发

实现以下协议之一即可扩展平台能力：

- **RunnerProtocol** — 测试运行器（如 pytest、Jest、Go test）
- **CollectorProtocol** — 结果收集器（当前内置 JUnit XML；Allure JSON/TAP 等可作为后续扩展）
- **SourceProtocol** — 代码获取（如 Git、SVN）

```python
import shlex
from pathlib import Path

from qaplatform.plugins.protocols import RunnerProtocol, TestRunResult

class MyRunner:
    name = "my-runner"

    def build_command(self, config: dict) -> str:
        argv = ["python", "-m", "pytest", "--junitxml=results/junit.xml", "tests"]
        return "cd /workspace && " + " ".join(shlex.quote(part) for part in argv)

    async def run_tests(self, working_dir: Path, config: dict, env_vars=None):
        # 执行测试并返回结果
        return TestRunResult(passed=10, failed=0, skipped=0, error=0, duration_ms=5000, exit_code=0)
```

## 常见问题

### QA Platform 是什么？

一个自托管的测试自动化执行与回归分析平台。它可以在隔离的 Docker 容器里运行 pytest、Jest、Playwright、Go test，也可以直接导入其他 CI 产出的 JUnit XML；在此基础上提供失败分诊、只重跑失败用例、flaky 检测与隔离、发版判断和条件通知。后端是 FastAPI + arq，前端是 React，MIT 许可证。

### 必须替换现有 CI 吗？

不必。现有 CI（如 GitHub Actions）继续跑测试，把 JUnit XML 通过 `POST /api/v1/projects/{project_id}/runs/import` 导入即可使用分诊、趋势、发版判断与通知。也可以让平台自己执行测试。注意导入不去重：同一文件上传两次会生成两条 Run。

### 支持哪些测试框架？

内置 Runner：pytest、Jest、Playwright、Go test；结果收集器：JUnit XML。任何能输出 JUnit XML 的框架都可以通过导入接入。「只重跑失败用例」目前只支持 pytest，其他 Runner 调用会返回 409。

### 失败分诊怎么判断一个失败是「新增」「flaky」还是「持续失败」？

对一次 Run 里每个失败或出错的用例：30 天窗口内至少 3 次观测、既有通过又有失败的，算已知 flaky；本次之前最近 3 次观测全部失败的，算持续失败；其余算新增失败。判定优先级是 flaky > 持续失败 > 新增。历史按项目内同一「套件 + 用例名」聚合，时间窗口以该 Run 的创建时间为锚点，所以结论不会随查看时间变化。

### 怎么只重跑失败的用例？

调用 `POST /api/v1/runs/{run_id}/retry-failed`，或在 Run 详情页点「重跑失败用例」。原 Run 必须已结束且有失败用例；失败用例超过 200 个时会拒绝，避免命令行过长。

### 隔离（quarantine）一个 flaky 用例会发生什么？

用例照常执行，但不再计入发版判断里的「新增失败」，也不会触发「新增失败」通知。隔离可以设置过期时间，到期后自动失效。

### 怎么判断一个版本能不能发？

`GET /api/v1/projects/{project_id}/analytics/release-summary` 对比目标 `git_ref` 与基线：原始通过率、剔除 flaky 后的通过率、新增失败、恢复的用例，以及因隔离被排除的用例。Run 详情页也有跳转入口。

### 在容器里跑不受信任的测试代码安全吗？

测试容器默认禁用网络，以非 root 用户（1000:1000）、只读根文件系统、去掉全部 capabilities 运行。但 Worker 需要挂载 `/var/run/docker.sock` 来创建测试容器，Worker 被攻破等同于拿到宿主 root。生产环境建议用 `tecnativa/docker-socket-proxy` 限制可用的 Docker API。

## License

MIT
