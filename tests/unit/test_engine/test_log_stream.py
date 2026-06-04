"""Tests for the Redis Stream-based log transport."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, call
from uuid import uuid4

import pytest

from qaplatform.engine.log_stream import (
    ArchivedLogsNotFound,
    LogStream,
    _ARCHIVE_FAILURE_TTL,
    _MAX_LINE_BYTES,
    _MAXLEN,
    _STREAM_TTL,
    _TRUNCATION_MARKER,
    _next_stream_id,
)

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

    def test_next_stream_id_accepts_str_and_bytes(self):
        assert _next_stream_id("1780386444371-0") == "1780386444371-1"
        assert _next_stream_id(b"1780386444371-12") == "1780386444371-13"

    @pytest.mark.asyncio
    async def test_write_log(self):
        await self.stream.write_log(self.run_id, "hello world")

        self.redis.xadd.assert_awaited_once_with(
            f"run:{self.run_id}:logs",
            {"stream": "stdout", "line": "hello world"},
            maxlen=_MAXLEN,
            approximate=True,
        )

    @pytest.mark.asyncio
    async def test_write_log_stderr(self):
        await self.stream.write_log(self.run_id, "error", stream="stderr")

        self.redis.xadd.assert_awaited_once_with(
            f"run:{self.run_id}:logs",
            {"stream": "stderr", "line": "error"},
            maxlen=_MAXLEN,
            approximate=True,
        )

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

        self.redis.pipeline.assert_called_once_with(transaction=False)
        pipeline_mock.xadd.assert_has_calls(
            [
                call(
                    f"run:{self.run_id}:logs",
                    {"stream": "stdout", "line": "line1"},
                    maxlen=_MAXLEN,
                    approximate=True,
                ),
                call(
                    f"run:{self.run_id}:logs",
                    {"stream": "stderr", "line": "line2"},
                    maxlen=_MAXLEN,
                    approximate=True,
                ),
                call(
                    f"run:{self.run_id}:logs",
                    {"stream": "stdout", "line": "line3"},
                    maxlen=_MAXLEN,
                    approximate=True,
                ),
            ]
        )
        pipeline_mock.execute.assert_awaited_once_with()

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

        assert entries == [
            {"id": msg1_id, "stream": "stdout", "line": "line1"},
            {"id": msg2_id, "stream": "stderr", "line": "line2"},
        ]
        self.redis.xread.assert_awaited_once_with(
            {f"run:{self.run_id}:logs": "0"},
            count=50,
        )

    @pytest.mark.asyncio
    async def test_read_logs_decodes_bytes_response(self):
        self.redis.xread.return_value = [
            (f"run:{self.run_id}:logs".encode(), [
                (b"1234567890-0", {b"stream": b"stdout", b"line": b"line1"}),
                (b"1234567891-0", {b"stream": b"stderr", b"line": b"line2"}),
            ]),
        ]

        entries = await self.stream.read_logs(self.run_id, last_id="0", count=50)

        assert entries == [
            {"id": "1234567890-0", "stream": "stdout", "line": "line1"},
            {"id": "1234567891-0", "stream": "stderr", "line": "line2"},
        ]

    @pytest.mark.asyncio
    async def test_read_logs_with_block(self):
        self.redis.xread.return_value = []

        await self.stream.read_logs(self.run_id, block_ms=5000)

        self.redis.xread.assert_awaited_once_with(
            {f"run:{self.run_id}:logs": "0"},
            count=100,
            block=5000,
        )

    @pytest.mark.asyncio
    async def test_archive_logs_success(self):
        # Simulate two batches then empty
        msg_data = [
            ("1-0", {"stream": "stdout", "line": "line1"}),
            ("2-0", {"stream": "stdout", "line": "line2"}),
        ]
        empty = []

        self.redis.xrange = AsyncMock(side_effect=[msg_data, empty])

        s3_client = AsyncMock()
        result = await self.stream.archive_logs(self.run_id, s3_client, "qa-platform")

        assert result is True
        assert self.redis.xrange.await_args_list == [
            call(f"run:{self.run_id}:logs", min="-", max="+", count=500),
            call(f"run:{self.run_id}:logs", min="2-1", max="+", count=500),
        ]
        expected_body = (
            b'{"stream": "stdout", "line": "line1"}\n'
            b'{"stream": "stdout", "line": "line2"}'
        )
        s3_client.put_object.assert_awaited_once_with(
            Bucket="qa-platform",
            Key=f"logs/{self.run_id}.jsonl",
            Body=expected_body,
            ContentType="application/x-ndjson",
        )
        assert [
            json.loads(line)
            for line in expected_body.decode("utf-8").splitlines()
        ] == [
            {"stream": "stdout", "line": "line1"},
            {"stream": "stdout", "line": "line2"},
        ]

        # Should set TTL on the stream key
        self.redis.expire.assert_awaited_once_with(
            f"run:{self.run_id}:logs",
            _STREAM_TTL,
        )
        self.redis.srem.assert_awaited_once_with(_ARCHIVE_RETRY_SET, str(self.run_id))

    @pytest.mark.asyncio
    async def test_archive_logs_failure_sets_long_ttl(self):
        s3_client = AsyncMock()
        s3_client.put_object.side_effect = Exception("S3 down")

        # Force xrange to raise
        self.redis.xrange = AsyncMock(side_effect=Exception("redis error"))

        result = await self.stream.archive_logs(self.run_id, s3_client, "qa-platform")

        assert result is False
        s3_client.put_object.assert_not_awaited()
        # Should have set the failure TTL
        self.redis.expire.assert_awaited_once_with(
            f"run:{self.run_id}:logs",
            _ARCHIVE_FAILURE_TTL,
        )
        self.redis.sadd.assert_awaited_once_with(_ARCHIVE_RETRY_SET, str(self.run_id))

    @pytest.mark.asyncio
    async def test_retry_failed_archives_replays_recorded_runs(self):
        failed_run = uuid4()
        self.redis.smembers.return_value = [str(self.run_id).encode(), str(failed_run)]
        self.redis.xrange = AsyncMock(side_effect=[
            [
                ("1-0", {"stream": "stdout", "line": "ok"}),
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
        assert self.redis.xrange.await_args_list == [
            call(f"run:{self.run_id}:logs", min="-", max="+", count=500),
            call(f"run:{self.run_id}:logs", min="1-1", max="+", count=500),
            call(f"run:{failed_run}:logs", min="-", max="+", count=500),
        ]
        s3_client.put_object.assert_awaited_once_with(
            Bucket="qa-platform",
            Key=f"logs/{self.run_id}.jsonl",
            Body=b'{"stream": "stdout", "line": "ok"}',
            ContentType="application/x-ndjson",
        )
        assert self.redis.expire.await_args_list == [
            call(f"run:{self.run_id}:logs", _STREAM_TTL),
            call(f"run:{failed_run}:logs", _ARCHIVE_FAILURE_TTL),
        ]
        self.redis.srem.assert_awaited_once_with(_ARCHIVE_RETRY_SET, str(self.run_id))
        self.redis.sadd.assert_awaited_once_with(_ARCHIVE_RETRY_SET, str(failed_run))

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

        with pytest.raises(ArchivedLogsNotFound) as exc_info:
            await self.stream.read_archived_logs(
                self.run_id,
                s3_client,
                "qa-platform",
            )

        assert str(self.run_id) in str(exc_info.value)
        s3_client.get_object.assert_awaited_once_with(
            Bucket="qa-platform",
            Key=f"logs/{self.run_id}.jsonl",
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
        line = self.redis.xadd.await_args.args[1]["line"]
        assert line == "short line"

    @pytest.mark.asyncio
    async def test_oversize_line_truncated_with_marker(self):
        line = "x" * 10000
        await self.stream.write_log(self.run_id, line)
        out = self.redis.xadd.await_args.args[1]["line"]
        expected = "x" * (_MAX_LINE_BYTES - len(_TRUNCATION_MARKER)) + _TRUNCATION_MARKER
        assert out == expected
        assert len(out.encode("utf-8")) == _MAX_LINE_BYTES

    @pytest.mark.asyncio
    async def test_truncation_preserves_utf8_boundary(self):
        line = "中" * 2000  # 6000 bytes
        await self.stream.write_log(self.run_id, line)
        out = self.redis.xadd.await_args.args[1]["line"]
        expected_prefix = "中" * (
            (_MAX_LINE_BYTES - len(_TRUNCATION_MARKER.encode("utf-8"))) // 3
        )
        expected = expected_prefix + _TRUNCATION_MARKER
        assert isinstance(out, str)
        assert out == expected
        assert len(out.encode("utf-8")) == (
            len(expected_prefix.encode("utf-8"))
            + len(_TRUNCATION_MARKER.encode("utf-8"))
        )
        assert len(out.encode("utf-8")) <= _MAX_LINE_BYTES
        assert "�" not in out

    @pytest.mark.asyncio
    async def test_write_batch_truncates_each_entry(self):
        long = "y" * 10000
        expected_truncated = (
            "y" * (_MAX_LINE_BYTES - len(_TRUNCATION_MARKER)) + _TRUNCATION_MARKER
        )
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
        self.redis.pipeline.assert_called_once_with(transaction=False)
        first = pipeline_mock.xadd.call_args_list[0].args[1]
        second = pipeline_mock.xadd.call_args_list[1].args[1]
        assert pipeline_mock.xadd.call_args_list == [
            call(
                f"run:{self.run_id}:logs",
                {"stream": "stdout", "line": "ok"},
                maxlen=_MAXLEN,
                approximate=True,
            ),
            call(
                f"run:{self.run_id}:logs",
                {"stream": "stderr", "line": expected_truncated},
                maxlen=_MAXLEN,
                approximate=True,
            ),
        ]
        assert first["line"] == "ok"
        assert second == {"stream": "stderr", "line": expected_truncated}
        assert len(second["line"].encode("utf-8")) == _MAX_LINE_BYTES
        pipeline_mock.execute.assert_awaited_once_with()
