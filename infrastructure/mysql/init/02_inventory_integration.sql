DROP PROCEDURE IF EXISTS migrate_orders_inventory;

DELIMITER //
CREATE PROCEDURE migrate_orders_inventory()
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = DATABASE() AND table_name = 'orders' AND column_name = 'idempotency_key'
    ) THEN
        ALTER TABLE orders ADD COLUMN idempotency_key VARCHAR(100) NULL AFTER user_id;
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = DATABASE() AND table_name = 'orders' AND column_name = 'request_hash'
    ) THEN
        ALTER TABLE orders ADD COLUMN request_hash CHAR(64) NULL AFTER idempotency_key;
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = DATABASE() AND table_name = 'orders' AND column_name = 'inventory_reservation_id'
    ) THEN
        ALTER TABLE orders ADD COLUMN inventory_reservation_id CHAR(36) NULL AFTER request_hash;
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = DATABASE() AND table_name = 'orders' AND column_name = 'inventory_status'
    ) THEN
        ALTER TABLE orders ADD COLUMN inventory_status VARCHAR(30) NULL AFTER inventory_reservation_id;
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = DATABASE() AND table_name = 'orders' AND column_name = 'order_event_key'
    ) THEN
        ALTER TABLE orders ADD COLUMN order_event_key VARCHAR(512) NULL AFTER inventory_status;
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM information_schema.statistics
        WHERE table_schema = DATABASE() AND table_name = 'orders' AND index_name = 'uq_orders_idempotency_key'
    ) THEN
        CREATE UNIQUE INDEX uq_orders_idempotency_key ON orders(idempotency_key);
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM information_schema.statistics
        WHERE table_schema = DATABASE() AND table_name = 'orders' AND index_name = 'uq_orders_inventory_reservation_id'
    ) THEN
        CREATE UNIQUE INDEX uq_orders_inventory_reservation_id ON orders(inventory_reservation_id);
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM information_schema.statistics
        WHERE table_schema = DATABASE() AND table_name = 'orders' AND index_name = 'idx_orders_inventory_status'
    ) THEN
        CREATE INDEX idx_orders_inventory_status ON orders(inventory_status);
    END IF;
END//
DELIMITER ;

CALL migrate_orders_inventory();
DROP PROCEDURE migrate_orders_inventory;
