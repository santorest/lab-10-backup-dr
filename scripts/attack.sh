#!/usr/bin/env bash
# The ransomware, at T0 (the backup agent is already stopped): stop the applications, destroy both databases and the
# local backup share, then use the stolen backup key against the off-site tier.
set -euo pipefail
# shellcheck source=scripts/lib.sh
. scripts/lib.sh
drkit versions --out out/drill/versions-before.json
mark t0=now
compose exec -T mssql-primary touch /tmp/stop-writer
compose exec -T pg-primary touch /tmp/stop-writer
sleep 2
sqlcmd mssql-primary "ALTER DATABASE [appointments] SET SINGLE_USER WITH ROLLBACK IMMEDIATE; DROP DATABASE [appointments];" >/dev/null
compose exec -T pg-primary psql -U postgres -d postgres -c "DROP DATABASE billing WITH (FORCE)" >/dev/null
compose stop mssql-primary pg-primary
find out/backup-local -mindepth 1 -delete
echo "Your files are encrypted. Pay to recover them." > out/backup-local/README-RANSOM.txt
drkit attack-offsite --out out/drill/attack.json
drkit survival --before out/drill/versions-before.json --out out/drill/survival.json
mark declared_at=now
