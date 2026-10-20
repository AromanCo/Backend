#!/bin/sh
set -eu
psql --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" -v ON_ERROR_STOP=1 -v app_password="$APP_DB_PASSWORD" <<'SQL'
CREATE ROLE aroman_app LOGIN PASSWORD :'app_password';
GRANT CONNECT ON DATABASE aroman TO aroman_app;
GRANT USAGE ON SCHEMA public TO aroman_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO aroman_app;
SQL
