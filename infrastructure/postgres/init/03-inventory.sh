#!/usr/bin/env bash
set -Eeuo pipefail

: "${POSTGRES_USER:?POSTGRES_USER is required}"
: "${INVENTORY_DB:?INVENTORY_DB is required}"
: "${INVENTORY_DB_USER:?INVENTORY_DB_USER is required}"
: "${INVENTORY_DB_PASSWORD:?INVENTORY_DB_PASSWORD is required}"
: "${POSTGRES_READER_USER:?POSTGRES_READER_USER is required}"
: "${POSTGRES_READER_PASSWORD:?POSTGRES_READER_PASSWORD is required}"

psql \
  --username "$POSTGRES_USER" \
  --dbname postgres \
  --set ON_ERROR_STOP=1 \
  --set inventory_db="$INVENTORY_DB" \
  --set inventory_user="$INVENTORY_DB_USER" \
  --set inventory_password="$INVENTORY_DB_PASSWORD" <<'SQL'
SELECT format('CREATE ROLE %I LOGIN', :'inventory_user')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :'inventory_user') \gexec

SELECT format(
  'ALTER ROLE %I WITH LOGIN PASSWORD %L NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION',
  :'inventory_user',
  :'inventory_password'
) \gexec

SELECT format('CREATE DATABASE %I OWNER %I', :'inventory_db', :'inventory_user')
WHERE NOT EXISTS (SELECT 1 FROM pg_database WHERE datname = :'inventory_db') \gexec

SELECT format('ALTER DATABASE %I OWNER TO %I', :'inventory_db', :'inventory_user') \gexec
SELECT format('REVOKE CONNECT ON DATABASE %I FROM PUBLIC', :'inventory_db') \gexec
SELECT format('GRANT CONNECT ON DATABASE %I TO %I', :'inventory_db', :'inventory_user') \gexec
SQL

psql \
  --username "$POSTGRES_USER" \
  --dbname "$INVENTORY_DB" \
  --set ON_ERROR_STOP=1 \
  --set inventory_user="$INVENTORY_DB_USER" <<'SQL'
CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE EXTENSION IF NOT EXISTS dblink;

SELECT format('SET ROLE %I', :'inventory_user') \gexec

CREATE TABLE IF NOT EXISTS inventory_stock (
    product_id BIGINT PRIMARY KEY,
    available_quantity INTEGER NOT NULL DEFAULT 0,
    reserved_quantity INTEGER NOT NULL DEFAULT 0,
    minimum_quantity INTEGER NOT NULL DEFAULT 0,
    version BIGINT NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT ck_inventory_available_nonnegative CHECK (available_quantity >= 0),
    CONSTRAINT ck_inventory_reserved_nonnegative CHECK (reserved_quantity >= 0),
    CONSTRAINT ck_inventory_reserved_within_available CHECK (reserved_quantity <= available_quantity),
    CONSTRAINT ck_inventory_minimum_nonnegative CHECK (minimum_quantity >= 0),
    CONSTRAINT ck_inventory_version_nonnegative CHECK (version >= 0)
);

CREATE TABLE IF NOT EXISTS inventory_reservations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    idempotency_key VARCHAR(100) NOT NULL UNIQUE,
    request_hash CHAR(64) NOT NULL,
    user_id VARCHAR(80) NOT NULL,
    order_id BIGINT UNIQUE,
    status VARCHAR(20) NOT NULL DEFAULT 'ACTIVE',
    expires_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT ck_inventory_reservation_idempotency_length
        CHECK (char_length(idempotency_key) BETWEEN 16 AND 100),
    CONSTRAINT ck_inventory_reservation_request_hash
        CHECK (request_hash ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_inventory_reservation_status
        CHECK (status IN ('ACTIVE', 'CONFIRMED', 'RELEASED', 'EXPIRED', 'CANCELLED')),
    CONSTRAINT ck_inventory_reservation_expiration
        CHECK (expires_at > created_at)
);

CREATE TABLE IF NOT EXISTS inventory_reservation_items (
    reservation_id UUID NOT NULL,
    product_id BIGINT NOT NULL,
    quantity INTEGER NOT NULL,
    PRIMARY KEY (reservation_id, product_id),
    CONSTRAINT fk_inventory_reservation_items_reservation
        FOREIGN KEY (reservation_id) REFERENCES inventory_reservations(id)
        ON DELETE CASCADE,
    CONSTRAINT fk_inventory_reservation_items_product
        FOREIGN KEY (product_id) REFERENCES inventory_stock(product_id)
        ON DELETE RESTRICT,
    CONSTRAINT ck_inventory_reservation_item_quantity
        CHECK (quantity BETWEEN 1 AND 1000)
);

CREATE TABLE IF NOT EXISTS stock_movements (
    id BIGSERIAL PRIMARY KEY,
    product_id BIGINT NOT NULL,
    movement_type VARCHAR(30) NOT NULL,
    quantity INTEGER NOT NULL,
    quantity_before INTEGER NOT NULL,
    quantity_after INTEGER NOT NULL,
    reservation_id UUID,
    order_id BIGINT,
    reason TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_stock_movements_product
        FOREIGN KEY (product_id) REFERENCES inventory_stock(product_id)
        ON DELETE RESTRICT,
    CONSTRAINT fk_stock_movements_reservation
        FOREIGN KEY (reservation_id) REFERENCES inventory_reservations(id)
        ON DELETE RESTRICT,
    CONSTRAINT ck_stock_movement_type
        CHECK (movement_type IN ('INITIAL_STOCK', 'MANUAL_ADJUSTMENT', 'SALE_CONFIRMED', 'ORDER_CANCELLED')),
    CONSTRAINT ck_stock_movement_quantity_nonzero CHECK (quantity <> 0),
    CONSTRAINT ck_stock_movement_before_nonnegative CHECK (quantity_before >= 0),
    CONSTRAINT ck_stock_movement_after_nonnegative CHECK (quantity_after >= 0),
    CONSTRAINT ck_stock_movement_arithmetic
        CHECK (quantity_after = quantity_before + quantity)
);

CREATE INDEX IF NOT EXISTS idx_inventory_stock_sellable
    ON inventory_stock ((available_quantity - reserved_quantity), minimum_quantity);
CREATE INDEX IF NOT EXISTS idx_inventory_reservations_status_expires
    ON inventory_reservations (status, expires_at);
CREATE INDEX IF NOT EXISTS idx_inventory_reservations_user_created
    ON inventory_reservations (user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_inventory_reservation_items_product
    ON inventory_reservation_items (product_id);
CREATE INDEX IF NOT EXISTS idx_stock_movements_product_created
    ON stock_movements (product_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_stock_movements_order
    ON stock_movements (order_id) WHERE order_id IS NOT NULL;

CREATE OR REPLACE FUNCTION inventory_set_updated_at()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_inventory_stock_updated_at ON inventory_stock;
CREATE TRIGGER trg_inventory_stock_updated_at
BEFORE UPDATE ON inventory_stock
FOR EACH ROW EXECUTE FUNCTION inventory_set_updated_at();

DROP TRIGGER IF EXISTS trg_inventory_reservations_updated_at ON inventory_reservations;
CREATE TRIGGER trg_inventory_reservations_updated_at
BEFORE UPDATE ON inventory_reservations
FOR EACH ROW EXECUTE FUNCTION inventory_set_updated_at();

RESET ROLE;
SQL

psql \
  --username "$POSTGRES_USER" \
  --dbname "$INVENTORY_DB" \
  --set ON_ERROR_STOP=1 \
  --set inventory_user="$INVENTORY_DB_USER" \
  --set reader_user="$POSTGRES_READER_USER" \
  --set reader_password="$POSTGRES_READER_PASSWORD" \
  --set inventory_db="$INVENTORY_DB" <<'SQL'
SELECT format('CREATE ROLE %I LOGIN', :'reader_user')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :'reader_user') \gexec

SELECT format('ALTER ROLE %I WITH LOGIN PASSWORD %L', :'reader_user', :'reader_password') \gexec
SELECT format('GRANT CONNECT ON DATABASE %I TO %I', :'inventory_db', :'reader_user') \gexec
SELECT format('GRANT USAGE ON SCHEMA public TO %I', :'reader_user') \gexec
SELECT format('GRANT SELECT ON ALL TABLES IN SCHEMA public TO %I', :'reader_user') \gexec
SELECT format('GRANT SELECT ON ALL SEQUENCES IN SCHEMA public TO %I', :'reader_user') \gexec
SELECT format(
  'ALTER DEFAULT PRIVILEGES FOR ROLE %I IN SCHEMA public GRANT SELECT ON TABLES TO %I',
  :'inventory_user',
  :'reader_user'
) \gexec
SELECT format(
  'ALTER DEFAULT PRIVILEGES FOR ROLE %I IN SCHEMA public GRANT SELECT ON SEQUENCES TO %I',
  :'inventory_user',
  :'reader_user'
) \gexec
SELECT format('ALTER ROLE %I SET default_transaction_read_only = on', :'reader_user') \gexec
SQL
