#!/bin/sh
set -eu
psql --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" -v ON_ERROR_STOP=1 \
  -v migrator_password="$MIGRATOR_DB_PASSWORD" -v app_password="$APP_DB_PASSWORD" <<'SQL'
CREATE ROLE aroman_migrator LOGIN PASSWORD :'migrator_password';
CREATE ROLE aroman_app LOGIN PASSWORD :'app_password';
ALTER DATABASE aroman OWNER TO aroman_migrator;
REVOKE CONNECT ON DATABASE aroman FROM PUBLIC;
GRANT CONNECT ON DATABASE aroman TO aroman_migrator;
GRANT CONNECT ON DATABASE aroman TO aroman_app;
GRANT USAGE ON SCHEMA public TO aroman_app;
ALTER DEFAULT PRIVILEGES FOR ROLE aroman_migrator IN SCHEMA public
  GRANT SELECT ON TABLES TO aroman_app;
SQL
