# T10: OpenTelemetry 装配收口

> **来源**：feature-catalog.md §4.2（当前实现口径见 feature-catalog.md §4.3）
> **必要性**：P2（增强项，不阻塞合规）
> **预计**：S/M（依赖决策 + 部署验证 + 小幅增强）

## 背景

基础 OpenTelemetry 追踪已经落地，不应再把本任务理解为“新增 tracing.py / FastAPI instrumentation”：

- `src/qaplatform/config.py` 已有 `otel_enabled`、`otel_exporter_endpoint`、`otel_service_name`、`otel_sample_rate`
- `src/qaplatform/observability/tracing.py` 已实现 `setup_tracing(settings)`、`instrument_fastapi(app, provider)`、`instrument_infra(container, provider)`、OTLP exporter 可选导入和敏感 header 防线
- `src/qaplatform/main.py` 已在 app factory / lifespan 装配 FastAPI、SQLAlchemy、Redis tracing
- `src/qaplatform/worker/settings.py` 已在 worker startup 初始化 DB/Redis 后装配 infra tracing
- `src/qaplatform/worker/tasks.py::execute_run` 与 `src/qaplatform/engine/executor.py::RunExecutor.execute` 已有 worker/job 与 source/container/collect/upload 手动 span
- `tests/unit/test_observability/test_tracing.py` 已覆盖 enabled/disabled、幂等、缺 exporter、FastAPI instrumentation、敏感 header 清理和 infra instrumentation

当前剩余缺口是：`pyproject.toml` 仍未声明 OTLP HTTP exporter 包（如 `opentelemetry-exporter-otlp-proto-http`），也缺 Jaeger/Tempo 等接收端的部署验证证据；trace-log 关联仍是后续优化。

> 注意：未获得 maintainer 允许前，不要新增 OTLP HTTP exporter 依赖；也不要把 `OTLPSpanExporter` 写成强制导入。当前源码采用 endpoint 配置后才尝试可选导入的安全降级策略。

## 当前配置项

```python
otel_enabled: bool = False  # 默认关闭
otel_exporter_endpoint: str | None = None  # 为空时不导出；启用时配置 OTLP/HTTP endpoint
otel_service_name: str = "qa-platform"
otel_sample_rate: float = Field(default=1.0, ge=0.0, le=1.0)
```

env var 命名：`QAP_OTEL_ENABLED` / `QAP_OTEL_EXPORTER_ENDPOINT` / etc.

## 实施起点

- **依赖决策**：确认是否允许新增 `opentelemetry-exporter-otlp-proto-http`
- **导出器收口**：若获准新增依赖，把当前可选导入路径接入正式依赖，并保留 endpoint 为空时不导出的行为；若不获准，保留可选导入并在部署文档说明“本地 tracing 仅创建 provider，不外发”
- **部署验证**：用 Jaeger/Tempo 或等价 OTLP/HTTP 接收端验证 API 请求、worker job 和 executor 子 span 可被看到
- **文档证据**：把验证命令、接收端 endpoint、示例 trace 名称和已知限制补到 runbook/ops 文档
- **可选增强**：若要做 trace-log 关联，使用 structlog processor 注入 trace_id/span_id，但不要把它混进 exporter 依赖决策的必做路径

## 已完成验收

- [x] `otel_enabled=False` 时启动正常，无 instrumentation 副作用
- [x] `otel_enabled=True` 时 `setup_tracing` 创建 `TracerProvider`
- [x] `main.py` 对 FastAPI app 调 `instrument_fastapi(app, provider)`
- [x] API / worker 在 container 初始化后对 SQLAlchemy async engine 的 `sync_engine` 和 Redis 调 `instrument_infra(container, provider)`
- [x] 多次创建 test app / 多次调用 setup 有幂等 guard
- [x] 缺 OTLP HTTP exporter 包时不会启动失败，会记录 warning 并保留本地 provider
- [x] FastAPI instrumentation 配置敏感 header sanitize 字段，并有 request hook 清理兜底
- [x] `execute_run` / `RunExecutor.execute` 已有手动 span
- [x] 单元测试覆盖 enabled / disabled、FastAPI、infra 和敏感 header 分支

## 剩余验收

- [ ] maintainer 明确是否允许新增 `opentelemetry-exporter-otlp-proto-http`
- [ ] 若允许新增依赖：`pyproject.toml` 声明 exporter 包，`OTLPSpanExporter` 导入路径为 `opentelemetry.exporter.otlp.proto.http.trace_exporter`
- [ ] 若不允许新增依赖：部署文档明确 endpoint 配置后的降级行为和 warning 名称
- [ ] 手工或自动化验证：启动 Jaeger/Tempo OTLP/HTTP 接收端，看到 API 请求 span、`execute_run` 和 `source_clone` / `container_run` / `collect_results` / `upload_artifacts` 子 span
- [ ] `/health` `/ready` `/metrics` 路径不生成业务 span 的行为有验证证据
- [ ] 若实现 tenant 维度属性，只记录 `tenant.id` / role 等低敏维度；不要写 user_id / token
- [ ] 若实现 trace-log 关联，日志只注入 trace_id/span_id，不引入 header/token/user PII

## 约束

- 不要重复新增 `src/qaplatform/observability/tracing.py`、config 字段或 main/worker 基础装配；这些已经存在
- 不引入超出 `pyproject.toml` 已声明的 OTel 包，除非 maintainer 明确允许新增 OTLP HTTP exporter
- 不要把 `OTLPSpanExporter` 改成无条件导入；缺 exporter 包时必须可降级启动
- 敏感 header 必须通过 `http_capture_headers_sanitize_fields` 或等效测试可证明的机制过滤
- 不要默认开启（`otel_enabled=False` 是设计决定）
- 不要换成 gRPC exporter（当前设计决策选 HTTP）
- 不要做 metrics exporter（Prometheus 已存在，不重复）
- arq 没有官方 instrumentor；当前用 `execute_run` 手动 span 即可

## 建议提交拆分

1. `docs: 记录 OpenTelemetry exporter 决策`
2. `feat: 接入 OTLP HTTP exporter 依赖`（仅在 maintainer 允许时）
3. `docs: 补 OpenTelemetry 部署验证证据`
4. `feat: 注入 trace-log 关联`（可选，独立提交）
