from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from drkit import cli
from drkit.models import iso
from tests.unit.fakes import FakeOffsite

POLICY = str(Path(__file__).resolve().parents[2] / "policy" / "dr-policy.yaml")


@pytest.fixture
def store(monkeypatch: pytest.MonkeyPatch) -> FakeOffsite:
    fake = FakeOffsite(clock=lambda: datetime(2026, 10, 2, 11, 0, tzinfo=UTC))
    monkeypatch.setattr(cli, "make_offsite", lambda lock_mode: fake)
    return fake


def test_timeline_and_settings(capsys: pytest.CaptureFixture[str]):
    assert cli.main(["timeline", "--policy", POLICY]) == 0
    lines = capsys.readouterr().out.splitlines()
    assert lines[0] == "0 appointments full" and lines[-1] == "390 appointments log"
    for name, value in [("archive_timeout_real", "1"), ("attack_minute", "400"), ("lock_mode", "COMPLIANCE")]:
        assert cli.main(["setting", "--policy", POLICY, name]) == 0
        assert capsys.readouterr().out.strip() == value


def test_unknown_setting_exits_2(capsys: pytest.CaptureFixture[str]):
    assert cli.main(["setting", "--policy", POLICY, "colour"]) == 2
    assert "unknown setting" in capsys.readouterr().err


def test_mark_and_get(tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    facts = tmp_path / "facts.json"
    assert cli.main(["mark", "--facts", str(facts), "t0=now", "appointments.rows=5"]) == 0
    assert cli.main(["mark", "--facts", str(facts), "--get", "appointments.rows"]) == 0
    assert capsys.readouterr().out.strip() == "5"
    assert json.loads(facts.read_text())["t0"].endswith("Z")


def test_meta_ship_attack_survival(tmp_path: Path, store: FakeOffsite):
    local = tmp_path / "local"
    (local / "mssql/full").mkdir(parents=True)
    (local / "pg/wal").mkdir(parents=True)
    bak = local / "mssql/full/f.bak"
    bak.write_bytes(b"F")
    assert cli.main(["meta", "--file", str(bak), "--system", "appointments", "--kind", "full", "--log-no", "0"]) == 0
    assert cli.main(["ship", "--policy", POLICY, "--local", str(local), "--lock-days", "1"]) == 0
    before = tmp_path / "before.json"
    assert cli.main(["versions", "--out", str(before)]) == 0
    assert cli.main(["attack-offsite", "--out", str(tmp_path / "attack.json")]) == 0
    assert cli.main(["survival", "--before", str(before), "--out", str(tmp_path / "lost.json")]) == 0
    assert json.loads((tmp_path / "lost.json").read_text()) == []
    assert json.loads((tmp_path / "attack.json").read_text())


def test_ship_watch_stops_at_the_stop_file(tmp_path: Path, store: FakeOffsite):
    local = tmp_path / "local"
    local.mkdir()
    stop = tmp_path / "stop"
    stop.touch()
    assert cli.main(["ship", "--policy", POLICY, "--local", str(local), "--lock-days", "1", "--watch", "0.01",
                     "--stop-file", str(stop)]) == 0  # fmt: skip


def test_fetch_command(tmp_path: Path, store: FakeOffsite, capsys: pytest.CaptureFixture[str]):
    local = tmp_path / "local"
    (local / "mssql/full").mkdir(parents=True)
    bak = local / "mssql/full/f.bak"
    bak.write_bytes(b"F")
    cli.main(["meta", "--file", str(bak), "--system", "appointments", "--kind", "full", "--log-no", "0"])
    cli.main(["ship", "--policy", POLICY, "--local", str(local), "--lock-days", "1"])
    before = iso(datetime.now(UTC) + timedelta(days=3650))
    args = ["fetch", "--policy", POLICY, "--system", "appointments", "--before", before, "--dest", str(tmp_path / "r")]
    assert cli.main(args) == 0
    assert "1 files fetched" in capsys.readouterr().out and (tmp_path / "r" / "f.bak").read_bytes() == b"F"


def test_report_and_gate(tmp_path: Path):
    t0 = datetime(2026, 10, 2, 12, 0, tzinfo=UTC)
    facts = {"t0": iso(t0), "declared_at": iso(t0 + timedelta(seconds=10))}
    for system, newest in (("appointments", 10), ("billing", 2)):
        facts |= {
            f"{system}.recovered_at": iso(t0 + timedelta(minutes=2)),
            f"{system}.newest_row_at": iso(t0 - timedelta(seconds=newest)),
            f"{system}.rows": "100",
            f"{system}.min_seq": "1",
            f"{system}.max_seq": "100",
            f"{system}.check": "ok",
        }
    (tmp_path / "facts.json").write_text(json.dumps(facts))
    (tmp_path / "attack.json").write_text("[]")
    (tmp_path / "lost.json").write_text("[]")
    restore = tmp_path / "restore"
    (restore / "mssql").mkdir(parents=True)
    out = tmp_path / "out"
    args = ["report", "--policy", POLICY, "--facts", str(tmp_path / "facts.json"),
            "--attack", str(tmp_path / "attack.json"), "--survival", str(tmp_path / "lost.json"),
            "--restore-dir", str(restore), "--out-dir", str(out)]  # fmt: skip
    assert cli.main(args) == 0
    assert cli.main(["gate", "--results", str(out / "results.json")]) == 0
    assert (out / "summary.md").exists() and (out / "report.html").exists()


def test_gate_fails_with_exit_1(tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    results = {
        "outcomes": [
            {"system": "appointments", "verified": True, "rpo_ok": False, "rto_ok": True,
             "rpo_policy_minutes": 40.0, "rpo_target_minutes": 15, "rto_seconds": 60,
             "rto_target_minutes": 30, "problems": []}
        ],
        "attack": {"accepted": [], "lost": []},
    }  # fmt: skip
    path = tmp_path / "r.json"
    path.write_text(json.dumps(results))
    assert cli.main(["gate", "--results", str(path)]) == 1
    assert "RPO 40.0 min > target 15 min" in capsys.readouterr().out


def test_bad_policy_exits_2(tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    assert cli.main(["timeline", "--policy", str(tmp_path / "missing.yaml")]) == 2
    assert "error:" in capsys.readouterr().err
