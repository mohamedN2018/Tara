#!/bin/bash
# Create one logical database + least-privilege role per bounded context.
# Runs once, as the superuser, on first initialization of the data volume.
# As new services arrive in later phases, append their CREATE USER / DATABASE
# blocks here (database-per-service — ADR-001 / doc 05).
set -euo pipefail

create_db() {
  local db="$1" user="$2" pass="$3"
  echo "[postgres-init] creating role '$user' and database '$db'"
  psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "postgres" <<-EOSQL
    DO \$\$
    BEGIN
      IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '${user}') THEN
        -- CREATEDB lets the test runner create its throwaway test database in dev.
        CREATE ROLE ${user} LOGIN CREATEDB PASSWORD '${pass}';
      END IF;
    END
    \$\$;
    SELECT 'CREATE DATABASE ${db} OWNER ${user}'
      WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = '${db}')\gexec
    GRANT ALL PRIVILEGES ON DATABASE ${db} TO ${user};
EOSQL
}

# Identity (Phase 1)
create_db "${IDENTITY_DB_NAME:-identity_db}" "${IDENTITY_DB_USER:-identity}" "${IDENTITY_DB_PASSWORD:-identity-dev-pass}"

# --- future services append below ---
# create_db "${PROFILE_DB_NAME}" "${PROFILE_DB_USER}" "${PROFILE_DB_PASSWORD}"
