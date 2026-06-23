#!/usr/bin/env bash
# Post container entrypoint. Web role runs migrations; workers/consumers skip.
set -euo pipefail

python /app/scripts/wait_for_db.py

if [ "${RUN_MIGRATIONS:-false}" = "true" ]; then
  if [ "${RUN_MAKEMIGRATIONS:-true}" = "true" ]; then
    echo "[post] makemigrations"
    python manage.py makemigrations posts --noinput
  fi
  echo "[post] migrate"
  python manage.py migrate --noinput
fi

exec "$@"
