"""Webhook HMAC-SHA256 signature verification utilities.

Implements GitHub-style ``sha256=<hex>`` payload signatures so that
incoming webhook requests can be authenticated against a per-project
shared secret.
"""

from __future__ import annotations

import hashlib
import hmac


def generate_webhook_signature(secret: str, payload: bytes) -> str:
    """Generate a ``sha256=<hex>`` signature for *payload* using *secret*.

    Primarily intended for testing and for server-side verification
    helpers.
    """
    digest = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def verify_webhook_signature(
    secret: str,
    payload: bytes,
    signature_header: str,
) -> bool:
    """Verify that *signature_header* matches the HMAC-SHA256 of *payload*.

    Parameters
    ----------
    secret:
        Shared webhook secret configured on the project.
    payload:
        Raw request body bytes.
    signature_header:
        Value of the ``X-Webhook-Signature`` header, expected in
        ``sha256=<hex>`` format (case-sensitive prefix).

    Returns
    -------
    bool
        ``True`` when the signature is valid, ``False`` otherwise.
        Uses :func:`hmac.compare_digest` to guard against timing
        attacks.
    """
    if not secret:
        # No secret configured -- nothing to verify.
        return True

    if not signature_header:
        return False

    expected = generate_webhook_signature(secret, payload)

    return hmac.compare_digest(expected, signature_header)
