SELECT
    product_id,
    COUNT(*) AS view_count
FROM navigation_events
WHERE event_type = 'PRODUCT_VIEW'
  AND product_id IS NOT NULL
GROUP BY product_id
ORDER BY view_count DESC, product_id
LIMIT 5;

