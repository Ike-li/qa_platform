"""Backward-compatible re-export of redact_url_userinfo.

The canonical implementation lives in ``qaplatform.engine.redact`` so the
engine layer can use it without importing from the worker package.  This
shim keeps existing ``from qaplatform.worker._redact import redact_url_userinfo``
call-sites working without modification.
"""
from qaplatform.engine.redact import redact_url_userinfo

__all__ = ["redact_url_userinfo"]
