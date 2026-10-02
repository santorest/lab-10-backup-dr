"""An in-memory versioned object store with optional compliance-mode Object Lock, for unit tests."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime

from drkit.offsite import OffsiteError, Refused, Version


@dataclass
class _Obj:
    version_id: str
    data: bytes | None  # None = delete marker
    retain_until: datetime | None
    last_modified: datetime


def _default_clock() -> datetime:
    return datetime(2026, 10, 2, 10, 0, tzinfo=UTC)


@dataclass
class FakeOffsite:
    locked: bool = True
    clock: Callable[[], datetime] = _default_clock
    objects: dict[str, list[_Obj]] = field(default_factory=dict)
    counter: int = 0

    def _new_id(self) -> str:
        self.counter += 1
        return f"v{self.counter}" if self.locked else "null"

    def put(self, key: str, data: bytes, retain_until: datetime | None) -> str:
        obj = _Obj(self._new_id(), data, retain_until if self.locked else None, self.clock())
        if self.locked:
            self.objects.setdefault(key, []).append(obj)
        else:
            self.objects[key] = [obj]  # unversioned bucket: an overwrite replaces the object
        return obj.version_id

    def get(self, key: str, version_id: str) -> bytes:
        for obj in self.objects.get(key, []):
            if obj.version_id == version_id and obj.data is not None:
                return obj.data
        raise KeyError(f"{key}@{version_id}")

    def versions(self, prefix: str) -> list[Version]:
        return [
            Version(k, o.version_id, o.last_modified, len(o.data or b""), o.data is None)
            for k, objs in sorted(self.objects.items())
            if k.startswith(prefix)
            for o in objs
        ]

    def delete(self, key: str) -> None:
        if self.locked:
            self.objects.setdefault(key, []).append(_Obj(self._new_id(), None, None, self.clock()))
        else:
            self.objects.pop(key, None)

    def delete_version(self, key: str, version_id: str) -> None:
        objs = self.objects.get(key, [])
        for obj in objs:
            if obj.version_id == version_id:
                if obj.retain_until is not None and obj.retain_until > self.clock():
                    raise Refused(f"AccessDenied: object {key} is WORM protected until {obj.retain_until}")
                objs.remove(obj)
                return

    def shorten_retention(self, key: str, version_id: str, until: datetime) -> None:
        if until <= self.clock():  # as MinIO: a malformed request, not a refusal
            raise OffsiteError("put_object_retention: MalformedXML the retain until date must be in the future")
        for obj in self.objects.get(key, []):
            if obj.version_id == version_id and obj.retain_until is not None and until < obj.retain_until:
                raise Refused("AccessDenied: compliance retention cannot be shortened")
