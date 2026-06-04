from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from qaplatform.infra.storage.s3 import S3Storage


class TestS3Storage:
    """Test S3 presigned URL generation."""

    @pytest.fixture
    def storage(self):
        return S3Storage(
            endpoint="http://localhost:9000",
            access_key="test",
            secret_key="test",
            bucket="qa-platform",
            region="us-east-1",
        )

    @pytest.mark.asyncio
    async def test_generate_presigned_url(self, storage):
        with patch.object(storage, "_get_client") as mock_client_ctx:
            mock_client = AsyncMock()
            mock_client.generate_presigned_url.return_value = (
                "http://localhost:9000/qa-platform/artifacts/test.html?X-Amz-Signature=abc"
            )
            mock_ctx = MagicMock()
            mock_ctx.__aenter__ = AsyncMock(return_value=mock_client)
            mock_ctx.__aexit__ = AsyncMock(return_value=False)
            mock_client_ctx.return_value = mock_ctx

            url = await storage.generate_presigned_url("artifacts/test.html")

        assert "X-Amz-Signature" in url
        mock_client.generate_presigned_url.assert_awaited_once_with(
            "get_object",
            Params={"Bucket": "qa-platform", "Key": "artifacts/test.html"},
            ExpiresIn=3600,
        )

    @pytest.mark.asyncio
    async def test_generate_presigned_url_custom_expiry(self, storage):
        with patch.object(storage, "_get_client") as mock_client_ctx:
            mock_client = AsyncMock()
            mock_client.generate_presigned_url.return_value = "http://example.com/signed"
            mock_ctx = MagicMock()
            mock_ctx.__aenter__ = AsyncMock(return_value=mock_client)
            mock_ctx.__aexit__ = AsyncMock(return_value=False)
            mock_client_ctx.return_value = mock_ctx

            url = await storage.generate_presigned_url("path/file.zip", expires_in=7200)

        assert url == "http://example.com/signed"
        mock_ctx.__aenter__.assert_awaited_once_with()
        mock_ctx.__aexit__.assert_awaited_once_with(None, None, None)
        mock_client.generate_presigned_url.assert_awaited_once_with(
            "get_object",
            Params={"Bucket": "qa-platform", "Key": "path/file.zip"},
            ExpiresIn=7200,
        )


class TestArtifactDownloadHelpers:
    """Test artifact download helper functions."""

    @pytest.mark.asyncio
    async def test_generate_download_url(self):
        from qaplatform.api.v1.artifacts import _generate_download_url

        mock_s3 = AsyncMock()
        mock_s3.generate_presigned_url.return_value = "http://s3/signed-url"

        url = await _generate_download_url(mock_s3, "qa-platform", "artifacts/abc/report.html", 3600)

        assert url == "http://s3/signed-url"
        mock_s3.generate_presigned_url.assert_awaited_once_with(
            "get_object",
            Params={"Bucket": "qa-platform", "Key": "artifacts/abc/report.html"},
            ExpiresIn=3600,
        )

    @pytest.mark.asyncio
    async def test_get_artifact_or_404_not_found(self):
        from fastapi import HTTPException

        from qaplatform.api.v1.artifacts import _get_artifact_or_404

        mock_repos = MagicMock()
        mock_repos.artifact = AsyncMock()
        mock_repos.artifact.get_by_id.return_value = None
        mock_repos.run = AsyncMock()
        artifact_id = uuid4()

        with pytest.raises(HTTPException) as exc_info:
            await _get_artifact_or_404(mock_repos, artifact_id, uuid4())

        assert exc_info.value.status_code == 404
        assert exc_info.value.detail == "Artifact not found"
        mock_repos.artifact.get_by_id.assert_awaited_once_with(artifact_id)
        mock_repos.run.get_for_tenant.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_get_artifact_or_404_wrong_tenant(self):
        from fastapi import HTTPException

        from qaplatform.api.v1.artifacts import _get_artifact_or_404

        tenant_id = uuid4()
        run_id = uuid4()

        mock_repos = MagicMock()
        mock_repos.artifact = AsyncMock()
        artifact = MagicMock(run_id=run_id)
        mock_repos.artifact.get_by_id.return_value = artifact

        # get_for_tenant filters by tenant in SQL — a cross-tenant run
        # surfaces as None, identical to a missing run.
        mock_repos.run = AsyncMock()
        mock_repos.run.get_for_tenant.return_value = None
        artifact_id = uuid4()

        with pytest.raises(HTTPException) as exc_info:
            await _get_artifact_or_404(mock_repos, artifact_id, tenant_id)

        assert exc_info.value.status_code == 404
        assert exc_info.value.detail == "Artifact not found"
        mock_repos.artifact.get_by_id.assert_awaited_once_with(artifact_id)
        mock_repos.run.get_for_tenant.assert_awaited_once_with(run_id, tenant_id)

    @pytest.mark.asyncio
    async def test_get_artifact_or_404_run_not_found(self):
        from fastapi import HTTPException

        from qaplatform.api.v1.artifacts import _get_artifact_or_404

        mock_repos = MagicMock()
        mock_repos.artifact = AsyncMock()
        artifact = MagicMock(run_id=uuid4())
        mock_repos.artifact.get_by_id.return_value = artifact

        mock_repos.run = AsyncMock()
        mock_repos.run.get_for_tenant.return_value = None
        artifact_id = uuid4()
        tenant_id = uuid4()

        with pytest.raises(HTTPException) as exc_info:
            await _get_artifact_or_404(mock_repos, artifact_id, tenant_id)

        assert exc_info.value.status_code == 404
        assert exc_info.value.detail == "Artifact not found"
        mock_repos.artifact.get_by_id.assert_awaited_once_with(artifact_id)
        mock_repos.run.get_for_tenant.assert_awaited_once_with(
            artifact.run_id,
            tenant_id,
        )

    @pytest.mark.asyncio
    async def test_get_artifact_or_404_success(self):
        from qaplatform.api.v1.artifacts import _get_artifact_or_404

        tenant_id = uuid4()
        run_id = uuid4()

        mock_repos = MagicMock()
        mock_repos.artifact = AsyncMock()
        artifact = MagicMock(run_id=run_id)
        mock_repos.artifact.get_by_id.return_value = artifact

        mock_repos.run = AsyncMock()
        run = MagicMock(tenant_id=tenant_id)
        mock_repos.run.get_for_tenant.return_value = run
        artifact_id = uuid4()

        result_artifact, result_run = await _get_artifact_or_404(
            mock_repos, artifact_id, tenant_id
        )

        assert result_artifact is artifact
        assert result_run is run
        mock_repos.artifact.get_by_id.assert_awaited_once_with(artifact_id)
        mock_repos.run.get_for_tenant.assert_awaited_once_with(run_id, tenant_id)


class TestDownloadArtifactRBAC:
    """P1-E: download_artifact must double-check project-scope RBAC,
    not just tenant. A user lacking RUN_READ on the project owning the
    run should hit 403, even if the artifact is in their tenant.
    """

    @pytest.mark.asyncio
    async def test_download_artifact_404_short_circuits_before_rbac_or_storage(self):
        from fastapi import HTTPException

        from qaplatform.api.v1.artifacts import download_artifact

        tenant_id = uuid4()
        run_id = uuid4()
        missing_artifact_id = uuid4()
        cross_tenant_artifact_id = uuid4()

        mock_repos = MagicMock()
        mock_repos.artifact = AsyncMock()
        cross_tenant_artifact = MagicMock(
            run_id=run_id,
            storage_path="reports/other-tenant/secret-report.html",
        )
        mock_repos.artifact.get_by_id.side_effect = [
            None,
            cross_tenant_artifact,
        ]
        mock_repos.run = AsyncMock()
        mock_repos.run.get_for_tenant.return_value = None

        user = MagicMock(tenant_id=tenant_id, user_id=uuid4(), role="reader")
        s3_client = AsyncMock()
        request = MagicMock()
        request.app.state.container.s3_client = s3_client
        session = MagicMock()

        with patch(
            "qaplatform.api.v1.artifacts.enforce_project_action",
            new=AsyncMock(),
        ) as enforce_project_action:
            responses = []
            for artifact_id in [missing_artifact_id, cross_tenant_artifact_id]:
                with pytest.raises(HTTPException) as exc_info:
                    await download_artifact(
                        artifact_id=artifact_id,
                        request=request,
                        repos=mock_repos,
                        user=user,
                        session=session,
                    )
                responses.append(exc_info.value)

        assert [(exc.status_code, exc.detail) for exc in responses] == [
            (404, "Artifact not found"),
            (404, "Artifact not found"),
        ]
        assert [args.args for args in mock_repos.artifact.get_by_id.await_args_list] == [
            (missing_artifact_id,),
            (cross_tenant_artifact_id,),
        ]
        mock_repos.run.get_for_tenant.assert_awaited_once_with(run_id, tenant_id)
        enforce_project_action.assert_not_awaited()
        s3_client.generate_presigned_url.assert_not_awaited()
        serialized_errors = repr([(exc.status_code, exc.detail) for exc in responses])
        assert str(cross_tenant_artifact_id) not in serialized_errors
        assert str(run_id) not in serialized_errors
        assert "secret-report.html" not in serialized_errors

    @pytest.mark.asyncio
    async def test_download_artifact_403_when_project_action_denied(self):
        from fastapi import HTTPException

        from qaplatform.api.v1.artifacts import download_artifact

        tenant_id = uuid4()
        project_id = uuid4()
        run_id = uuid4()
        artifact_id = uuid4()

        mock_repos = MagicMock()
        mock_repos.artifact = AsyncMock()
        artifact = MagicMock(
            run_id=run_id, storage_path="artifacts/abc/report.html"
        )
        mock_repos.artifact.get_by_id.return_value = artifact
        mock_repos.run = AsyncMock()
        run = MagicMock(tenant_id=tenant_id, project_id=project_id)
        mock_repos.run.get_for_tenant.return_value = run

        user = MagicMock(tenant_id=tenant_id, user_id=uuid4(), role="reader")
        s3_client = AsyncMock()
        request = MagicMock()
        request.app.state.container.s3_client = s3_client
        session = MagicMock()
        captured = {}

        async def _deny(_session, _user, _project_id, _action, **_kw):
            captured["session"] = _session
            captured["user"] = _user
            captured["project_id"] = _project_id
            captured["action"] = _action
            raise HTTPException(status_code=403, detail="Insufficient permissions")

        with patch(
            "qaplatform.api.v1.artifacts.enforce_project_action", new=_deny
        ):
            with pytest.raises(HTTPException) as exc_info:
                await download_artifact(
                    artifact_id=artifact_id,
                    request=request,
                    repos=mock_repos,
                    user=user,
                    session=session,
                )

        from qaplatform.api.auth.permissions import Action

        assert exc_info.value.status_code == 403
        assert exc_info.value.detail == "Insufficient permissions"
        assert captured["project_id"] == project_id
        assert captured["action"] == Action.RUN_READ
        assert captured["user"] is user
        assert captured["session"] is session
        mock_repos.artifact.get_by_id.assert_awaited_once_with(artifact_id)
        mock_repos.run.get_for_tenant.assert_awaited_once_with(run_id, tenant_id)
        s3_client.generate_presigned_url.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_download_artifact_passes_project_id_to_rbac(self):
        from qaplatform.api.v1.artifacts import download_artifact

        tenant_id = uuid4()
        project_id = uuid4()
        run_id = uuid4()

        mock_repos = MagicMock()
        mock_repos.artifact = AsyncMock()
        artifact = MagicMock(
            run_id=run_id, storage_path="artifacts/abc/report.html"
        )
        mock_repos.artifact.get_by_id.return_value = artifact
        mock_repos.run = AsyncMock()
        run = MagicMock(tenant_id=tenant_id, project_id=project_id)
        mock_repos.run.get_for_tenant.return_value = run

        user = MagicMock(tenant_id=tenant_id, user_id=uuid4(), role="reader")

        request = MagicMock()
        request.app.state.container.s3_client = AsyncMock()
        request.app.state.container.s3_client.generate_presigned_url.return_value = (
            "http://s3/signed"
        )
        request.app.state.container.settings.s3_bucket = "qa-platform"
        request.app.state.container.settings.s3_presigned_url_ttl = 3600
        session = MagicMock()

        captured = {}

        async def _capture(_session, _user, _project_id, _action, **_kw):
            captured["session"] = _session
            captured["user"] = _user
            captured["project_id"] = _project_id
            captured["action"] = _action

        with patch(
            "qaplatform.api.v1.artifacts.enforce_project_action", new=_capture
        ):
            artifact_id = uuid4()
            result = await download_artifact(
                artifact_id=artifact_id,
                request=request,
                repos=mock_repos,
                user=user,
                session=session,
            )

        from qaplatform.api.auth.permissions import Action

        assert captured["project_id"] == project_id
        assert captured["action"] == Action.RUN_READ
        assert captured["user"] is user
        assert captured["session"] is session
        mock_repos.artifact.get_by_id.assert_awaited_once_with(artifact_id)
        mock_repos.run.get_for_tenant.assert_awaited_once_with(run_id, tenant_id)
        request.app.state.container.s3_client.generate_presigned_url.assert_awaited_once_with(
            "get_object",
            Params={"Bucket": "qa-platform", "Key": "artifacts/abc/report.html"},
            ExpiresIn=3600,
        )
        assert result == {
            "download_url": "http://s3/signed",
            "expires_in": 3600,
        }

    @pytest.mark.asyncio
    async def test_download_artifact_503_when_storage_unavailable_after_rbac(self):
        from fastapi import HTTPException

        from qaplatform.api.v1.artifacts import download_artifact

        tenant_id = uuid4()
        project_id = uuid4()
        run_id = uuid4()
        artifact_id = uuid4()

        mock_repos = MagicMock()
        mock_repos.artifact = AsyncMock()
        artifact = MagicMock(
            run_id=run_id, storage_path="artifacts/abc/report.html"
        )
        mock_repos.artifact.get_by_id.return_value = artifact
        mock_repos.run = AsyncMock()
        run = MagicMock(tenant_id=tenant_id, project_id=project_id)
        mock_repos.run.get_for_tenant.return_value = run

        user = MagicMock(tenant_id=tenant_id, user_id=uuid4(), role="reader")

        request = MagicMock()
        request.app.state.container.s3_client = None
        session = MagicMock()
        captured = {}

        async def _capture(_session, _user, _project_id, _action, **_kw):
            captured["session"] = _session
            captured["user"] = _user
            captured["project_id"] = _project_id
            captured["action"] = _action

        with patch(
            "qaplatform.api.v1.artifacts.enforce_project_action", new=_capture
        ):
            with pytest.raises(HTTPException) as exc_info:
                await download_artifact(
                    artifact_id=artifact_id,
                    request=request,
                    repos=mock_repos,
                    user=user,
                    session=session,
                )

        from qaplatform.api.auth.permissions import Action

        assert exc_info.value.status_code == 503
        assert exc_info.value.detail == "Artifact download is not available"
        assert captured["project_id"] == project_id
        assert captured["action"] == Action.RUN_READ
        assert captured["user"] is user
        assert captured["session"] is session
        mock_repos.artifact.get_by_id.assert_awaited_once_with(artifact_id)
        mock_repos.run.get_for_tenant.assert_awaited_once_with(run_id, tenant_id)

    def test_download_artifact_documents_storage_unavailable_response(self):
        from fastapi import FastAPI

        from qaplatform.api.v1.artifacts import router

        app = FastAPI()
        app.include_router(router, prefix="/api/v1")

        responses = app.openapi()["paths"][
            "/api/v1/artifacts/{artifact_id}/download"
        ]["get"]["responses"]

        assert responses["503"]["content"]["application/json"]["schema"] == {
            "$ref": "#/components/schemas/ErrorResponse"
        }


class TestArtifactPreview:
    @pytest.mark.asyncio
    async def test_preview_url_enforces_rbac_and_returns_tokenized_url(self):
        from qaplatform.api.v1.artifacts import get_artifact_preview_url

        tenant_id = uuid4()
        project_id = uuid4()
        run_id = uuid4()
        artifact_id = uuid4()

        mock_repos = MagicMock()
        mock_repos.artifact = AsyncMock()
        artifact = MagicMock(
            id=artifact_id,
            run_id=run_id,
            storage_path=f"reports/{run_id}/allure-report/index.html",
        )
        artifact.name = "allure-report/index.html"
        artifact.type = "allure-report"
        artifact.mime_type = "text/html"
        mock_repos.artifact.get_by_id.return_value = artifact
        mock_repos.run = AsyncMock()
        mock_repos.run.get_for_tenant.return_value = MagicMock(project_id=project_id)

        request = MagicMock()
        request.app.state.container.s3_client = AsyncMock()
        request.app.state.container.settings.s3_presigned_url_ttl = 3600
        request.app.state.container.settings.jwt_secret = "test-secret-with-at-least-32-bytes"
        request.url_for.return_value = "http://test/api/v1/artifacts/preview-token/index.html"
        user = MagicMock(tenant_id=tenant_id)
        session = MagicMock()

        with patch(
            "qaplatform.api.v1.artifacts.enforce_project_action",
            new=AsyncMock(),
        ) as enforce_project_action:
            result = await get_artifact_preview_url(
                artifact_id=artifact_id,
                request=request,
                repos=mock_repos,
                user=user,
                session=session,
            )

        enforce_project_action.assert_awaited_once()
        request.url_for.assert_called_once()
        url_kwargs = request.url_for.call_args.kwargs
        assert url_kwargs["artifact_id"] == str(artifact_id)
        assert url_kwargs["artifact_path"] == "index.html"
        assert isinstance(url_kwargs["token"], str)
        assert result == {
            "preview_url": "http://test/api/v1/artifacts/preview-token/index.html",
            "expires_in": 3600,
        }

    @pytest.mark.asyncio
    async def test_preview_file_maps_relative_allure_asset_to_same_report_prefix(self):
        from qaplatform.api.v1.artifacts import (
            _create_preview_token,
            preview_artifact_file,
        )

        artifact_id = uuid4()
        run_id = uuid4()
        secret = "test-secret-with-at-least-32-bytes"
        token = _create_preview_token(
            secret,
            artifact_id,
            3600,
            storage_prefix=f"reports/{run_id}/allure-report",
            allow_relative_assets=True,
        )

        mock_repos = MagicMock()
        mock_repos.artifact = AsyncMock()
        mock_repos.artifact.get_by_id.return_value = MagicMock(
            storage_path=f"reports/{run_id}/allure-report/index.html",
        )

        class _Body:
            async def read(self):
                return b"console.log('ok')"

        s3_client = AsyncMock()
        s3_client.get_object.return_value = {"Body": _Body()}
        request = MagicMock()
        request.app.state.container.s3_client = s3_client
        request.app.state.container.settings.s3_bucket = "qa-platform"
        request.app.state.container.settings.jwt_secret = secret

        response = await preview_artifact_file(
            artifact_id=artifact_id,
            token=token,
            artifact_path="assets/app.js",
            request=request,
            repos=mock_repos,
        )

        s3_client.get_object.assert_awaited_once_with(
            Bucket="qa-platform",
            Key=f"reports/{run_id}/allure-report/assets/app.js",
        )
        assert response.body == b"console.log('ok')"
        assert response.media_type == "text/javascript"
        assert "sandbox allow-scripts allow-downloads" in response.headers[
            "content-security-policy"
        ]
        assert "allow-same-origin" not in response.headers[
            "content-security-policy"
        ]
        assert response.headers["x-content-type-options"] == "nosniff"
        assert response.headers["referrer-policy"] == "no-referrer"
        assert response.headers["access-control-allow-origin"] == "*"

    @pytest.mark.asyncio
    async def test_preview_file_rejects_relative_asset_without_allure_asset_scope(self):
        from fastapi import HTTPException

        from qaplatform.api.v1.artifacts import (
            _create_preview_token,
            preview_artifact_file,
        )

        artifact_id = uuid4()
        run_id = uuid4()
        secret = "test-secret-with-at-least-32-bytes"
        token = _create_preview_token(
            secret,
            artifact_id,
            3600,
            storage_prefix=f"reports/{run_id}/html",
            allow_relative_assets=False,
        )

        mock_repos = MagicMock()
        mock_repos.artifact = AsyncMock()
        mock_repos.artifact.get_by_id.return_value = MagicMock(
            storage_path=f"reports/{run_id}/html/index.html",
        )
        s3_client = AsyncMock()
        request = MagicMock()
        request.app.state.container.s3_client = s3_client
        request.app.state.container.settings.jwt_secret = secret

        with pytest.raises(HTTPException) as exc_info:
            await preview_artifact_file(
                artifact_id=artifact_id,
                token=token,
                artifact_path="assets/app.js",
                request=request,
                repos=mock_repos,
            )

        assert exc_info.value.status_code == 404
        s3_client.get_object.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_preview_file_rejects_invalid_token_before_storage_lookup(self):
        from fastapi import HTTPException

        from qaplatform.api.v1.artifacts import preview_artifact_file

        request = MagicMock()
        request.app.state.container.s3_client = AsyncMock()
        request.app.state.container.settings.jwt_secret = "test-secret-with-at-least-32-bytes"
        mock_repos = MagicMock()
        mock_repos.artifact = AsyncMock()

        with pytest.raises(HTTPException) as exc_info:
            await preview_artifact_file(
                artifact_id=uuid4(),
                token="not-a-token",
                artifact_path="index.html",
                request=request,
                repos=mock_repos,
            )

        assert exc_info.value.status_code == 403
        mock_repos.artifact.get_by_id.assert_not_awaited()
