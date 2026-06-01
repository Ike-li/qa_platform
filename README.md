# QA Platform

QA 自动化执行平台 —— 管理项目、配置流水线、执行测试、收集结果，一站式完成。

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
- Node.js >= 22.13（或 20.19+；前端 Vite 8 / ESLint 10 需要）

### 1. 克隆与配置

```bash
git clone <repo-url> && cd qa_platform
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

# (可选) 导入种子数据
.venv/bin/python scripts/seed_admin.py
```

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
make up   # 启动全部 6 个服务（postgres, redis, minio, api, frontend, worker）
```

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
| `GET /api/v1/runs/{id}` | 运行详情 |
| `GET /api/v1/runs/{id}/results` | 测试结果过滤查询 |
| `GET /api/v1/runs/{id}/artifacts` | 产物列表 |
| `GET /api/v1/artifacts/{id}/download` | 产物预签名下载 |
| `GET /api/v1/runs/{id}/logs?ticket=...` | SSE 实时日志 |
| `GET /api/v1/runs/{id}/logs/archive` | 归档日志分页回看 |
| `GET /api/v1/runs/{id}/events?ticket=...` | SSE 状态事件 |
| `GET /api/v1/audit-events` | 审计事件查询 |

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

## License

MIT
