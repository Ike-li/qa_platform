"""Redact secrets before persisting public error or log text.

git clone failures over HTTPS basic-auth surface URLs like
``https://x-access-token:<token>@host/repo`` in the exception text. That
text reaches GET /runs/{id} via run.error_message, leaking the token to
any RUN_READ user. Container stdout/stderr reaches live SSE and archived
logs, so configured environment secret values are also stripped before the
line is written to Redis.
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping
import re
from typing import Any

# Capture: scheme://, optional userinfo (user[:pass]@), host+rest.
_URL_USERINFO_RE = re.compile(
    r"(?P<scheme>\b[a-zA-Z][a-zA-Z0-9+.\-]*://)"
    r"(?:[^/\s:@]+(?::[^/\s@]*)?@)"
    r"(?P<rest>[^\s]*)"
)
_SENSITIVE_ENV_KEY_RE = re.compile(
    r"(secret|token|password|passwd|pwd|credential|api[_-]?key|private[_-]?key|auth)",
    re.IGNORECASE,
)
_REDACTION_MARKER = "[REDACTED]"
_MIN_SECRET_VALUE_LENGTH = 8
_MIN_NAMED_SECRET_VALUE_LENGTH = 4


def redact_url_userinfo(text: str) -> str:
    """Replace ``user[:pass]@`` segments inside URLs with ``***``.

    Leaves the scheme and host intact so error messages remain useful.
    """
    if not text:
        return text
    return _URL_USERINFO_RE.sub(r"\g<scheme>***@\g<rest>", text)


def redact_sensitive_text(
    text: str,
    env_vars: Mapping[str, Any] | Iterable[Any] | None = None,
) -> str:
    """Redact URL userinfo and configured environment secret values.

    Environment variables are encrypted at rest and redacted from audits; the
    same values must not leak back through worker stdout/stderr when user tests
    print them. Short, non-sensitive values are intentionally ignored to avoid
    turning common words or numbers into noisy false positives.
    """
    redacted = text
    for value in _secret_values(env_vars):
        redacted = redacted.replace(value, _REDACTION_MARKER)
    return redact_url_userinfo(redacted)


def _secret_values(
    env_vars: Mapping[str, Any] | Iterable[Any] | None,
) -> list[str]:
    if env_vars is None:
        return []

    values: set[str] = set()
    if isinstance(env_vars, Mapping):
        for key, raw_value in env_vars.items():
            value = _normalise_secret_value(raw_value)
            if value is None:
                continue
            if _is_secret_env_value(str(key), value):
                values.add(value)
    else:
        for raw_value in env_vars:
            value = _normalise_secret_value(raw_value)
            if value is not None and len(value) >= _MIN_SECRET_VALUE_LENGTH:
                values.add(value)

    return sorted(values, key=len, reverse=True)


def _normalise_secret_value(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, bytes):
        text = value.decode("utf-8", errors="ignore")
    else:
        text = str(value)
    if not text:
        return None
    return text


def _is_secret_env_value(key: str, value: str) -> bool:
    if len(value) >= _MIN_SECRET_VALUE_LENGTH:
        return True
    return (
        len(value) >= _MIN_NAMED_SECRET_VALUE_LENGTH
        and _SENSITIVE_ENV_KEY_RE.search(key) is not None
    )
