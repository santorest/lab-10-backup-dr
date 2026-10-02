"""Get a system's restore chain from the off-site tier alone, using only versions written before T0."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from drkit.chain import mssql_restore_sql, select_chain
from drkit.manifest import Entry, ManifestError, dumps, loads, sha256_bytes
from drkit.models import Policy, System
from drkit.offsite import Offsite


class FetchError(RuntimeError):
    """The off-site copy cannot provide a trustworthy restore chain."""


def _manifest(offsite: Offsite, before: datetime) -> list[Entry]:
    candidates = [v for v in offsite.versions("manifest/") if not v.is_delete_marker and v.last_modified < before]
    for v in sorted(candidates, key=lambda v: (v.key, v.last_modified), reverse=True):
        try:
            return loads(offsite.get(v.key, v.version_id).decode("utf-8"))
        except (ManifestError, UnicodeDecodeError):
            continue
    raise FetchError("no usable manifest written before T0 on the off-site tier")


def fetch(offsite: Offsite, policy: Policy, system: System, before: datetime, dest: Path) -> list[Entry]:
    entries = _manifest(offsite, before)
    chain = select_chain(entries, system, before)
    dest.mkdir(parents=True, exist_ok=True)
    for x in chain:
        data = offsite.get(x.key, x.version_id)
        if sha256_bytes(data) != x.sha256:
            raise FetchError(f"checksum mismatch for {x.key} (version {x.version_id})")
        name = x.key.rsplit("/", 1)[-1]
        if system.engine == "postgres":
            target = dest / "base.tar" if x.kind == "base" else dest / "wal" / name
        else:
            target = dest / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    if system.engine == "mssql":
        (dest / "restore.sql").write_text(mssql_restore_sql(chain, system.database), encoding="utf-8")
    (dest / "manifest.json").write_text(dumps([x for x in entries if x.system == system.name]), encoding="utf-8")
    (dest / "chain.json").write_text(json.dumps([x.key for x in chain], indent=2) + "\n", encoding="utf-8")
    return chain
