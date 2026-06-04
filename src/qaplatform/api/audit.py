"""Backward-compatible import location for the shared audit helper."""
from __future__ import annotations

from qaplatform.infra.audit import write_audit

__all__ = ["write_audit"]
