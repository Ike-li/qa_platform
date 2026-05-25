# T10: OpenTelemetry 装配

> **来源**：feature-catalog.md §4.2（设计见 §4.3）
> **必要性**：P2（增强项，不阻塞合规）
> **预计**：M（多文件改动）

## 背景

`pyproject.toml` 已声明 `opentelemetry-*` 依赖，但代码无 `TracerProvider` / `FastAPIInstrumentor` 装配。设计已锁定（OTLP/HTTP exporter），按规格实施即可。

## 实施起点

- **新增**：`src/qaplatform/observability/tracing.py`（装配入口 setup_tracing(settings)）
- **配置**：`src/qaplatform/config.py` 加 4 个 OTel 字段
- **装配位置**：
  - `src/qaplatform/main.py` lifespan 启动调 setup_tracing
  - `src/qaplatform/worker/settings.py` worker 启动同样调
- **手动 span**：`src/qaplatform/worker/tasks.py:execute_run`

## 配置项（加到 config.py）

```python
otel_enabled: bool = False  # 默认关闭
otel_exporter_endpoint: str = "http://localhost:4318/v1/traces"
otel_service_name: str = "qa-platform"
otel_sample_rate: float = Field(default=1.0, ge=0.0, le=1.0)
```

env var 命名：`QAP_OTEL_ENABLED` / `QAP_OTEL_EXPORTER_ENDPOINT` / etc.

## setup_tracing 大致结构

```python
def setup_tracing(settings: Settings) -> None:
    if not settings.otel_enabled:
        return
    
    resource = Resource.create({"service.name": settings.otel_service_name})
    provider = TracerProvider(
        resource=resource,
        sampler=ParentBased(TraceIdRatioBased(settings.otel_sample_rate)),
    )
    exporter = OTLPSpanExporter(endpoint=settings.otel_exporter_endpoint)
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
    
    FastAPIInstrumentor().instrument(
        tracer_provider=provider,
        excluded_urls="health,metrics",
        request_hook=_strip_auth_headers,  # 剔除 Authorization / X-API-Token
    )
    SQLAlchemyInstrumentor().instrument(tracer_provider=provider)
    RedisInstrumentor().instrument(tracer_provider=provider)


def _strip_auth_headers(span, scope):
    """Remove sensitive headers from request span attributes."""
    headers = dict(scope.get("headers") or [])
    for sensitive in (b"authorization", b"x-api-token", b"cookie"):
        headers.pop(sensitive, None)
    # Note: don't write back; just don't let them be recorded
```

## execute_run 手动 span

```python
async def execute_run(ctx, run_id):
    tracer = trace.get_tracer(__name__)
    with tracer.start_as_current_span("execute_run", attributes={"run.id": str(run_id)}):
        with tracer.start_as_current_span("source_clone"): ...
        with tracer.start_as_current_span("container_run"): ...
        with tracer.start_as_current_span("collect_results"): ...
        with tracer.start_as_current_span("upload_artifacts"): ...
```

## 验收标准

- [ ] `otel_enabled=False` 时启动正常，无任何 instrumentation 副作用
- [ ] `otel_enabled=True` 时 setup_tracing 成功装配；FastAPI、SQLAlchemy、Redis 三个 instrumentor 全部生效
- [ ] HTTP 请求的 span 含 `http.method` / `http.route` / `http.status_code`
- [ ] **不含** `Authorization` / `X-API-Token` / `Cookie` header（敏感字段过滤）
- [ ] `execute_run` 链路含 4 个子 span
- [ ] 采样率：sample_rate=0.5 时大约一半请求生成 span
- [ ] `/health/live` `/health/ready` `/metrics` 路径不生成 span（excluded_urls）
- [ ] 单元测试：setup_tracing 在 enabled / disabled 两个分支
- [ ] 手工验证：起一个 jaeger/tempo OTLP 接收端，看到 trace 链路

## 约束

- 不引入超出 pyproject 已声明的 OTel 包；如缺包必须在 PR 里说明
- request_hook 必须过滤敏感 header（**审计 directive 隐含要求**）
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
