#!/usr/bin/env bash
set -Eeuo pipefail

: "${MYSQL_ROOT_PASSWORD:?MYSQL_ROOT_PASSWORD is required}"
: "${MYSQL_READER_USER:?MYSQL_READER_USER is required}"
: "${MYSQL_READER_PASSWORD:?MYSQL_READER_PASSWORD is required}"

if [[ ! "$MYSQL_READER_USER" =~ ^[a-zA-Z0-9_]+$ ]]; then
  echo "MYSQL_READER_USER contains unsupported characters" >&2
  exit 1
fi

if [[ "$MYSQL_READER_PASSWORD" == *"'"* || "$MYSQL_READER_PASSWORD" == *"\\"* ]]; then
  echo "MYSQL_READER_PASSWORD cannot contain single quotes or backslashes" >&2
  exit 1
fi

MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysql --protocol=socket --user=root <<SQL
CREATE USER IF NOT EXISTS '${MYSQL_READER_USER}'@'%'
  IDENTIFIED WITH mysql_native_password BY '${MYSQL_READER_PASSWORD}';
ALTER USER '${MYSQL_READER_USER}'@'%'
  IDENTIFIED WITH mysql_native_password BY '${MYSQL_READER_PASSWORD}';
GRANT SELECT ON hardtech_orders.* TO '${MYSQL_READER_USER}'@'%';
FLUSH PRIVILEGES;
SQL
