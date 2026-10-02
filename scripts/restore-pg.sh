#!/usr/bin/env bash
# Recovery of billing on the clean PostgreSQL: base backup + every WAL segment shipped before T0, then promotion.
set -euo pipefail
# shellcheck source=scripts/lib.sh
. scripts/lib.sh
system=billing
dest=out/restore/pg
t0=$(drkit mark --facts "$FACTS" --get t0)
drkit fetch --policy "$POLICY" --system "$system" --before "$t0" --dest "$dest" \
  || { echo "$system: fetch failed" >&2; exit 2; }
# shellcheck disable=SC2016  # expanded inside the container
compose exec -T pg-restore sh -eu -c '
  d=/var/lib/postgresql/restored; rm -rf "$d"; mkdir -p "$d"; chmod 700 "$d"
  tar -xf /restore/base.tar -C "$d"; tar -xzf "$d/base.tar.gz" -C "$d"; rm "$d/base.tar.gz"; mkdir -p "$d/pg_wal"
  printf "%s\n" "restore_command = '"'"'gunzip -c /restore/wal/%f.gz > %p'"'"'" >> "$d/postgresql.auto.conf"
  touch "$d/recovery.signal"
  pg_ctl -D "$d" -w -t 600 -o "-c archive_mode=off" -l /tmp/restore.log start'
for _ in $(seq 1 150); do
  [ "$(compose exec -T pg-restore psql -tAc 'SELECT pg_is_in_recovery()')" = f ] && break
  sleep 2
done
check=ok
compose exec -T pg-restore pg_amcheck --install-missing -d billing >/dev/null || check=fail
IFS='|' read -r newest rows lo hi < <(compose exec -T pg-restore psql -d billing -tA -F '|' -f /lab/verify.sql)
# Replay stops at the first segment it cannot fetch and still promotes: record how far it got (checked by drkit report).
replayed=$(compose exec -T pg-restore psql -tAc "SELECT pg_walfile_name(pg_last_wal_replay_lsn())" | tr -d '\r')
mark "$system.newest_row_at=$newest" "$system.rows=$rows" "$system.min_seq=$lo" "$system.max_seq=$hi" \
  "$system.check=$check" "$system.last_replayed_wal=$replayed" "$system.recovered_at=now"
echo "$system: recovered ($rows rows, newest $newest, check $check, replayed to $replayed)"
