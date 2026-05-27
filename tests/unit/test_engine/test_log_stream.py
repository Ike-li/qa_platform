"""Tests for the Redis Stream-based log transport."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from qaplatform.engine.log_stream import ArchivedLogsNotFound, LogStream

_ARCHIVE_RETRY_SET = "run:logs:archive_failed"


class TestLogStream:
    def setup_method(self):
        self.redis = AsyncMock()
        self.stream = LogStream(self.redis)
        self.run_id = uuid4()

    def test_stream_key_format(self):
        key = LogStream._stream_key("run-123")
        assert key == "run:run-123:logs"

    def test_stream_key_with_uuid(self):
        key = LogStream._stream_key(self.run_id)
        assert key == f"run:{self.run_id}:logs"

    @pytest.mark.asyncio
    async def test_write_log(self):
        await self.stream.write_log(self.run_id, "hello world")

        self.redis.xadd.assert_awaited_once()
        call_args = self.redis.xadd.call_args
        key = call_args[0][0]
        data = call_args[0][1]
        assert key == f"run:{self.run_id}:logs"
        assert data == {"stream": "stdout", "line": "hello world"}

    @pytest.mark.asyncio
    async def test_write_log_stderr(self):
        await self.stream.write_log(self.run_id, "error", stream="stderr")

        data = self.redis.xadd.call_args[0][1]
        assert data["stream"] == "stderr"
        assert data["line"] == "error"

    @pytest.mark.asyncio
    async def test_write_batch(self):
        lines = [
            {"stream": "stdout", "line": "line1"},
            {"stream": "stderr", "line": "line2"},
            {"stream": "stdout", "line": "line3"},
        ]
        pipeline_mock = AsyncMock()
        pipeline_mock.execute = AsyncMock(return_value=[])
        pipeline_mock.xadd = MagicMock(return_value=pipeline_mock)
        self.redis.pipeline = MagicMock(return_value=pipeline_mock)

        await self.stream.write_batch(self.run_id, lines)

        # Should call pipeline.execute once
        pipeline_mock.execute.assert_awaited_once()
        # Pipeline should have 3 xadd calls
        assert pipeline_mock.xadd.call_count == 3

    @pytest.mark.asyncio
    async def test_read_logs_empty(self):
        self.redis.xread.return_value = []

        entries = await self.stream.read_logs(self.run_id)
        assert entries == []

    @pytest.mark.asyncio
    async def test_read_logs_with_data(self):
        msg1_id = "1234567890-0"
        msg2_id = "1234567891-0"
        self.redis.xread.return_value = [
            (f"run:{self.run_id}:logs", [
                (msg1_id, {"stream": "stdout", "line": "line1"}),
                (msg2_id, {"stream": "stderr", "line": "line2"}),
            ]),
        ]

        entries = await self.stream.read_logs(self.run_id, last_id="0", count=50)

        assert len(entries) == 2
        assert entries[0]["id"] == msg1_id
        assert entries[0]["stream"] == "stdout"
        assert entries[0]["line"] == "line1"
        assert entries[1]["id"] == msg2_id
        assert entries[1]["stream"] == "stderr"

    @pytest.mark.asyncio
    async def test_read_logs_with_block(self):
        self.redis.xread.return_value = []

        await self.stream.read_logs(self.run_id, block_ms=5000)

        call_kwargs = self.redis.xread.call_args.kwargs
        assert call_kwargs.get("block") == 5000

    @pytest.mark.asyncio
    async def test_archive_logs_success(self):
        # Simulate two batches then empty
        msg_data = [
            (f"run:{self.run_id}:logs", [
                ("1-0", {"stream": "stdout", "line": "line1"}),
                ("2-0", {"stream": "stdout", "line": "line2"}),
            ]),
        ]
        empty = []

        self.redis.xread = AsyncMock(side_effect=[msg_data, empty])

        s3_client = AsyncMock()
        result = await self.stream.archive_logs(self.run_id, s3_client, "qa-platform")

        assert result is True
        s3_client.put_object.assert_awaited_once()
        call_kwargs = s3_client.put_object.call_args.kwargs
        assert call_kwargs["Bucket"] == "qa-platform"
        assert call_kwargs["Key"] == f"logs/{self.run_id}.jsonl"
        assert call_kwargs["ContentType"] == "application/x-ndjson"

        # Should set TTL on the stream key
        self.redis.expire.assert_awaited_once()
        self.redis.srem.assert_awaited_once_with(_ARCHIVE_RETRY_SET, str(self.run_id))

    @pytest.mark.asyncio
    async def test_archive_logs_failure_sets_long_ttl(self):
        s3_client = AsyncMock()
        s3_client.put_object.side_effect = Exception("S3 down")

        # Force xread to raise
        self.redis.xread = AsyncMock(side_effect=Exception("redis error"))

        result = await self.stream.archive_logs(self.run_id, s3_client, "qa-platform")

        assert result is False
        # Should have set the failure TTL
        self.redis.expire.assert_awaited_once()
        self.redis.sadd.assert_awaited_once_with(_ARCHIVE_RETRY_SET, str(self.run_id))

    @pytest.mark.asyncio
    async def test_retry_failed_archives_replays_recorded_runs(self):
        failed_run = uuid4()
        self.redis.smembers.return_value = [str(self.run_id).encode(), str(failed_run)]
        self.redis.xread = AsyncMock(side_effect=[
            [
                (f"run:{self.run_id}:logs", [
                    ("1-0", {"stream": "stdout", "line": "ok"}),
                ]),
            ],
            [],
            Exception("redis still down"),
        ])
        s3_client = AsyncMock()

        retried = await self.stream.retry_failed_archives(
            s3_client,
            "qa-platform",
            limit=10,
        )

        assert retried == 1
        assert s3_client.put_object.await_count == 1
        self.redis.srem.assert_any_await(_ARCHIVE_RETRY_SET, str(self.run_id))
        self.redis.sadd.assert_any_await(_ARCHIVE_RETRY_SET, str(failed_run))

    @pytest.mark.asyncio
    async def test_read_archived_logs_parses_jsonl_body(self):
        class _Body:
            async def read(self):
                return (
                    b'{"stream": "stdout", "line": "first"}\n'
                    b'{"stream": "stderr", "line": "second"}\n'
                )

        s3_client = AsyncMock()
        s3_client.get_object.return_value = {"Body": _Body()}

        entries = await self.stream.read_archived_logs(
            self.run_id,
            s3_client,
            "qa-platform",
        )

        assert entries == [
            {"stream": "stdout", "line": "first"},
            {"stream": "stderr", "line": "second"},
        ]
        s3_client.get_object.assert_awaited_once_with(
            Bucket="qa-platform",
            Key=f"logs/{self.run_id}.jsonl",
        )

    @pytest.mark.asyncio
    async def test_read_archived_logs_missing_object_raises_not_found(self):
        class _MissingObject(Exception):
            response = {"Error": {"Code": "NoSuchKey"}}

        s3_client = AsyncMock()
        s3_client.get_object.side_effect = _MissingObject("missing")

        with pytest.raises(ArchivedLogsNotFound):
            await self.stream.read_archived_logs(
                self.run_id,
                s3_client,
                "qa-platform",
            )

    @pytest.mark.asyncio
    async def test_delete_stream(self):
        await self.stream.delete_stream(self.run_id)
        self.redis.delete.assert_awaited_once_with(f"run:{self.run_id}:logs")


class TestLogStreamLineTruncation:
    """P1-H: log lines must be capped at 4KB before reaching Redis to
    keep producers like base64 dumps from blowing up Redis nodes or
    stalling SSE consumers.
    """

    def setup_method(self):
        self.redis = AsyncMock()
        self.stream = LogStream(self.redis)
        self.run_id = uuid4()

    @pytest.mark.asyncio
    async def test_short_line_passes_through(self):
        await self.stream.write_log(self.run_id, "short line")
        line = self.redis.xadd.call_args[0][1]["line"]
        assert line == "short line"

    @pytest.mark.asyncio
    async def test_oversize_line_truncated_with_marker(self):
        line = "x" * 10000
        await self.stream.write_log(self.run_id, line)
        out = self.redis.xadd.call_args[0][1]["line"]
        assert len(out.encode("utf-8")) <= 4096
        assert out.endswith("...[truncated]")

    @pytest.mark.asyncio
    async def test_truncation_preserves_utf8_boundary(self):
        line = "中" * 2000  # 6000 bytes
        await self.stream.write_log(self.run_id, line)
        out = self.redis.xadd.call_args[0][1]["line"]
        assert isinstance(out, str)
        assert len(out.encode("utf-8")) <= 4096
        assert out.endswith("...[truncated]")
        assert "�" not in out

    @pytest.mark.asyncio
    async def test_write_batch_truncates_each_entry(self):
        long = "y" * 10000
        pipeline_mock = AsyncMock()
        pipeline_mock.execute = AsyncMock(return_value=[])
        pipeline_mock.xadd = MagicMock(return_value=pipeline_mock)
        self.redis.pipeline = MagicMock(return_value=pipeline_mock)

        await self.stream.write_batch(
            self.run_id,
            [
                {"stream": "stdout", "line": "ok"},
                {"stream": "stderr", "line": long},
            ],
        )
        assert pipeline_mock.xadd.call_count == 2
        first = pipeline_mock.xadd.call_args_list[0][0][1]
        second = pipeline_mock.xadd.call_args_list[1][0][1]
        assert first["line"] == "ok"
        assert len(second["line"].encode("utf-8")) <= 4096
        assert second["line"].endswith("...[truncated]")
