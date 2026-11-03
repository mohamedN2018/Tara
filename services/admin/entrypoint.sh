#!/usr/bin/env bash
# Admin container entrypoint. Runs migrations then execs the CMD.
set -euo pipefail

python /app/scripts/wait_for_db.py

if [ "${RUN_MIGRATIONS:-false}" = "true" ]; then
  echo "[admin] migrate"
  python manage.py migrate --noinput
fi

exec "$@"
