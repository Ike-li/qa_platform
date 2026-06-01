from __future__ import annotations

from pathlib import Path

from tests.unit.release_quality_contract_helpers import (
    _marked_block,
    _quality_ops_row,
    _quality_ops_row_containing,
    _read,
)


ROOT = Path(__file__).resolve().parents[2]
LOGGING_TEST = ROOT / "tests" / "unit" / "test_logging.py"
OBSERVABILITY_TRACING_TEST = (
    ROOT / "tests" / "unit" / "test_observability" / "test_tracing.py"
)


def test_quality_ops_capture_logging_renderer_output_shape_contract():
    quality_ops = _quality_ops_row_containing("Logging renderer output shape 契约")
    logging_test = _read(LOGGING_TEST)

    assert "Logging renderer output shape 契约" in quality_ops
    assert "`tests/unit/test_logging.py` 2 passed" in quality_ops
    assert "root handler 类型/stdout/ProcessorFormatter 投影证明唯一 handler" in (
        quality_ops
    )
    assert "json 分支解析 stdout JSON 并锁住 event/request_id/level/logger" in (
        quality_ops
    )
    assert "console 分支锁住 console 输出包含 event/component" in quality_ops
    assert "不退化成 JSON renderer" in quality_ops
    assert "只看 root handler 数量、level 和 uvicorn handler 绑定" in quality_ops
    assert "json/console renderer 选错" in quality_ops
    assert "structlog processor 丢 level/logger" in quality_ops
    assert "装了一个 handler" in quality_ops

    assert "import json" in logging_test
    assert "import sys" in logging_test
    assert "def _root_handler_projection(root: logging.Logger) -> list[dict[str, object]]:" in (
        logging_test
    )
    assert '"type": type(handler)' in logging_test
    assert '"stream": handler.stream' in logging_test
    assert '"formatter": type(handler.formatter)' in logging_test
    assert '"type": logging.StreamHandler' in logging_test
    assert '"stream": sys.stdout' in logging_test
    assert '"formatter": structlog.stdlib.ProcessorFormatter' in logging_test
    assert "assert len(root.handlers) == 1" not in logging_test
    assert "def test_configure_logging_installs_root_handler_and_json_renderer(capsys):" in (
        logging_test
    )
    assert 'structlog.get_logger("qaplatform.test").warning(' in logging_test
    assert "payload = json.loads(capsys.readouterr().out.strip().splitlines()[-1])" in (
        logging_test
    )
    for expected in [
        'assert payload["event"] == "json-ready"',
        'assert payload["request_id"] == "req-1"',
        'assert payload["level"] == "warning"',
        'assert payload["logger"] == "qaplatform.test"',
        'assert "console-ready" in output',
        'assert "component" in output',
        'assert not output.lstrip().startswith("{")',
    ]:
        assert expected in logging_test


def test_quality_ops_capture_opentelemetry_fastapi_exact_instrumentation_contract():
    tracing_test = _read(OBSERVABILITY_TRACING_TEST)
    direct_row = _quality_ops_row(
        "| 2026-05-31 | N/A（OpenTelemetry FastAPI kwargs direct dict projection 契约）"
    )
    row = _quality_ops_row(
        "| 2026-05-31 | N/A（OpenTelemetry FastAPI exact instrumentation/span 契约）"
    )

    assert "OpenTelemetry FastAPI kwargs direct dict projection 契约" in direct_row
    assert (
        "`tests/unit/test_observability/test_tracing.py::test_instrument_fastapi_app_once` 1 passed"
        in direct_row
    )
    assert "tracing full 8 passed" in direct_row
    assert "release quality docs contract full 339 passed" in direct_row
    assert "`tracer_provider`" in direct_row
    assert "其余 kwargs 作为完整 dict 等值断言" in direct_row
    assert "额外 kwargs 被夹带" in direct_row
    assert "kwargs direct dict projection 契约" in direct_row
    assert "kwargs 字段集合看起来对" in direct_row

    assert "OpenTelemetry FastAPI exact instrumentation/span 契约" in row
    assert (
        "`tests/unit/test_observability/test_tracing.py::test_instrument_fastapi_app_once tests/unit/test_observability/test_tracing.py::test_instrument_fastapi_records_route_status_and_excludes_ops_paths` 2 passed"
        in row
    )
    assert "tracing full 8 passed" in row
    assert "release quality docs contract full 198 passed" in row
    assert "`FastAPIInstrumentor.instrument_app(app, ...)` 的完整 kwargs 字段集合" in row
    assert "excluded_urls" in row
    assert "server_request_hook" in row
    assert "request header capture/sanitize 配置" in row
    assert "exact list" in row
    assert "captured request headers 必须为空" in row
    assert "`len(...) == 1`" in row
    assert "ops 路径也产出 server span" in row
    assert "FastAPI tracing 大概装上了" in row

    once_block = _marked_block(
        tracing_test,
        "def test_instrument_fastapi_app_once",
        "def test_instrument_fastapi_records_route_status_and_excludes_ops_paths",
    )
    span_block = _marked_block(
        tracing_test,
        "def test_instrument_fastapi_records_route_status_and_excludes_ops_paths",
        "def test_instrument_infra",
    )

    for expected in [
        "fastapi_args, fastapi_kwargs = calls[\"fastapi_app\"][0]",
        'assert [args for args, _ in calls["fastapi_app"]] == [(app,)]',
        "assert fastapi_args == (app,)",
        'assert fastapi_kwargs["tracer_provider"] is provider',
        "fastapi_kwargs_without_provider = {",
        'key: value for key, value in fastapi_kwargs.items() if key != "tracer_provider"',
        "assert fastapi_kwargs_without_provider == {",
        '"excluded_urls": tracing._EXCLUDED_URLS',
        '"server_request_hook": tracing._strip_sensitive_request_headers',
        '"http_capture_headers_server_request": []',
        '"http_capture_headers_sanitize_fields": [',
        "tracing._strip_sensitive_request_headers",
        '"authorization"',
        '"x-api-token"',
        '"cookie"',
    ]:
        assert expected in once_block
    assert "assert len(calls[\"fastapi_app\"])" not in once_block
    assert "assert set(fastapi_kwargs)" not in once_block
    assert 'fastapi_kwargs["excluded_urls"]' not in once_block
    assert '"metrics" in fastapi_kwargs["excluded_urls"]' not in once_block
    assert '"authorization" in fastapi_kwargs' not in once_block

    for expected in [
        "span_projection = []",
        "for span in server_spans:",
        '"method": attributes.get("http.method")',
        '"route": attributes.get("http.route")',
        '"status_code": attributes.get("http.status_code")',
        '"captured_request_headers": sorted(',
        'if key.startswith("http.request.header.")',
        "assert span_projection == [",
        '"method": "GET"',
        '"route": "/items/{item_id}"',
        '"status_code": 200',
        '"captured_request_headers": []',
    ]:
        assert expected in span_block
    assert "assert len(server_spans)" not in span_block
    assert "server_spans[0]" not in span_block
    assert "assert not any(" not in span_block
