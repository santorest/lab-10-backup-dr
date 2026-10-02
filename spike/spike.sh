#!/usr/bin/env bash
# Throwaway feasibility spike: native backups on both engines, Object Lock refusal, restores in clean containers.
set -euxo pipefail
cd "$(dirname "$0")"
c() { docker compose -f compose.yaml "$@"; }
sql() { c exec -T "$1" sh -c 'SQLCMDPASSWORD="$MSSQL_SA_PASSWORD" /opt/mssql-tools18/bin/sqlcmd -C -b -S localhost -U sa -h -1 -W -Q "$1"' sh "$2"; }
rm -rf ../out && mkdir -p ../out/backup-local/mssql ../out/backup-local/pg/wal ../out/backup-local/pg/base ../out/restore/mssql ../out/restore/pg/wal
chmod -R 777 ../out
c up -d mssql-primary mssql-restore pg-primary pg-restore minio
for i in $(seq 1 60); do sql mssql-primary "SELECT 1" && sql mssql-restore "SELECT 1" && break; sleep 3; done
for i in $(seq 1 60); do c exec -T pg-primary pg_isready -U postgres && break; sleep 2; done
for i in $(seq 1 30); do c run --rm -T mc ready admin && break; sleep 2; done
# Object Lock bucket, writer user with delete rights, no bypass
c run --rm -T mc mb --with-lock admin/backups
c run --rm -T mc retention set --default COMPLIANCE 1d admin/backups
c run --rm -T mc admin policy create admin backup-writer /policy/writer.json
c run --rm -T mc admin user add admin "$DRKIT_S3_KEY" "$DRKIT_S3_SECRET"
c run --rm -T mc admin policy attach admin backup-writer --user "$DRKIT_S3_KEY"
# SQL Server: full + log, readable by the host, restore in the clean container
sql mssql-primary "CREATE DATABASE appointments; ALTER DATABASE appointments SET RECOVERY FULL;"
sql mssql-primary "CREATE TABLE appointments.dbo.ticks(seq bigint IDENTITY PRIMARY KEY, written_at datetime2(3) NOT NULL DEFAULT SYSUTCDATETIME()); INSERT appointments.dbo.ticks DEFAULT VALUES;"
sql mssql-primary "BACKUP DATABASE appointments TO DISK = N'/backup/mssql/full.bak.part' WITH CHECKSUM, INIT, COMPRESSION"
sql mssql-primary "INSERT appointments.dbo.ticks DEFAULT VALUES; BACKUP LOG appointments TO DISK = N'/backup/mssql/log1.trn' WITH CHECKSUM, INIT, COMPRESSION"
ls -ln ../out/backup-local/mssql
c exec -T -u root mssql-primary sh -c 'chmod 644 /backup/mssql/* && mv /backup/mssql/full.bak.part /backup/mssql/full.bak'
cp ../out/backup-local/mssql/* ../out/restore/mssql/
sql mssql-restore "RESTORE FILELISTONLY FROM DISK = N'/restore/full.bak'"
sql mssql-restore "RESTORE DATABASE appointments FROM DISK = N'/restore/full.bak' WITH NORECOVERY, CHECKSUM, MOVE N'appointments' TO N'/var/opt/mssql/data/appointments.mdf', MOVE N'appointments_log' TO N'/var/opt/mssql/data/appointments_log.ldf'; RESTORE LOG appointments FROM DISK = N'/restore/log1.trn' WITH NORECOVERY, CHECKSUM; RESTORE DATABASE appointments WITH RECOVERY;"
sql mssql-restore "DBCC CHECKDB(appointments) WITH NO_INFOMSGS; SELECT COUNT(*) FROM appointments.dbo.ticks"
# Off-site: upload, then the writer tries to destroy the locked version
c run --rm -T mc cp /backup/mssql/full.bak writer/backups/mssql/full.bak
c run --rm -T mc ls --versions writer/backups/mssql/
vid=$(c run --rm -T mc ls --versions --json writer/backups/mssql/full.bak | sed -n 's/.*"versionId":"\([^"]*\)".*/\1/p' | head -1)
echo "version id: $vid"
if c run --rm -T mc rm --version-id "$vid" writer/backups/mssql/full.bak; then echo "SPIKE FAIL: locked version deleted"; exit 1; fi
c run --rm -T mc rm writer/backups/mssql/full.bak   # delete marker only
c run --rm -T mc ls --versions writer/backups/mssql/
# PostgreSQL: base backup + archived WAL, restore by replaying all WAL, no target
c exec -T pg-primary psql -U postgres -d billing -c "CREATE TABLE ticks(seq bigserial PRIMARY KEY, written_at timestamptz NOT NULL DEFAULT clock_timestamp()); INSERT INTO ticks DEFAULT VALUES;"
c exec -T pg-primary sh -c 'pg_basebackup -U postgres -D /tmp/base -Ft -z -X none --checkpoint=fast -v 2>&1' | tee ../out/basebackup.log
grep "write-ahead log start point" ../out/basebackup.log
c exec -T pg-primary sh -c 'tar -cf /backup/pg/base/base.tar -C /tmp/base . && chmod 644 /backup/pg/base/base.tar'
for i in 1 2 3 4 5; do c exec -T pg-primary psql -U postgres -d billing -c "INSERT INTO ticks DEFAULT VALUES"; sleep 1; done
sleep 3; ls -ln ../out/backup-local/pg/wal | head
cp ../out/backup-local/pg/base/base.tar ../out/restore/pg/ && cp ../out/backup-local/pg/wal/* ../out/restore/pg/wal/
c exec -T pg-restore sh -eu -c '
  d=/var/lib/postgresql/restored; rm -rf "$d"; mkdir -p "$d"; chmod 700 "$d"
  tar -xf /restore/base.tar -C "$d"; tar -xzf "$d/base.tar.gz" -C "$d"; rm "$d/base.tar.gz"; mkdir -p "$d/pg_wal"
  echo "restore_command = '"'"'gunzip -c /restore/wal/%f.gz > %p'"'"'" >> "$d/postgresql.auto.conf"
  touch "$d/recovery.signal"
  pg_ctl -D "$d" -w -t 300 -o "-c archive_mode=off" -l /tmp/restore.log start; tail -20 /tmp/restore.log'
for i in $(seq 1 60); do [ "$(c exec -T pg-restore psql -tAc 'SELECT pg_is_in_recovery()')" = f ] && break; sleep 2; done
c exec -T pg-restore psql -d billing -tAc "SELECT count(*), max(written_at) FROM ticks"
c exec -T pg-restore pg_amcheck --install-missing -d billing && echo "amcheck ok"
echo "SPIKE DONE"
