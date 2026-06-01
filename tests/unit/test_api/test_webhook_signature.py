"""Tests for webhook HMAC-SHA256 signature verification."""

from __future__ import annotations

import hashlib
import hmac as _hmac
import re
from unittest.mock import patch

from qaplatform.infra.webhook_signature import (
    generate_webhook_signature,
    verify_webhook_signature,
)


# ------------------------------------------------------------------
# generate + verify round-trip
# ------------------------------------------------------------------

class TestGenerateAndVerify:
    """Basic round-trip tests for signature generation and verification."""

    def test_valid_signature_passes(self):
        secret = "my-super-secret"
        payload = b'{"git_ref": "main"}'
        sig = generate_webhook_signature(secret, payload)
        assert verify_webhook_signature(secret, payload, sig) is True

    def test_valid_signature_with_different_payloads(self):
        secret = "another-secret"
        for payload in [b"{}", b'{"key": "value"}', b"a" * 10_000]:
            sig = generate_webhook_signature(secret, payload)
            assert verify_webhook_signature(secret, payload, sig) is True

    def test_signature_format_is_sha256_equals_hex(self):
        sig = generate_webhook_signature("s", b"data")
        assert re.fullmatch(r"sha256=[0-9a-f]{64}", sig)


# ------------------------------------------------------------------
# Invalid signatures
# ------------------------------------------------------------------

class TestInvalidSignature:
    """Rejection of tampered or malformed signatures."""

    def test_wrong_signature_returns_false(self):
        secret = "secret"
        payload = b"hello"
        wrong_sig = "sha256=" + "0" * 64
        assert verify_webhook_signature(secret, payload, wrong_sig) is False

    def test_tampered_payload_returns_false(self):
        secret = "secret"
        sig = generate_webhook_signature(secret, b"original")
        assert verify_webhook_signature(secret, b"tampered", sig) is False

    def test_wrong_secret_returns_false(self):
        payload = b"data"
        sig = generate_webhook_signature("correct-secret", payload)
        assert verify_webhook_signature("wrong-secret", payload, sig) is False


# ------------------------------------------------------------------
# Empty / missing secret -- caller policy must decide, helper rejects
# ------------------------------------------------------------------

class TestEmptySecret:
    """Empty secrets must not make arbitrary signatures valid."""

    def test_empty_secret_rejects_signature_header(self):
        assert verify_webhook_signature("", b"payload", "sha256=garbage") is False

    def test_empty_secret_rejects_missing_signature_header(self):
        assert verify_webhook_signature("", b"", "") is False


# ------------------------------------------------------------------
# Malformed signature header
# ------------------------------------------------------------------

class TestMalformedHeader:
    """Various malformed header values must be rejected."""

    def test_missing_sha256_prefix(self):
        secret = "secret"
        payload = b"data"
        hex_digest = hashlib.sha256(b"data").hexdigest()
        # Missing the "sha256=" prefix
        assert verify_webhook_signature(secret, payload, hex_digest) is False

    def test_empty_signature_header(self):
        assert verify_webhook_signature("secret", b"data", "") is False

    def test_uppercase_prefix_rejected(self):
        """The prefix is case-sensitive: ``SHA256=`` should not match."""
        secret = "secret"
        payload = b"data"
        sig = generate_webhook_signature(secret, payload).upper()
        assert verify_webhook_signature(secret, payload, sig) is False


# ------------------------------------------------------------------
# Timing safety
# ------------------------------------------------------------------

class TestTimingSafety:
    """Ensure :func:`hmac.compare_digest` is used (no short-circuit)."""

    def test_uses_constant_time_compare(self):
        """Verify the implementation delegates comparison to hmac.compare_digest."""
        secret = "secret"
        payload = b"payload"
        expected = generate_webhook_signature(secret, payload)
        supplied = "sha256=" + "f" * 64

        with patch(
            "qaplatform.infra.webhook_signature.hmac.compare_digest",
            return_value=False,
        ) as compare_digest:
            result = verify_webhook_signature(secret, payload, supplied)

        assert result is False
        compare_digest.assert_called_once_with(expected, supplied)

    def test_early_reject_for_empty_secret(self):
        """Empty secret is rejected before comparison."""
        with patch(
            "qaplatform.infra.webhook_signature.hmac.compare_digest",
        ) as compare_digest:
            result = verify_webhook_signature("", b"anything", "sha256=invalid")

        assert result is False
        compare_digest.assert_not_called()


# ------------------------------------------------------------------
# Determinism
# ------------------------------------------------------------------

class TestDeterminism:
    """Same inputs always produce the same signature."""

    def test_same_input_same_output(self):
        secret = "deterministic"
        payload = b"consistent"
        sig1 = generate_webhook_signature(secret, payload)
        sig2 = generate_webhook_signature(secret, payload)
        assert sig1 == sig2

    def test_known_vector(self):
        """Cross-check against a manually computed HMAC-SHA256."""
        secret = "test-key"
        payload = b"hello world"
        expected_mac = _hmac.new(
            secret.encode(), payload, hashlib.sha256
        ).hexdigest()
        expected = f"sha256={expected_mac}"
        assert generate_webhook_signature(secret, payload) == expected
