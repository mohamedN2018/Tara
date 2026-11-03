#!/usr/bin/env bash
# Back up everything the Dokploy stack cannot rebuild: all databases, media and
# the JWT signing keys. Schedule it daily (Dokploy "Schedules", or cron) and copy
# the output off the server.
#   COMPOSE_PROJECT=tara BACKUP_DIR=/var/backups/tara scripts/backup.sh
set -euo pipefail

project="${COMPOSE_PROJECT:-tara}"
target="${BACKUP_DIR:-./backups}/$(date -u +%Y%m%dT%H%M%SZ)"
keep_days="${BACKUP_KEEP_DAYS:-14}"
mkdir -p "$target"

docker exec "${project}-postgres-1" sh -c 'pg_dumpall -U "$POSTGRES_USER"' | gzip > "$target/postgres.sql.gz"

archive_volume() {
  docker run --rm -v "${project}_$1:/data:ro" alpine:3.20 tar -czf - -C /data . > "$target/$1.tar.gz"
}
archive_volume miniodata
archive_volume identity-keys

gzip -t "$target/postgres.sql.gz"
find "${BACKUP_DIR:-./backups}" -mindepth 1 -maxdepth 1 -type d -mtime "+${keep_days}" -exec rm -rf {} +
echo "backup written to $target"
