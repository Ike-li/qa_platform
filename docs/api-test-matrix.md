# API Test Matrix Plan

## 目标

OpenAPI 是接口测试的唯一真源。当前目标范围为 `/api/v1/**`、`/health`、`/ready`、`/webhooks/{provider}`，共 69 个 operation。接口 operation 矩阵文件为 `tests/api_matrix/openapi_operation_matrix.yml`，由 `scripts/validate_api_test_matrix.py` 与运行时 OpenAPI 文档做一致性校验；原子测试点矩阵文件为 `tests/api_matrix/openapi_test_case_matrix.yml`，由 `scripts/validate_api_test_case_matrix.py` 从 operation 矩阵展开校验。

本计划分三层执行：

1. Contract smoke：继续使用 `tests/integration/test_openapi_contract_smoke.py` 自动枚举所有目标 operation，验证 HTTPBearer 声明、公开接口 allowlist、未认证拒绝态、实际状态码是否在 OpenAPI responses 中声明，以及 JSON 错误壳。
2. Behavior matrix：按业务域扩展黑盒行为测试。所有测试数据只通过公开 API 创建和清理；不能通过公开 API 构造前置状态的 success 路径必须标记为 `blocked_by_missing_public_setup`，不能伪造为已覆盖。
3. Real-stack behavior：`tests/integration/test_openapi_real_stack_behavior.py` 在 compose API/worker/MinIO 栈上通过公开 API 创建项目、环境、pipeline 和 run，由真实 worker 写入 TestResult、Artifact 与 archived logs，再验证 OpenAPI success 路径。

## 覆盖维度

| 维度 | 必须验证的内容 |
| --- | --- |
| `contract` | operation 被 OpenAPI 枚举，method/path/tag/request body/responses 与矩阵一致。 |
| `auth` | 受保护接口声明 `HTTPBearer`；无 token、无效 token、过期 token、登出后 token、权限拒绝进入声明的拒绝态。公开接口必须显式列入 allowlist。 |
| `success` | 使用公开 API 创建前置数据，验证 2xx/业务成功语义、响应 schema、数据可被后续公开 API 查询。 |
| `schema_negative` | 缺必填、类型错误、非法 enum、非法 UUID、分页边界、日期边界、字符串长度边界。 |
| `rbac_tenant` | A 租户资源不能被 B 租户读取、修改、删除或通过列表泄漏；同租户不同角色按权限矩阵拒绝或允许。 |
| `declared_responses` | 运行时出现的状态码必须出现在 OpenAPI `responses`，全局只允许 contract smoke 中声明的 `401/422` 兼容拒绝态。 |

## 当前矩阵状态

Operation 覆盖状态：

| 状态 | 数量 | 含义 |
| --- | ---: | --- |
| `covered` | 64 | `/health`、`/ready`、Auth、Project CRUD、project members list、project resources CRUD、audit-events、公开 API 可构造的 runs/SSE/webhook operation，以及 real-stack 可构造的 artifact、archived logs、analytics 有数据成功态已有黑盒行为测试。 |
| `partial` | 0 | 不再保留未决 partial；不可稳定构造的 success 路径统一进入阻塞清单。 |
| `blocked_by_missing_public_setup` | 5 | success 路径需要无法通过公开 API 创建的前置状态，已记录阻塞原因。 |
| `missing` | 0 | 不允许合入。新增 OpenAPI operation 未进入矩阵时校验失败。 |

原子测试点状态：

| 状态 | 数量 | 含义 |
| --- | ---: | --- |
| `total_cases` | 414 | 69 个 operation × `contract`、`auth`、`success`、`schema_negative`、`rbac_tenant`、`declared_responses` 6 个维度。 |
| `covered` | 409 | 已由 contract smoke、黑盒行为测试、real-stack 行为测试或声明状态校验覆盖/守护的原子测试点。 |
| `blocked_by_missing_public_setup` | 5 | 仅 success 维度阻塞；对应下方阻塞清单，不能计入已完成成功态。 |
| `missing` | 0 | 不允许合入。新增 operation 或维度漂移会导致 case matrix validator 失败。 |

当前 pytest 原子化状态：

| 测试文件 | pytest items | 说明 |
| --- | ---: | --- |
| `tests/integration/test_openapi_contract_smoke.py` | 210 | 3 个全局契约检查 + 69 个 `contract` + 69 个 `auth` + 69 个 `declared_responses` 原子用例。 |
| `tests/integration/test_openapi_behavior_blackbox.py` | 130 | 4 个 workflow 聚合用例 + 1 个跨租户特殊流用例 + 8 个 Auth `success` 原子用例 + 48 个 Project/Resource/Run/Webhook/Audit `success` 原子用例 + 30 个 `schema_negative` 原子用例 + 39 个 `rbac_tenant` 原子用例。 |
| `tests/integration/test_openapi_real_stack_behavior.py` | 1 | 1 个 compose worker/S3 黑盒 workflow，经公开 API 构造 passed/failed runs，覆盖 artifact download、preview-url、preview token、Allure 入口、archived logs、analytics trends/flaky/test-history 8 个 success 原子用例。 |
| 合计 | 341 | `RUN_INTEGRATION_TESTS=1 ... --collect-only -q` 当前收集结果。 |

阻塞项：

| Operation | 阻塞原因 |
| --- | --- |
| `GET /api/v1/admin/status` | 200 path 需要 platform admin 身份；公开 API 只能注册普通租户身份。 |
| `POST /api/v1/projects/branches` | 200 path 需要可访问的 public/SSH Git 远程仓库；本地 `file://` 仓库被公开 schema 拒绝，外网 Git fixture 不适合作为稳定黑盒门禁。 |
| `POST /api/v1/projects/{project_id}/members` | 成功添加成员需要第二个同租户用户；注册接口会创建隔离租户。 |
| `PUT /api/v1/projects/{project_id}/members/{user_id}` | 成功更新成员需要已有同租户成员行；缺公开 tenant invite/setup API。 |
| `DELETE /api/v1/projects/{project_id}/members/{user_id}` | 成功删除成员需要已有同租户成员行；缺公开 tenant invite/setup API。 |

## 业务域测试矩阵

| 业务域 | Operation 数 | 必做场景 |
| --- | ---: | --- |
| Ops | 2 | liveness/readiness 成功、依赖降级、响应 schema、不可被认证状态影响。 |
| Auth | 8 | 注册、登录、刷新、登出、SSE ticket、API token CRUD、无效/过期/登出 token、权限拒绝。 |
| Projects | 6 | CRUD、列表 search/status/filter/pagination、slug 冲突、git 字段校验、删除后不可见；`/projects/branches` success 为阻塞项。 |
| Project resources | 25 | environments、pipelines、schedules、credentials、notification rules 的 CRUD、分页、schema negative、跨租户不可见、加密/脱敏响应；project members list 已覆盖，members 写操作仍为阻塞项。 |
| Runs / Logs / Artifacts | 14 | 触发运行、批量取消/重试、查询运行、结果、通知、SSE、终态幂等、跨租户不可见已覆盖；real-stack 行为测试覆盖 artifact download、preview、Allure 入口与归档日志成功态。 |
| Analytics / Audit | 4 | audit-events 的分页、actor/resource/time 过滤、schema negative、跨租户不可见已覆盖；analytics 的空结果、参数校验、跨租户隔离，以及 worker ingestion 后 trends/flaky/test-history 有数据成功态已覆盖。 |
| Webhooks | 3 | 非法 provider、缺签名、错误签名、空 body、非法 JSON、unsupported event、branch filtered、幂等重复事件、project/provider 两类入口成功态。 |
| Admin | 1 | 普通 owner 403、未认证拒绝、platform admin 200 阻塞项。 |

## 执行命令

矩阵一致性校验：

```bash
.venv/bin/python scripts/validate_api_test_matrix.py
.venv/bin/python scripts/validate_api_test_case_matrix.py
```

当前 contract smoke：

```bash
RUN_INTEGRATION_TESTS=1 .venv/bin/python -m pytest tests/integration/test_openapi_contract_smoke.py -q
```

Auth + Project 黑盒行为切片：

```bash
RUN_INTEGRATION_TESTS=1 .venv/bin/python -m pytest tests/integration/test_openapi_behavior_blackbox.py -q
```

Resource CRUD 黑盒行为切片：

```bash
RUN_INTEGRATION_TESTS=1 .venv/bin/python -m pytest tests/integration/test_openapi_behavior_blackbox.py -q
```

Runs / Logs / Webhooks 黑盒行为切片：

```bash
RUN_INTEGRATION_TESTS=1 .venv/bin/python -m pytest tests/integration/test_openapi_behavior_blackbox.py -q
```

Worker / S3 real-stack 黑盒行为切片：

```bash
RUN_INTEGRATION_TESTS=1 .venv/bin/python -m pytest tests/integration/test_openapi_real_stack_behavior.py -q
```

Analytics / Audit / Branches 收口切片：

```bash
RUN_INTEGRATION_TESTS=1 .venv/bin/python -m pytest tests/integration/test_openapi_behavior_blackbox.py -q
```

关联契约回归：

```bash
.venv/bin/python -m pytest tests/unit/test_api_test_matrix_validator.py -q
.venv/bin/python -m pytest tests/unit/test_api_test_case_matrix_validator.py -q
.venv/bin/python -m pytest tests/unit/test_frontend_api_contract.py -q
.venv/bin/python -m pytest tests/unit/test_release_gate_workflow.py -q
.venv/bin/python -m ruff check scripts/export_openapi.py scripts/validate_api_test_matrix.py scripts/validate_api_test_case_matrix.py tests/support/api_data.py tests/integration/test_openapi_contract_smoke.py tests/integration/test_openapi_behavior_blackbox.py tests/integration/test_openapi_real_stack_behavior.py tests/integration/conftest.py tests/unit/test_release_gate_workflow.py tests/unit/test_api_test_matrix_validator.py tests/unit/test_api_test_case_matrix_validator.py
```

测试数据工具：

`tests/support/api_data.py` 提供 `ApiTestDataFactory`，用于通过公开 HTTP API 创建 actor、project、environment、pipeline、schedule、credential、notification rule 和 run 前置数据，并按反向创建顺序清理可删除资源。行为测试新增前置数据时应优先扩展这个工厂；当前公开 API 没有删除用户接口，因此注册出来的测试用户不在该工具中清理。

## 维护规则

1. 新增、删除或修改 OpenAPI operation 时，必须同步更新 `tests/api_matrix/openapi_operation_matrix.yml`，否则 `scripts/validate_api_test_matrix.py` 和 `scripts/validate_api_test_case_matrix.py` 失败。
2. `coverage_status: missing` 不能进入主干；至少要标为 `partial` 并记录 `gap_notes`，或标为 `blocked_by_missing_public_setup` 并写明公开 API 层面的阻塞原因。
3. 行为测试不得读取数据库、仓储实现或业务内部 helper 来构造断言；只允许通过公开 HTTP API 搭建、查询和清理数据。新增可复用前置数据时优先放入 `tests/support/api_data.py`，测试结束必须触发清理。
4. PR required integration 可以继续排除 `openapi_contract`；nightly/manual lane 运行 OpenAPI contract smoke，并上传 OpenAPI JSON、pytest JUnit、collect 输出和运行日志。
5. Release gate 必须把 OpenAPI artifact 与 `openapi-contract` 结果作为发布证据。
