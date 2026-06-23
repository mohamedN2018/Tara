#!/usr/bin/env bash
# Marketplace container entrypoint. Web role runs migrations + seeds categories.
set -euo pipefail

python /app/scripts/wait_for_db.py

if [ "${RUN_MIGRATIONS:-false}" = "true" ]; then
  if [ "${RUN_MAKEMIGRATIONS:-true}" = "true" ]; then
    echo "[marketplace] makemigrations"
    python manage.py makemigrations marketplace --noinput
  fi
  echo "[marketplace] migrate"
  python manage.py migrate --noinput
  echo "[marketplace] seed categories"
  python manage.py seed_categories || true
fi

exec "$@"
