from __future__ import annotations

import json
import logging
import sys
from types import SimpleNamespace

import structlog

from qaplatform.logging import configure_logging


def _settings(log_format="json", log_level="info"):
    return SimpleNamespace(log_format=log_format, log_level=log_level)


def _root_handler_projection(root: logging.Logger) -> list[dict[str, object]]:
    return [
        {
            "type": type(handler),
            "stream": handler.stream,
            "formatter": type(handler.formatter),
        }
        for handler in root.handlers
    ]


def test_configure_logging_installs_root_handler_and_json_renderer(capsys):
    configure_logging(_settings(log_format="json", log_level="warning"))

    root = logging.getLogger()
    assert _root_handler_projection(root) == [
        {
            "type": logging.StreamHandler,
            "stream": sys.stdout,
            "formatter": structlog.stdlib.ProcessorFormatter,
        }
    ]
    assert root.level == logging.WARNING
    assert logging.getLogger("uvicorn.access").handlers == root.handlers
    assert logging.getLogger("uvicorn.error").handlers == root.handlers
    assert structlog.is_configured()

    structlog.get_logger("qaplatform.test").warning(
        "json-ready",
        request_id="req-1",
    )
    payload = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert payload["event"] == "json-ready"
    assert payload["request_id"] == "req-1"
    assert payload["level"] == "warning"
    assert payload["logger"] == "qaplatform.test"


def test_configure_logging_supports_console_format(capsys):
    configure_logging(_settings(log_format="console", log_level="debug"))

    root = logging.getLogger()
    assert _root_handler_projection(root) == [
        {
            "type": logging.StreamHandler,
            "stream": sys.stdout,
            "formatter": structlog.stdlib.ProcessorFormatter,
        }
    ]
    assert root.level == logging.DEBUG

    structlog.get_logger("qaplatform.test").debug(
        "console-ready",
        component="worker",
    )
    output = capsys.readouterr().out.strip()
    assert "console-ready" in output
    assert "component" in output
    assert not output.lstrip().startswith("{")
