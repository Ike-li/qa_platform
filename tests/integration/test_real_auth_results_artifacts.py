"""Real backend integration coverage for auth tokens, run results, and artifacts.

These tests intentionally exercise production wiring where it matters:

* JWT login -> API token creation -> API-token authenticated request -> revoke.
* Run result filtering and uniqueness against PostgreSQL constraints.
* Artifact soft-delete visibility through both repository and API paths.
"""

from __future__ import annotations

import os
from uuid import uuid4

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_INTEGRATION_TESTS") != "1",
    reason="set RUN_INTEGRATION_TESTS=1 to run integration tests",
)


@pytest_asyncio.fixture
async def real_auth_app(test_settings, integration_db_schema):
    """FastAPI app with real auth dependencies and no current-user override."""
    from qaplatform.api import create_app
    from qaplatform.dependencies import init_container
    from qaplatform.plugins.registry import PluginRegistry

    container = init_container(test_settings)
    await container.init_db()
    await container.init_redis()
    container.init_crypto()

    plugin_registry = PluginRegistry()
    plugin_registry.register_builtins()
    container.plugin_registry = plugin_registry

    app = create_app(container=container, settings=test_settings)
    app.state.container = container

    yield app

    app.dependency_overrides.clear()
    await container.close()


@pytest_asyncio.fixture
async def real_auth_client(real_auth_app):
    transport = ASGITransport(app=real_auth_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


@pytest.mark.asyncio
async def test_real_jwt_created_api_token_authenticates_updates_last_used_and_revokes(
    real_auth_client,
    integration_db_session,
):
    from qaplatform.api.auth.token_service import TokenService
    from qaplatform.infra.database.models import ApiToken, AuditEvent

    suffix = uuid4().hex[:8]
    username = f"api_token_{suffix}"
    password = "correct-horse-battery"

    register_resp = await real_auth_client.post(
        "/api/v1/auth/register",
        json={
            "username": username,
            "email": f"{username}@example.com",
            "password": password,
        },
    )
    assert register_resp.status_code == 201, register_resp.text
    access_token = register_resp.json()["access_token"]

    create_resp = await real_auth_client.post(
        "/api/v1/auth/tokens",
        headers={"Authorization": f"Bearer {access_token}"},
        json={"name": "ci-smoke", "scopes": ["project.read"], "expires_days": 7},
    )
    assert create_resp.status_code == 201, create_resp.text
    created = create_resp.json()
    full_api_token = created["token"]
    parsed = TokenService.parse_bearer_token(full_api_token)
    assert parsed is not None
    token_id, secret = parsed
    assert token_id == created["token_id"]

    record = (
        await integration_db_session.execute(
            select(ApiToken).where(ApiToken.token_id == token_id)
        )
    ).scalar_one()
    assert record.name == "ci-smoke"
    assert record.scopes == ["project.read"]
    assert record.secret_hash != secret
    assert TokenService.verify_token(secret, record.secret_hash)
    assert record.last_used_at is None

    token_auth_resp = await real_auth_client.get(
        "/api/v1/projects",
        headers={"Authorization": f"Bearer {full_api_token}"},
    )
    assert token_auth_resp.status_code == 200, token_auth_resp.text

    await integration_db_session.refresh(record)
    assert record.last_used_at is not None

    revoke_resp = await real_auth_client.delete(
        f"/api/v1/auth/tokens/{token_id}",
        headers={"Authorization": f"Bearer {access_token}"},
    )
    assert revoke_resp.status_code == 204, revoke_resp.text

    await integration_db_session.refresh(record)
    assert record.is_revoked is True

    rejected_resp = await real_auth_client.get(
        "/api/v1/projects",
        headers={"Authorization": f"Bearer {full_api_token}"},
    )
    assert rejected_resp.status_code == 401, rejected_resp.text

    audit_actions = (
        await integration_db_session.execute(
            select(AuditEvent.action).where(
                AuditEvent.user_id == record.user_id,
                AuditEvent.action.in_(
                    ["auth.api_token_create", "auth.api_token_revoke"]
                ),
            )
        )
    ).scalars().all()
    assert {"auth.api_token_create", "auth.api_token_revoke"}.issubset(
        set(audit_actions)
    )


@pytest.mark.asyncio
async def test_run_results_api_filters_real_rows_and_recovers_after_duplicate(
    integration_client,
    integration_db_session,
    seed_run,
):
    from qaplatform.infra.database.models import TestResultStatusEnum
    from qaplatform.infra.database.repositories.run_repo import TestResultRepository

    run_id = seed_run["run"].id
    repo = TestResultRepository(integration_db_session)

    await repo.bulk_create(
        [
            {
                "run_id": run_id,
                "suite": "checkout",
                "name": "test_cart_total",
                "status": TestResultStatusEnum.PASSED,
                "duration_ms": 42,
                "tags": ["smoke"],
                "metadata_": {"node": "gw0"},
            },
            {
                "run_id": run_id,
                "suite": "checkout",
                "name": "test_payment_decline",
                "status": TestResultStatusEnum.FAILED,
                "duration_ms": 87,
                "error_message": "AssertionError: card declined",
                "tags": ["payments"],
                "metadata_": {"node": "gw1"},
            },
        ]
    )
    await integration_db_session.commit()

    resp = await integration_client.get(
        f"/api/v1/runs/{run_id}/results",
        params={"status": "failed", "suite": "checkout", "q": "card"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total"] == 1
    assert body["data"][0]["name"] == "test_payment_decline"
    assert body["data"][0]["status"] == "failed"

    with pytest.raises(IntegrityError):
        await repo.bulk_create(
            [
                {
                    "run_id": run_id,
                    "suite": "checkout",
                    "name": "test_payment_decline",
                    "status": TestResultStatusEnum.ERROR,
                    "duration_ms": 1,
                    "tags": [],
                    "metadata_": {},
                }
            ]
        )
        await integration_db_session.commit()

    await integration_db_session.rollback()

    after_rollback_resp = await integration_client.get(
        f"/api/v1/runs/{run_id}/results",
        params={"suite": "checkout", "per_page": 100},
    )
    assert after_rollback_resp.status_code == 200, after_rollback_resp.text
    after_rollback_body = after_rollback_resp.json()
    assert after_rollback_body["total"] == 2
    assert {
        item["name"] for item in after_rollback_body["data"]
    } == {"test_cart_total", "test_payment_decline"}


@pytest.mark.asyncio
async def test_run_artifacts_api_hides_soft_deleted_real_rows(
    integration_client,
    integration_db_session,
    seed_run,
):
    from qaplatform.infra.database.repositories.run_repo import ArtifactRepository

    run_id = seed_run["run"].id
    repo = ArtifactRepository(integration_db_session)

    visible = await repo.create(
        run_id=run_id,
        type="report",
        name="summary.html",
        storage_path=f"runs/{run_id}/summary.html",
        size_bytes=2048,
        mime_type="text/html",
    )
    deleted = await repo.create(
        run_id=run_id,
        type="trace",
        name="trace.zip",
        storage_path=f"runs/{run_id}/trace.zip",
        size_bytes=4096,
        mime_type="application/zip",
    )
    await repo.delete(deleted)
    await integration_db_session.commit()

    repo_items, repo_total = await repo.list_by_run(run_id, limit=100)
    assert repo_total == 1
    assert [item.id for item in repo_items] == [visible.id]

    resp = await integration_client.get(f"/api/v1/runs/{run_id}/artifacts")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total"] == 1
    assert body["data"][0]["id"] == str(visible.id)
    assert body["data"][0]["name"] == "summary.html"
