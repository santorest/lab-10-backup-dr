#!/usr/bin/env bash
# Per-run secrets: database admin passwords, MinIO root and the backup writer's key. Nothing here is committed.
set -euo pipefail
rand() { openssl rand -hex 16; }
vars=(
  "MSSQL_SA_PASSWORD=Lab10-$(rand)-Aa1"
  "PG_PASSWORD=$(rand)"
  "MINIO_ROOT_PASSWORD=$(rand)"
  "DRKIT_S3_KEY=backup-writer"
  "DRKIT_S3_SECRET=$(rand)"
)
for kv in "${vars[@]}"; do
  if [ -n "${GITHUB_ENV:-}" ]; then
    echo "::add-mask::${kv#*=}"
    echo "$kv" >> "$GITHUB_ENV"
  else
    echo "export ${kv%%=*}='${kv#*=}'"
  fi
done
