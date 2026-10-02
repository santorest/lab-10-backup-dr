# shellcheck shell=bash
# Shared helpers for the drill scripts (sourced from the repository root). Passwords stay inside the containers.
compose() { docker compose -f lab/compose.yaml "$@"; }
export POLICY=policy/dr-policy.yaml
export FACTS=out/drill/facts.json
export DRKIT_S3_ENDPOINT=${DRKIT_S3_ENDPOINT:-http://127.0.0.1:9000}
export DRKIT_S3_BUCKET=${DRKIT_S3_BUCKET:-backups}
# sqlcmd SERVICE "T-SQL"  |  sqlcmd_file SERVICE /path/in/container.sql
# shellcheck disable=SC2016  # $MSSQL_SA_PASSWORD and $1 expand inside the container
sqlcmd() { compose exec -T "$1" sh -c 'SQLCMDPASSWORD="$MSSQL_SA_PASSWORD" /opt/mssql-tools18/bin/sqlcmd -C -b -S localhost -U sa -h -1 -W -s "|" -Q "$1"' sh "$2"; }
# shellcheck disable=SC2016
sqlcmd_file() { compose exec -T "$1" sh -c 'SQLCMDPASSWORD="$MSSQL_SA_PASSWORD" /opt/mssql-tools18/bin/sqlcmd -C -b -S localhost -U sa -h -1 -W -s "|" -i "$1"' sh "$2"; }
psql_primary() { compose exec -T pg-primary psql -U postgres -d billing -v ON_ERROR_STOP=1 -tA "$@"; }
mark() { drkit mark --facts "$FACTS" "$@"; }
utc_stamp() { date -u +%Y%m%dT%H%M%S%3NZ; }
