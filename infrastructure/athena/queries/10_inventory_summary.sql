WITH latest_snapshot AS (
    SELECT MAX(snapshot_at) AS snapshot_at
    FROM inventory
),
current_inventory AS (
    SELECT i.*
    FROM inventory i
    CROSS JOIN latest_snapshot s
    WHERE i.snapshot_at = s.snapshot_at
)
SELECT
    COUNT(*) AS total_products,
    COALESCE(SUM(available_quantity), CAST(0 AS BIGINT)) AS physical_units,
    COALESCE(SUM(reserved_quantity), CAST(0 AS BIGINT)) AS reserved_units,
    COALESCE(SUM(sellable_quantity), CAST(0 AS BIGINT)) AS sellable_units,
    COUNT_IF(low_stock) AS low_stock_products,
    MAX(snapshot_at) AS snapshot_at
FROM current_inventory;
