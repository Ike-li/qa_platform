# QA Platform

English | [简体中文](README.zh-CN.md)

A self-hosted test automation and regression analysis platform. Run pytest, Jest, Playwright or Go test in isolated Docker containers — or import JUnit XML from the CI you already have — then triage failures, rerun only the failed tests, detect and quarantine flaky tests, and answer "can we ship this build?".

[![CI](https://github.com/Ike-li/qa_platform/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/Ike-li/qa_platform/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.12](https://img.shields.io/badge/python-3.12-blue.svg)](pyproject.toml)

> 📖 Further docs (in Chinese): [Architecture](docs/architecture.md) · [Feature catalog](docs/feature-catalog.md) · [Development guide](docs/development.md) · [Backlog](docs/BACKLOG.md)

## Architecture

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

| Layer | Stack |
|---|---|
| Frontend | React 19 · Vite 8 · TailwindCSS 4 · TanStack Query · Radix UI · Recharts |
| Backend API | FastAPI · Pydantic v2 · SQLAlchemy 2 (async) · Alembic |
| Task queue | arq (Redis-backed) |
| Execution engine | Tests run in Docker containers (aiodocker) |
| Storage | PostgreSQL 16 · Redis 7 · MinIO (S3-compatible) |
| Observability | structlog · Prometheus; basic OpenTelemetry tracing is wired in, OTLP HTTP exporter pending (task T10) |

## Features

The regression loop:

- **Import results from any CI** — send the JUnit XML your existing pipeline already produces to the API and it becomes a Run; no pipeline changes required
- **Failure triage** — every failed test is classified as *new failure*, *known flaky* or *persistent failure*, and grouped by error signature
- **Rerun only failed tests** — one click reruns just the tests that failed last time (pytest for now)
- **Flaky test detection and quarantine** — find tests that flip between pass and fail; quarantined tests still run but no longer count toward release decisions or "new failure" alerts, with optional expiry
- **Release verdict** — compare a target branch against a baseline: raw pass rate, flaky-adjusted pass rate, new failures and recovered tests
- **Conditional notifications** — alert on status, pass rate, consecutive failures, new failures or recoveries via Email, Webhook, DingTalk or WeCom

Platform capabilities:

- **Multi-tenant RBAC** — two layers of roles: tenant (Owner/Admin/Member/Viewer) and project (Admin/Developer/Viewer)
- **Pipelines** — define test pipelines with environments and a credential store; private HTTPS tokens / SSH keys are injected into `git clone` only at execution time
- **Containerized execution** — tests run in isolated Docker containers with timeouts, cancellation and Docker OOMKilled detection
- **Live logs** — execution logs streamed over SSE; finished Runs can be replayed from logs archived in S3
- **Plugin system** — Runner / Collector / Source protocols, with built-in pytest, Jest, Playwright, Go test, JUnit and Git plugins
- **Artifacts** — everything under `results/` is uploaded to S3 with count/size limits, presigned downloads and HTML/Allure previews
- **Audit log** — key operations are audited and queryable at `/api/v1/audit-events`; an architecture contract test requires every new write endpoint to be audited and redacted
- **Scheduling** — cron-style scheduled pipeline runs

## Quick start

### Prerequisites

- Docker & Docker Compose
- Python >= 3.12
- Node.js >= 22.13 (matches `engines` in `frontend/package.json`)

### 1. Clone and configure

```bash
git clone https://github.com/Ike-li/qa_platform.git && cd qa_platform
cp .env.example .env
# edit .env as needed
```

### 2. Start infrastructure

```bash
make infra-up   # PostgreSQL, Redis and MinIO only
```

### 3. Initialize the database

```bash
# create a virtualenv and install backend dependencies
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"

# run migrations
.venv/bin/alembic upgrade head

# (optional) seed an admin user. ADMIN_PASSWORD is required; there is no default password
ADMIN_PASSWORD='<your-strong-password>' .venv/bin/python scripts/seed_admin.py
```

> **Keeping dependency versions in line with CI**
>
> CI installs exact versions from `uv.lock` (`uv export --frozen` + `pip install -r`),
> while `pip install -e ".[dev]"` above installs the latest available versions, so the two can differ.
> For an exact match use `uv sync --frozen`, or run `uv pip install -e '.[dev]' --upgrade` first.
>
> **After changing dependencies in `pyproject.toml`, run `uv lock` and commit `uv.lock`**,
> otherwise CI's `uv lock --check` fails.

> Log in as `admin` with the `ADMIN_PASSWORD` you set above.

### 4. Start the backend

```bash
.venv/bin/uvicorn qaplatform.main:create_app --factory --reload --port 8000
```

### 5. Start the frontend

```bash
cd frontend
npm ci
npm run dev   # http://localhost:5173 by default
```

### 6. Start a worker (optional, needed to execute tests)

```bash
.venv/bin/arq qaplatform.worker.settings.WorkerSettings
```

### Docker deployment

```bash
make up   # starts all 6 services (postgres, redis, minio, api, frontend, worker)
```

> **Security note**: the worker container mounts `/var/run/docker.sock` to launch test containers, so a compromised worker gets root on the host. In production, restrict the exposed Docker API with `tecnativa/docker-socket-proxy`, or move to a Kubernetes Job backend.

## Project layout

```
qa_platform/
├── src/qaplatform/
│   ├── api/                  # FastAPI routes & middleware
│   │   ├── auth/             #   JWT / permissions / tokens
│   │   ├── middleware/       #   CORS / rate limiting / request ID / security headers
│   │   └── v1/              #   v1 routes (projects, runs, pipelines, ...)
│   ├── domain/               # domain models & services
│   │   ├── models/           #   Pydantic models (run, project, user, ...)
│   │   └── services/         #   business logic (execution, scheduling, discovery)
│   ├── engine/               # execution engine
│   │   ├── executor.py       #   core executor
│   │   ├── docker_backend.py #   Docker container management
│   │   ├── cancel.py         #   cancellation
│   │   └── log_stream.py     #   log streaming
│   ├── infra/                # infrastructure layer
│   │   ├── database/         #   SQLAlchemy models & repositories
│   │   └── storage/          #   S3 storage
│   ├── plugins/              # plugin system
│   │   ├── protocols.py      #   Runner / Collector / Source protocols
│   │   └── builtin/          #   built-in plugins (pytest, Jest, Playwright, Go, JUnit, Git)
│   ├── worker/               # arq async jobs
│   ├── config.py             # settings (Pydantic Settings)
│   └── main.py               # FastAPI app factory
├── frontend/                 # React SPA
│   └── src/
│       ├── components/       #   UI components
│       ├── pages/            #   pages (login, projects, runs, settings)
│       ├── hooks/            #   custom hooks (auth, projects, runs, SSE)
│       └── lib/              #   API client & utilities
├── tests/
│   ├── unit/                 # unit tests
│   ├── integration/          # integration tests
│   └── e2e/                  # end-to-end tests
├── alembic/                  # database migrations
├── docker-compose.yml
├── Dockerfile
├── Makefile
└── pyproject.toml
```

## API docs

With the backend running:

- Swagger UI: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc

Key endpoints:

| Path | Description |
|---|---|
| `POST /api/v1/auth/login` | Log in |
| `GET /api/v1/projects` | List projects |
| `POST /api/v1/projects/{project_id}/pipelines` | Create a pipeline |
| `POST /api/v1/runs` | Trigger a test run |
| `POST /api/v1/projects/{project_id}/runs/import` | Import JUnit XML as a Run |
| `GET /api/v1/runs/{id}` | Run details |
| `GET /api/v1/runs/{id}/results` | Filter test results |
| `GET /api/v1/runs/{run_id}/triage` | Failure triage for a Run |
| `POST /api/v1/runs/{run_id}/retry-failed` | Rerun only the failed tests |
| `GET /api/v1/projects/{project_id}/analytics/release-summary` | Release verdict against a baseline |
| `GET /api/v1/runs/{id}/artifacts` | List artifacts |
| `GET /api/v1/artifacts/{id}/download` | Presigned artifact download |
| `GET /api/v1/runs/{id}/logs?ticket=...` | Live logs (SSE) |
| `GET /api/v1/runs/{id}/logs/archive` | Paginated archived logs |
| `GET /api/v1/runs/{id}/events?ticket=...` | Status events (SSE) |
| `GET /api/v1/audit-events` | Query audit events |

## Documentation

See [docs/README.md](docs/README.md) for the full index (in Chinese):

- Current implementation and scope: `architecture.md`, `feature-catalog.md`, `product.md`, `TODO.md`, `development.md`, `runbook.md`, `testing-strategy.md`
- Task packages: `docs/tasks/`

## Common commands

These Makefile targets assume an activated virtualenv, or `.venv/bin` on `PATH`.

```bash
make infra-up    # PostgreSQL, Redis and MinIO only
make up          # full Docker Compose stack
make down        # stop Docker services
make logs        # container logs
make migrate     # run database migrations
make test        # run tests
make lint        # lint (ruff)
make format      # format (ruff)
make seed        # seed data
```

## Environment variables

All variables are prefixed with `QAP_`; see [.env.example](.env.example) for the full list. The important ones:

| Variable | Description | Default |
|---|---|---|
| `QAP_DATABASE_URL` | PostgreSQL connection string | — |
| `QAP_REDIS_URL` | Redis connection string | — |
| `QAP_S3_ENDPOINT` | MinIO/S3 endpoint | — |
| `QAP_JWT_SECRET` | JWT signing secret | — |
| `QAP_ENCRYPTION_KEY` | credential encryption key (64 hex chars) | — |
| `QAP_MAX_CONCURRENT_RUNS` | maximum concurrent runs | 5 |
| `QAP_LOG_FORMAT` | log format (json / console) | json |

## Testing

```bash
# unit tests
.venv/bin/pytest tests/unit -q

# integration tests (most heavy cases need RUN_INTEGRATION_TESTS=1; some start testcontainers themselves)
RUN_INTEGRATION_TESTS=1 .venv/bin/pytest tests/integration -q

# E2E smoke (run from the repo root; needs npm dependencies installed in both the root and
# frontend/, plus the .venv from Quick start; Playwright starts the API and frontend itself)
npm run test:e2e -- tests/e2e/auth-flow.spec.ts

# local worker-backed E2E; the script exports QAP_E2E_WORKER=1 by default,
# so real-run-trigger starts a controlled worker instead of being skipped
E2E_ADMIN_PASSWORD=admin123 ./scripts/run-e2e.sh

# the interactive smoke suite treats skips as failures by default; allow skips only when exploring
# RESULTS_DIR=... pins the parent output directory; each sub-script writes evidence to <script-name>/
./scripts/smoke/run-all.sh
SMOKE_ADMIN_PASSWORD="$E2E_ADMIN_PASSWORD" ./scripts/smoke/run-all.sh
SMOKE_ALLOW_SKIPS=1 ./scripts/smoke/run-all.sh

# coverage
.venv/bin/pytest --cov=qaplatform --cov-report=html
```

## Plugin development

Implement one of these protocols to extend the platform:

- **RunnerProtocol** — test runners (e.g. pytest, Jest, Go test)
- **CollectorProtocol** — result collectors (JUnit XML is built in; Allure JSON/TAP are possible future extensions)
- **SourceProtocol** — source checkout (e.g. Git, SVN)

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
        # run the tests and return the result
        return TestRunResult(passed=10, failed=0, skipped=0, error=0, duration_ms=5000, exit_code=0)
```

## FAQ

### What is QA Platform?

A self-hosted test automation and regression analysis platform. It runs pytest, Jest, Playwright and Go test in isolated Docker containers, or imports JUnit XML produced by any other CI. On top of that it provides failure triage, rerunning only failed tests, flaky test detection and quarantine, release verdicts and conditional notifications. The backend is FastAPI + arq, the frontend is React, and it is MIT-licensed.

### Do I have to replace my existing CI?

No. Keep running tests in your existing CI (for example GitHub Actions) and import the JUnit XML with `POST /api/v1/projects/{project_id}/runs/import` to get triage, trends, release verdicts and notifications. The platform can also execute tests itself. Imports are not deduplicated: uploading the same file twice creates two Runs.

### Which test frameworks are supported?

Built-in runners: pytest, Jest, Playwright and Go test. Built-in result collector: JUnit XML. Any framework that can emit JUnit XML can be connected through import. Rerunning only failed tests currently supports pytest; other runners get HTTP 409.

### How does failure triage decide whether a failure is new, flaky or persistent?

For each failed or errored test in a Run: a test with at least 3 observations in a 30-day window that both passed and failed is *known flaky*; a test whose 3 most recent prior observations all failed is a *persistent failure*; everything else is a *new failure*. Precedence is flaky > persistent > new. History is aggregated per project by test suite and name, and the window is anchored to the Run's creation time, so the verdict does not change depending on when you look.

### How do I rerun only the failed tests?

Call `POST /api/v1/runs/{run_id}/retry-failed`, or click **Retry Failed** on the Run detail page. The original Run must have finished and contain failed tests; more than 200 failed tests is rejected to avoid an overly long command line.

### What happens when I quarantine a flaky test?

The test still runs, but it no longer counts as a new failure in release verdicts and no longer triggers "new failure" notifications. A quarantine can have an expiry time, after which it stops applying.

### How do I decide whether a build can be released?

`GET /api/v1/projects/{project_id}/analytics/release-summary` compares a target `git_ref` with a baseline: raw pass rate, flaky-adjusted pass rate, new failures, recovered tests, and tests excluded because they are quarantined. The Run detail page links to it as well.

### Is it safe to run untrusted test code?

Test containers have networking disabled by default and run as a non-root user (1000:1000) with a read-only root filesystem and all capabilities dropped. However, the worker mounts `/var/run/docker.sock` to create test containers, so a compromised worker is equivalent to root on the host. In production, restrict the available Docker API with `tecnativa/docker-socket-proxy`.

## License

MIT
