"""Offsite on MinIO/S3 with boto3. Exercised by the CI drill, not by unit tests."""

from __future__ import annotations

import os
from datetime import datetime
from typing import Any

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

from drkit.offsite import OffsiteError, Refused, Version

REFUSALS = {"AccessDenied", "ObjectLocked", "InvalidRequest", "InvalidObjectState", "MethodNotAllowed"}


class S3Offsite:
    def __init__(self, endpoint: str, access_key: str, secret_key: str, bucket: str, lock_mode: str) -> None:
        self.bucket = bucket
        self.lock_mode = lock_mode
        self.client: Any = boto3.client(
            "s3",
            endpoint_url=endpoint,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            region_name="us-east-1",
            config=Config(s3={"addressing_style": "path"}, retries={"max_attempts": 3}),
        )

    def _call(self, name: str, **kwargs: Any) -> Any:
        try:
            return getattr(self.client, name)(Bucket=self.bucket, **kwargs)
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code", "")
            message = exc.response.get("Error", {}).get("Message", "")
            if code in REFUSALS:
                raise Refused(f"{code}: {message}") from exc
            raise OffsiteError(f"{name}: {code} {message}") from exc
        except BotoCoreError as exc:
            raise OffsiteError(f"{name}: {exc}") from exc

    def put(self, key: str, data: bytes, retain_until: datetime | None) -> str:
        extra: dict[str, Any] = {}
        if retain_until is not None and self.lock_mode != "none":
            extra = {"ObjectLockMode": self.lock_mode, "ObjectLockRetainUntilDate": retain_until}
        response = self._call("put_object", Key=key, Body=data, **extra)
        return str(response.get("VersionId") or "null")

    def get(self, key: str, version_id: str) -> bytes:
        extra = {} if version_id == "null" else {"VersionId": version_id}
        body: bytes = self._call("get_object", Key=key, **extra)["Body"].read()
        return body

    def versions(self, prefix: str) -> list[Version]:
        out: list[Version] = []
        marker: dict[str, str] = {}
        while True:
            page = self._call("list_object_versions", Prefix=prefix, **marker)
            for v in page.get("Versions", []):
                out.append(Version(v["Key"], v.get("VersionId") or "null", v["LastModified"], int(v["Size"]), False))
            for v in page.get("DeleteMarkers", []):
                out.append(Version(v["Key"], v.get("VersionId") or "null", v["LastModified"], 0, True))
            if not page.get("IsTruncated"):
                return out
            marker = {"KeyMarker": page["NextKeyMarker"], "VersionIdMarker": page["NextVersionIdMarker"]}

    def delete(self, key: str) -> None:
        self._call("delete_object", Key=key)

    def delete_version(self, key: str, version_id: str) -> None:
        self._call("delete_object", Key=key, VersionId=version_id)

    def shorten_retention(self, key: str, version_id: str, until: datetime) -> None:
        mode = self.lock_mode if self.lock_mode != "none" else "GOVERNANCE"
        retention = {"Mode": mode, "RetainUntilDate": until}
        self._call("put_object_retention", Key=key, VersionId=version_id, Retention=retention)


def offsite_from_env(lock_mode: str = "COMPLIANCE") -> S3Offsite:
    try:
        return S3Offsite(
            os.environ["DRKIT_S3_ENDPOINT"],
            os.environ["DRKIT_S3_KEY"],
            os.environ["DRKIT_S3_SECRET"],
            os.environ.get("DRKIT_S3_BUCKET", "backups"),
            lock_mode,
        )
    except KeyError as exc:
        raise OffsiteError(f"{exc.args[0]} is not set") from exc
