#!/usr/bin/env bash
# Graph container entrypoint. Web role runs migrations; workers/consumers skip.
set -euo pipefail

python /app/scripts/wait_for_db.py

if [ "${RUN_MIGRATIONS:-false}" = "true" ]; then
  if [ "${RUN_MAKEMIGRATIONS:-true}" = "true" ]; then
    echo "[graph] makemigrations"
    python manage.py makemigrations graph --noinput
  fi
  echo "[graph] migrate"
  python manage.py migrate --noinput
fi

exec "$@"
