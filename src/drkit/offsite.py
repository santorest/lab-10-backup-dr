"""What drkit needs from the off-site object store; s3.S3Offsite implements it for MinIO/S3."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


@dataclass(frozen=True)
class Version:
    key: str
    version_id: str
    last_modified: datetime
    size: int
    is_delete_marker: bool


class OffsiteError(RuntimeError):
    """The object store failed."""


class Refused(OffsiteError):
    """The object store refused a destructive request (Object Lock or access policy)."""


class Offsite(Protocol):
    def put(self, key: str, data: bytes, retain_until: datetime | None) -> str: ...
    def get(self, key: str, version_id: str) -> bytes: ...
    def versions(self, prefix: str) -> list[Version]: ...
    def delete(self, key: str) -> None: ...
    def delete_version(self, key: str, version_id: str) -> None: ...
    def shorten_retention(self, key: str, version_id: str, until: datetime) -> None: ...
