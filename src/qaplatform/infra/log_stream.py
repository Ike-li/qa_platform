from __future__ import annotations

import json
import logging
from inspect import isawaitable
from typing import TYPE_CHECKING, Any
from uuid import UUID

if TYPE_CHECKING:
    import redis.asyncio as redis

log = logging.getLogger(__name__)

# Maximum stream length before auto-trim
_MAXLEN = 10_000
# TTL for the stream key after run completion (seconds)
_STREAM_TTL = 3600  # 1 hour
# TTL for stream on archive failure (seconds)
_ARCHIVE_FAILURE_TTL = 86400  # 24 hours
# Redis set of run IDs whose log archive failed and should be retried.
_ARCHIVE_RETRY_SET = "run:logs:archive_failed"
# Per-line byte cap (PRD §observability: 4KB max per log line) — guards
# against pathological producers (e.g. base64 blobs) blowing up Redis or
# stalling SSE consumers.
_MAX_LINE_BYTES = 4096
_TRUNCATION_MARKER = "...[truncated]"


class ArchivedLogsNotFound(Exception):
    """Raised when an archived log object does not exist in object storage."""


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


def _next_stream_id(stream_id: bytes | str) -> str:
    """Return the next inclusive-safe Redis Stream ID after ``stream_id``."""
    if isinstance(stream_id, bytes):
        stream_id = stream_id.decode("utf-8")
    timestamp, sequence = stream_id.split("-", 1)
    return f"{timestamp}-{int(sequence) + 1}"


def _redis_text(value: Any) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    if isinstance(value, str):
        return value
    return str(value)


def _redis_field(data: dict[Any, Any], name: str, default: str) -> str:
    value = data.get(name)
    if value is None:
        value = data.get(name.encode("utf-8"))
    if value is None:
        return default
    return _redis_text(value)


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

    @staticmethod
    def _run_id_value(value: Any) -> str:
        if isinstance(value, bytes):
            return value.decode("utf-8")
        return str(value)

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
                        "id": _redis_text(msg_id),
                        "stream": _redis_field(data, "stream", "stdout"),
                        "line": _redis_field(data, "line", ""),
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
            # Read all historical entries in the stream. ``XREAD`` starts at
            # IDs greater than the supplied cursor for live reads, but client
            # behavior around historical tail cursors is easy to misuse here.
            # ``XRANGE`` with an explicitly advanced inclusive cursor gives a
            # finite, deterministic archive pass.
            all_entries: list[dict[str, str]] = []
            cursor = "-"
            while True:
                messages = await self._redis.xrange(key, min=cursor, max="+", count=500)
                if not messages:
                    break
                for msg_id, data in messages:
                    cursor = _next_stream_id(msg_id)
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
            try:
                await self._redis.srem(_ARCHIVE_RETRY_SET, str(run_id))
            except Exception:
                log.warning("failed to clear log archive retry marker for run %s", run_id, exc_info=True)
            log.info("archived %d log entries for run %s", len(all_entries), run_id)
            return True

        except Exception:
            log.exception("failed to archive logs for run %s", run_id)
            try:
                await self._redis.expire(key, _ARCHIVE_FAILURE_TTL)
            except Exception:
                pass
            try:
                await self._redis.sadd(_ARCHIVE_RETRY_SET, str(run_id))
            except Exception:
                log.warning("failed to record log archive retry marker for run %s", run_id, exc_info=True)
            return False

    async def read_archived_logs(
        self,
        run_id: UUID | str,
        s3_client: Any,
        bucket: str,
    ) -> list[dict[str, Any]]:
        """Read archived run logs from S3 JSONL storage.

        Archive rows are intentionally normalized to the same public shape as
        live log rows: ``{"stream": "...", "line": "..."}``. Object-storage
        dependencies differ in how they expose ``Body`` during tests vs.
        aiobotocore, so the body reader accepts bytes, strings, sync reads, and
        async reads.
        """
        s3_key = f"logs/{run_id}.jsonl"

        try:
            response = await s3_client.get_object(Bucket=bucket, Key=s3_key)
        except Exception as exc:
            if _is_missing_object_error(exc):
                raise ArchivedLogsNotFound(str(run_id)) from exc
            raise

        raw_body = await _read_s3_body(response.get("Body", b""))
        if not raw_body:
            return []

        entries: list[dict[str, Any]] = []
        for raw_line in raw_body.decode("utf-8").splitlines():
            if not raw_line.strip():
                continue
            entry = json.loads(raw_line)
            entries.append(
                {
                    **entry,
                    "stream": entry.get("stream", "stdout"),
                    "line": entry.get("line", ""),
                }
            )
        return entries

    async def retry_failed_archives(
        self,
        s3_client: Any,
        bucket: str,
        *,
        limit: int = 100,
    ) -> int:
        """Retry log archives remembered after prior failures.

        Returns the number of run streams successfully archived during this
        pass. Failed retries keep their retry marker and 24h stream TTL.
        """
        raw_run_ids = await self._redis.smembers(_ARCHIVE_RETRY_SET)
        retried = 0
        for raw_run_id in list(raw_run_ids)[:limit]:
            run_id = self._run_id_value(raw_run_id)
            if await self.archive_logs(run_id, s3_client, bucket):
                retried += 1
        return retried

    async def delete_stream(self, run_id: UUID | str) -> None:
        """Delete the Redis Stream key for a run."""
        key = self._stream_key(run_id)
        await self._redis.delete(key)


async def _read_s3_body(body: Any) -> bytes:
    if isinstance(body, bytes):
        return body
    if isinstance(body, str):
        return body.encode("utf-8")
    if hasattr(body, "read"):
        value = body.read()
        if isawaitable(value):
            value = await value
        if isinstance(value, bytes):
            return value
        if isinstance(value, str):
            return value.encode("utf-8")
    return bytes(body)


def _is_missing_object_error(exc: Exception) -> bool:
    response = getattr(exc, "response", None)
    if isinstance(response, dict):
        code = response.get("Error", {}).get("Code")
        if code in {"NoSuchKey", "404", "NotFound"}:
            return True
    return exc.__class__.__name__ in {"NoSuchKey", "NoSuchKeyError"}
