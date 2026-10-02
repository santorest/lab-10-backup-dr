#!/usr/bin/env bash
# The off-site bucket: with Object Lock (compliance) or, for the demo of the mistake, without. The writer key may
# delete objects and versions, so only the lock can stop someone who holds it.
set -euo pipefail
# shellcheck source=scripts/lib.sh
. scripts/lib.sh
mode=$1 days=$2
mc() { compose run --rm -T mc "$@"; }
for _ in $(seq 1 30); do mc ready admin >/dev/null 2>&1 && break; sleep 2; done
if [ "$mode" = COMPLIANCE ]; then
  mc mb --with-lock admin/backups
  mc retention set --default COMPLIANCE "${days}d" admin/backups
else
  mc mb admin/backups
fi
mc admin policy create admin backup-writer /policy/writer.json
mc admin user add admin "$DRKIT_S3_KEY" "$DRKIT_S3_SECRET"
mc admin policy attach admin backup-writer --user "$DRKIT_S3_KEY"
