#!/usr/bin/env bash
# Recovery of appointments on the clean SQL Server, from the off-site tier only; verified before it counts.
set -euo pipefail
# shellcheck source=scripts/lib.sh
. scripts/lib.sh
system=appointments
dest=out/restore/mssql
t0=$(drkit mark --facts "$FACTS" --get t0)
if ! drkit fetch --policy "$POLICY" --system "$system" --before "$t0" --dest "$dest" \
   || ! sqlcmd_file mssql-restore /restore/restore.sql >/dev/null; then
  echo "$system: restore failed" >&2
  exit 2
fi
check=ok
sqlcmd mssql-restore "DBCC CHECKDB([$system]) WITH NO_INFOMSGS" >/dev/null || check=fail
IFS='|' read -r newest rows lo hi < <(sqlcmd_file mssql-restore /lab/verify.sql | tail -1 | tr -d '\r')
drkit mark --facts "out/drill/$system.facts.json" "$system.newest_row_at=$newest" "$system.rows=$rows" "$system.min_seq=$lo" "$system.max_seq=$hi" \
  "$system.check=$check" "$system.recovered_at=now"
echo "$system: recovered ($rows rows, newest $newest, check $check)"
