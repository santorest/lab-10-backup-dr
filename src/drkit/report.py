"""Results as JSON (for the gate), Markdown (job summary) and HTML (artifact). Deterministic, escaped."""

from __future__ import annotations

import html
import json
from collections.abc import Sequence

from drkit.attack import Attempt
from drkit.measure import Outcome
from drkit.offsite import Version

Backups = dict[str, dict[str, tuple[int, int]]]
HEAD = ["System", "Engine", "RPO target", "RPO achieved", "Met", "RTO target", "RTO achieved", "Met", "Verified"]


def _md(text: object) -> str:
    return str(text).replace("\\", "\\\\").replace("|", "\\|").replace("\r", " ").replace("\n", " ")


def _num(value: float | None, digits: int = 1) -> str:
    return "—" if value is None else f"{value:.{digits}f}"


def results_json(
    outcomes: Sequence[Outcome],
    attempts: Sequence[Attempt],
    lost: Sequence[Version],
    backups: Backups,
    meta: dict[str, str],
) -> str:
    data = {
        "meta": meta,
        "outcomes": [
            {
                "system": o.system,
                "engine": o.engine,
                "rpo_target_minutes": o.rpo_target_minutes,
                "rto_target_minutes": o.rto_target_minutes,
                "rpo_real_seconds": o.rpo_real_seconds,
                "rpo_policy_minutes": o.rpo_policy_minutes,
                "rto_seconds": o.rto_seconds,
                "verified": o.verified,
                "rpo_ok": o.rpo_ok,
                "rto_ok": o.rto_ok,
                "problems": list(o.problems),
            }
            for o in outcomes
        ],
        "attack": {
            "attempts": len(attempts),
            "refused": sum(a.refused for a in attempts),
            "accepted": [{"action": a.action, "key": a.key} for a in attempts if not a.refused],
            "lost": [{"key": v.key, "version_id": v.version_id} for v in lost],
        },
        "backups": {s: {k: {"count": c, "bytes": b} for k, (c, b) in kinds.items()} for s, kinds in backups.items()},
    }
    return json.dumps(data, indent=2, sort_keys=True) + "\n"


def _rows(outcomes: Sequence[Outcome]) -> list[list[str]]:
    rows = []
    for o in outcomes:
        rto_minutes = o.rto_seconds / 60 if o.rto_seconds is not None else None
        rows.append(
            [
                o.system,
                o.engine,
                f"≤ {o.rpo_target_minutes:g} min",
                f"{_num(o.rpo_policy_minutes)} min ({_num(o.rpo_real_seconds)} s real)",
                "yes" if o.rpo_ok else "NO",
                f"≤ {o.rto_target_minutes:g} min",
                f"{_num(rto_minutes)} min ({_num(o.rto_seconds)} s)",
                "yes" if o.rto_ok else "NO",
                "yes" if o.verified else "NO: " + "; ".join(o.problems),
            ]
        )
    return rows


def render_markdown(
    outcomes: Sequence[Outcome],
    attempts: Sequence[Attempt],
    lost: Sequence[Version],
    backups: Backups,
    meta: dict[str, str],
) -> str:
    out = [
        "## Disaster recovery drill",
        "",
        " · ".join(f"{k} {_md(v)}" for k, v in sorted(meta.items())),
        "",
        "| " + " | ".join(HEAD) + " |",
        "|" + "---|" * len(HEAD),
    ]
    out += ["| " + " | ".join(_md(c) for c in row) + " |" for row in _rows(outcomes)]
    refused = sum(a.refused for a in attempts)
    out += ["", f"Off-site attack: {len(attempts)} attempts, {refused} refused, {len(lost)} backup versions lost.", ""]
    accepted = sorted({a.action for a in attempts if not a.refused})
    if accepted:
        out += ["Accepted (not destructive unless listed as lost): " + ", ".join(_md(a) for a in accepted), ""]
    sample = [a for a in attempts if a.refused][:3]
    if sample:
        out += ["| Action | Key | Refusal |", "|---|---|---|"]
        out += [f"| {_md(a.action)} | {_md(a.key)} | {_md(a.detail)} |" for a in sample]
        out.append("")
    out += ["| System | Kind | Files | Bytes |", "|---|---|---|---|"]
    out += [f"| {_md(s)} | {_md(k)} | {c} | {b} |" for s in sorted(backups) for k, (c, b) in sorted(backups[s].items())]
    return "\n".join(out) + "\n"


def render_html(
    outcomes: Sequence[Outcome],
    attempts: Sequence[Attempt],
    lost: Sequence[Version],
    backups: Backups,
    meta: dict[str, str],
) -> str:
    e = html.escape
    rows = "".join("<tr>" + "".join(f"<td>{e(c)}</td>" for c in row) + "</tr>" for row in _rows(outcomes))
    refusals = "".join(
        f"<tr><td>{e(a.action)}</td><td>{e(a.key)}</td><td>{e(a.detail)}</td></tr>" for a in attempts if a.refused
    )
    backup_rows = "".join(
        f"<tr><td>{e(s)}</td><td>{e(k)}</td><td>{c}</td><td>{b}</td></tr>"
        for s in sorted(backups)
        for k, (c, b) in sorted(backups[s].items())
    )
    meta_line = " · ".join(f"{e(k)} {e(v)}" for k, v in sorted(meta.items()))
    head = "".join(f"<th>{h}</th>" for h in HEAD)
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8"><title>DR drill</title>'
        "<style>body{font-family:sans-serif;margin:2rem}table{border-collapse:collapse;margin:1rem 0}"
        "td,th{border:1px solid #999;padding:.3rem .6rem;text-align:left}</style></head><body>"
        f"<h1>Disaster recovery drill</h1><p>{meta_line}</p>"
        f"<table><tr>{head}</tr>{rows}</table>"
        f"<h2>Off-site attack</h2><p>{len(attempts)} attempts, {sum(a.refused for a in attempts)} refused, "
        f"{len(lost)} backup versions lost.</p>"
        f"<table><tr><th>Action</th><th>Key</th><th>Refusal</th></tr>{refusals}</table>"
        "<h2>Backups shipped</h2><table><tr><th>System</th><th>Kind</th><th>Files</th><th>Bytes</th></tr>"
        f"{backup_rows}</table></body></html>\n"
    )
