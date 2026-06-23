#!/usr/bin/env bash
# Feed container entrypoint. Web role runs migrations; workers/consumers skip.
set -euo pipefail

python /app/scripts/wait_for_db.py

if [ "${RUN_MIGRATIONS:-false}" = "true" ]; then
  if [ "${RUN_MAKEMIGRATIONS:-true}" = "true" ]; then
    echo "[feed] makemigrations"
    python manage.py makemigrations feed --noinput
  fi
  echo "[feed] migrate"
  python manage.py migrate --noinput
fi

exec "$@"
