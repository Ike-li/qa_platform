from __future__ import annotations

import json
import logging
from typing import Any
from uuid import UUID

import redis.asyncio as redis

log = logging.getLogger(__name__)

# Maximum stream length before auto-trim
_MAXLEN = 10_000
# TTL for the stream key after run completion (seconds)
_STREAM_TTL = 3600  # 1 hour
# TTL for stream on archive failure (seconds)
_ARCHIVE_FAILURE_TTL = 86400  # 24 hours
# Per-line byte cap (PRD §observability: 4KB max per log line) — guards
# against pathological producers (e.g. base64 blobs) blowing up Redis or
# stalling SSE consumers.
_MAX_LINE_BYTES = 4096
_TRUNCATION_MARKER = "...[truncated]"


def _truncate_line(line: str) -> str:
    """Cap a log line at _MAX_LINE_BYTES (UTF-8) with a trailing marker.

    Truncates on byte length, not char count, then trims any partial
    multibyte sequence at the boundary.
    """
    encoded = line.encode("utf-8")
    if len(encoded) <= _MAX_LINE_BYTES:
        return line
    marker_bytes = _TRUNCATION_MARKER.encode("utf-8")
    cap = _MAX_LINE_BYTES - len(marker_bytes)
    return encoded[:cap].decode("utf-8", errors="ignore") + _TRUNCATION_MARKER


class LogStream:
    """Redis Stream-based real-time log transport for run executions.

    Writes are done via ``XADD run:{id}:logs`` with auto-trim (MAXLEN).
    Reads use ``XREAD`` for SSE subscribers.
    After run completion, logs are archived to S3 as JSONL.
    """

    def __init__(self, redis_client: redis.Redis) -> None:
        self._redis = redis_client

    @staticmethod
    def _stream_key(run_id: UUID | str) -> str:
        return f"run:{run_id}:logs"

    async def write_log(
        self,
        run_id: UUID | str,
        line: str,
        *,
        stream: str = "stdout",
    ) -> None:
        """Append a single log line to the run's Redis Stream."""
        key = self._stream_key(run_id)
        await self._redis.xadd(
            key,
            {"stream": stream, "line": _truncate_line(line)},
            maxlen=_MAXLEN,
            approximate=True,
        )

    async def write_batch(
        self,
        run_id: UUID | str,
        lines: list[dict[str, str]],
    ) -> None:
        """Append multiple log entries. Each entry is {stream, line}."""
        key = self._stream_key(run_id)
        pipe = self._redis.pipeline(transaction=False)
        for entry in lines:
            capped = dict(entry)
            if "line" in capped:
                capped["line"] = _truncate_line(capped["line"])
            pipe.xadd(
                key,
                capped,
                maxlen=_MAXLEN,
                approximate=True,
            )
        await pipe.execute()

    async def read_logs(
        self,
        run_id: UUID | str,
        last_id: str = "0",
        count: int = 100,
        block_ms: int | None = None,
    ) -> list[dict[str, Any]]:
        """Read log entries from the stream. Returns list of {id, stream, line}."""
        key = self._stream_key(run_id)
        kwargs: dict[str, Any] = {"count": count}
        if block_ms is not None:
            kwargs["block"] = block_ms

        result = await self._redis.xread({key: last_id}, **kwargs)
        entries: list[dict[str, Any]] = []
        if result:
            for _stream_name, messages in result:
                for msg_id, data in messages:
                    entries.append({
                        "id": msg_id,
                        "stream": data.get("stream", "stdout"),
                        "line": data.get("line", ""),
                    })
        return entries

    async def archive_logs(
        self,
        run_id: UUID | str,
        s3_client: Any,
        bucket: str,
    ) -> bool:
        """Archive logs from Redis Stream to S3 as JSONL.

        Returns True on success, False on failure.
        On success, sets a short TTL on the stream key.
        On failure, sets a longer TTL (24h) to allow retry.
        """
        key = self._stream_key(run_id)
        s3_key = f"logs/{run_id}.jsonl"

        try:
            # Read all entries in the stream
            all_entries: list[dict[str, str]] = []
            cursor = "0"
            while True:
                batch = await self._redis.xread({key: cursor}, count=500)
                if not batch:
                    break
                for _stream_name, messages in batch:
                    if not messages:
                        return True  # no more entries
                    for msg_id, data in messages:
                        cursor = msg_id
                        all_entries.append(data)

            # Build JSONL content
            lines = [json.dumps(entry) for entry in all_entries]
            body = "\n".join(lines).encode("utf-8")

            await s3_client.put_object(
                Bucket=bucket,
                Key=s3_key,
                Body=body,
                ContentType="application/x-ndjson",
            )

            # Set short TTL — keep stream alive for in-flight SSE readers
            await self._redis.expire(key, _STREAM_TTL)
            log.info("archived %d log entries for run %s", len(all_entries), run_id)
            return True

        except Exception:
            log.exception("failed to archive logs for run %s", run_id)
            try:
                await self._redis.expire(key, _ARCHIVE_FAILURE_TTL)
            except Exception:
                pass
            return False

    async def delete_stream(self, run_id: UUID | str) -> None:
        """Delete the Redis Stream key for a run."""
        key = self._stream_key(run_id)
        await self._redis.delete(key)
