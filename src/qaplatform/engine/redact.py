"""Backward-compatible re-export for redaction helpers.

The canonical implementation is pure and lives in
``qaplatform.domain.services.redact`` so plugins can redact without importing
the engine layer.
"""
from __future__ import annotations

from qaplatform.domain.services.redact import (
    redact_sensitive_text,
    redact_url_userinfo,
)

__all__ = ["redact_sensitive_text", "redact_url_userinfo"]
