from __future__ import annotations

import hashlib
from datetime import UTC
from typing import Any

from app.modules.storage.base import StorageBackend, StorageFileInfo, StorageResult


class S3Storage(StorageBackend):
    def __init__(
        self,
        bucket: str,
        endpoint_url: str | None = None,
        region: str = "us-east-1",
        access_key_id: str | None = None,
        secret_access_key: str | None = None,
        prefix: str = "",
    ) -> None:
        self._bucket = bucket
        self._endpoint_url = endpoint_url
        self._region = region
        self._access_key_id = access_key_id
        self._secret_access_key = secret_access_key
        self._prefix = prefix.strip("/")
        self._client: Any = None

    async def _get_client(self) -> Any:
        if self._client is not None:
            return self._client

        try:
            import aioboto3
        except ImportError:
            raise ImportError("aioboto3 is required for S3 storage")

        session = aioboto3.Session(
            aws_access_key_id=self._access_key_id,
            aws_secret_access_key=self._secret_access_key,
            region_name=self._region,
        )
        self._client = session.client("s3", endpoint_url=self._endpoint_url)
        return self._client

    def _key(self, path: str) -> str:
        if self._prefix:
            return f"{self._prefix}/{path.lstrip('/')}"
        return path.lstrip("/")

    async def write(self, path: str, data: bytes) -> StorageResult:
        client = await self._get_client()
        key = self._key(path)
        checksum = hashlib.sha256(data).hexdigest()

        await client.put_object(
            Bucket=self._bucket,
            Key=key,
            Body=data,
            ContentSHA256=checksum,
        )

        return StorageResult(
            path=key,
            size_bytes=len(data),
            checksum=checksum,
        )

    async def read(self, path: str) -> bytes:
        client = await self._get_client()
        key = self._key(path)
        response = await client.get_object(Bucket=self._bucket, Key=key)
        data = await response["Body"].read()
        return data

    async def delete(self, path: str) -> bool:
        client = await self._get_client()
        key = self._key(path)
        try:
            await client.delete_object(Bucket=self._bucket, Key=key)
            return True
        except Exception:
            return False

    async def exists(self, path: str) -> bool:
        client = await self._get_client()
        key = self._key(path)
        try:
            await client.head_object(Bucket=self._bucket, Key=key)
            return True
        except Exception:
            return False

    async def list_files(self, prefix: str) -> list[StorageFileInfo]:
        client = await self._get_client()
        key_prefix = self._key(prefix)

        files: list[StorageFileInfo] = []
        paginator = client.get_paginator("list_objects_v2")
        async for page in paginator.paginate(Bucket=self._bucket, Prefix=key_prefix):
            contents = page.get("Contents", [])
            for obj in contents:
                files.append(
                    StorageFileInfo(
                        path=obj["Key"],
                        size_bytes=obj["Size"],
                        checksum=obj.get("ETag", "").strip('"'),
                        modified_at=obj["LastModified"].replace(tzinfo=UTC),
                    ),
                )
        return files

    async def info(self, path: str) -> StorageFileInfo | None:
        client = await self._get_client()
        key = self._key(path)
        try:
            response = await client.head_object(Bucket=self._bucket, Key=key)
            return StorageFileInfo(
                path=key,
                size_bytes=response["ContentLength"],
                checksum=response.get("ETag", "").strip('"'),
                modified_at=response["LastModified"].replace(tzinfo=UTC),
            )
        except Exception:
            return None

    async def copy(self, source: str, destination: str) -> StorageResult:
        client = await self._get_client()
        src_key = self._key(source)
        dst_key = self._key(destination)

        copy_source = {"Bucket": self._bucket, "Key": src_key}
        response = await client.copy_object(
            Bucket=self._bucket,
            Key=dst_key,
            CopySource=copy_source,
        )

        head = await client.head_object(Bucket=self._bucket, Key=dst_key)
        return StorageResult(
            path=dst_key,
            size_bytes=head["ContentLength"],
            checksum=response.get("CopyObjectResult", {}).get("ETag", "").strip('"'),
        )
