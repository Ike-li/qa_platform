from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

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
        mock_client.generate_presigned_url.assert_called_once_with(
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

            await storage.generate_presigned_url("path/file.zip", expires_in=7200)

        mock_client.generate_presigned_url.assert_called_once_with(
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

        url = await _generate_download_url(mock_s3, "qa-platform", "artifacts/abc/report.html")

        assert url == "http://s3/signed-url"
        mock_s3.generate_presigned_url.assert_called_once_with(
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

        with pytest.raises(HTTPException) as exc_info:
            await _get_artifact_or_404(mock_repos, uuid4(), uuid4())

        assert exc_info.value.status_code == 404

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

        mock_repos.run = AsyncMock()
        run = MagicMock(tenant_id=uuid4())  # different tenant
        mock_repos.run.get_by_id.return_value = run

        with pytest.raises(HTTPException) as exc_info:
            await _get_artifact_or_404(mock_repos, uuid4(), tenant_id)

        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_get_artifact_or_404_run_not_found(self):
        from fastapi import HTTPException

        from qaplatform.api.v1.artifacts import _get_artifact_or_404

        mock_repos = MagicMock()
        mock_repos.artifact = AsyncMock()
        artifact = MagicMock(run_id=uuid4())
        mock_repos.artifact.get_by_id.return_value = artifact

        mock_repos.run = AsyncMock()
        mock_repos.run.get_by_id.return_value = None

        with pytest.raises(HTTPException) as exc_info:
            await _get_artifact_or_404(mock_repos, uuid4(), uuid4())

        assert exc_info.value.status_code == 404

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
        mock_repos.run.get_by_id.return_value = run

        result = await _get_artifact_or_404(mock_repos, uuid4(), tenant_id)

        assert result is artifact
