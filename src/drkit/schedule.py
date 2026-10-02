"""The backup schedule laid out on the drill's policy-minute timeline (attack at duration_minutes)."""

from __future__ import annotations

from dataclasses import dataclass

from drkit.models import Policy


@dataclass(frozen=True, order=True)
class Step:
    minute: int
    order: int  # within a minute: full/base before diff before log
    system: str
    kind: str


def timeline(policy: Policy) -> list[Step]:
    steps: list[Step] = []
    for s in policy.systems:
        for minute in range(policy.duration_minutes):
            if s.engine == "mssql":
                if minute % policy.full_every == 0:
                    steps.append(Step(minute, 0, s.name, "full"))
                elif minute % policy.diff_every == 0:
                    steps.append(Step(minute, 1, s.name, "diff"))
                if minute > 0 and minute % policy.log_every == 0:
                    steps.append(Step(minute, 2, s.name, "log"))
            elif minute % policy.base_every == 0:
                steps.append(Step(minute, 0, s.name, "base"))
    return sorted(steps)
