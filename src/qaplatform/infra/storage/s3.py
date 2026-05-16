from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

from aiobotocore.session import get_session


class S3Storage:
    """S3-compatible object storage client."""

    def __init__(
        self,
        endpoint: str,
        access_key: str,
        secret_key: str,
        bucket: str,
        region: str = "us-east-1",
    ) -> None:
        self._endpoint = endpoint
        self._access_key = access_key
        self._secret_key = secret_key
        self._bucket = bucket
        self._region = region
        self._session = get_session()

    @asynccontextmanager
    async def _get_client(self) -> AsyncIterator:
        async with self._session.create_client(
            "s3",
            endpoint_url=self._endpoint,
            aws_access_key_id=self._access_key,
            aws_secret_access_key=self._secret_key,
            region_name=self._region,
        ) as client:
            yield client

    async def generate_presigned_url(
        self, key: str, expires_in: int = 3600
    ) -> str:
        async with self._get_client() as client:
            url = await client.generate_presigned_url(
                "get_object",
                Params={"Bucket": self._bucket, "Key": key},
                ExpiresIn=expires_in,
            )
        return url
