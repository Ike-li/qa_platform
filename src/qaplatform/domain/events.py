from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any
from uuid import UUID

if TYPE_CHECKING:
    from collections.abc import Callable

    from qaplatform.domain.models.run import RunStatus

type EventHandler = Callable[..., Any]


@dataclass
class DomainEvent:
    event_type: str
    occurred_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class RunCompletedEvent(DomainEvent):
    run_id: UUID = field(default_factory=lambda: UUID(int=0))
    status: RunStatus | None = None
    event_type: str = "run.completed"


@dataclass
class RunFailedEvent(DomainEvent):
    run_id: UUID = field(default_factory=lambda: UUID(int=0))
    error: str = ""
    event_type: str = "run.failed"


@dataclass
class RunCancelledEvent(DomainEvent):
    run_id: UUID = field(default_factory=lambda: UUID(int=0))
    event_type: str = "run.cancelled"


# ---- Handler registry ----

_handlers: dict[str, list[EventHandler]] = defaultdict(list)


def register(event_type: str, handler: EventHandler) -> None:
    """Register a handler for an event type."""
    _handlers[event_type].append(handler)


def unregister(event_type: str, handler: EventHandler) -> None:
    """Remove a previously registered handler."""
    _handlers[event_type].remove(handler)


def clear_handlers() -> None:
    """Remove all registered handlers (useful in tests)."""
    _handlers.clear()


async def dispatch(event: DomainEvent) -> None:
    """Dispatch an event to all registered handlers."""
    for handler in _handlers.get(event.event_type, []):
        if _is_coroutine(handler):
            await handler(event)
        else:
            handler(event)


def _is_coroutine(func: Callable) -> bool:
    import asyncio
    return asyncio.iscoroutinefunction(func)
