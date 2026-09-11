#!/usr/bin/env bash
set -euo pipefail

: "${PI_APP_USER:?PI_APP_USER is required}"
: "${PI_APP_PASSWORD:?PI_APP_PASSWORD is required}"

psql --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
  -v app_user="$PI_APP_USER" -v app_password="$PI_APP_PASSWORD" -v db_name="$POSTGRES_DB" <<'SQL'
SELECT format(
  'CREATE ROLE %I LOGIN PASSWORD %L NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION',
  :'app_user', :'app_password'
)
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :'app_user')\gexec
GRANT CONNECT ON DATABASE :"db_name" TO :"app_user";
GRANT USAGE, CREATE ON SCHEMA public TO :"app_user";
SQL
