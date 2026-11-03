#!/usr/bin/env bash
# Restore a backup made by scripts/backup.sh onto a stack with EMPTY volumes.
# Start only the backing services first:
#   docker compose -f docker-compose.dokploy.yml up -d postgres minio
#   COMPOSE_PROJECT=tara scripts/restore.sh backups/20261103T010000Z
# Then bring up the rest of the stack.
set -euo pipefail

project="${COMPOSE_PROJECT:-tara}"
source_dir="${1:?Usage: restore.sh <backup directory>}"

restore_volume() {
  docker run --rm -i -v "${project}_$1:/data" alpine:3.20 tar -xzf - -C /data < "$source_dir/$1.tar.gz"
}
restore_volume miniodata
restore_volume identity-keys

# The init script already created the roles and empty databases, so "already
# exists" errors here are expected; a failed row load is not, so keep the log.
gunzip -c "$source_dir/postgres.sql.gz" \
  | docker exec -i "${project}-postgres-1" sh -c 'psql -q -U "$POSTGRES_USER" -d postgres' \
  2> "$source_dir/restore.log" > /dev/null || true
if grep -E 'ERROR' "$source_dir/restore.log" | grep -vq 'already exists'; then
  echo "Restore finished with errors, see $source_dir/restore.log" >&2
  exit 1
fi
echo "restored from $source_dir"
