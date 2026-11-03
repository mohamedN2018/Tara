#!/usr/bin/env bash
# Search container entrypoint. Web role runs migrations; indexer skips.
set -euo pipefail

python /app/scripts/wait_for_db.py

if [ "${RUN_MIGRATIONS:-false}" = "true" ]; then
  echo "[search] migrate"
  python manage.py migrate --noinput
fi

exec "$@"
