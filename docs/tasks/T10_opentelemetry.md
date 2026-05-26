# T10: OpenTelemetry 装配

> **来源**：feature-catalog.md §4.2（设计见 feature-catalog.md §4.3）
> **必要性**：P2（增强项，不阻塞合规）
> **预计**：M（多文件改动）

## 背景

`pyproject.toml` 已声明部分 `opentelemetry-*` 依赖，但代码无 `TracerProvider` / `FastAPIInstrumentor` 装配。设计已锁定为 OTLP/HTTP exporter。

> 注意：当前 `pyproject.toml` 未声明 OTLP HTTP exporter 包（如 `opentelemetry-exporter-otlp-proto-http`）。执行本任务前必须确认是否允许新增该依赖；未确认时应停下报告，不要硬写无法导入的 `OTLPSpanExporter`。

## 实施起点

- **新增**：`src/qaplatform/observability/tracing.py`（建议拆 `setup_tracing(settings)` 返回/设置 provider，另提供 `instrument_fastapi(app, provider)` / `instrument_infra(container, provider)`，避免把只有 settings 的函数写成能访问 app/engine）
- **配置**：`src/qaplatform/config.py` 扩展 OTel 字段（当前已有 `otel_exporter_endpoint: str | None = None`，不要重复定义）
- **装配位置**：
  - `src/qaplatform/main.py` `create_app()` 已拿到 FastAPI `app`，FastAPI instrumentation 应对这个 app 调用 `FastAPIInstrumentor.instrument_app(app, ...)`
  - `src/qaplatform/main.py` lifespan / container 初始化后可拿到 `container.db_engine`，SQLAlchemy instrumentation 对 async engine 应传 `container.db_engine.sync_engine`
  - `src/qaplatform/worker/settings.py::on_startup` 在 `container.init_db()` 后同样对 `container.db_engine.sync_engine` 和 Redis instrumentor 装配；worker 进程没有 FastAPI app，不应调用 FastAPI app instrumentation
- **手动 span**：`src/qaplatform/worker/tasks.py::execute_run` 可包住整体 arq job；`source_clone` / `container_run` / `collect_results` / `upload_artifacts` 子 span 的实际调用点在 `src/qaplatform/engine/executor.py::RunExecutor.execute`
- **租户属性注意**：当前认证用户在 FastAPI dependency 中解析，不会自动出现在 `server_request_hook` 的 ASGI scope 里；若本任务要给请求 span 加 `tenant.id` / `user.role`，应在 `src/qaplatform/api/deps.py::get_current_user` 归一化 `UserIdentity` 后用 `trace.get_current_span().set_attribute(...)` 设置，并避免写入 user_id / token 等敏感值

## 配置项（扩展 config.py）

```python
otel_enabled: bool = False  # 默认关闭
otel_exporter_endpoint: str | None = None  # 为空时不导出；启用时配置 OTLP/HTTP endpoint
otel_service_name: str = "qa-platform"
otel_sample_rate: float = Field(default=1.0, ge=0.0, le=1.0)
```

env var 命名：`QAP_OTEL_ENABLED` / `QAP_OTEL_EXPORTER_ENDPOINT` / etc.

## setup_tracing 大致结构

```python
def setup_tracing(settings: Settings) -> TracerProvider | None:
    if not settings.otel_enabled:
        return None
    
    resource = Resource.create({"service.name": settings.otel_service_name})
    provider = TracerProvider(
        resource=resource,
        sampler=ParentBased(TraceIdRatioBased(settings.otel_sample_rate)),
    )
    exporter = OTLPSpanExporter(endpoint=settings.otel_exporter_endpoint)
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
    return provider


def instrument_fastapi(app, provider) -> None:
    FastAPIInstrumentor.instrument_app(
        app,
        tracer_provider=provider,
        excluded_urls="^/health$,^/ready$,^/metrics$",
        http_capture_headers_sanitize_fields=[
            "authorization",
            "cookie",
            "x-api-token",
            "set-cookie",
        ],
    )


def instrument_infra(container, provider) -> None:
    if container.db_engine is not None:
        # db_engine 是 AsyncEngine；SQLAlchemyInstrumentor 需要底层 sync_engine。
        SQLAlchemyInstrumentor().instrument(
            engine=container.db_engine.sync_engine,
            tracer_provider=provider,
        )
    RedisInstrumentor().instrument(tracer_provider=provider)
```

> 官方 OTel FastAPI instrumentor 的 app 级 API 是 `FastAPIInstrumentor.instrument_app(app, ...)`；`server_request_hook` 只接收 span/scope，不能靠“删 scope copy”保证敏感 header 不落 trace。若启用 header capture，应使用 `http_capture_headers_sanitize_fields` 做脱敏防线。

## execute_run 手动 span

```python
async def execute_run(ctx, run_id):
    tracer = trace.get_tracer(__name__)
    with tracer.start_as_current_span("execute_run", attributes={"run.id": str(run_id)}):
        ...

# RunExecutor.execute 内部再包：
with tracer.start_as_current_span("source_clone"): ...
with tracer.start_as_current_span("container_run"): ...
with tracer.start_as_current_span("collect_results"): ...
with tracer.start_as_current_span("upload_artifacts"): ...
```

## 验收标准

- [ ] `otel_enabled=False` 时启动正常，无任何 instrumentation 副作用
- [ ] `otel_enabled=True` 时 setup_tracing 成功装配；API 进程启用 FastAPI、SQLAlchemy、Redis instrumentor；worker 进程启用 SQLAlchemy、Redis instrumentor
- [ ] 多次创建 test app / 多次调用 setup 不会重复 instrument 或因重复 `trace.set_tracer_provider(...)` 产生运行期异常；测试可用幂等 guard 或可重置测试夹具
- [ ] HTTP 请求的 span 含 `http.method` / `http.route` / `http.status_code`
- [ ] 若实现 tenant 维度属性，只记录 `tenant.id` / role 等低敏维度；不要假设 FastAPI request hook 自动能拿到 `CurrentUser`
- [ ] **不含** `Authorization` / `Cookie` header；若请求里出现 legacy `X-API-Token` 也必须剔除（敏感字段过滤；当前认证入口仍是 `Authorization: Bearer ...`）
- [ ] `execute_run` 链路含 4 个子 span
- [ ] 采样率：sample_rate=0.5 时大约一半请求生成 span
- [ ] `/health` `/ready` `/metrics` 路径不生成 span（excluded_urls；当前源码健康检查路径不是 `/health/live` / `/health/ready`）
- [ ] 单元测试：setup_tracing 在 enabled / disabled 两个分支
- [ ] 手工验证：起一个 jaeger/tempo OTLP 接收端，看到 trace 链路

## 约束

- 不引入超出 pyproject 已声明的 OTel 包，除非 maintainer 明确允许新增 OTLP HTTP exporter；未获确认时必须停下报告，不要写无法导入的代码；若获准新增依赖，PR 描述必须说明偏离
- 不要把 `OTLPSpanExporter` 写成未声明依赖的导入；HTTP exporter 的导入路径来自 `opentelemetry-exporter-otlp-proto-http` 包：`opentelemetry.exporter.otlp.proto.http.trace_exporter`
- 敏感 header 必须通过 `http_capture_headers_sanitize_fields` 或等效测试可证明的机制过滤（**审计 directive 隐含要求**）；不要依赖一个不写回 scope 的 request hook copy
- commit 拆分：
  1. `feat: config 加 OpenTelemetry 配置字段`
  2. `feat: 装配 OTel TracerProvider + FastAPI/SQLA/Redis instrumentor`
  3. `feat: execute_run 链路手动 span（source/container/collect/upload）`
  4. `test: setup_tracing enabled/disabled 单元测试`

## 不要做

- 不要做 trace-log 关联（structlog inject trace_id）— P3 后续
- 不要默认开启（otel_enabled=False 是设计决定）
- 不要换成 gRPC exporter（设计决策选 HTTP）
- 不要做 metrics exporter（Prometheus 已存在，不重复）
- arq 没有官方 instrumentor，不要自己实现一个完整的 instrumentor — 在 execute_run 手动 span 已足够
