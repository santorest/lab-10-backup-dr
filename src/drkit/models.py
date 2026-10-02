"""The backup and recovery policy (policy/dr-policy.yaml) and UTC time helpers."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

ENGINES = ("mssql", "postgres")
LOCK_MODES = ("COMPLIANCE", "none")
_FRACTION = re.compile(r"(\.\d{1,6})\d*")


class ConfigError(ValueError):
    """The policy (or another input file) is missing, malformed or inconsistent."""


@dataclass(frozen=True)
class System:
    name: str
    engine: str
    database: str
    rpo_minutes: float
    rto_minutes: float


@dataclass(frozen=True)
class Policy:
    systems: tuple[System, ...]
    full_every: int
    diff_every: int
    log_every: int
    base_every: int
    archive_timeout_seconds: int
    local_days: int
    offsite_days: int
    lock_mode: str
    time_scale: int
    duration_minutes: int
    ci_lock_days: int

    def system(self, name: str) -> System:
        for s in self.systems:
            if s.name == name:
                return s
        raise ConfigError(f"no system named {name!r} in the policy")

    def engine_system(self, engine: str) -> System:
        for s in self.systems:
            if s.engine == engine:
                return s
        raise ConfigError(f"no {engine} system in the policy")


def parse_utc(text: str) -> datetime:
    cleaned = _FRACTION.sub(r"\1", text.strip().replace("Z", "+00:00"), count=1)
    try:
        value = datetime.fromisoformat(cleaned)
    except ValueError as exc:
        raise ConfigError(f"not an ISO 8601 time: {text!r}") from exc
    if value.tzinfo is None:
        raise ConfigError(f"time without a zone: {text!r}")
    return value.astimezone(UTC)


def iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _positive(section: dict[str, Any], key: str) -> int:
    value = section.get(key)
    if isinstance(value, bool) or not isinstance(value, int | float) or value <= 0:
        raise ConfigError(f"{key} must be a positive number, got {value!r}")
    return int(value)


def load_policy(path: Path) -> Policy:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        raise ConfigError(f"cannot read {path}: {exc}") from exc
    try:
        systems: list[System] = []
        for item in data["systems"]:
            engine = item["engine"]
            if engine not in ENGINES:
                raise ConfigError(f"{item['name']}: engine must be one of {ENGINES}, got {engine!r}")
            systems.append(
                System(
                    name=str(item["name"]),
                    engine=engine,
                    database=str(item["database"]),
                    rpo_minutes=_positive(item, "rpo_minutes"),
                    rto_minutes=_positive(item, "rto_minutes"),
                )
            )
        names = [s.name for s in systems]
        if len(set(names)) != len(names):
            raise ConfigError(f"duplicate system names: {names}")
        if sorted(s.engine for s in systems) != sorted(ENGINES):
            raise ConfigError("the policy needs exactly one system per engine (mssql, postgres)")
        mssql, pg = data["schedule"]["mssql"], data["schedule"]["postgres"]
        retention, drill = data["retention"], data["drill"]
        lock_mode = retention["offsite_lock_mode"]
        if lock_mode not in LOCK_MODES:
            raise ConfigError(f"offsite_lock_mode must be one of {LOCK_MODES}, got {lock_mode!r}")
        return Policy(
            systems=tuple(systems),
            full_every=_positive(mssql, "full_every_minutes"),
            diff_every=_positive(mssql, "diff_every_minutes"),
            log_every=_positive(mssql, "log_every_minutes"),
            base_every=_positive(pg, "base_every_minutes"),
            archive_timeout_seconds=_positive(pg, "archive_timeout_seconds"),
            local_days=_positive(retention, "local_days"),
            offsite_days=_positive(retention, "offsite_days"),
            lock_mode=lock_mode,
            time_scale=_positive(drill, "time_scale"),
            duration_minutes=_positive(drill, "duration_minutes"),
            ci_lock_days=_positive(drill, "ci_lock_days"),
        )
    except (KeyError, TypeError) as exc:
        raise ConfigError(f"{path}: missing or malformed key {exc}") from exc
