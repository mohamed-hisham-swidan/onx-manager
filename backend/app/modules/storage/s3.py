from __future__ import annotations

import base64
import hashlib
import logging
from datetime import UTC
from typing import Any

from app.modules.storage.base import StorageBackend, StorageFileInfo, StorageResult

logger = logging.getLogger(__name__)


class S3Storage(StorageBackend):
    def __init__(
        self,
        bucket: str,
        endpoint_url: str | None = None,
        region: str = "us-east-1",
        access_key_id: str | None = None,
        secret_access_key: str | None = None,
        prefix: str = "",
        session: Any = None,
    ) -> None:
        self._bucket = bucket
        self._endpoint_url = endpoint_url
        self._region = region
        self._access_key_id = access_key_id
        self._secret_access_key = secret_access_key
        self._prefix = prefix.strip("/")
        self._session_instance = session

    @property
    def _session(self) -> Any:
        if self._session_instance is not None:
            return self._session_instance

        try:
            import aioboto3
        except ImportError:
            raise ImportError("aioboto3 is required for S3 storage")

        self._session_instance = aioboto3.Session(
            aws_access_key_id=self._access_key_id,
            aws_secret_access_key=self._secret_access_key,
            region_name=self._region,
        )
        return self._session_instance

    @_session.setter
    def _session(self, value: Any) -> None:
        self._session_instance = value

    def _key(self, path: str) -> str:
        cleaned = path.lstrip("/")
        if self._prefix:
            if cleaned == self._prefix or cleaned.startswith(f"{self._prefix}/"):
                return cleaned
            return f"{self._prefix}/{cleaned}"
        return cleaned

    async def write(self, path: str, data: bytes) -> StorageResult:
        key = self._key(path)
        digest_bytes = hashlib.sha256(data).digest()
        checksum = digest_bytes.hex()
        checksum_b64 = base64.b64encode(digest_bytes).decode("ascii")

        async with self._session.client("s3", endpoint_url=self._endpoint_url) as client:
            await client.put_object(
                Bucket=self._bucket,
                Key=key,
                Body=data,
                ChecksumSHA256=checksum_b64,
            )

        return StorageResult(
            path=key,
            size_bytes=len(data),
            checksum=checksum,
        )

    async def read(self, path: str) -> bytes:
        key = self._key(path)
        async with self._session.client("s3", endpoint_url=self._endpoint_url) as client:
            response = await client.get_object(Bucket=self._bucket, Key=key)
            data = await response["Body"].read()
            return data

    async def delete(self, path: str) -> bool:
        key = self._key(path)
        try:
            async with self._session.client("s3", endpoint_url=self._endpoint_url) as client:
                await client.delete_object(Bucket=self._bucket, Key=key)
                return True
        except Exception as e:
            logger.warning("Failed to delete S3 key %s: %s", key, e)
            return False

    async def exists(self, path: str) -> bool:
        key = self._key(path)
        try:
            async with self._session.client("s3", endpoint_url=self._endpoint_url) as client:
                await client.head_object(Bucket=self._bucket, Key=key)
                return True
        except Exception as e:
            error_code = ""
            status_code = None
            if hasattr(e, "response") and isinstance(e.response, dict):
                error_code = str(e.response.get("Error", {}).get("Code", ""))
                status_code = e.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
            if error_code in ("404", "NoSuchKey", "NotFound") or status_code == 404:
                return False
            logger.error("Failed to check existence of S3 key %s: %s", key, e)
            raise

    async def list_files(self, prefix: str) -> list[StorageFileInfo]:
        key_prefix = self._key(prefix)

        files: list[StorageFileInfo] = []
        async with self._session.client("s3", endpoint_url=self._endpoint_url) as client:
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
        key = self._key(path)
        try:
            async with self._session.client("s3", endpoint_url=self._endpoint_url) as client:
                response = await client.head_object(Bucket=self._bucket, Key=key)
                return StorageFileInfo(
                    path=key,
                    size_bytes=response["ContentLength"],
                    checksum=response.get("ETag", "").strip('"'),
                    modified_at=response["LastModified"].replace(tzinfo=UTC),
                )
        except Exception as e:
            logger.warning("Failed to get info for S3 key %s: %s", key, e)
            return None

    async def copy(self, source: str, destination: str) -> StorageResult:
        src_key = self._key(source)
        dst_key = self._key(destination)

        copy_source = {"Bucket": self._bucket, "Key": src_key}
        async with self._session.client("s3", endpoint_url=self._endpoint_url) as client:
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
