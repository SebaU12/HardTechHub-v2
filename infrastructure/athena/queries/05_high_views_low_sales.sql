WITH latest_products AS (
    SELECT MAX(snapshot_at) AS snapshot_at FROM products
),
latest_items AS (
    SELECT MAX(snapshot_at) AS snapshot_at FROM order_items
),
latest_orders AS (
    SELECT MAX(snapshot_at) AS snapshot_at FROM orders
),
current_products AS (
    SELECT p.* FROM products p CROSS JOIN latest_products s WHERE p.snapshot_at = s.snapshot_at
),
current_items AS (
    SELECT i.* FROM order_items i CROSS JOIN latest_items s WHERE i.snapshot_at = s.snapshot_at
),
current_orders AS (
    SELECT o.* FROM orders o CROSS JOIN latest_orders s WHERE o.snapshot_at = s.snapshot_at
),
views AS (
    SELECT product_id, COUNT(*) AS view_count
    FROM navigation_events
    WHERE event_type = 'PRODUCT_VIEW' AND product_id IS NOT NULL
    GROUP BY product_id
),
sales AS (
    SELECT i.product_id, SUM(i.quantity) AS units_sold
    FROM current_items i
    JOIN current_orders o ON o.id = i.order_id AND o.status <> 'CANCELLED'
    GROUP BY i.product_id
)
SELECT
    p.id AS product_id,
    p.name,
    p.category,
    COALESCE(v.view_count, 0) AS view_count,
    COALESCE(s.units_sold, 0) AS units_sold
FROM current_products p
LEFT JOIN views v ON v.product_id = p.id
LEFT JOIN sales s ON s.product_id = p.id
WHERE COALESCE(v.view_count, 0) > 0
ORDER BY view_count DESC, units_sold ASC, product_id
LIMIT 10;
