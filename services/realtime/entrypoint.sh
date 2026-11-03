#!/usr/bin/env bash
# Realtime gateway entrypoint. No database / migrations — just exec the command
# (daphne ASGI server, or the consume_events bridge worker).
set -euo pipefail
if [ "${TARA_ENV:-}" = "production" ]; then
  python manage.py check --deploy --fail-level ERROR
fi

exec "$@"
