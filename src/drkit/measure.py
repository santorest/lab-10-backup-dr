"""Achieved RPO and RTO from what the restored database actually contains."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from drkit.models import System


@dataclass(frozen=True)
class Verification:
    newest_row_at: datetime | None
    rows: int
    min_seq: int | None
    max_seq: int | None
    check_ok: bool
    replay_complete: bool = True  # PostgreSQL: replay reached the last fetched WAL segment

    @property
    def contiguous(self) -> bool:
        if self.rows <= 0 or self.min_seq is None or self.max_seq is None:
            return False
        return self.max_seq - self.min_seq + 1 == self.rows


@dataclass(frozen=True)
class Outcome:
    system: str
    engine: str
    rpo_target_minutes: float
    rto_target_minutes: float
    rpo_real_seconds: float | None
    rpo_policy_minutes: float | None
    rto_seconds: float | None
    verified: bool
    problems: tuple[str, ...]

    @property
    def rpo_ok(self) -> bool:
        return (
            self.verified and self.rpo_policy_minutes is not None and self.rpo_policy_minutes <= self.rpo_target_minutes
        )

    @property
    def rto_ok(self) -> bool:
        return self.verified and self.rto_seconds is not None and self.rto_seconds / 60 <= self.rto_target_minutes


def measure(
    system: System,
    time_scale: int,
    t0: datetime,
    declared_at: datetime,
    recovered_at: datetime | None,
    verification: Verification | None,
) -> Outcome:
    problems: list[str] = []
    if recovered_at is None:
        problems.append("restore did not finish")
    if verification is None:
        problems.append("not verified")
    else:
        if not verification.check_ok:
            problems.append("consistency check failed")
        if not verification.replay_complete:
            problems.append("replay stopped before the end of the shipped WAL")
        if verification.newest_row_at is None or verification.rows == 0:
            problems.append("no rows restored")
        elif verification.newest_row_at >= t0:
            problems.append("restored data is newer than T0 (the attack)")
        if verification.rows and not verification.contiguous:
            problems.append("restored rows are not contiguous")
    newest = verification.newest_row_at if verification else None
    rpo_real = (t0 - newest).total_seconds() if newest is not None else None
    rpo_policy = rpo_real * time_scale / 60 if rpo_real is not None else None
    rto = (recovered_at - declared_at).total_seconds() if recovered_at is not None else None
    return Outcome(
        system.name,
        system.engine,
        system.rpo_minutes,
        system.rto_minutes,
        rpo_real,
        rpo_policy,
        rto,
        not problems,
        tuple(problems),
    )
