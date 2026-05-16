"""Audit log helper.

A thin wrapper that records administrative actions to the audit.event
table without failing the originating request. Audit failures are logged
and swallowed (the user action has already succeeded by the time we get
here, and audit history is best-effort observability — not a hard
business invariant).
"""
from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

log = logging.getLogger(__name__)


def _serialize(value: Any) -> dict | None:
    if value is None:
        return None
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if isinstance(value, dict):
        return value
    return {"value": str(value)}


async def write_audit(
    repos: Any,
    user: Any,
    *,
    action: str,
    resource_type: str,
    resource_id: UUID | None = None,
    before: Any = None,
    after: Any = None,
) -> None:
    """Record an audit event; never raises."""
    try:
        await repos.audit.create(
            tenant_id=user.tenant_id,
            user_id=user.user_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            before_state=_serialize(before),
            after_state=_serialize(after),
        )
    except Exception:
        log.warning(
            "audit write failed (action=%s resource=%s id=%s)",
            action,
            resource_type,
            resource_id,
            exc_info=True,
        )
