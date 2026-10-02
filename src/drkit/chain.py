"""Which backups restore a system to its last safe point, and the T-SQL that restores them."""

from __future__ import annotations

import re
from collections.abc import Sequence
from datetime import datetime

from drkit.manifest import Entry
from drkit.models import System, iso

_WAL = re.compile(r"(?:^|/)([0-9A-F]{8})([0-9A-F]{8})([0-9A-F]{8})\.gz$")
SEGMENTS_PER_LOG = 0x100  # 16 MB segments


class ChainError(ValueError):
    """No complete restore chain exists."""


def wal_segment(name: str) -> tuple[int, int] | None:
    m = _WAL.search(name)
    if not m:
        return None
    return int(m.group(1), 16), int(m.group(2), 16) * SEGMENTS_PER_LOG + int(m.group(3), 16)


def _name(timeline: int, segno: int) -> str:
    return f"{timeline:08X}{segno // SEGMENTS_PER_LOG:08X}{segno % SEGMENTS_PER_LOG:08X}"


def _mssql(mine: list[Entry], system: str, before: datetime) -> list[Entry]:
    for x in mine:
        if x.kind in ("full", "diff", "log") and x.log_no is None:
            raise ChainError(f"{system}: {x.key} has no log_no")
    fulls = [x for x in mine if x.kind == "full"]
    if not fulls:
        raise ChainError(f"{system}: no full backup before {iso(before)}")
    full = fulls[-1]
    diffs = [x for x in mine if x.kind == "diff" and x.seq > full.seq]
    base = diffs[-1] if diffs else full
    start = base.log_no or 0
    logs = sorted((x for x in mine if x.kind == "log" and (x.log_no or 0) > start), key=lambda x: x.log_no or 0)
    expected = start + 1
    for log in logs:
        if log.log_no != expected:
            raise ChainError(f"{system}: log backup {expected} is missing (the next one is {log.log_no})")
        expected += 1
    return [full, *([base] if base is not full else []), *logs]


def _postgres(mine: list[Entry], system: str, before: datetime) -> list[Entry]:
    bases = [x for x in mine if x.kind == "base"]
    if not bases:
        raise ChainError(f"{system}: no base backup before {iso(before)}")
    base = bases[-1]
    start = wal_segment(base.wal_start + ".gz") if base.wal_start else None
    if start is None:
        raise ChainError(f"{system}: {base.key} has no valid wal_start")
    timeline, first = start
    segments: dict[int, Entry] = {}
    others: list[Entry] = []
    for x in mine:
        if x.kind != "wal":
            continue
        seg = wal_segment(x.key)
        if seg is None:
            others.append(x)
        elif seg[0] == timeline and seg[1] >= first:
            segments[seg[1]] = x
    if first not in segments:
        raise ChainError(f"{system}: first WAL segment {base.wal_start} needed by {base.key} is missing")
    run: list[Entry] = []
    for segno in range(first, max(segments) + 1):
        if segno not in segments:
            raise ChainError(f"{system}: WAL segment {_name(timeline, segno)} is missing")
        run.append(segments[segno])
    return [base, *run, *others]


def replay_complete(last_replayed_walfile: str, chain_keys: Sequence[str]) -> bool:
    """PostgreSQL replays WAL until a segment is missing or unreadable and then promotes, so a restore that stopped
    early looks like a good one. True only if replay reached the last segment that was fetched (any timeline: after
    promotion pg_walfile_name() names the new one)."""
    replayed = wal_segment(last_replayed_walfile.strip() + ".gz")
    fetched = [seg[1] for key in chain_keys if (seg := wal_segment(key)) is not None]
    return replayed is not None and bool(fetched) and replayed[1] >= max(fetched)


def select_chain(entries: Sequence[Entry], system: System, before: datetime) -> list[Entry]:
    mine = sorted((x for x in entries if x.system == system.name and x.finished_at < before), key=lambda x: x.seq)
    return _mssql(mine, system.name, before) if system.engine == "mssql" else _postgres(mine, system.name, before)


def _quote(text: str) -> str:
    return text.replace("'", "''")


def mssql_restore_sql(chain: Sequence[Entry], database: str) -> str:
    db = "[" + database.replace("]", "]]") + "]"
    name = _quote(database)
    lines: list[str] = []
    for x in chain:
        path = "/restore/" + _quote(x.key.rsplit("/", 1)[-1])
        if x.kind == "full":
            lines.append(
                f"RESTORE DATABASE {db} FROM DISK = N'{path}' WITH NORECOVERY, CHECKSUM, REPLACE, "
                f"MOVE N'{name}' TO N'/var/opt/mssql/data/{name}.mdf', "
                f"MOVE N'{name}_log' TO N'/var/opt/mssql/data/{name}_log.ldf';"
            )
        elif x.kind == "diff":
            lines.append(f"RESTORE DATABASE {db} FROM DISK = N'{path}' WITH NORECOVERY, CHECKSUM;")
        else:
            lines.append(f"RESTORE LOG {db} FROM DISK = N'{path}' WITH NORECOVERY, CHECKSUM;")
    lines.append(f"RESTORE DATABASE {db} WITH RECOVERY;")
    return "\n".join(lines) + "\n"
