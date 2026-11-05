#!/usr/bin/env bash
# Check for missing migrations, then run one service's test suite, in a
# throwaway container from its built image.
# Needs the core stack's Postgres and Redis to be up (`make up`).
#   scripts/test-service.sh post
set -euo pipefail

service="$1"
env_file=".env.test-${service}"
trap 'rm -f "$env_file"' EXIT
# `docker run --env-file` keeps inline comments, so strip them.
sed -E 's/[[:space:]]+#.*$//' .env | grep -E '^[A-Z0-9_]+=' > "$env_file"

network="--network tara_default"
pytest_args="--create-db"
if [ "$service" = "bff" ]; then
  # Not a Django service: no database.
  network=""
  pytest_args=""
fi

# Test tools live in a derived image, so only the first run after a build downloads them.
MSYS_NO_PATHCONV=1 docker build -q -t "tara/${service}:test" - > /dev/null <<EOF
FROM tara/${service}:dev
USER root
ENV PIP_CONSTRAINT=
RUN pip install -q --timeout 20 --retries 5 --root-user-action=ignore \
    "pytest>=8" "pytest-django>=4.8" pytest-cov pytest-asyncio httpx "hypothesis>=6.100"
EOF

# shellcheck disable=SC2086
MSYS_NO_PATHCONV=1 docker run --rm $network --env-file "$env_file" \
  -e POSTGRES_HOST=postgres -e REDIS_URL=redis://redis:6379/15 -e RABBITMQ_URL= \
  -e PYTEST_ARGS="$pytest_args" --entrypoint sh "tara/${service}:test" -ec '
    if [ -d "$(ls -d */migrations 2>/dev/null | head -1)" ]; then
      python manage.py makemigrations --check --dry-run
    fi
    python -m pytest -q --no-header -p no:cacheprovider -W ignore $PYTEST_ARGS'
