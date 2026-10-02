#!/usr/bin/env bash
# The whole drill: primaries + MinIO -> compressed backup schedule shipped to the Object Lock bucket -> ransomware at
# T0 -> restore from the off-site copy alone to clean containers -> verify -> RPO/RTO report -> gate.
# Same script in CI and locally (Docker + `pip install -r requirements.txt && pip install --no-deps -e .`;
# run `eval "$(bash scripts/make-secrets.sh)"` first).
set -euo pipefail
: "${MSSQL_SA_PASSWORD:?run scripts/make-secrets.sh first}"
cd "$(dirname "$0")/.."
# shellcheck source=scripts/lib.sh
. scripts/lib.sh
rm -rf out/backup-local out/restore out/drill
mkdir -p out/backup-local/mssql/full out/backup-local/mssql/diff out/backup-local/mssql/log \
         out/backup-local/pg/base out/backup-local/pg/wal out/restore/mssql out/restore/pg out/drill
chmod -R 777 out/backup-local out/restore
PG_ARCHIVE_TIMEOUT=$(drkit setting --policy "$POLICY" archive_timeout_real)
export PG_ARCHIVE_TIMEOUT
compose up -d --wait mssql-primary mssql-restore pg-primary pg-restore minio
lock_days=$(drkit setting --policy "$POLICY" ci_lock_days)
bash scripts/setup-offsite.sh "$(drkit setting --policy "$POLICY" lock_mode)" "$lock_days"
bash scripts/seed.sh
drkit ship --policy "$POLICY" --local out/backup-local --lock-days "$lock_days" \
  --watch 1 --stop-file out/drill/stop-ship > out/drill/ship.log 2>&1 &
ship_pid=$!
scale=$(drkit setting --policy "$POLICY" time_scale)
start_ms=$(date +%s%3N)
wait_until() {  # policy minute -> real time since start
  local target now
  target=$((start_ms + $1 * 60000 / scale))
  now=$(date +%s%3N)
  if [ "$target" -gt "$now" ]; then
    sleep "$(printf '%d.%03d' $(((target - now) / 1000)) $(((target - now) % 1000)))"
  fi
}
while read -r minute system kind; do
  wait_until "$minute"
  bash scripts/backup-step.sh "$system" "$kind" < /dev/null   # docker compose exec would eat the timeline
done < <(drkit timeline --policy "$POLICY")
wait_until "$(drkit setting --policy "$POLICY" attack_minute)"
touch out/drill/stop-ship            # the attacker stops the backup agent first
wait "$ship_pid"
bash scripts/attack.sh
status=0
bash scripts/restore-mssql.sh & mssql_pid=$!
bash scripts/restore-pg.sh & pg_pid=$!
wait "$mssql_pid" || status=2
wait "$pg_pid" || status=2
drkit report --policy "$POLICY" --facts "$FACTS" --attack out/drill/attack.json --survival out/drill/survival.json \
  --restore-dir out/restore --out-dir out
cp out/backup-local/README-RANSOM.txt out/drill/ 2>/dev/null || true
drkit gate --results out/results.json || status=$?
exit "$status"
