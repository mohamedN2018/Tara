#!/usr/bin/env bash
# Search container entrypoint. Web role runs migrations; indexer skips.
set -euo pipefail

python /app/scripts/wait_for_db.py

if [ "${RUN_MIGRATIONS:-false}" = "true" ]; then
  if [ "${RUN_MAKEMIGRATIONS:-true}" = "true" ]; then
    echo "[search] makemigrations"
    python manage.py makemigrations searchsvc --noinput
  fi
  echo "[search] migrate"
  python manage.py migrate --noinput
fi

exec "$@"
