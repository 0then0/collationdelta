#!/bin/sh
# Test-stand psql: run the PostgreSQL client that ships inside a disposable server
# container named by CD_CONTAINER. Only variable NAMES are forwarded to docker, so
# credentials from the standard PG* environment never appear in any argv.
# If CD_SHIM_LOG is set, the argv received by psql is appended to that file.
[ -n "$CD_SHIM_LOG" ] && printf '%s\n' "$*" >> "$CD_SHIM_LOG"
exec docker exec -i \
  -e PGHOST -e PGPORT -e PGUSER -e PGDATABASE -e PGPASSWORD -e PGSSLMODE -e PGOPTIONS \
  -e PGCLIENTENCODING -e PGAPPNAME -e PGCONNECT_TIMEOUT \
  "${CD_CONTAINER:?CD_CONTAINER is not set}" psql "$@"
