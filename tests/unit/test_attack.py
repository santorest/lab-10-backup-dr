from __future__ import annotations

from datetime import UTC, datetime, timedelta

from drkit.attack import attack, survival
from tests.unit.fakes import FakeOffsite

NOW = datetime(2026, 10, 2, 10, 0, tzinfo=UTC)


def seeded(locked: bool) -> FakeOffsite:
    store = FakeOffsite(locked=locked, clock=lambda: NOW)
    for key in ("mssql/full/f.bak", "pg/wal/000000010000000000000002.gz", "manifest/manifest-000002.json"):
        store.put(key, b"original " + key.encode(), NOW + timedelta(days=1))
    return store


def test_locked_store_refuses_every_destructive_attempt_and_keeps_every_original():
    store = seeded(locked=True)
    before = store.versions("")
    attempts = attack(store, NOW)
    by_action = {(a.action, a.refused) for a in attempts}
    assert ("delete-version", True) in by_action and ("shorten-retention", True) in by_action
    assert ("delete-version", False) not in by_action
    assert ("overwrite", False) in by_action and ("delete", False) in by_action  # allowed, but not destructive
    assert survival(before, store.versions("")) == []
    for v in before:  # originals still readable by version id
        assert store.get(v.key, v.version_id).startswith(b"original")


def test_unlocked_store_loses_everything():
    store = seeded(locked=False)
    before = store.versions("")
    attempts = attack(store, NOW)
    assert any(a.action == "delete-version" and not a.refused for a in attempts)
    assert len(survival(before, store.versions(""))) == 3


def test_survival_ignores_delete_markers_and_new_versions():
    store = seeded(locked=True)
    before = store.versions("")
    store.delete("mssql/full/f.bak")
    store.put("mssql/full/f.bak", b"encrypted", None)
    assert survival(before, store.versions("")) == []


def test_attack_targets_each_key_once_for_overwrite_and_delete():
    store = seeded(locked=True)
    attempts = attack(store, NOW)
    overwrites = [a.key for a in attempts if a.action == "overwrite"]
    assert sorted(overwrites) == sorted(set(overwrites)) and len(overwrites) == 3
