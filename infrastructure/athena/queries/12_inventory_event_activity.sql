SELECT
    CAST(from_iso8601_timestamp("timestamp") AS date) AS event_date,
    event_type,
    COUNT(*) AS event_count
FROM inventory_events
WHERE event_type IN (
    'STOCK_ADJUSTED',
    'STOCK_RESERVED',
    'STOCK_CONFIRMED',
    'STOCK_RELEASED',
    'RESERVATION_EXPIRED',
    'STOCK_RESTORED',
    'LOW_STOCK_DETECTED'
)
GROUP BY 1, 2
ORDER BY event_date DESC, event_type;
