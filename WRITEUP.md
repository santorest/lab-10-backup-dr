---
title: "Backup & Disaster Recovery with a Ransomware Drill"
id: "lab-10-backup-dr"
category: "Database Security"
type: "Lab"
status: "in progress"
date: "2026-10-02"
time_to_reproduce: "One CI run (fork, enable Actions, run CI); the measured duration is in the Results"
skills: [SQL Server, PostgreSQL, MinIO, S3 Object Lock, Python, boto3, Docker, GitHub Actions]
frameworks: [CIS Controls v8 (11.1, 11.2, 11.3, 11.4, 11.5, 17.4), MITRE ATT&CK (T1486, T1490, T1485)]
repo: "https://github.com/santorest/lab-10-backup-dr"
bundle: "Published on the portfolio site with its SHA-256 checksum"
---

# Backup & Disaster Recovery with a Ransomware Drill

> **TL;DR:** A SQL Server and a PostgreSQL database are backed up to a local share and to an object-storage bucket
> with Object Lock. A scripted ransomware drops both databases, wipes the share and uses the stolen backup key against
> the bucket; both databases are then restored from the immutable copy alone to clean hosts, verified, and the
> achieved RPO and RTO are measured against written targets. A runbook and a tabletop exercise complete it.
> Everything runs in GitHub Actions against containers. **The CI runs are real; the data is synthetic.**

| | |
|---|---|
| **Role played** | Database / security engineer responsible for recoverability of a small clinic's databases |
| **Environment** | Public GitHub repository, GitHub-hosted Ubuntu runners, SQL Server 2025 and PostgreSQL 18 containers, MinIO (Chainguard build) |
| **Tools** | Python 3.12, boto3, native SQL Server backups, `pg_basebackup` + WAL archiving, `sqlcmd`, `pg_amcheck`, pytest, ruff, mypy, shellcheck, gitleaks |
| **Deliverable** | Backup shipping and restore toolkit (`drkit`), ransomware drill, measured RPO/RTO with a gate, DR runbook and tabletop (EN/ES), CI, branch ruleset, demo PRs |

---

## 1. Problem

Ransomware operators go after the backups first: a backup that the compromised servers can reach, or that the
stolen backup credentials can delete, is gone when it is needed. "We have backups" is not a recovery plan; a
recovery plan says how much data and how much time the business can lose, keeps at least one copy that the attacker
cannot destroy, and proves — regularly, with numbers — that the databases come back within those limits.

## 2. Design

- **Two tiers.** Native backups land on a local share (fast to restore from, but reachable). Every finished file is
  shipped to an off-site bucket with **Object Lock in compliance mode**: until the retention date no one can delete a
  locked version or shorten its retention — not the backup key, not an administrator.
- **The key is not the protection.** The backup writer key is allowed to delete objects and versions. If deletion
  were blocked only by permissions, whoever steals a more privileged key could still do it; the lock does not
  depend on who asks.
- **Manifest with versions.** Every shipped file is recorded with its object version and SHA-256; the manifest is
  shipped and locked too. Recovery fetches each file by version, so an attacker's overwrite (a newer version) or
  delete marker changes nothing.
- **The last safe point.** Recovery only reads object versions the store wrote **before T0**, the start of the
  attack. Anything later may be the attacker's.
- **Compressed time.** The schedule runs at one policy minute per real second. RPO, which depends on the backup
  interval, is measured in real seconds and converted to policy minutes for the comparison; RTO, which depends on
  the restore work, is not compressed.

## 3. The drill

1. Two primaries with a writer each (one row per second: the ground truth for data loss).
2. SQL Server: full at policy minute 0, log backups every 15, a differential at 360. PostgreSQL: a base backup and
   continuous WAL archiving. `drkit ship` copies each finished file to the bucket.
3. At T0 (policy minute 400) the ransomware stops the backup agent, drops both databases, wipes the local share and,
   with the stolen key, tries on every object version: shorten retention, delete the version, overwrite, delete.
4. `drkit fetch` builds each restore chain from the bucket alone — newest full, newest later differential and every
  later log (a missing log number is an error); base backup and contiguous WAL from its start segment (a missing
  segment is an error) — downloads by version id and checks every SHA-256.
5. Restores on clean containers, then `DBCC CHECKDB` / `pg_amcheck` and a check that the restored rows are
   contiguous.

## 4. Measurement

- **Achieved RPO** = T0 − the newest row in the restored database: data actually lost, read from the data.
- **Achieved RTO** = from "recovery declared" to "restore verified", wall clock.
- **Gate**: fails on a missed target, a restore that is not verified, or any original version lost off-site.

## 5. Runbook and tabletop

The runbook (`docs/runbook.md`) gives the roles, four decision points — is the data trustworthy, restore in place
or to clean hosts, which restore point is the last *safe* one, when to return to service — and the per-engine
procedures with the commands the drill runs, so CI exercises the runbook on every run. The tabletop
(`docs/tabletop-ransomware.md`) is a written exercise with timed injects (the backup share encrypted too, extortion,
pressure to restore the newest backup) and the expected decisions; it has not been run with people.

## 6. Pipeline

| Job | What it proves |
|---|---|
| `lint` | ruff, mypy (strict), shellcheck |
| `unit` | the pure modules on fixtures and a fake versioned store with Object Lock: chain gaps, stale differential, post-T0 versions, checksum mismatch, attack and survival, RPO/RTO edges, report escaping; coverage gate 90 % |
| `drill` | the whole cycle on both engines; artifacts: report, attack log, manifests, restore chains, timings |
| `secrets` | gitleaks over the full history |

It runs on every pull request, on pushes to `main`, weekly and on demand. A ruleset on `main` requires a pull
request and all four jobs.

## 7. Results

Results are added from the first CI runs.

## 8. Lessons

- **The tool you planned to parse changed.** PostgreSQL 18's `pg_basebackup -v` with `-X none` no longer prints
  the WAL start point; the backup's own `backup_manifest` records it (`WAL-Ranges` → `Start-LSN`), so the drill
  reads it from there.
- **Files written by one service are not readable by the next.** SQL Server writes its backups as `0660` owned by
  its own user, and PostgreSQL archives WAL as `0600`; the shipper on the host could read neither. Each backup is
  written to a `.part` file, made readable, then renamed, so the shipper never sees a half-written or unreadable
  file.
- **The image you planned on can disappear.** MinIO's own community container images are no longer published; the
  lab uses a maintained build (Chainguard) pinned by digest.
- **Object Lock behaves as documented, and that is worth proving.** With a key that may delete versions, MinIO
  refused every delete of a locked version ("WORM protected and cannot be overwritten"); a plain delete only added a
  delete marker on top of the intact original.

## 9. Limits

- Containers and synthetic data; small databases, so the absolute RTO minutes do not transfer to production.
- Compressed time for the backup schedule (RPO converted back to policy minutes; RTO not compressed).
- MinIO stands in for cloud immutable storage (S3 Object Lock, Azure immutable blobs).
- The tabletop is written, not run with people.
- Not covered: backup encryption key management, VM and file-server backups, high availability.

## 10. Reproduce it

Fork the repository and enable Actions: every push runs the drill. Locally (Linux, macOS or WSL with Docker), follow
the README's quick start: `bash scripts/run-drill.sh` writes `out/report.html` and `out/results.json`.

## 11. Mapping

| Framework | Items |
|---|---|
| CIS Controls v8 | 11.1 establish and maintain a data recovery process, 11.2 perform automated backups, 11.3 protect recovery data, 11.4 establish and maintain an isolated instance of recovery data, 11.5 test data recovery, 17.4 establish and maintain an incident response process |
| MITRE ATT&CK | T1486 Data Encrypted for Impact, T1490 Inhibit System Recovery (attacks on the backups), T1485 Data Destruction — what the drill simulates and recovers from |
