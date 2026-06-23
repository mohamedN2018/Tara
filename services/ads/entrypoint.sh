#!/usr/bin/env bash
# Ads container entrypoint. Web role runs migrations; relay skips.
set -euo pipefail

python /app/scripts/wait_for_db.py

if [ "${RUN_MIGRATIONS:-false}" = "true" ]; then
  if [ "${RUN_MAKEMIGRATIONS:-true}" = "true" ]; then
    echo "[ads] makemigrations"
    python manage.py makemigrations ads --noinput
  fi
  echo "[ads] migrate"
  python manage.py migrate --noinput
fi

exec "$@"
