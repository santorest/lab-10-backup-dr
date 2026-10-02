"""The drill fails when a target is missed, a restore is not verified, or the off-site tier lost a version."""

from __future__ import annotations

from typing import Any


def failures(results: dict[str, Any]) -> list[str]:
    out: list[str] = []
    for o in results["outcomes"]:
        if not o["verified"]:
            out.append(f"{o['system']}: not recovered ({'; '.join(o['problems'])})")
            continue
        if not o["rpo_ok"]:
            out.append(f"{o['system']}: RPO {o['rpo_policy_minutes']:.1f} min > target {o['rpo_target_minutes']:g} min")
        if not o["rto_ok"]:
            out.append(f"{o['system']}: RTO {o['rto_seconds'] / 60:.1f} min > target {o['rto_target_minutes']:g} min")
    lost = results["attack"]["lost"]
    if lost:
        out.append(f"{len(lost)} backup version(s) destroyed on the off-site tier")
    return out
