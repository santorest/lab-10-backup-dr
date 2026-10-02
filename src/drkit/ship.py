"""Ship finished backup files from the local tier to the off-site store and keep the manifest."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from drkit.manifest import Entry, dumps, loads, sha256_bytes
from drkit.models import iso, parse_utc
from drkit.offsite import Offsite

SKIP_NAMES = {"manifest.json", "README-RANSOM.txt"}


@dataclass(frozen=True)
class Meta:
    system: str
    kind: str
    finished_at: datetime
    log_no: int | None = None
    wal_start: str | None = None


def _sidecar(path: Path) -> Path:
    return path.with_name(path.name + ".meta.json")


def write_meta(path: Path, meta: Meta) -> Path:
    data = {
        "system": meta.system,
        "kind": meta.kind,
        "finished_at": iso(meta.finished_at),
        "log_no": meta.log_no,
        "wal_start": meta.wal_start,
    }
    target = _sidecar(path)
    tmp = target.with_name(target.name + ".part")
    tmp.write_text(json.dumps(data) + "\n", encoding="utf-8")
    os.replace(tmp, target)
    return target


def _meta(path: Path, rel: str, wal_system: str) -> Meta | None:
    if rel.startswith("pg/wal/"):
        return Meta(wal_system, "wal", datetime.fromtimestamp(path.stat().st_mtime, UTC))
    sidecar = _sidecar(path)
    if not sidecar.exists():
        return None
    data = json.loads(sidecar.read_text(encoding="utf-8"))
    return Meta(data["system"], data["kind"], parse_utc(data["finished_at"]), data.get("log_no"), data.get("wal_start"))


def _ready(local: Path) -> list[Path]:
    files = [
        p
        for p in local.rglob("*")
        if p.is_file() and not p.name.endswith((".part", ".meta.json")) and p.name not in SKIP_NAMES
    ]
    return sorted(files, key=lambda p: (p.stat().st_mtime, p.as_posix()))


def ship_once(local: Path, offsite: Offsite, wal_system: str, retain_until: datetime | None) -> list[Entry]:
    manifest_path = local / "manifest.json"
    entries = loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else []
    shipped = {e.key for e in entries}
    new: list[Entry] = []
    for path in _ready(local):
        rel = path.relative_to(local).as_posix()
        if rel in shipped:
            continue
        meta = _meta(path, rel, wal_system)
        if meta is None:
            continue
        data = path.read_bytes()
        version_id = offsite.put(rel, data, retain_until)
        new.append(
            Entry(
                len(entries) + len(new) + 1,
                meta.system,
                meta.kind,
                rel,
                version_id,
                sha256_bytes(data),
                len(data),
                meta.finished_at,
                meta.log_no,
                meta.wal_start,
            )
        )
    if new:
        entries += new
        text = dumps(entries)
        tmp = manifest_path.with_name("manifest.json.part")
        tmp.write_text(text, encoding="utf-8")
        os.replace(tmp, manifest_path)
        offsite.put(f"manifest/manifest-{entries[-1].seq:06d}.json", text.encode("utf-8"), retain_until)
    return new
