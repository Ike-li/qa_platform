from __future__ import annotations

import json
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette.sse import EventSourceResponse

from qaplatform.api.auth.permissions import Action
from qaplatform.api.deps import (
    UserIdentity,
    _get_db_session,
    _get_repos,
    enforce_project_action,
    get_redis,
)
from qaplatform.dependencies import RepositoryBundle
from qaplatform.domain.models.run import TERMINAL_STATUSES

router = APIRouter(prefix="/runs", tags=["sse"])


def _decode(val: bytes | str) -> str:
    """Decode bytes to str if needed (Redis returns bytes by default)."""
    return val.decode() if isinstance(val, bytes) else val


def _resolve_last_event_id(
    header_value: str | None,
    query_value: str | None,
) -> str:
    return header_value or query_value or "0"


async def _authenticate_sse_ticket(
    request: Request,
    ticket: str = Query(...),
) -> UserIdentity:
    """Authenticate SSE connection via single-use ticket from Redis.
    
    Uses atomic GETDEL to prevent race condition where two concurrent
    requests both succeed with the same ticket.
    """
    redis = request.app.state.container.redis_client
    key = f"sse_ticket:{ticket}"
    payload = await redis.getdel(key)
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired SSE ticket",
        )
    raw_payload = _decode(payload)
    try:
        payload_body = json.loads(raw_payload)
        if not isinstance(payload_body, dict):
            raise ValueError("SSE ticket payload must be a JSON object")
        user_id = payload_body["user_id"]
        role = payload_body["role"]
        tenant_id = payload_body["tenant_id"]
        scopes = payload_body.get("scopes")
        if not isinstance(role, str):
            raise ValueError("SSE ticket role must be a string")
        if scopes is not None and (
            not isinstance(scopes, list)
            or not all(isinstance(scope, str) for scope in scopes)
        ):
            raise ValueError("SSE ticket scopes must be a string list or null")
        user_uuid = UUID(str(user_id))
        tenant_uuid = UUID(str(tenant_id))
    except (json.JSONDecodeError, KeyError, TypeError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired SSE ticket",
        )
    return UserIdentity(
        user_id=user_uuid,
        role=role,
        tenant_id=tenant_uuid,
        scopes=scopes,
    )


@router.get(
    "/{run_id}/logs",
    summary="SSE 实时日志流",
    description="从 Redis Stream 读取执行日志，使用一次性 ticket 认证",
)
async def stream_logs(
    run_id: UUID,
    request: Request,
    redis=Depends(get_redis),
    user: UserIdentity = Depends(_authenticate_sse_ticket),
    repos: RepositoryBundle = Depends(_get_repos),
    session: AsyncSession = Depends(_get_db_session),
    last_event_id: str | None = Header(None, alias="Last-Event-ID"),
    last_event_id_query: str | None = Query(None, alias="last_event_id"),
):
    run = await repos.run.get_for_tenant(run_id, user.tenant_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    await enforce_project_action(session, user, run.project_id, Action.RUN_READ)

    stream_key = f"run:{run_id}:logs"
    status_key = f"run:{run_id}:status"

    async def event_generator():
        cursor = _resolve_last_event_id(last_event_id, last_event_id_query)
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
    description="Run 状态变更的实时推送，使用一次性 ticket 认证",
)
async def stream_events(
    run_id: UUID,
    request: Request,
    redis=Depends(get_redis),
    user: UserIdentity = Depends(_authenticate_sse_ticket),
    repos: RepositoryBundle = Depends(_get_repos),
    session: AsyncSession = Depends(_get_db_session),
    last_event_id: str | None = Header(None, alias="Last-Event-ID"),
    last_event_id_query: str | None = Query(None, alias="last_event_id"),
):
    run = await repos.run.get_for_tenant(run_id, user.tenant_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    await enforce_project_action(session, user, run.project_id, Action.RUN_READ)

    stream_key = f"run:{run_id}:events"
    status_key = f"run:{run_id}:status"

    async def event_generator():
        cursor = _resolve_last_event_id(last_event_id, last_event_id_query)
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
