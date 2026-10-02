#!/usr/bin/env bash
# Schemas on both primaries, then one writer per database: one row per second until the attack stops it.
set -euo pipefail
# shellcheck source=scripts/lib.sh
. scripts/lib.sh
sqlcmd_file mssql-primary /lab/schema.sql >/dev/null
psql_primary -f /lab/schema.sql >/dev/null
# shellcheck disable=SC2016  # expanded inside the container
compose exec -d mssql-primary sh -c 'while [ ! -f /tmp/stop-writer ]; do SQLCMDPASSWORD="$MSSQL_SA_PASSWORD" /opt/mssql-tools18/bin/sqlcmd -C -S localhost -U sa -d appointments -Q "INSERT dbo.ticks DEFAULT VALUES" >/dev/null 2>&1; sleep 1; done'
compose exec -d pg-primary sh -c 'while [ ! -f /tmp/stop-writer ]; do psql -U postgres -d billing -c "INSERT INTO ticks DEFAULT VALUES" >/dev/null 2>&1; sleep 1; done'
