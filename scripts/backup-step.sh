#!/usr/bin/env bash
# One scheduled backup: written to a .part file, made readable, renamed, then described in a sidecar for the shipper.
set -euo pipefail
# shellcheck source=scripts/lib.sh
. scripts/lib.sh
system=$1 kind=$2
stamp=$(utc_stamp)
case "$kind" in
  full|diff|log)
    ext=bak; [ "$kind" = log ] && ext=trn
    name="mssql/$kind/${system}_${kind}_${stamp}.$ext"
    case "$kind" in
      full) opts="CHECKSUM, INIT, COMPRESSION"; what=DATABASE ;;
      diff) opts="DIFFERENTIAL, CHECKSUM, INIT, COMPRESSION"; what=DATABASE ;;
      *) opts="CHECKSUM, INIT, COMPRESSION"; what=LOG ;;
    esac
    sqlcmd mssql-primary "BACKUP $what [$system] TO DISK = N'/backup/$name.part' WITH $opts" >/dev/null
    compose exec -T -u root mssql-primary sh -c "chmod 644 '/backup/$name.part' && mv '/backup/$name.part' '/backup/$name'"
    counter=out/drill/$system.log_no
    n=$(cat "$counter" 2>/dev/null || echo 0)
    if [ "$kind" = log ]; then n=$((n + 1)); echo "$n" > "$counter"; fi
    drkit meta --file "out/backup-local/$name" --system "$system" --kind "$kind" --log-no "$n"
    ;;
  base)
    label="${system}_base_${stamp}"
    compose exec -T pg-primary pg_basebackup -U postgres -D "/tmp/$label" -Ft -z -X none --checkpoint=fast >/dev/null
    # PostgreSQL 18 does not print the start point with -X none; the backup manifest records it (WAL-Ranges).
    lsn=$(compose exec -T pg-primary grep -o '"Start-LSN": *"[0-9A-F/]*"' "/tmp/$label/backup_manifest" \
      | sed 's/.*"\([0-9A-F]*\/[0-9A-F]*\)"/\1/')
    [ -n "$lsn" ] || { echo "no Start-LSN in the base backup's manifest" >&2; exit 2; }
    wal=$(psql_primary -c "SELECT pg_walfile_name('$lsn')")
    compose exec -T pg-primary sh -c "tar -cf /backup/pg/base/$label.tar.part -C /tmp/$label . && chmod 644 /backup/pg/base/$label.tar.part && mv /backup/pg/base/$label.tar.part /backup/pg/base/$label.tar && rm -rf /tmp/$label"
    drkit meta --file "out/backup-local/pg/base/$label.tar" --system "$system" --kind base --wal-start "$wal"
    ;;
  *) echo "unknown backup kind $kind" >&2; exit 2 ;;
esac
echo "$(date -u +%H:%M:%S) $system $kind"
