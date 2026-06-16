from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient


@pytest.fixture
def run_id():
    return uuid.uuid4()


@pytest.fixture
def tenant_id():
    return uuid.uuid4()


@pytest.fixture
def mock_repos():
    repos = MagicMock()
    repos.artifact = AsyncMock()
    repos.artifact.list_by_run = AsyncMock(return_value=([], 0))
    return repos


@pytest.fixture
async def app_factory(mock_repos):
    def _create_app(s3_client_configured=True):
        from qaplatform.api.deps import _get_db_session, _get_repos
        from qaplatform.main import create_app

        container = MagicMock()
        if s3_client_configured:
            container.s3_client = MagicMock()
        else:
            container.s3_client = None

        container.redis_client = None
        container.settings.s3_bucket = "qa-platform"
        container.settings.s3_presigned_url_ttl = 3600
        container.settings.jwt_secret = "test-secret-with-at-least-32-bytes"

        app = create_app(container=container)

        async def _override_repos():
            return mock_repos

        async def _override_session():
            yield AsyncMock()

        app.dependency_overrides[_get_repos] = _override_repos
        app.dependency_overrides[_get_db_session] = _override_session
        return app

    return _create_app


@pytest.mark.asyncio
async def test_view_shared_report_s3_not_configured(app_factory, run_id):
    app = app_factory(s3_client_configured=False)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            f"/public/reports/{run_id}",
            params={"token": "some-token"},
        )
        assert resp.status_code == 503
        assert resp.json()["detail"] == "Report sharing is not available"


@pytest.mark.asyncio
async def test_view_shared_report_invalid_token(app_factory, run_id):
    from qaplatform.api.v1 import public_reports

    app = app_factory(s3_client_configured=True)
    
    mock_verify = AsyncMock(return_value=(False, None))

    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr(public_reports, "verify_share_token", mock_verify)
        
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(
                f"/public/reports/{run_id}",
                params={"token": "invalid-token"},
            )
            assert resp.status_code == 403
            assert resp.json()["detail"] == "Invalid share token"


@pytest.mark.asyncio
async def test_view_shared_report_expired_token(app_factory, run_id, tenant_id):
    from qaplatform.api.v1 import public_reports

    app = app_factory(s3_client_configured=True)
    
    expired_at = datetime.now(timezone.utc) - timedelta(days=1)
    share_token_obj = SimpleNamespace(
        expires_at=expired_at,
        max_access_count=None,
        access_count=0,
        tenant_id=tenant_id,
    )
    mock_verify = AsyncMock(return_value=(False, share_token_obj))

    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr(public_reports, "verify_share_token", mock_verify)
        
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(
                f"/public/reports/{run_id}",
                params={"token": "expired-token"},
            )
            assert resp.status_code == 403
            assert resp.json()["detail"] == "Share link has expired"


@pytest.mark.asyncio
async def test_view_shared_report_max_access_reached(app_factory, run_id, tenant_id):
    from qaplatform.api.v1 import public_reports

    app = app_factory(s3_client_configured=True)
    
    expires_at = datetime.now(timezone.utc) + timedelta(days=5)
    share_token_obj = SimpleNamespace(
        expires_at=expires_at,
        max_access_count=5,
        access_count=5,
        tenant_id=tenant_id,
    )
    mock_verify = AsyncMock(return_value=(False, share_token_obj))

    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr(public_reports, "verify_share_token", mock_verify)
        
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(
                f"/public/reports/{run_id}",
                params={"token": "max-access-token"},
            )
            assert resp.status_code == 403
            assert resp.json()["detail"] == "Share link access limit reached"


@pytest.mark.asyncio
async def test_view_shared_report_missing_allure_report(app_factory, run_id, tenant_id, mock_repos):
    from qaplatform.api.v1 import public_reports

    app = app_factory(s3_client_configured=True)
    
    expires_at = datetime.now(timezone.utc) + timedelta(days=5)
    share_token_obj = SimpleNamespace(
        expires_at=expires_at,
        max_access_count=None,
        access_count=1,
        tenant_id=tenant_id,
    )
    mock_verify = AsyncMock(return_value=(True, share_token_obj))
    
    # Repos returns empty list for artifacts
    mock_repos.artifact.list_by_run.return_value = ([], 0)

    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr(public_reports, "verify_share_token", mock_verify)
        
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(
                f"/public/reports/{run_id}",
                params={"token": "valid-token"},
            )
            assert resp.status_code == 404
            assert resp.json()["error"]["message"] == "Allure report not found for this run"
            assert resp.json()["error"]["code"] == "NOT_FOUND"


@pytest.mark.asyncio
async def test_view_shared_report_success_redirect(app_factory, run_id, tenant_id, mock_repos):
    from qaplatform.api.v1 import public_reports

    app = app_factory(s3_client_configured=True)
    
    expires_at = datetime.now(timezone.utc) + timedelta(days=5)
    share_token_obj = SimpleNamespace(
        expires_at=expires_at,
        max_access_count=None,
        access_count=1,
        tenant_id=tenant_id,
    )
    mock_verify = AsyncMock(return_value=(True, share_token_obj))
    
    # Mock Allure report artifact
    artifact_id = uuid.uuid4()
    allure_artifact = SimpleNamespace(
        id=artifact_id,
        type="allure-report",
        name="some/path/allure-report/index.html",
        storage_path="runs/123/allure-report",
    )
    mock_repos.artifact.list_by_run.return_value = ([allure_artifact], 1)

    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr(public_reports, "verify_share_token", mock_verify)
        
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(
                f"/public/reports/{run_id}",
                params={"token": "valid-token"},
                follow_redirects=False,
            )
            assert resp.status_code == 302
            location = resp.headers["location"]
            assert f"/api/v1/artifacts/{artifact_id}/preview/" in location
            assert "/index.html" in location
