from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from drkit.models import ConfigError, iso, load_policy, parse_utc

ROOT = Path(__file__).resolve().parents[2]
POLICY = ROOT / "policy" / "dr-policy.yaml"


def test_repository_policy_loads():
    p = load_policy(POLICY)
    assert [s.name for s in p.systems] == ["appointments", "billing"]
    assert p.system("appointments").rpo_minutes == 15 and p.system("billing").rto_minutes == 60
    assert (p.full_every, p.diff_every, p.log_every, p.base_every) == (1440, 360, 15, 10080)
    assert (p.lock_mode, p.time_scale, p.duration_minutes, p.ci_lock_days) == ("COMPLIANCE", 60, 400, 1)
    assert p.engine_system("postgres").name == "billing"


@pytest.mark.parametrize(
    ("old", "new", "message"),
    [
        ("engine: mssql,", "engine: oracle,", "engine"),
        ("rpo_minutes: 15", "rpo_minutes: 0", "rpo_minutes"),
        ("log_every_minutes: 15", "log_every_minutes: -1", "log_every_minutes"),
        ("offsite_lock_mode: COMPLIANCE", "offsite_lock_mode: GOVERNANCE", "offsite_lock_mode"),
        ("time_scale: 60", "time_scale: x", "time_scale"),
        ("{name: billing,", "{name: appointments,", "duplicate"),
    ],
)
def test_policy_rejects_bad_values(tmp_path: Path, old: str, new: str, message: str):
    text = POLICY.read_text(encoding="utf-8")
    assert old in text
    path = tmp_path / "p.yaml"
    path.write_text(text.replace(old, new, 1), encoding="utf-8")
    with pytest.raises(ConfigError, match=message):
        load_policy(path)


def test_policy_needs_one_system_per_engine(tmp_path: Path):
    text = POLICY.read_text(encoding="utf-8").replace("engine: postgres", "engine: mssql")
    path = tmp_path / "p.yaml"
    path.write_text(text, encoding="utf-8")
    with pytest.raises(ConfigError, match="one system per engine"):
        load_policy(path)


def test_missing_file_is_a_config_error(tmp_path: Path):
    with pytest.raises(ConfigError, match="cannot read"):
        load_policy(tmp_path / "nope.yaml")


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("2026-10-02T10:00:00Z", datetime(2026, 10, 2, 10, 0, tzinfo=UTC)),
        ("2026-10-02T10:00:00.1234567Z", datetime(2026, 10, 2, 10, 0, 0, 123456, tzinfo=UTC)),
        ("2026-10-02T12:00:00+02:00", datetime(2026, 10, 2, 10, 0, tzinfo=UTC)),
    ],
)
def test_parse_utc(text: str, expected: datetime):
    assert parse_utc(text) == expected


@pytest.mark.parametrize("text", ["2026-10-02T10:00:00", "yesterday", ""])
def test_parse_utc_rejects_naive_or_garbage(text: str):
    with pytest.raises(ConfigError):
        parse_utc(text)


def test_iso_round_trip():
    t = datetime(2026, 10, 2, 10, 0, 0, 5000, tzinfo=UTC)
    assert iso(t) == "2026-10-02T10:00:00.005000Z" and parse_utc(iso(t)) == t
