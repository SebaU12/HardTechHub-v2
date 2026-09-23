WITH latest_products AS (
    SELECT MAX(snapshot_at) AS snapshot_at FROM products
),
latest_orders AS (
    SELECT MAX(snapshot_at) AS snapshot_at FROM orders
),
latest_items AS (
    SELECT MAX(snapshot_at) AS snapshot_at FROM order_items
),
current_products AS (
    SELECT p.* FROM products p CROSS JOIN latest_products s WHERE p.snapshot_at = s.snapshot_at
),
current_orders AS (
    SELECT o.* FROM orders o CROSS JOIN latest_orders s WHERE o.snapshot_at = s.snapshot_at
),
current_items AS (
    SELECT i.* FROM order_items i CROSS JOIN latest_items s WHERE i.snapshot_at = s.snapshot_at
)
SELECT
    p.category,
    SUM(i.quantity) AS units_sold,
    CAST(SUM(i.subtotal) AS DECIMAL(18, 2)) AS sales_amount
FROM current_items i
JOIN current_orders o ON o.id = i.order_id AND o.status <> 'CANCELLED'
JOIN current_products p ON p.id = i.product_id
GROUP BY p.category
ORDER BY sales_amount DESC, p.category;

