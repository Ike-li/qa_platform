# 重构检查清单 (Refactoring Checklist)

**目的**: 确保模块结构/路径/命名重构时,所有直接和间接引用都同步更新,避免测试、脚本、配置失配。

---

## 📋 通用检查清单

每次进行以下类型的重构时,**必须**完成对应检查项:

### 1️⃣ 移动/重命名模块或文件

**影响面**: Python import 路径、`patch()` 字符串、配置文件引用

**检查步骤**:
```bash
# 旧路径: src/qaplatform/old/module.py → 新路径: src/qaplatform/new/module.py

# ✅ 检查 1: 显式 import 引用
rg "from qaplatform\.old\.module import|import qaplatform\.old\.module" --type py

# ✅ 检查 2: 字符串形式的模块路径(测试 mock、动态加载)
rg '"qaplatform\.old\.module"|"qaplatform/old/module"' --type py --type json --type yaml

# ✅ 检查 3: pytest fixture / conftest 中的路径配置
rg "qaplatform\.old" tests/conftest.py tests/*/conftest.py

# ✅ 检查 4: CI/脚本中的模块引用
rg "qaplatform\.old" .github/ scripts/ --type yaml --type py
```

**常见遗漏点**:
- `@patch("qaplatform.old.module.SomeClass")` 在单测中
- `sys.modules["qaplatform.old.module"]` 动态引用
- `alembic` 迁移脚本中的模型 import

---

### 2️⃣ 重命名类或函数(跨模块可见)

**影响面**: 直接调用、类型注解、序列化配置、审计 allowlist

**检查步骤**:
```bash
# 旧名: OldClassName → 新名: NewClassName

# ✅ 检查 1: 代码中的直接引用
rg "OldClassName" --type py

# ✅ 检查 2: 类型注解和文档字符串
rg "OldClassName" --type py -A 2 -B 2  # 看上下文,避免注释/文档过时

# ✅ 检查 3: JSON/YAML 配置中的类名引用(如果有序列化)
rg "OldClassName" --type json --type yaml

# ✅ 检查 4: 审计脚本 allowlist(如 check_tenant_isolation.py)
rg "OldClassName" scripts/
```

**常见遗漏点**:
- Pydantic 模型的 `__discriminator__` 字段值
- 枚举值的字符串表示
- 审计/安全扫描工具的白名单

---

### 3️⃣ 更改 logger 名称或层级

**影响面**: 测试中的 `caplog` 断言、日志配置文件

**检查步骤**:
```bash
# 旧 logger: qaplatform.api.v1.auth → 新 logger: qaplatform.api.auth.commands

# ✅ 检查 1: caplog.records 过滤
rg 'record\.name == "qaplatform\.api\.v1\.auth"' --type py

# ✅ 检查 2: caplog.set_level 配置
rg 'logger="qaplatform\.api\.v1\.auth"' --type py

# ✅ 检查 3: logging 配置文件
rg "qaplatform\.api\.v1\.auth" --type yaml --type toml --type ini

# ✅ 检查 4: 日志聚合工具的过滤规则(如 Sentry、DataDog 配置)
rg "qaplatform\.api\.v1\.auth" deploy/ k8s/ --type yaml
```

**常见遗漏点**:
- 单测和集成测试中断言特定 logger 的 warning/error
- CI 日志解析脚本中的正则匹配

---

### 4️⃣ 拆分或合并 Repository/Service 类

**影响面**: 审计脚本 allowlist、依赖注入配置、测试 fixture

**检查步骤**:
```bash
# 例: TestResultRepository 从 run_repo.py 拆分到 test_result_repo.py

# ✅ 检查 1: 审计脚本 allowlist(路径变化)
rg "run_repo\.py.*TestResultRepository" scripts/

# ✅ 检查 2: 依赖注入容器配置
rg "TestResultRepository" src/qaplatform/dependencies.py src/qaplatform/container.py

# ✅ 检查 3: pytest fixture 中的 mock
rg "@pytest\.fixture.*test_result_repo|TestResultRepository" tests/

# ✅ 检查 4: 单测中的 patch 目标路径
rg 'patch\(".*run_repo.*TestResultRepository"\)' --type py
```

**常见遗漏点**:
- 安全审计脚本的 `(path, class, method)` 白名单三元组
- FastAPI 依赖注入的 `Depends()` 参数

---

### 5️⃣ 修改 API 端点路径或参数

**影响面**: e2e 测试 mock、前端 API 调用、OpenAPI contract 测试

**检查步骤**:
```bash
# 例: /api/v1/runs 新增 project_id 查询参数

# ✅ 检查 1: e2e 测试的 mock 路由匹配
rg 'path === "/api/v1/runs"' tests/e2e/ --type ts --type js

# ✅ 检查 2: 前端 API 调用(确认传参)
rg '"/runs"|api\.get.*runs' frontend/src/ --type ts --type tsx

# ✅ 检查 3: OpenAPI contract 测试的参数断言
rg "project_id" tests/contract/ tests/integration/test_api_endpoints.py

# ✅ 检查 4: Postman/Newman collection(如果有)
rg "/runs" postman/ newman/ --type json
```

**常见遗漏点**:
- e2e mock 只按 `path` 匹配,忽略 query 参数变化
- 前端的 `queryKey` 缓存键未更新

---

### 6️⃣ 更改数据库模型字段或关系

**影响面**: Alembic 迁移、工厂 fixture、种子数据脚本

**检查步骤**:
```bash
# 例: Run 模型新增 environment_id 外键

# ✅ 检查 1: 生成 Alembic 迁移(自动检测)
.venv/bin/alembic revision --autogenerate -m "add environment_id to run"

# ✅ 检查 2: 测试 fixture factory 更新必填字段
rg "def.*run.*factory|RunFactory" tests/ --type py -A 5

# ✅ 检查 3: 种子数据脚本
rg "insert.*run|Run\(" scripts/seed_data.py tests/integration/conftest.py

# ✅ 检查 4: repository 查询条件(JOIN 新表)
rg "select\(Run\)|join\(Run" src/qaplatform/infra/database/repositories/ --type py
```

**常见遗漏点**:
- 测试 factory 不更新新增的非 nullable 字段,导致 IntegrityError
- 审计脚本的 `RUN_MODELS` 常量未包含新关联表

---

## 🔧 自动化辅助工具

### 快速搜索脚本

保存为 `scripts/check_refactor_refs.sh`:

```bash
#!/bin/bash
# 用法: ./scripts/check_refactor_refs.sh <old_pattern> [file_types]
# 示例: ./scripts/check_refactor_refs.sh "qaplatform.api.v1.auth" "py,ts,yaml"

OLD_PATTERN="$1"
FILE_TYPES="${2:-py,ts,tsx,json,yaml,toml}"

echo "🔍 搜索模式: $OLD_PATTERN"
echo "📁 文件类型: $FILE_TYPES"
echo ""

# 代码中的引用
echo "=== 代码文件 ==="
rg "$OLD_PATTERN" --type-list | grep -E "$(echo $FILE_TYPES | tr ',' '|')" | \
  xargs -I{} rg "$OLD_PATTERN" --type {}

# 配置文件
echo ""
echo "=== 配置/脚本 ==="
rg "$OLD_PATTERN" .github/ scripts/ deploy/ --type yaml --type sh --type json

# 测试文件
echo ""
echo "=== 测试文件 ==="
rg "$OLD_PATTERN" tests/ --type py --type ts

echo ""
echo "✅ 搜索完成。确认上述引用都已更新后再提交。"
```

### pre-commit hook(可选)

在 `.pre-commit-config.yaml` 添加自定义检查:

```yaml
- repo: local
  hooks:
    - id: check-stale-module-refs
      name: 检查过时的模块引用
      entry: python scripts/check_stale_refs.py
      language: system
      pass_filenames: false
      always_run: true
```

---

## 🚨 CI 红色信号处理流程

**原则**: 永远不在红色 CI 上堆叠新提交

### 当 CI 失败时

1. **立即停止新功能开发**
   - 不要"先提交这个功能,回头再修 CI"
   - 失败信号会被后续提交掩埋,定位成本指数级增长

2. **定位失败提交**
   ```bash
   # 找到第一个红色 commit
   gh run list --limit 20 --json conclusion,headSha,displayTitle
   git log --oneline <红色commit>^..<当前HEAD>
   ```

3. **本地复现失败**
   ```bash
   # 单测失败
   pytest tests/unit/path/to/test.py::test_name -v
   
   # 集成测试失败
   RUN_INTEGRATION_TESTS=1 pytest tests/integration/test_name.py -v
   
   # lint 失败
   ruff check src tests
   cd frontend && npm run lint
   ```

4. **修复策略选择**
   - **情况 A**: 失败由当前分支引入 → 在当前分支修复后推送
   - **情况 B**: 失败由 main 上游引入 → 通知团队/立即修 main
   - **情况 C**: 外部依赖问题(docker pull 失败) → rerun failed jobs

5. **验证修复**
   ```bash
   # 本地全量检查(模拟 CI)
   ruff check src tests scripts
   cd frontend && npm run lint && npx tsc --noEmit && cd ..
   pytest tests/unit -m "not slow"
   RUN_INTEGRATION_TESTS=1 pytest tests/integration -m "not heavy_docker"
   ```

---

## 🧪 测试原则:避免过度耦合实现

### ❌ 不推荐:断言内部实现细节

```python
# 反例 1: 断言 logger 名称
def test_login_failure_logs_warning(caplog):
    caplog.set_level(logging.WARNING, logger="qaplatform.api.v1.auth")
    # 问题:重构 logger 层级时测试会坏
```

```python
# 反例 2: mock 内部私有方法
@patch("qaplatform.api.v1.auth._resolve_tenant_id")
def test_register(mock_resolve):
    # 问题:内部重构私有函数时测试会坏
```

```python
# 反例 3: 断言 SQL 查询细节
def test_list_runs_filters_by_project(session):
    runs = repo.list_runs(project_id=uuid4())
    # 直接检查生成的 SQL 语句
    assert "JOIN project" in str(session.queries[-1])
    # 问题:ORM 优化或改用子查询时测试会坏
```

### ✅ 推荐:测试行为契约

```python
# 正例 1: 测试日志行为(不关心 logger 名)
def test_login_failure_logs_warning(caplog):
    # 只断言日志级别和关键信息,不限定 logger 名
    response = client.post("/auth/login", json={"username": "bad", "password": "bad"})
    assert response.status_code == 401
    assert any(
        record.levelno == logging.WARNING and "login_failed" in record.getMessage()
        for record in caplog.records
    )
```

```python
# 正例 2: 测试公开 API 行为
def test_register_rejects_duplicate_email():
    # 通过公开接口测试,不 mock 内部
    response = client.post("/auth/register", json={"email": "test@example.com", ...})
    assert response.status_code == 201
    
    response = client.post("/auth/register", json={"email": "test@example.com", ...})
    assert response.status_code == 409
    assert "already exists" in response.json()["detail"]
```

```python
# 正例 3: 测试数据正确性(不关心查询实现)
def test_list_runs_filters_by_project(session):
    project_a = create_project(name="A")
    project_b = create_project(name="B")
    run_a1 = create_run(project=project_a)
    run_b1 = create_run(project=project_b)
    
    runs = repo.list_runs(project_id=project_a.id)
    
    # 断言结果正确性,不关心 JOIN 还是子查询
    assert len(runs) == 1
    assert runs[0].id == run_a1.id
```

### 原则总结

| 应该测试的(契约) | 不应该测试的(实现) |
|----------------|------------------|
| HTTP 状态码和响应结构 | 内部函数调用次数 |
| 数据查询结果的正确性 | SQL 语句的具体形式 |
| 副作用的可观测行为(如日志存在) | Logger 的具体名称 |
| 跨租户隔离是否生效 | Repository 方法的调用顺序 |
| 权限拒绝返回 403 | 用了哪个装饰器实现权限检查 |

**例外**: 当实现细节**本身就是安全边界**时(如审计脚本验证特定查询模式),可以断言实现。

---

## 📝 Checklist 使用建议

### 提交前自查

在 PR 描述中添加检查项:

```markdown
## 重构影响面检查

- [x] 搜索旧模块路径的所有引用(import + 字符串)
- [x] 更新测试中的 patch 路径
- [x] 更新审计脚本 allowlist
- [ ] 更新部署配置(如果涉及)
- [x] 本地运行全量测试套件
- [x] CI 全绿后才合并
```

### Code Review 重点

Reviewer 应关注:

1. **影响面评估**: PR 改了 N 个文件,是否遗漏配置/测试/脚本?
2. **测试覆盖**: 新增的重构路径是否有对应测试验证?
3. **向后兼容**: 如果是公开 API,是否需要保留旧路径的兼容层?

---

## 🎯 核心原则

1. **重构不是"改完就完"** — 改完主体代码只是 50%,同步配套物是另外 50%
2. **搜索是最便宜的保险** — `rg`/`grep` 30 秒,能避免 CI 红 30 分钟
3. **CI 是唯一的真相** — 本地过了不代表 CI 会过,推送后立即看结果
4. **红色 CI 是技术债** — 每多堆一个提交,就多一层考古成本

---

## 📚 相关资源

- [Python Import 最佳实践](https://docs.python.org/3/reference/import.html)
- [pytest mock 最佳实践](https://docs.pytest.org/en/stable/how-to/monkeypatch.html)
- [Martin Fowler: Refactoring](https://refactoring.com/)
- 本项目审计脚本: `scripts/check_tenant_isolation.py`

---

**最后更新**: 2026-06-07  
**维护者**: @Ike-li  
**来源**: CI 全红诊断经验总结(commits `cded795` + `ea5ecd4`)
