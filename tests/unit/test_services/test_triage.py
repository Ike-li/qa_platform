"""失败签名归一化（T12）单测：路径/数字/UUID 替换、首行截取、长度截断。"""

from __future__ import annotations

import pytest

from qaplatform.domain.services.triage import (
    EMPTY_SIGNATURE,
    SIGNATURE_MAX_LENGTH,
    failure_signature,
)


class TestFailureSignature:
    def test_numbers_normalized(self):
        assert (
            failure_signature("AssertionError: expected 1 got 2")
            == "AssertionError: expected <num> got <num>"
        )

    def test_same_signature_for_different_numbers(self):
        a = failure_signature("AssertionError: expected 1 got 2")
        b = failure_signature("AssertionError: expected 33 got 777")
        assert a == b

    def test_absolute_path_normalized(self):
        assert (
            failure_signature("error in /tmp/pytest-123/test_x.py")
            == "error in <path>"
        )

    def test_relative_path_normalized(self):
        assert (
            failure_signature("tests/unit/test_a.py:42: AssertionError")
            == "<path>:<num>: AssertionError"
        )

    def test_uuid_normalized_before_numbers(self):
        result = failure_signature(
            "missing id 550e8400-e29b-41d4-a716-446655440000"
        )
        assert result == "missing id <uuid>"

    def test_first_line_only(self):
        assert failure_signature("TypeError: boom\nTraceback ...\n  more") == (
            "TypeError: boom"
        )

    def test_truncated_to_max_length(self):
        assert len(failure_signature("x" * 500)) == SIGNATURE_MAX_LENGTH

    def test_none_message_uses_placeholder(self):
        assert failure_signature(None) == EMPTY_SIGNATURE

    @pytest.mark.parametrize("message", ["", "   ", " \n \n "])
    def test_blank_message_uses_placeholder(self, message):
        assert failure_signature(message) == EMPTY_SIGNATURE

    def test_dotted_suite_name_not_treated_as_path(self):
        # JUnit classname（tests.unit.test_x）不含斜杠，不应被路径规则吞掉。
        assert (
            failure_signature("tests.unit.test_x failed badly")
            == "tests.unit.test_x failed badly"
        )

    def test_mixed_message(self):
        result = failure_signature(
            "ConnectionError: host 10.0.0.1 retry 3 of 5 at /var/log/app/x.log"
        )
        assert result == (
            "ConnectionError: host <num>.<num>.<num>.<num> retry <num> "
            "of <num> at <path>"
        )

    def test_leading_whitespace_stripped(self):
        assert failure_signature("   boom 42  ") == "boom <num>"
