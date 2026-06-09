# CI 失败修复方案

**日期**: 2026-06-09  
**CI Run**: 27218262836  
**状态**: ❌ 失败

---

## 🚨 问题分析

### 失败原因
```
pydantic_core._pydantic_core.ValidationError: 7 validation errors for Settings
- database_url (Field required)
- redis_url (Field required)
- s3_endpoint (Field required)
- s3_access_key (Field required)
- s3_secret_key (Field required)
- jwt_secret (Field required)
- encryption_key (Field required)
```

### 失败步骤
```
backend-integration-test → Validate OpenAPI API test matrix
python scripts/validate_api_test_matrix.py
```

### 根本原因
`validate_api_test_matrix.py` 脚本导入了 `qaplatform.main.create_app`，触发了 Settings 初始化，但 `backend-integration-test` job 在该步骤**没有配置环境变量**。

---

## 🔍 代码追踪

### 调用链
```
scripts/validate_api_test_matrix.py:11
  ↓
from qaplatform.main import create_app
  ↓
src/qaplatform/main.py:331
  ↓
app = create_app()
  ↓
src/qaplatform/main.py:96
  ↓
_settings_obj = settings or (container.settings if container else Settings())
  ↓
Settings() 初始化失败（缺少环境变量）
```

### CI 配置问题
`.github/workflows/ci.yml`:
- `backend-test` job: ✅ 有环境变量（第 80-87 行）
- `backend-integration-test` job: ❌ **缺少基本环境变量**
  - 只有性能测试相关的环境变量
  - 没有 `QAP_DATABASE_URL`, `QAP_REDIS_URL` 等

---

## 🛠️ 修复方案

### 方案 A: 添加环境变量到 backend-integration-test ⭐ 推荐

在 `.github/workflows/ci.yml` 的 `backend-integration-test` job 的 `env` 部分添加：

```yaml
backend-integration-test:
  runs-on: ubuntu-latest
  timeout-minutes: 90
  env:
    # 基础配置（新增）
    QAP_DATABASE_URL: postgresql+asyncpg://qaplatform:qaplatform@localhost:5432/qaplatform
    QAP_REDIS_URL: redis://localhost:6379/0
    QAP_S3_ENDPOINT: http://localhost:9000
    QAP_S3_ACCESS_KEY: minioadmin
    QAP_S3_SECRET_KEY: minioadmin
    QAP_JWT_SECRET: test-secret-at-least-32bytes-long!
    QAP_ENCRYPTION_KEY: 0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef
    # 性能测试配置（已有）
    QAP_PERFORMANCE_GATE_PROFILE: ...
    # ...其他性能配置
```

**优点**: 简单直接，与 backend-test 保持一致  
**缺点**: 环境变量重复（但可以接受）

---

### 方案 B: 重构 Settings 初始化

修改 `src/qaplatform/main.py`，使 Settings 初始化更容错：

```python
def create_app(...):
    try:
        _settings_obj = settings or (container.settings if container else Settings())
    except ValidationError as e:
        # 如果是验证脚本调用，使用空配置
        if "validate_api_test_matrix" in sys.argv[0]:
            _settings_obj = None
        else:
            raise
    ...
```

**优点**: 不需要修改 CI 配置  
**缺点**: 
- 代码逻辑变复杂
- 容易引入其他问题
- 不推荐

---

### 方案 C: 修改验证脚本不导入 create_app

修改 `scripts/validate_api_test_matrix.py`，不直接导入 `create_app`：

```python
# 不要这样
from qaplatform.main import create_app

# 改成
import subprocess
import sys

# 导出 OpenAPI 到临时文件
result = subprocess.run(
    [sys.executable, "scripts/export_openapi.py", "/tmp/openapi.json"],
    capture_output=True,
)
if result.returncode != 0:
    sys.exit(1)

# 读取 OpenAPI spec
with open("/tmp/openapi.json") as f:
    openapi_spec = json.load(f)

# 验证逻辑...
```

**优点**: 完全解耦，不需要 Settings  
**缺点**: 
- 需要重构验证脚本
- 工作量较大

---

## ✅ 推荐行动方案

**立即修复（方案 A）**:

1. 编辑 `.github/workflows/ci.yml`
2. 在 `backend-integration-test` job 的 `env` 添加 7 个基础环境变量
3. 提交并推送
4. 检查 CI 是否通过

**修复位置**: `.github/workflows/ci.yml` 约第 320 行（`backend-integration-test` job）

---

## 📝 修复代码

```yaml
  backend-integration-test:
    runs-on: ubuntu-latest
    timeout-minutes: 90
    env:
      # ===== 基础配置（修复 Settings 初始化）=====
      QAP_DATABASE_URL: postgresql+asyncpg://qaplatform:qaplatform@localhost:5432/qaplatform
      QAP_REDIS_URL: redis://localhost:6379/0
      QAP_S3_ENDPOINT: http://localhost:9000
      QAP_S3_ACCESS_KEY: minioadmin
      QAP_S3_SECRET_KEY: minioadmin
      QAP_JWT_SECRET: test-secret-at-least-32bytes-long!
      QAP_ENCRYPTION_KEY: 0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef
      # ===== 性能测试配置（已有）=====
      QAP_PERFORMANCE_GATE_PROFILE: ${{ github.event_name == 'workflow_dispatch' && inputs.gate || 'nightly' }}
      PERF_EXTERNAL_STACK_WORKER_FIRST_SIGNAL_MS: "180000"
      # ...其他性能配置
```

---

## 🎯 验证步骤

修复后验证：

```bash
# 1. 本地验证（模拟 CI 环境）
unset QAP_DATABASE_URL QAP_REDIS_URL QAP_S3_ENDPOINT \
      QAP_S3_ACCESS_KEY QAP_S3_SECRET_KEY \
      QAP_JWT_SECRET QAP_ENCRYPTION_KEY

# 2. 运行验证脚本（应该失败）
python scripts/validate_api_test_matrix.py
# 预期: ValidationError

# 3. 设置环境变量
export QAP_DATABASE_URL=postgresql+asyncpg://qaplatform:qaplatform@localhost:5432/qaplatform
export QAP_REDIS_URL=redis://localhost:6379/0
export QAP_S3_ENDPOINT=http://localhost:9000
export QAP_S3_ACCESS_KEY=minioadmin
export QAP_S3_SECRET_KEY=minioadmin
export QAP_JWT_SECRET=test-secret-at-least-32bytes-long!
export QAP_ENCRYPTION_KEY=0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef

# 4. 再次运行（应该成功）
python scripts/validate_api_test_matrix.py
# 预期: 成功

# 5. 推送修复后检查 CI
git push
./scripts/check-ci.sh
```

---

## 📊 历史 CI 状态

```
✅ 08381f0 Fix P1-2: seed_admin.py empty password bypass
❌ 9a69e9e Add unit tests for P1-2 seed_admin password validation
❌ 0074043 Update status: mark report sharing feature as completed (刚推送)
```

**注意**: `9a69e9e` 也失败了，可能是同样的原因。

---

## 💡 预防措施

### 短期
1. ✅ 修复 CI 配置
2. ✅ 添加到 BACKLOG

### 中期
1. 创建 CI 环境变量模板
2. 在 CLAUDE.md 中添加"修改 CI 配置后必须本地测试"

### 长期
1. 重构验证脚本，减少对 Settings 的依赖
2. 添加 CI 配置测试

---

**创建时间**: 2026-06-09  
**状态**: 待修复  
**优先级**: P0 (阻塞 CI)  
**预计修复时间**: 10 分钟
