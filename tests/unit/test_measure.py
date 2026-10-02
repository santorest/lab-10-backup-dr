from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from drkit.measure import Verification, measure
from drkit.models import System

APPT = System("appointments", "mssql", "appointments", 15, 30)
T0 = datetime(2026, 10, 2, 12, 0, tzinfo=UTC)
DECLARED = T0 + timedelta(seconds=20)


def good(newest_seconds_before: float = 10) -> Verification:
    return Verification(T0 - timedelta(seconds=newest_seconds_before), 391, 1, 391, True)


def test_rpo_is_scaled_and_rto_is_wall_clock():
    o = measure(APPT, 60, T0, DECLARED, DECLARED + timedelta(minutes=3), good(10))
    assert o.verified and o.problems == ()
    assert o.rpo_real_seconds == 10 and o.rpo_policy_minutes == 10 and o.rpo_ok
    assert o.rto_seconds == 180 and o.rto_ok


def test_rpo_exactly_at_the_target_passes_and_just_over_fails():
    assert measure(APPT, 60, T0, DECLARED, DECLARED, good(15)).rpo_ok
    assert not measure(APPT, 60, T0, DECLARED, DECLARED, good(15.5)).rpo_ok


def test_rto_over_the_target_fails():
    assert not measure(APPT, 60, T0, DECLARED, DECLARED + timedelta(minutes=31), good()).rto_ok


@pytest.mark.parametrize(
    ("recovered", "verification", "problem"),
    [
        (None, good(), "restore did not finish"),
        (DECLARED, None, "not verified"),
        (DECLARED, Verification(T0, 1, 1, 1, False), "consistency check failed"),
        (DECLARED, Verification(T0 - timedelta(seconds=5), 10, 1, 11, True), "not contiguous"),
        (DECLARED, Verification(None, 0, None, None, True), "no rows"),
        (DECLARED, Verification(T0 + timedelta(seconds=1), 5, 1, 5, True), "newer than T0"),
    ],
)
def test_nothing_good_is_measured_from_a_bad_restore(recovered, verification, problem: str):
    o = measure(APPT, 60, T0, DECLARED, recovered, verification)
    assert not o.verified and any(problem in p for p in o.problems)
    assert not (o.rpo_ok and o.rto_ok)


def test_replay_that_stopped_early_is_not_verified():
    v = Verification(T0 - timedelta(seconds=2), 10, 1, 10, True, replay_complete=False)
    o = measure(APPT, 60, T0, DECLARED, DECLARED, v)
    assert not o.verified and any("replay stopped before the end" in p for p in o.problems)
