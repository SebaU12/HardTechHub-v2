WITH latest_snapshot AS (
    SELECT MAX(snapshot_at) AS snapshot_at
    FROM inventory
)
SELECT
    i.product_id,
    i.available_quantity,
    i.reserved_quantity,
    i.sellable_quantity,
    i.minimum_quantity,
    i.version,
    i.updated_at,
    i.snapshot_at
FROM inventory i
CROSS JOIN latest_snapshot s
WHERE i.snapshot_at = s.snapshot_at
  AND i.low_stock
ORDER BY i.sellable_quantity ASC, i.product_id ASC;
