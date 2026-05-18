"""Tests for webhook HMAC-SHA256 signature verification."""

from __future__ import annotations

import hashlib
import hmac as _hmac

import pytest

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
        assert sig.startswith("sha256=")
        hex_part = sig[len("sha256="):]
        # All hex characters
        assert all(c in "0123456789abcdef" for c in hex_part)
        # SHA-256 produces 32 bytes = 64 hex chars
        assert len(hex_part) == 64


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
# Empty / missing secret -- skip verification
# ------------------------------------------------------------------

class TestEmptySecret:
    """When no secret is configured, verification is skipped."""

    def test_empty_secret_skips_verification(self):
        assert verify_webhook_signature("", b"payload", "sha256=garbage") is True

    def test_none_like_empty_secret(self):
        # Caller passes empty string when project has no webhook_secret
        assert verify_webhook_signature("", b"", "") is True


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
        """Verify the implementation uses hmac.compare_digest.

        We inspect the source rather than measure timing, since CI
        environments make wall-clock assertions unreliable.
        """
        import inspect
        src = inspect.getsource(verify_webhook_signature)
        assert "compare_digest" in src

    def test_early_return_for_empty_secret(self):
        """Empty secret returns True immediately (no comparison)."""
        # This also ensures we don't accidentally compare with empty string
        result = verify_webhook_signature("", b"anything", "sha256=invalid")
        assert result is True


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
