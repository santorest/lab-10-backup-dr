# Tabletop exercise — ransomware on the database server

> A written exercise; it has not been run with people. The CI drill is its technical half: it performs the attack
> and the recovery described here and measures them.

## Scenario

Friday, 22:40. The clinic's booking system stops answering. The DBA on call finds the `appointments` database gone
from the SQL Server and a file called `README-RANSOM.txt` on the backup share. The billing system's PostgreSQL
server is unreachable too.

## Objectives

1. Decide quickly that the environment is not trustworthy and recover to clean hosts.
2. Pick the last *safe* restore point instead of the newest backup.
3. Recover within the targets: `appointments` RPO ≤ 15 min, RTO ≤ 30 min; `billing` RPO ≤ 5 min, RTO ≤ 60 min.
4. Keep communications consistent and decisions recorded.

## Participants

Facilitator, incident commander, DBA on call, security lead, communications, business owner (roles as in
`docs/runbook.md`).

## Injects

| Time | Inject | Expected decision | Runbook |
|---|---|---|---|
| 22:40 | Detection: database dropped, ransom note on the backup share | Declare a major incident; the incident commander takes the timeline; nobody touches the servers beyond isolating them | §2, D1 |
| 23:00 | The backup share is encrypted too; local backups are gone | Recovery will come from the off-site tier; confirm its versions are intact (refused deletes in the storage logs) | §1, D1 |
| 23:20 | Extortion e-mail: pay or patient data will be published | Security lead and business owner take this separately from recovery; communications prepares the notification; no contact with the attacker without legal advice; no payment decision under time pressure | §2, §7 |
| 23:45 | The business wants the newest backup restored "now" | The security lead sets T0 from the evidence; restore the newest backup **written before T0**, to clean hosts | D2, D3 |
| 01:30 | Restores finished — reconnect the applications? | Only after verification passed, the business owner accepted the measured data loss and credentials were rotated | D4, §6, §7 |

## Facilitator notes

What good looks like: isolation before investigation; one decision log; recovery to clean hosts; T0 set by the
security lead, not by whoever is most impatient; RPO and RTO measured, not estimated; credentials rotated before
reconnecting.

Common mistakes to probe:

- Restoring onto the compromised server "because it is faster".
- Trusting the newest backup without asking when the attacker got in.
- Assuming the backup share is safe because it is "a different server".
- Treating payment as a recovery option; it does not restore trust in the systems.
- Several people talking to staff and patients with different messages.

## Hot wash (template)

| Question | Notes | Owner | Due |
|---|---|---|---|
| What went well? | | | |
| What slowed us down? | | | |
| Which decision was hardest, and what information was missing? | | | |
| What changes in the runbook? | | | |
| What changes in the backups or their protection? | | | |
