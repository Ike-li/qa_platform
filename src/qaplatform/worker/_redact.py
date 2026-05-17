"""Redact secrets from worker-originated text written to run.error_message.

git clone failures over HTTPS basic-auth surface URLs like
``https://x-access-token:<token>@host/repo`` in the exception text. That
text reaches GET /runs/{id} via run.error_message, leaking the token to
any RUN_READ user. Strip the userinfo segment before persisting.
"""
from __future__ import annotations

import re

# Capture: scheme://, optional userinfo (user[:pass]@), host+rest.
_URL_USERINFO_RE = re.compile(
    r"(?P<scheme>\b[a-zA-Z][a-zA-Z0-9+.\-]*://)"
    r"(?:[^/\s:@]+(?::[^/\s@]*)?@)"
    r"(?P<rest>[^\s]*)"
)


def redact_url_userinfo(text: str) -> str:
    """Replace ``user[:pass]@`` segments inside URLs with ``***``.

    Leaves the scheme and host intact so error messages remain useful.
    """
    if not text:
        return text
    return _URL_USERINFO_RE.sub(r"\g<scheme>***@\g<rest>", text)
