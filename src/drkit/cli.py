"""drkit command line. Exit codes: 0 ok, 1 gate failed, 2 error."""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path

from drkit.attack import Attempt, attack, survival
from drkit.chain import ChainError, replay_complete
from drkit.fetch import FetchError, fetch
from drkit.gate import failures
from drkit.manifest import ManifestError, loads
from drkit.measure import Verification, measure
from drkit.models import ConfigError, Policy, System, iso, load_policy, parse_utc
from drkit.offsite import Offsite, OffsiteError, Version
from drkit.report import render_html, render_markdown, results_json
from drkit.schedule import timeline
from drkit.ship import Meta, ship_once, write_meta


def make_offsite(lock_mode: str) -> Offsite:  # replaced in tests
    from drkit.s3 import offsite_from_env

    return offsite_from_env(lock_mode)


def _now() -> datetime:
    return datetime.now(UTC)


def _versions_to_json(versions: Sequence[Version]) -> str:
    rows = [
        {
            "key": v.key,
            "version_id": v.version_id,
            "last_modified": iso(v.last_modified),
            "size": v.size,
            "is_delete_marker": v.is_delete_marker,
        }
        for v in versions
    ]
    return json.dumps(rows, indent=2) + "\n"


def _versions_from_json(text: str) -> list[Version]:
    return [
        Version(d["key"], d["version_id"], parse_utc(d["last_modified"]), int(d["size"]), bool(d["is_delete_marker"]))
        for d in json.loads(text)
    ]


def _setting(policy: Policy, name: str) -> str:
    values = {
        "archive_timeout_real": str(max(1, round(policy.archive_timeout_seconds / policy.time_scale))),
        "time_scale": str(policy.time_scale),
        "attack_minute": str(policy.duration_minutes),
        "lock_mode": policy.lock_mode,
        "ci_lock_days": str(policy.ci_lock_days),
    }
    if name not in values:
        raise ConfigError(f"unknown setting {name!r}; one of {sorted(values)}")
    return values[name]


def _facts(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    data: dict[str, str] = json.loads(path.read_text(encoding="utf-8"))
    return data


def _replay_complete(facts: dict[str, str], system: System, restore_dir: Path) -> bool:
    """SQL Server proves its chain (every RESTORE LOG must succeed); PostgreSQL must show it replayed to the end."""
    if system.engine != "postgres":
        return True
    chain = restore_dir / "pg" / "chain.json"
    last = facts.get(f"{system.name}.last_replayed_wal", "")
    if not last or not chain.exists():
        return False  # not proven
    return replay_complete(last, json.loads(chain.read_text(encoding="utf-8")))


def _verification(facts: dict[str, str], system: System, restore_dir: Path) -> Verification | None:
    name = system.name
    if f"{name}.check" not in facts:
        return None
    newest = facts.get(f"{name}.newest_row_at", "")
    lo, hi = facts.get(f"{name}.min_seq", ""), facts.get(f"{name}.max_seq", "")
    return Verification(
        parse_utc(newest) if newest else None,
        int(facts.get(f"{name}.rows", "0") or 0),
        int(lo) if lo else None,
        int(hi) if hi else None,
        facts[f"{name}.check"] == "ok",
        _replay_complete(facts, system, restore_dir),
    )


def _backups(restore_dir: Path, policy: Policy) -> dict[str, dict[str, tuple[int, int]]]:
    out: dict[str, dict[str, tuple[int, int]]] = {}
    for system in policy.systems:
        path = restore_dir / ("mssql" if system.engine == "mssql" else "pg") / "manifest.json"
        kinds: dict[str, tuple[int, int]] = {}
        if path.exists():
            for e in loads(path.read_text(encoding="utf-8")):
                count, size = kinds.get(e.kind, (0, 0))
                kinds[e.kind] = (count + 1, size + e.size)
        out[system.name] = kinds
    return out


def _attempts(path: Path) -> list[Attempt]:
    if not path.exists():
        return []
    return [Attempt(**a) for a in json.loads(path.read_text(encoding="utf-8"))]


def _ship(args: argparse.Namespace) -> None:
    policy = load_policy(args.policy)
    store = make_offsite(policy.lock_mode)
    wal_system = policy.engine_system("postgres").name
    while True:
        stopping = args.stop_file is not None and args.stop_file.exists()
        until = None if policy.lock_mode == "none" else _now() + timedelta(days=args.lock_days)
        for e in ship_once(args.local, store, wal_system, until):
            print(f"shipped {e.key} ({e.size} bytes, version {e.version_id})", flush=True)
        if args.watch is None or stopping:
            return
        time.sleep(args.watch)


def _report(args: argparse.Namespace) -> None:
    policy = load_policy(args.policy)
    facts: dict[str, str] = {}
    for path in args.facts:  # one file per writer: the parallel restores never share one
        facts |= _facts(path)
    t0, declared = parse_utc(facts["t0"]), parse_utc(facts["declared_at"])
    outcomes = []
    for s in policy.systems:
        recovered = facts.get(f"{s.name}.recovered_at")
        outcomes.append(
            measure(s, policy.time_scale, t0, declared, parse_utc(recovered) if recovered else None,
                    _verification(facts, s, args.restore_dir))
        )  # fmt: skip
    lost = _versions_from_json(args.survival.read_text(encoding="utf-8")) if args.survival.exists() else []
    attempts = _attempts(args.attack)
    backups = _backups(args.restore_dir, policy)
    meta = {"t0": facts["t0"], "time_scale": str(policy.time_scale)}
    args.out_dir.mkdir(parents=True, exist_ok=True)
    (args.out_dir / "results.json").write_text(results_json(outcomes, attempts, lost, backups, meta), encoding="utf-8")
    (args.out_dir / "summary.md").write_text(render_markdown(outcomes, attempts, lost, backups, meta), encoding="utf-8")
    (args.out_dir / "report.html").write_text(render_html(outcomes, attempts, lost, backups, meta), encoding="utf-8")


def run(args: argparse.Namespace) -> int:
    cmd = args.command
    if cmd == "timeline":
        for s in timeline(load_policy(args.policy)):
            print(s.minute, s.system, s.kind)
    elif cmd == "setting":
        print(_setting(load_policy(args.policy), args.name))
    elif cmd == "meta":
        write_meta(args.file, Meta(args.system, args.kind, _now(), args.log_no, args.wal_start))
    elif cmd == "ship":
        _ship(args)
    elif cmd == "versions":
        args.out.write_text(_versions_to_json(make_offsite("COMPLIANCE").versions("")), encoding="utf-8")
    elif cmd == "attack-offsite":
        attempts = attack(make_offsite("COMPLIANCE"), _now())
        args.out.write_text(json.dumps([a.__dict__ for a in attempts], indent=2) + "\n", encoding="utf-8")
        print(f"{len(attempts)} attempts, {sum(a.refused for a in attempts)} refused")
    elif cmd == "survival":
        before = _versions_from_json(args.before.read_text(encoding="utf-8"))
        lost = survival(before, make_offsite("COMPLIANCE").versions(""))
        args.out.write_text(_versions_to_json(lost), encoding="utf-8")
        print(f"{len(lost)} backup versions lost")
    elif cmd == "fetch":
        policy = load_policy(args.policy)
        system = policy.system(args.system)
        chain = fetch(make_offsite(policy.lock_mode), policy, system, parse_utc(args.before), args.dest)
        print(f"{args.system}: {len(chain)} files fetched and verified")
    elif cmd == "mark":
        facts = _facts(args.facts)
        if args.get:
            print(facts.get(args.get, ""))
            return 0
        for pair in args.pairs:
            key, _, value = pair.partition("=")
            facts[key] = iso(_now()) if value == "now" else value
        args.facts.write_text(json.dumps(facts, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    elif cmd == "report":
        _report(args)
    elif cmd == "gate":
        problems = failures(json.loads(args.results.read_text(encoding="utf-8")))
        for p in problems:
            print(f"gate: {p}")
        if problems:
            return 1
        print("gate passed: every system recovered within its targets and no off-site version was lost")
    return 0


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="drkit")
    sub = p.add_subparsers(dest="command", required=True)
    s = sub.add_parser("timeline")
    s.add_argument("--policy", type=Path, required=True)
    s = sub.add_parser("setting")
    s.add_argument("--policy", type=Path, required=True)
    s.add_argument("name")
    s = sub.add_parser("meta")
    s.add_argument("--file", type=Path, required=True)
    s.add_argument("--system", required=True)
    s.add_argument("--kind", required=True, choices=["full", "diff", "log", "base"])
    s.add_argument("--log-no", type=int)
    s.add_argument("--wal-start")
    s = sub.add_parser("ship")
    s.add_argument("--policy", type=Path, required=True)
    s.add_argument("--local", type=Path, required=True)
    s.add_argument("--lock-days", type=int, required=True)
    s.add_argument("--watch", type=float)
    s.add_argument("--stop-file", type=Path)
    for name in ("versions", "attack-offsite"):
        s = sub.add_parser(name)
        s.add_argument("--out", type=Path, required=True)
    s = sub.add_parser("survival")
    s.add_argument("--before", type=Path, required=True)
    s.add_argument("--out", type=Path, required=True)
    s = sub.add_parser("fetch")
    s.add_argument("--policy", type=Path, required=True)
    s.add_argument("--system", required=True)
    s.add_argument("--before", required=True)
    s.add_argument("--dest", type=Path, required=True)
    s = sub.add_parser("mark")
    s.add_argument("--facts", type=Path, required=True)
    s.add_argument("--get")
    s.add_argument("pairs", nargs="*")
    s = sub.add_parser("report")
    s.add_argument("--facts", type=Path, nargs="+", required=True, help="merged in order (one file per writer)")
    for name in ("--policy", "--attack", "--survival", "--restore-dir", "--out-dir"):
        s.add_argument(name, type=Path, required=True)
    s = sub.add_parser("gate")
    s.add_argument("--results", type=Path, required=True)
    return p


def main(argv: Sequence[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        return run(args)
    except (ConfigError, ManifestError, ChainError, FetchError, OffsiteError, OSError, KeyError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
