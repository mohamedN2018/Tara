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

# Profile & Social Graph (Phase 2)
create_db "${PROFILE_DB_NAME:-profile_db}" "${PROFILE_DB_USER:-profile}" "${PROFILE_DB_PASSWORD:-profile-dev-pass}"
create_db "${GRAPH_DB_NAME:-graph_db}" "${GRAPH_DB_USER:-graph}" "${GRAPH_DB_PASSWORD:-graph-dev-pass}"

# Media, Post & Feed (Phase 3)
create_db "${MEDIA_DB_NAME:-media_db}" "${MEDIA_DB_USER:-media}" "${MEDIA_DB_PASSWORD:-media-dev-pass}"
create_db "${POST_DB_NAME:-post_db}" "${POST_DB_USER:-post}" "${POST_DB_PASSWORD:-post-dev-pass}"
create_db "${FEED_DB_NAME:-feed_db}" "${FEED_DB_USER:-feed}" "${FEED_DB_PASSWORD:-feed-dev-pass}"

# Chat (Phase 4) — the Realtime gateway has no database
create_db "${CHAT_DB_NAME:-chat_db}" "${CHAT_DB_USER:-chat}" "${CHAT_DB_PASSWORD:-chat-dev-pass}"

# Marketplace (Phase 5)
create_db "${MARKET_DB_NAME:-market_db}" "${MARKET_DB_USER:-market}" "${MARKET_DB_PASSWORD:-market-dev-pass}"

# Notifications, Search, Moderation, Admin (Phase 6)
create_db "${NOTIF_DB_NAME:-notif_db}" "${NOTIF_DB_USER:-notif}" "${NOTIF_DB_PASSWORD:-notif-dev-pass}"
create_db "${SEARCH_DB_NAME:-search_db}" "${SEARCH_DB_USER:-search}" "${SEARCH_DB_PASSWORD:-search-dev-pass}"
create_db "${MODERATION_DB_NAME:-moderation_db}" "${MODERATION_DB_USER:-moderation}" "${MODERATION_DB_PASSWORD:-moderation-dev-pass}"
create_db "${ADMIN_DB_NAME:-admin_db}" "${ADMIN_DB_USER:-adminsvc}" "${ADMIN_DB_PASSWORD:-admin-dev-pass}"

# Advertisement (Phase 7)
create_db "${ADS_DB_NAME:-ads_db}" "${ADS_DB_USER:-ads}" "${ADS_DB_PASSWORD:-ads-dev-pass}"

# --- future services append below ---
