from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from drkit.fetch import FetchError, fetch
from drkit.manifest import Entry, dumps, sha256_bytes
from drkit.models import load_policy
from tests.unit.fakes import FakeOffsite

POLICY = load_policy(Path(__file__).resolve().parents[2] / "policy" / "dr-policy.yaml")
APPT = POLICY.system("appointments")
T0 = datetime(2026, 10, 2, 12, 0, tzinfo=UTC)


class Clock:
    def __init__(self) -> None:
        self.now = T0 - timedelta(minutes=10)

    def __call__(self) -> datetime:
        return self.now


def stored(store: FakeOffsite, key: str, data: bytes, seq: int, kind: str, log_no: int) -> Entry:
    vid = store.put(key, data, T0 + timedelta(days=1))
    return Entry(seq, "appointments", kind, key, vid, sha256_bytes(data), len(data), T0 - timedelta(minutes=10), log_no)


def setup() -> tuple[FakeOffsite, Clock, list[Entry]]:
    clock = Clock()
    store = FakeOffsite(clock=clock)
    entries = [
        stored(store, "mssql/full/f.bak", b"FULL", 1, "full", 0),
        stored(store, "mssql/log/l1.trn", b"LOG1", 2, "log", 1),
    ]
    store.put("manifest/manifest-000002.json", dumps(entries).encode(), T0 + timedelta(days=1))
    return store, clock, entries


def test_fetch_downloads_the_chain_and_writes_restore_sql(tmp_path: Path):
    store, _, _ = setup()
    chain = fetch(store, POLICY, APPT, T0, tmp_path)
    assert [x.key for x in chain] == ["mssql/full/f.bak", "mssql/log/l1.trn"]
    assert (tmp_path / "f.bak").read_bytes() == b"FULL" and (tmp_path / "l1.trn").read_bytes() == b"LOG1"
    assert "RESTORE LOG [appointments] FROM DISK = N'/restore/l1.trn'" in (tmp_path / "restore.sql").read_text()
    assert (tmp_path / "manifest.json").exists() and (tmp_path / "chain.json").exists()


def test_fetch_ignores_versions_written_after_t0(tmp_path: Path):
    store, clock, _ = setup()
    clock.now = T0 + timedelta(seconds=5)  # the attacker, after T0
    store.put("mssql/full/f.bak", b"ENCRYPTED", None)
    store.put("manifest/manifest-999999.json", b'{"version": 1, "entries": []}', None)
    store.delete("mssql/log/l1.trn")
    chain = fetch(store, POLICY, APPT, T0, tmp_path)
    assert len(chain) == 2 and (tmp_path / "f.bak").read_bytes() == b"FULL"


def test_fetch_fails_on_checksum_mismatch(tmp_path: Path):
    store, _, entries = setup()
    bad = [entries[0], replace(entries[1], sha256="0" * 64)]
    store.put("manifest/manifest-000003.json", dumps(bad).encode(), T0 + timedelta(days=1))
    with pytest.raises(FetchError, match="checksum mismatch for mssql/log/l1.trn"):
        fetch(store, POLICY, APPT, T0, tmp_path)


def test_fetch_without_a_manifest_before_t0_is_an_error(tmp_path: Path):
    with pytest.raises(FetchError, match="no usable manifest"):
        fetch(FakeOffsite(clock=lambda: T0), POLICY, APPT, T0, tmp_path)


def test_fetch_postgres_layout(tmp_path: Path):
    store = FakeOffsite(clock=lambda: T0 - timedelta(minutes=10))
    data = {"pg/base/b.tar": b"BASE", "pg/wal/000000010000000000000002.gz": b"W2"}
    vids = {k: store.put(k, v, T0 + timedelta(days=1)) for k, v in data.items()}
    wal_key = "pg/wal/000000010000000000000002.gz"
    entries = [
        Entry(1, "billing", "base", "pg/base/b.tar", vids["pg/base/b.tar"], sha256_bytes(b"BASE"), 4,
              T0 - timedelta(minutes=10), wal_start="000000010000000000000002"),
        Entry(2, "billing", "wal", wal_key, vids[wal_key], sha256_bytes(b"W2"), 2, T0 - timedelta(minutes=9)),
    ]  # fmt: skip
    store.put("manifest/manifest-000002.json", dumps(entries).encode(), T0 + timedelta(days=1))
    fetch(store, POLICY, POLICY.system("billing"), T0, tmp_path)
    assert (tmp_path / "base.tar").read_bytes() == b"BASE"
    assert (tmp_path / "wal" / "000000010000000000000002.gz").read_bytes() == b"W2"
