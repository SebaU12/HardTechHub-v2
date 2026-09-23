WITH latest_snapshot AS (
    SELECT MAX(snapshot_at) AS snapshot_at
    FROM orders
),
current_orders AS (
    SELECT o.*
    FROM orders o
    CROSS JOIN latest_snapshot s
    WHERE o.snapshot_at = s.snapshot_at
)
SELECT
    COUNT(*) AS order_count,
    COUNT_IF(status <> 'CANCELLED') AS non_cancelled_orders,
    CAST(SUM(CASE WHEN status <> 'CANCELLED' THEN total_amount ELSE DECIMAL '0.00' END) AS DECIMAL(18, 2)) AS gross_revenue,
    CAST(AVG(CASE WHEN status <> 'CANCELLED' THEN total_amount END) AS DECIMAL(18, 2)) AS average_order_value
FROM current_orders;

