#!/usr/bin/env bash
# Moderation container entrypoint. Web role runs migrations; consumers skip.
set -euo pipefail

python /app/scripts/wait_for_db.py

if [ "${RUN_MIGRATIONS:-false}" = "true" ]; then
  echo "[moderation] migrate"
  python manage.py migrate --noinput
fi

exec "$@"
