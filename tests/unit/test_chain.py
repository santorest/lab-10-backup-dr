from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from drkit.chain import ChainError, mssql_restore_sql, select_chain, wal_segment
from drkit.manifest import Entry
from drkit.models import System

T0 = datetime(2026, 10, 2, 12, 0, tzinfo=UTC)
APPT = System("appointments", "mssql", "appointments", 15, 30)
BILL = System("billing", "postgres", "billing", 5, 60)


def e(seq: int, kind: str, key: str, minutes_before: float, system: str = "appointments", **kw: object) -> Entry:
    finished = T0 - timedelta(minutes=minutes_before)
    return Entry(seq, system, kind, key, f"v{seq}", "a" * 64, 1, finished, **kw)  # type: ignore[arg-type]


def mssql_entries() -> list[Entry]:
    return [
        e(1, "full", "mssql/full/f1.bak", 400, log_no=0),
        e(2, "log", "mssql/log/l1.trn", 385, log_no=1),
        e(3, "log", "mssql/log/l2.trn", 370, log_no=2),
        e(4, "diff", "mssql/diff/d1.bak", 40, log_no=2),
        e(5, "log", "mssql/log/l3.trn", 25, log_no=3),
        e(6, "log", "mssql/log/l4.trn", 10, log_no=4),
    ]


def test_full_newest_diff_and_logs_after_it():
    chain = select_chain(mssql_entries(), APPT, T0)
    assert [x.key for x in chain] == ["mssql/full/f1.bak", "mssql/diff/d1.bak", "mssql/log/l3.trn", "mssql/log/l4.trn"]


def test_without_diff_all_logs_from_the_full():
    entries = [x for x in mssql_entries() if x.kind != "diff"]
    assert [x.log_no for x in select_chain(entries, APPT, T0)] == [0, 1, 2, 3, 4]


def test_missing_log_is_an_error_not_a_shorter_restore():
    entries = [x for x in mssql_entries() if x.key != "mssql/log/l3.trn"]
    with pytest.raises(ChainError, match="log backup 3 is missing"):
        select_chain(entries, APPT, T0)


def test_differential_older_than_the_full_is_ignored():
    entries = [
        e(1, "diff", "mssql/diff/old.bak", 500, log_no=0),
        e(2, "full", "mssql/full/f.bak", 400, log_no=0),
        e(3, "log", "mssql/log/l1.trn", 385, log_no=1),
    ]
    assert [x.key for x in select_chain(entries, APPT, T0)] == ["mssql/full/f.bak", "mssql/log/l1.trn"]


def test_files_finished_after_t0_are_not_used():
    entries = [*mssql_entries(), e(7, "log", "mssql/log/l5.trn", -1, log_no=5)]
    assert select_chain(entries, APPT, T0)[-1].key == "mssql/log/l4.trn"


def test_no_full_is_an_error():
    with pytest.raises(ChainError, match="no full backup"):
        select_chain([e(1, "log", "mssql/log/l1.trn", 10, log_no=1)], APPT, T0)


def test_missing_log_no_is_an_error():
    with pytest.raises(ChainError, match="log_no"):
        select_chain([e(1, "full", "mssql/full/f.bak", 10)], APPT, T0)


def wal(seq: int, name: str, minutes_before: float = 5) -> Entry:
    return e(seq, "wal", f"pg/wal/{name}.gz", minutes_before, system="billing")


def pg_entries() -> list[Entry]:
    return [
        wal(1, "000000010000000000000001", 401),
        e(2, "base", "pg/base/b.tar", 400, system="billing", wal_start="000000010000000000000002"),
        wal(3, "000000010000000000000002"),
        wal(4, "000000010000000000000002.00000028.backup"),
        wal(5, "000000010000000000000003"),
        wal(6, "0000000100000000000000FF"),
        wal(7, "000000010000000100000000"),
    ]


def test_postgres_base_and_contiguous_wal_across_a_log_id_boundary():
    entries = pg_entries()
    hole = [wal(10 + i, f"0000000100000000000000{n:02X}") for i, n in enumerate(range(4, 255))]
    chain = select_chain([*entries, *hole], BILL, T0)
    assert chain[0].kind == "base"
    names = [x.key.rsplit("/", 1)[1] for x in chain[1:]]
    assert names[0] == "000000010000000000000002.gz" and names[-1] == "000000010000000000000002.00000028.backup.gz"
    assert "000000010000000100000000.gz" in names and "000000010000000000000001.gz" not in names


def test_postgres_hole_in_the_wal_is_an_error():
    with pytest.raises(ChainError, match="WAL segment 000000010000000000000004 is missing"):
        select_chain(pg_entries(), BILL, T0)


def test_postgres_missing_first_segment_is_an_error():
    entries = [x for x in pg_entries() if "0000000000000002.gz" not in x.key]
    with pytest.raises(ChainError, match="first WAL segment 000000010000000000000002"):
        select_chain(entries, BILL, T0)


def test_wal_segment():
    assert wal_segment("pg/wal/000000010000000100000000.gz") == (1, 256)
    assert wal_segment("pg/wal/000000010000000000000002.00000028.backup.gz") is None


def test_restore_sql():
    sql = mssql_restore_sql(select_chain(mssql_entries(), APPT, T0), "appointments")
    lines = sql.strip().splitlines()
    assert lines[0].startswith(
        "RESTORE DATABASE [appointments] FROM DISK = N'/restore/f1.bak' WITH NORECOVERY, CHECKSUM"
    )
    assert "MOVE N'appointments' TO N'/var/opt/mssql/data/appointments.mdf'" in lines[0] and "REPLACE" in lines[0]
    assert lines[1] == "RESTORE DATABASE [appointments] FROM DISK = N'/restore/d1.bak' WITH NORECOVERY, CHECKSUM;"
    assert lines[2] == "RESTORE LOG [appointments] FROM DISK = N'/restore/l3.trn' WITH NORECOVERY, CHECKSUM;"
    assert lines[-1] == "RESTORE DATABASE [appointments] WITH RECOVERY;"


def test_restore_sql_quotes_names():
    chain = [e(1, "full", "mssql/full/o'brien.bak", 10, log_no=0)]
    sql = mssql_restore_sql(chain, "a]b")
    assert "N'/restore/o''brien.bak'" in sql and "[a]]b]" in sql
