SELECT
    item.product_id,
    SUM(item.quantity) AS confirmed_units,
    COUNT(DISTINCT event_id) AS confirmations
FROM (
    SELECT event_id, payload.items AS items
    FROM inventory_events
    WHERE event_type = 'STOCK_CONFIRMED'
) confirmed
CROSS JOIN UNNEST(confirmed.items) AS t(item)
GROUP BY item.product_id
ORDER BY confirmed_units DESC, item.product_id;
