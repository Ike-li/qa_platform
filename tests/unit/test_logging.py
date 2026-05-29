from __future__ import annotations

import logging
from types import SimpleNamespace

import structlog

from qaplatform.logging import configure_logging


def _settings(log_format="json", log_level="info"):
    return SimpleNamespace(log_format=log_format, log_level=log_level)


def test_configure_logging_installs_root_handler_and_json_renderer():
    configure_logging(_settings(log_format="json", log_level="warning"))

    root = logging.getLogger()
    assert len(root.handlers) == 1
    assert root.level == logging.WARNING
    assert logging.getLogger("uvicorn.access").handlers == root.handlers
    assert logging.getLogger("uvicorn.error").handlers == root.handlers
    assert structlog.is_configured()


def test_configure_logging_supports_console_format():
    configure_logging(_settings(log_format="console", log_level="debug"))

    root = logging.getLogger()
    assert len(root.handlers) == 1
    assert root.level == logging.DEBUG
