# Disaster recovery runbook — clinic databases

This runbook is exercised by the CI drill: the commands below are the ones `scripts/run-drill.sh` runs, so every
push to `main` and every weekly run proves that they still work. It covers recovery from backups; high availability
and virtual-machine backups are out of scope.

## 1. Purpose and scope

| System | Engine | What it does | RPO target | RTO target |
|---|---|---|---|---|
| `appointments` | SQL Server 2025 | bookings — the core system | ≤ 15 min | ≤ 30 min |
| `billing` | PostgreSQL 18 | invoices | ≤ 5 min | ≤ 60 min |

**RPO** (recovery point objective) is how much data the business accepts to lose, measured as time. **RTO**
(recovery time objective) is how long it may take, from the moment recovery is declared until the system is
verified and usable. Targets live in `policy/dr-policy.yaml`.

Backups have two tiers:

- **Local**: the backup share. SQL Server writes full (daily), differential (every 6 h) and log (every 15 min)
  backups; PostgreSQL writes a base backup (weekly) and archives its write-ahead log continuously. Fast to restore
  from, but reachable by an attacker who reaches the database servers.
- **Off-site**: an object-storage bucket with **Object Lock in compliance mode**. Every finished backup file is
  copied there with a retention date and recorded in a manifest with its object version and SHA-256. Until the
  retention date nobody — not the backup key, not an administrator — can delete or shorten the retention of a
  locked version.

## 2. Roles

| Role | Responsibilities |
|---|---|
| Incident commander | Declares the incident, owns the timeline and the decisions below, calls the others |
| DBA on call | Runs the restores and the verification, reports progress against the RTO |
| Security lead | Decides what is trustworthy, sets T0 (see D3), preserves evidence, rotates credentials |
| Communications | Informs staff, patients and, where required, the regulator; one voice |
| Business owner | Accepts the data loss, approves the return to service |

Escalation goes by role: DBA on call → incident commander → security lead and business owner. Contact details are
kept in the on-call tool, not in this document.

## 3. Decision points

- **D1 — Is the data reachable and trustworthy?** After ransomware, assume **no**: neither the database servers nor
  the backup share. Do not try to repair them in place.
- **D2 — Restore in place or to clean hosts?** Always to **clean hosts** after a compromise. The old servers are
  evidence and may still hold the attacker's tools.
- **D3 — Which restore point is the last safe one?** The newest backup **written before T0**, where T0 is the start
  of the malicious activity. The security lead sets T0; if the attacker was inside earlier than the encryption, T0
  moves back to the first malicious action, and so does the restore point. "The newest backup" is not automatically
  safe: anything written after T0 may be the attacker's. The tooling enforces this: it only reads object versions
  the store wrote before T0, fetches each backup by its version id and rejects any checksum mismatch.
- **D4 — When to return to service?** When the restore has passed verification (consistency check, row counts,
  continuity of the data), the business owner has accepted the measured data loss, and the credentials the attacker
  may have (database administrators, the backup writer key) have been rotated.

## 4. Procedure — SQL Server (`appointments`)

1. Record the time recovery is declared (`drkit mark --facts out/drill/facts.json declared_at=now` in the drill).
2. Fetch the restore chain from the off-site tier only, using the T0 from D3:
   ```bash
   drkit fetch --policy policy/dr-policy.yaml --system appointments --before <T0> --dest out/restore/mssql
   ```
   This selects the newest full backup, the newest differential after it and every log backup after that, checks
   that no log backup is missing, downloads each file by version id, verifies its SHA-256 and writes
   `restore.sql`. A gap or a checksum mismatch stops here with an error — never a shorter restore.
3. On the clean SQL Server, run the generated script (full and differential `WITH NORECOVERY`, every log
   `WITH NORECOVERY`, then `RESTORE DATABASE … WITH RECOVERY`):
   ```bash
   sqlcmd -C -b -S localhost -U sa -i /restore/restore.sql
   ```
4. Verify: `DBCC CHECKDB([appointments]) WITH NO_INFOMSGS` must be clean; `lab/mssql/verify.sql` returns the newest
   row's time, the row count and the first/last sequence numbers (rows must be contiguous).
5. Record the time verification passed (`recovered_at`). That is the end of the RTO.

## 5. Procedure — PostgreSQL (`billing`)

1. Fetch the base backup and the archived WAL written before T0:
   ```bash
   drkit fetch --policy policy/dr-policy.yaml --system billing --before <T0> --dest out/restore/pg
   ```
   The WAL segments must be contiguous from the segment the base backup starts at; a missing segment stops here.
2. On the clean PostgreSQL, as the `postgres` user: create an empty data directory, extract `base.tar` and the
   `base.tar.gz` inside it, add `restore_command = 'gunzip -c /restore/wal/%f.gz > %p'` to
   `postgresql.auto.conf`, create `recovery.signal`, and start the server with `pg_ctl -D <dir> -w start`.
   PostgreSQL replays every WAL segment it can fetch and then promotes itself (`SELECT pg_is_in_recovery()` returns
   `f`).
3. Verify: `pg_amcheck --install-missing -d billing` must be clean; `lab/pg/verify.sql` returns the newest row's
   time, the row count and the first/last sequence numbers. Recovery stops at the first segment it cannot fetch and
   promotes anyway, so also check how far it got: `SELECT pg_walfile_name(pg_last_wal_replay_lsn())` must name the
   last segment that was fetched (`drkit report` fails the restore otherwise).
4. Record `recovered_at`.

## 6. Measuring the result

- **Achieved RPO** = T0 − the time of the newest row present in the restored database: the data actually lost, read
  from the data, not from the backup schedule.
- **Achieved RTO** = `recovered_at` − `declared_at`, wall clock, including download, checksum, restore and checks.
- `drkit report` writes both against the targets, plus what the attacker tried on the off-site tier;
  `drkit gate` fails if a target is missed, a restore is not verified, or an off-site version was lost.

**Compressed time in the drill.** The drill plays the schedule with one policy minute per real second, so a
400-minute stretch (a full backup, a differential and 26 log backups) takes about seven minutes. The achieved RPO
is converted back to policy minutes to compare it with the target; the RTO is not compressed — restores take the
time they take.

## 7. After recovery

- Rotate the backup writer key and every database administrator credential.
- Keep the evidence: the attack log (`attack.json`), the pre-attack version list, the manifest used and the old
  servers' disks.
- Hold a hot wash within a week (template in `docs/tabletop-ransomware.md`) and update this runbook.
