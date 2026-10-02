from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from drkit.manifest import Entry, ManifestError, dumps, loads, sha256_bytes

T = datetime(2026, 10, 2, 10, 0, tzinfo=UTC)


def entry(seq: int, **kw: object) -> Entry:
    base: dict[str, object] = dict(
        seq=seq,
        system="appointments",
        kind="full",
        key=f"mssql/full/f{seq}.bak",
        version_id=f"v{seq}",
        sha256="a" * 64,
        size=10,
        finished_at=T,
        log_no=0,
    )
    base.update(kw)
    return Entry(**base)  # type: ignore[arg-type]


def test_round_trip():
    entries = [
        entry(1),
        entry(2, kind="log", key="mssql/log/l1.trn", log_no=1),
        entry(3, system="billing", kind="base", key="pg/base/b.tar", log_no=None, wal_start="000000010000000000000002"),
    ]
    assert loads(dumps(entries)) == entries


def test_sha256():
    assert sha256_bytes(b"abc") == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda d: d["entries"][0].update(kind="snapshot"), "kind"),
        (lambda d: d["entries"][0].update(sha256="xyz"), "sha256"),
        (lambda d: d["entries"][1].update(seq=1), "seq"),
        (lambda d: d["entries"][0].pop("version_id"), "version_id"),
        (lambda d: d["entries"][0].update(finished_at="2026-10-02T10:00:00"), "zone"),
        (lambda d: d.update(version=2), "version"),
    ],
)
def test_rejects_bad_manifests(mutate, message: str):
    data = json.loads(dumps([entry(1), entry(2)]))
    mutate(data)
    with pytest.raises(ManifestError, match=message):
        loads(json.dumps(data))


def test_not_json():
    with pytest.raises(ManifestError, match="not JSON"):
        loads("{nope")
