from __future__ import annotations

import os

os.environ.setdefault("QAP_DATABASE_URL", "postgresql+asyncpg://e2e:e2e@127.0.0.1:5432/e2e")
os.environ.setdefault("QAP_REDIS_URL", "redis://127.0.0.1:6379/15")
os.environ.setdefault("QAP_S3_ENDPOINT", "http://127.0.0.1:9000")
os.environ.setdefault("QAP_S3_ACCESS_KEY", "e2e")
os.environ.setdefault("QAP_S3_SECRET_KEY", "e2e")
os.environ.setdefault("QAP_JWT_SECRET", "e2e-secret-at-least-32bytes-long!")
os.environ.setdefault(
    "QAP_ENCRYPTION_KEY",
    "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
)

from qaplatform.config import Settings
from qaplatform.main import create_app


class E2EContainer:
    def __init__(self) -> None:
        self.settings = Settings()

    async def close(self) -> None:
        return None


container = E2EContainer()
app = create_app(container=container, settings=container.settings)
