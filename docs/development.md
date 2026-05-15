# 开发环境搭建

## 前置条件

- Python 3.12+
- Docker & Docker Compose
- Homebrew (macOS)

## 快速启动

```bash
# 1. 复制环境变量
cp .env.example .env

# 2. 启动基础设施
make up

# 3. 安装依赖
pip install -e ".[test]"

# 4. 执行数据库迁移
make migrate

# 5. 创建默认 admin 用户
make seed

# 6. 启动 API
uvicorn qaplatform.api:create_app --factory --reload
```

## 常用命令

| 命令 | 说明 |
|------|------|
| `make up` | 启动 PostgreSQL、Redis、MinIO |
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

测试使用 testcontainers 自动拉起 PostgreSQL 和 Redis 容器，无需手动启动基础设施：

```bash
make test
```

集成测试位于 `tests/integration/`，单元测试位于 `tests/unit/`。
