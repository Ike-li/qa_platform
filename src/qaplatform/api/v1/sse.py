from __future__ import annotations

import json
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Request
from sse_starlette.sse import EventSourceResponse

from qaplatform.api.deps import get_current_user_bearer_only, get_redis
from qaplatform.domain.models.run import TERMINAL_STATUSES

router = APIRouter(prefix="/runs", tags=["sse"])


def _decode(val: bytes | str) -> str:
    """Decode bytes to str if needed (Redis returns bytes by default)."""
    return val.decode() if isinstance(val, bytes) else val


@router.get(
    "/{run_id}/logs",
    summary="SSE 实时日志流",
    description="从 Redis Stream 读取执行日志，仅接受 Bearer Token 认证",
)
async def stream_logs(
    run_id: UUID,
    request: Request,
    redis=Depends(get_redis),
    _user=Depends(get_current_user_bearer_only),
    last_event_id: str | None = Header(None, alias="Last-Event-ID"),
):
    stream_key = f"run:{run_id}:logs"
    status_key = f"run:{run_id}:status"

    async def event_generator():
        cursor = last_event_id or "0"
        terminal_seen = False

        while True:
            if await request.is_disconnected():
                break

            read_kwargs: dict = {"count": 100}
            if not terminal_seen:
                read_kwargs["block"] = 5000  # 5s long poll

            entries = await redis.xread(
                {stream_key: cursor},
                **read_kwargs,
            )

            if entries:
                for _stream_name, messages in entries:
                    for msg_id, data in messages:
                        cursor = msg_id
                        yield {
                            "id": _decode(msg_id),
                            "event": "log",
                            "data": json.dumps(data),
                        }
            elif terminal_seen:
                run_status = await redis.hget(status_key, "status")
                yield {
                    "event": "done",
                    "data": json.dumps({"status": run_status}),
                }
                break
            else:
                yield {"event": "heartbeat", "data": ""}

            if not terminal_seen:
                run_status = await redis.hget(status_key, "status")
                if run_status in {s.value for s in TERMINAL_STATUSES}:
                    terminal_seen = True

    return EventSourceResponse(event_generator())


@router.get(
    "/{run_id}/events",
    summary="SSE 状态变更事件",
    description="Run 状态变更的实时推送，仅接受 Bearer Token 认证",
)
async def stream_events(
    run_id: UUID,
    request: Request,
    redis=Depends(get_redis),
    _user=Depends(get_current_user_bearer_only),
    last_event_id: str | None = Header(None, alias="Last-Event-ID"),
):
    stream_key = f"run:{run_id}:events"
    status_key = f"run:{run_id}:status"

    async def event_generator():
        cursor = last_event_id or "0"
        terminal_seen = False

        while True:
            if await request.is_disconnected():
                break

            read_kwargs: dict = {"count": 50}
            if not terminal_seen:
                read_kwargs["block"] = 5000

            entries = await redis.xread(
                {stream_key: cursor},
                **read_kwargs,
            )

            if entries:
                for _stream_name, messages in entries:
                    for msg_id, data in messages:
                        cursor = msg_id
                        yield {
                            "id": _decode(msg_id),
                            "event": "status_change",
                            "data": json.dumps(data),
                        }
            elif terminal_seen:
                run_status = await redis.hget(status_key, "status")
                yield {
                    "event": "done",
                    "data": json.dumps({"status": run_status}),
                }
                break
            else:
                yield {"event": "heartbeat", "data": ""}

            if not terminal_seen:
                run_status = await redis.hget(status_key, "status")
                if run_status in {s.value for s in TERMINAL_STATUSES}:
                    terminal_seen = True

    return EventSourceResponse(event_generator())
