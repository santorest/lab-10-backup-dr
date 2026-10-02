from __future__ import annotations

from pathlib import Path

from drkit.models import load_policy
from drkit.schedule import timeline

POLICY = Path(__file__).resolve().parents[2] / "policy" / "dr-policy.yaml"


def test_repository_timeline():
    steps = timeline(load_policy(POLICY))
    as_tuples = [(s.minute, s.system, s.kind) for s in steps]
    assert as_tuples[:2] == [(0, "appointments", "full"), (0, "billing", "base")]
    logs = [m for m, _, k in as_tuples if k == "log"]
    assert logs == list(range(15, 400, 15)) and len(logs) == 26
    assert (360, "appointments", "diff") in as_tuples
    assert as_tuples.index((360, "appointments", "diff")) < as_tuples.index((360, "appointments", "log"))
    assert max(m for m, _, _ in as_tuples) == 390


def test_hourly_logs_leave_a_40_minute_gap_before_the_attack():
    policy = load_policy(POLICY)
    hourly = type(policy)(**{**policy.__dict__, "log_every": 60})
    logs = [s.minute for s in timeline(hourly) if s.kind == "log"]
    assert logs[-1] == 360 and hourly.duration_minutes - logs[-1] == 40
