#!/usr/bin/env bash
# Moderation container entrypoint. Web role runs migrations; consumers skip.
set -euo pipefail

python /app/scripts/wait_for_db.py

if [ "${RUN_MIGRATIONS:-false}" = "true" ]; then
  if [ "${RUN_MAKEMIGRATIONS:-true}" = "true" ]; then
    echo "[moderation] makemigrations"
    python manage.py makemigrations moderation --noinput
  fi
  echo "[moderation] migrate"
  python manage.py migrate --noinput
fi

exec "$@"
