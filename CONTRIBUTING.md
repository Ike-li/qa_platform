# 贡献指南

欢迎参与 QA Platform 项目的开发！本文档将帮助你了解如何贡献代码、提交 PR 和参与项目维护。

## 目录

- [开发环境设置](#开发环境设置)
- [代码规范](#代码规范)
- [提交指南](#提交指南)
- [Pull Request 流程](#pull-request-流程)
- [测试要求](#测试要求)
- [文档更新](#文档更新)

---

## 开发环境设置

### 前置要求

- Python 3.12+
- Node.js 18+
- Docker & Docker Compose
- PostgreSQL 15+ (可通过 Docker 运行)
- Redis 7+ (可通过 Docker 运行)

### 快速启动

```bash
# 1. 克隆仓库
git clone https://github.com/Ike-li/qa_platform.git
cd qa_platform

# 2. 后端设置
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -e ".[dev]"

# 3. 前端设置
cd frontend
npm install
cd ..

# 4. 启动服务
docker-compose up -d  # 启动 PostgreSQL, Redis
python -m alembic upgrade head  # 运行数据库迁移
python -m qaplatform  # 启动 API 服务器

# 5. 启动前端 (新终端)
cd frontend
npm run dev
```

访问 http://localhost:5173 查看应用。

---

> **依赖版本与 CI 保持一致**
>
> CI 从 `uv.lock` 安装精确版本（`uv export --frozen` + `pip install -r`），
> 上面的 `pip install -e ".[dev]"` 装的是当前可得的最新版，两者可能不同。
> 需要完全对齐时用 `uv sync --frozen`，或先 `uv pip install -e '.[dev]' --upgrade`。
>
> **改动 `pyproject.toml` 的依赖后必须运行 `uv lock` 并提交 `uv.lock`**，
> 否则 CI 的 `uv lock --check` 会失败。

## 代码规范

### 后端 (Python)

我们使用 **Ruff** 进行代码格式化和 lint：

```bash
# 检查代码
ruff check .

# 自动修复
ruff check --fix .

# 格式化
ruff format .
```

**代码风格：**
- 遵循 PEP 8
- 使用类型注解 (Type Hints)
- 最大行长度：120 字符
- 使用 `snake_case` 命名变量和函数
- 使用 `PascalCase` 命名类

**架构约定：**
- API 路由放在 `src/qaplatform/api/v1/`
- 业务逻辑放在 `src/qaplatform/services/`
- 数据库模型放在 `src/qaplatform/infra/database/models.py`
- Repository 放在 `src/qaplatform/infra/database/repositories/`

### 前端 (TypeScript/React)

我们使用 **ESLint** 和 **TypeScript**：

```bash
cd frontend

# 检查代码
npm run lint

# 类型检查
npm run type-check

# 构建检查
npm run build
```

**代码风格：**
- 遵循 ESLint 配置
- 优先使用函数组件和 Hooks
- 使用 TypeScript 严格模式
- 组件文件使用 `kebab-case.tsx`
- 工具函数使用 `camelCase`

---

## 提交指南

### Commit Message 格式

使用语义化的 commit message，格式：

```
<type>: <subject>

<body>
```

**Type 类型：**
- `feat`: 新功能
- `fix`: Bug 修复
- `test`: 添加或修改测试
- `docs`: 文档更新
- `refactor`: 代码重构
- `perf`: 性能优化
- `chore`: 构建或辅助工具变更
- `style`: 代码格式调整（不影响逻辑）

**示例：**

```bash
feat: add report sharing feature

- Generate time-limited share tokens
- Support access count limits
- Add public report access endpoint
```

```bash
fix: resolve race condition in log archiver

Ensure S3 upload completes before marking as archived.
Fixes #123
```

```bash
test: add integration tests for user_repo

Coverage improved from 61% to 97%
```

---

## Pull Request 流程

### 1. 创建分支

从 `main` 创建功能分支：

```bash
git checkout -b feat/your-feature-name
# 或
git checkout -b fix/bug-description
```

### 2. 开发和测试

- 编写代码并确保通过所有测试
- 添加必要的单元测试和集成测试
- 更新相关文档

```bash
# 运行后端测试
pytest

# 运行前端测试
cd frontend && npm test

# 检查代码覆盖率
pytest --cov
```

### 3. 提交代码

```bash
git add .
git commit -m "feat: your feature description"
git push origin feat/your-feature-name
```

### 4. 创建 Pull Request

- 在 GitHub 上创建 PR
- 填写 PR 模板（如果有）
- 描述变更内容和测试情况
- 关联相关 Issue

**PR 标题格式：**
```
feat: Add report sharing feature
fix: Fix user authentication bug
test: Add tests for project repository
```

**PR 描述应包含：**
- 变更摘要
- 测试情况（单元测试、集成测试、手动测试）
- 截图（如果是 UI 变更）
- 破坏性变更说明（如果有）

### 5. Code Review

- 响应 reviewer 的评论
- 根据反馈修改代码
- 确保 CI 检查通过

### 6. 合并

- PR 获得批准后，由维护者合并到 `main`
- 合并后删除功能分支

---

## 测试要求

### 后端测试

**必须包含：**
- 单元测试：覆盖业务逻辑
- 集成测试：覆盖 API 端点和数据库交互
- 目标覆盖率：≥ 85%

**测试位置：**
- 单元测试：`tests/unit/`
- 集成测试：`tests/integration/`

**运行测试：**
```bash
# 所有测试
pytest

# 特定文件
pytest tests/unit/test_user_repo.py

# 带覆盖率
pytest --cov --cov-report=term-missing
```

### 前端测试

**必须包含：**
- 组件测试：使用 Vitest + Testing Library
- 类型检查：确保 TypeScript 编译通过

**测试位置：**
- `frontend/src/**/*.test.tsx`
- `frontend/src/**/*.test.ts`

**运行测试：**
```bash
cd frontend

# 所有测试
npm test

# Watch 模式
npm run test:watch

# 覆盖率
npm run test:coverage
```

---

## 文档更新

### 何时更新文档

- 添加新功能：更新 `docs/feature-catalog.md` 和相关文档
- 修改 API：更新 API 文档
- 架构变更：更新 `docs/architecture.md`
- 完成任务：更新 `docs/BACKLOG.md` 或 `docs/TODO.md`

### 文档位置

- `docs/feature-catalog.md` - 功能清单
- `docs/architecture.md` - 架构文档
- `docs/BACKLOG.md` - 技术改进待办
- `docs/TODO.md` - 功能开发任务
- `CHANGELOG.md` - 版本历史

### 文档规范

- 使用中文编写
- 保持格式一致
- 添加代码示例
- 包含必要的截图

---

## 常见问题

### Q: 如何运行完整的 CI 检查？

```bash
# 后端
ruff check .
pytest --cov

# 前端
cd frontend
npm run lint
npm run type-check
npm test
npm run build
```

### Q: 如何添加数据库迁移？

```bash
# 创建迁移
alembic revision -m "add new column"

# 编辑生成的文件: alembic/versions/xxx.py
# 运行迁移
alembic upgrade head
```

### Q: 如何调试测试？

```bash
# Python 测试
pytest -v -s tests/unit/test_user_repo.py::test_specific

# 前端测试
cd frontend
npm test -- --run tests/unit/utils.test.ts
```

---

## 获取帮助

- 查看 [README.md](README.md) 了解项目概述
- 查看 [docs/architecture.md](docs/architecture.md) 了解架构
- 提交 Issue 报告 bug 或请求功能
- 加入讨论区参与讨论

---

## 许可证

贡献代码即表示你同意你的贡献将遵循项目的开源许可证。

---

**感谢你的贡献！** 🎉
