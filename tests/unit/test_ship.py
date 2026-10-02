from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

from drkit.manifest import loads, sha256_bytes
from drkit.ship import Meta, ship_once, write_meta
from tests.unit.fakes import FakeOffsite

NOW = datetime(2026, 10, 2, 10, 0, tzinfo=UTC)
UNTIL = NOW + timedelta(days=1)


def layout(tmp_path: Path) -> Path:
    local = tmp_path / "backup-local"
    for d in ("mssql/full", "mssql/log", "pg/base", "pg/wal"):
        (local / d).mkdir(parents=True)
    return local


def test_ships_ready_files_once_and_uploads_the_manifest(tmp_path: Path):
    local = layout(tmp_path)
    full = local / "mssql/full/appointments_full_1.bak"
    full.write_bytes(b"FULL")
    write_meta(full, Meta("appointments", "full", NOW, log_no=0))
    (local / "mssql/log/appointments_log_1.trn.part").write_bytes(b"half")  # still being written
    (local / "mssql/log/orphan.trn").write_bytes(b"no sidecar yet")
    wal = local / "pg/wal/000000010000000000000002.gz"
    wal.write_bytes(b"WAL")
    later = full.stat().st_mtime + 10  # shipping order follows mtime
    os.utime(wal, (later, later))
    store = FakeOffsite(clock=lambda: NOW)

    shipped = ship_once(local, store, "billing", UNTIL)

    assert [(e.seq, e.key, e.kind, e.system) for e in shipped] == [
        (1, "mssql/full/appointments_full_1.bak", "full", "appointments"),
        (2, "pg/wal/000000010000000000000002.gz", "wal", "billing"),
    ]
    assert shipped[0].sha256 == sha256_bytes(b"FULL") and shipped[0].log_no == 0
    assert store.get(shipped[0].key, shipped[0].version_id) == b"FULL"
    manifest_keys = [v.key for v in store.versions("manifest/")]
    assert manifest_keys == ["manifest/manifest-000002.json"]
    assert loads((local / "manifest.json").read_text(encoding="utf-8")) == shipped
    assert ship_once(local, store, "billing", UNTIL) == []  # nothing new, no new manifest
    assert len(store.versions("manifest/")) == 1


def test_later_files_continue_the_sequence(tmp_path: Path):
    local = layout(tmp_path)
    store = FakeOffsite(clock=lambda: NOW)
    first = local / "mssql/full/f.bak"
    first.write_bytes(b"F")
    write_meta(first, Meta("appointments", "full", NOW, log_no=0))
    ship_once(local, store, "billing", UNTIL)
    log = local / "mssql/log/l1.trn"
    log.write_bytes(b"L")
    write_meta(log, Meta("appointments", "log", NOW, log_no=1))
    [entry] = ship_once(local, store, "billing", UNTIL)
    assert (entry.seq, entry.log_no) == (2, 1)
    keys = [v.key for v in store.versions("manifest/")]
    assert keys == ["manifest/manifest-000001.json", "manifest/manifest-000002.json"]


def test_base_backup_keeps_its_wal_start(tmp_path: Path):
    local = layout(tmp_path)
    base = local / "pg/base/billing_base_1.tar"
    base.write_bytes(b"BASE")
    write_meta(base, Meta("billing", "base", NOW, wal_start="000000010000000000000002"))
    [entry] = ship_once(local, FakeOffsite(clock=lambda: NOW), "billing", UNTIL)
    assert entry.wal_start == "000000010000000000000002"
