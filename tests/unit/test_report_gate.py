from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

from drkit.attack import Attempt, attack, survival
from drkit.gate import failures
from drkit.measure import Outcome, Verification, measure
from drkit.models import System
from drkit.offsite import Version
from drkit.report import render_html, render_markdown, results_json
from tests.unit.fakes import FakeOffsite

T0 = datetime(2026, 10, 2, 12, 0, tzinfo=UTC)
APPT = System("appointments", "mssql", "appointments", 15, 30)
BILL = System("billing", "postgres", "billing", 5, 60)
META = {"t0": "2026-10-02T12:00:00Z", "run": "local"}


def verified(seconds: float) -> Verification:
    return Verification(T0 - timedelta(seconds=seconds), 100, 1, 100, True)


def outcomes(rpo_appt: float = 10) -> list[Outcome]:
    return [
        measure(APPT, 60, T0, T0, T0 + timedelta(minutes=2), verified(rpo_appt)),
        measure(BILL, 60, T0, T0, T0 + timedelta(minutes=1), verified(2)),
    ]


ATTEMPTS = [Attempt("delete-version", "mssql/full/<f>.bak", "v1", True, "AccessDenied: WORM | locked")]
BACKUPS = {"appointments": {"full": (1, 2048), "log": (26, 9000)}, "billing": {"base": (1, 4096), "wal": (400, 80000)}}


def test_clean_run_has_no_failures():
    data = json.loads(results_json(outcomes(), ATTEMPTS, [], BACKUPS, META))
    assert failures(data) == []
    assert data["outcomes"][0]["rpo_policy_minutes"] == 10 and data["attack"]["refused"] == 1


def test_missed_rpo_and_lost_versions_fail_the_gate():
    lost = [Version("mssql/full/f.bak", "v1", T0, 10, False)]
    data = json.loads(results_json(outcomes(rpo_appt=40), ATTEMPTS, lost, BACKUPS, META))
    msgs = failures(data)
    assert any("appointments: RPO 40.0 min > target 15 min" in m for m in msgs)
    assert any("1 backup version" in m for m in msgs)


def test_unverified_restore_fails_the_gate():
    bad = [measure(APPT, 60, T0, T0, None, None), outcomes()[1]]
    msgs = failures(json.loads(results_json(bad, [], [], BACKUPS, META)))
    assert any("appointments: not recovered" in m for m in msgs)


def test_reports_escape_untrusted_text():
    html = render_html(outcomes(), ATTEMPTS, [], BACKUPS, META)
    md = render_markdown(outcomes(), ATTEMPTS, [], BACKUPS, META)
    assert "<f>" not in html and "&lt;f&gt;" in html
    assert "WORM \\| locked" in md and "| appointments |" in md


def test_short_rto_is_shown_in_seconds_too():
    fast = [measure(APPT, 60, T0, T0, T0 + timedelta(seconds=2.1), verified(10))]
    md = render_markdown(fast, [], [], BACKUPS, META)
    assert "0.0 min (2.1 s)" in md


class _WeakLock(FakeOffsite):
    """A store whose lock lets the retention be shortened (e.g. a bypass permission): nothing is lost yet."""

    def shorten_retention(self, key: str, version_id: str, until: datetime) -> None:
        for obj in self.objects.get(key, []):
            if obj.version_id == version_id:
                obj.retain_until = until


def test_accepted_retention_shortening_fails_the_gate():
    store = _WeakLock(clock=lambda: T0)
    store.put("mssql/full/f.bak", b"FULL", T0 + timedelta(days=1))
    before = store.versions("")
    attempts = attack(store, T0)
    lost = survival(before, store.versions(""))
    assert lost == []  # every version still exists one minute before it becomes deletable
    msgs = failures(json.loads(results_json(outcomes(), attempts, lost, BACKUPS, META)))
    assert any("shorten-retention" in m and "accepted" in m for m in msgs)
    md = render_markdown(outcomes(), attempts, lost, BACKUPS, META)
    assert "not destructive unless listed as lost" not in md
