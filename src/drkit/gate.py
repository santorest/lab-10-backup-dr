"""The drill fails when a target is missed, a restore is not verified, or the off-site tier lost a version."""

from __future__ import annotations

from typing import Any

DESTRUCTIVE = ("shorten-retention", "delete-version")  # what Object Lock must refuse; overwrite/delete only add on top


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
    # A shortened retention loses nothing yet — the versions become deletable a minute later. Any destructive request
    # the store accepted is a failure, whether or not a version is already gone.
    for action in DESTRUCTIVE:
        accepted = [a for a in results["attack"]["accepted"] if a["action"] == action]
        if accepted:
            out.append(f"{len(accepted)} {action} attempt(s) accepted on the off-site tier")
    lost = results["attack"]["lost"]
    if lost:
        out.append(f"{len(lost)} backup version(s) destroyed on the off-site tier")
    return out
