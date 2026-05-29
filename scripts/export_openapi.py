from __future__ import annotations

import json
from pathlib import Path

from qaplatform.config import Settings
from qaplatform.main import create_app


def _contract_settings() -> Settings:
    return Settings(
        database_url="postgresql+asyncpg://qaplatform:qaplatform@localhost:5432/qaplatform",
        redis_url="redis://localhost:6379/0",
        s3_endpoint="http://localhost:9000",
        s3_access_key="minioadmin",
        s3_secret_key="minioadmin",
        jwt_secret="contract-test-secret-at-least-32bytes!",
        encryption_key="0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
        debug=True,
        environment="test",
    )


def main() -> None:
    output = Path("artifacts/frontend-api-contract/openapi.json")
    output.parent.mkdir(parents=True, exist_ok=True)

    app = create_app(container=None, settings=_contract_settings())
    output.write_text(
        json.dumps(app.openapi(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"openapi_exported={output}")


if __name__ == "__main__":
    main()
