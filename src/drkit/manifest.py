"""The backup manifest: every file shipped off-site, its object version and its SHA-256."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any

from drkit.models import ConfigError, iso, parse_utc

KINDS = ("full", "diff", "log", "base", "wal")
_SHA = re.compile(r"^[0-9a-f]{64}$")


class ManifestError(ValueError):
    """The manifest is malformed."""


@dataclass(frozen=True)
class Entry:
    seq: int
    system: str
    kind: str
    key: str
    version_id: str
    sha256: str
    size: int
    finished_at: datetime
    log_no: int | None = None  # SQL Server: own number for a log; the last log before it for a full/diff
    wal_start: str | None = None  # PostgreSQL base: the first WAL segment it needs


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def dumps(entries: Sequence[Entry]) -> str:
    rows = [{**asdict(e), "finished_at": iso(e.finished_at)} for e in entries]
    return json.dumps({"version": 1, "entries": rows}, indent=2) + "\n"


def _entry(item: dict[str, Any]) -> Entry:
    try:
        kind = item["kind"]
        if kind not in KINDS:
            raise ManifestError(f"kind must be one of {KINDS}, got {kind!r}")
        if not _SHA.match(str(item["sha256"])):
            raise ManifestError(f"sha256 is not a hex digest: {item['sha256']!r}")
        return Entry(
            seq=int(item["seq"]),
            system=str(item["system"]),
            kind=kind,
            key=str(item["key"]),
            version_id=str(item["version_id"]),
            sha256=str(item["sha256"]),
            size=int(item["size"]),
            finished_at=parse_utc(str(item["finished_at"])),
            log_no=None if item.get("log_no") is None else int(item["log_no"]),
            wal_start=None if item.get("wal_start") is None else str(item["wal_start"]),
        )
    except KeyError as exc:
        raise ManifestError(f"entry without {exc.args[0]}") from exc
    except ConfigError as exc:
        raise ManifestError(str(exc)) from exc


def loads(text: str) -> list[Entry]:
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ManifestError(f"not JSON: {exc}") from exc
    if not isinstance(data, dict) or data.get("version") != 1:
        raise ManifestError("unsupported manifest version")
    entries = [_entry(item) for item in data.get("entries", [])]
    for before, after in zip(entries, entries[1:], strict=False):
        if after.seq <= before.seq:
            raise ManifestError(f"seq must increase: {before.seq} then {after.seq}")
    return entries
