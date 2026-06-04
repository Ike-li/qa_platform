from __future__ import annotations

import sys as _sys

from qaplatform.infra import log_stream as _log_stream
from qaplatform.infra.log_stream import ArchivedLogsNotFound, LogStream

__all__ = ["ArchivedLogsNotFound", "LogStream"]

_sys.modules[__name__] = _log_stream
