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
| 可观测性 | structlog · OpenTelemetry · Prometheus |

## 核心功能

- **多租户 RBAC** — 租户级 (Owner/Admin/Member/Viewer) + 项目级 (Admin/Developer/Viewer) 双层权限
- **流水线管理** — 定义测试流水线，配置运行环境与凭据
- **容器化执行** — 测试在隔离 Docker 容器中运行，支持超时、取消、OOM 检测
- **实时日志** — SSE 推送执行日志，前端实时展示
- **插件系统** — Runner / Collector / Source 三类插件协议，内置 pytest + JUnit + Git
- **产物管理** — 测试报告、截图、覆盖率等产物上传至 S3，支持预签名下载
- **审计日志** — 关键操作全量审计，PII/Secret 脱敏
- **定时调度** — Cron 风格定时触发测试流水线

## 快速开始

### 前置依赖

- Docker & Docker Compose
- Python >= 3.12
- Node.js >= 18

### 1. 克隆与配置

```bash
git clone <repo-url> && cd qa_platform
cp .env.example .env
# 按需修改 .env 中的配置
```

### 2. 启动基础设施

```bash
make up   # 启动 PostgreSQL、Redis、MinIO
```

### 3. 初始化数据库

```bash
# 创建虚拟环境并安装后端依赖
python -m venv .venv
.venv/bin/pip install -e ".[dev]"

# 执行迁移
.venv/bin/alembic upgrade head

# (可选) 导入种子数据
.venv/bin/python -m qaplatform.seed
```

### 4. 启动后端

```bash
.venv/bin/uvicorn qaplatform.main:create_app --factory --reload --port 8000
```

### 5. 启动前端

```bash
cd frontend
npm install
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
│   │   └── builtin/          #   内置插件 (pytest, junit, git)
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
| `POST /api/v1/projects/{id}/pipelines` | 创建流水线 |
| `POST /api/v1/runs` | 触发测试运行 |
| `GET /api/v1/runs/{id}` | 运行详情 |
| `GET /api/v1/runs/{id}/artifacts` | 产物列表 |
| `GET /api/v1/sse/runs/{id}/logs` | SSE 实时日志 |

## 常用命令

```bash
make up          # 启动 Docker 服务
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

# 集成测试（需要运行中的 PostgreSQL & Redis）
.venv/bin/pytest tests/integration -q

# 覆盖率
.venv/bin/pytest --cov=qaplatform --cov-report=html
```

## 插件开发

实现以下协议之一即可扩展平台能力：

- **RunnerProtocol** — 测试运行器（如 pytest、Jest、Go test）
- **CollectorProtocol** — 结果收集器（如 JUnit XML、Allure）
- **SourceProtocol** — 代码获取（如 Git、SVN）

```python
from qaplatform.plugins.protocols import RunnerProtocol, TestRunResult

class MyRunner:
    name = "my-runner"

    async def run_tests(self, working_dir, config, env_vars=None):
        # 执行测试并返回结果
        return TestRunResult(passed=10, failed=0, skipped=0, error=0, duration_ms=5000, exit_code=0)
```

## License

MIT
