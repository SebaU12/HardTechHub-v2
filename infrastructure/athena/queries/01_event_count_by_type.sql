WITH all_events AS (
    SELECT event_type FROM navigation_events
    UNION ALL
    SELECT event_type FROM compatibility_events
    UNION ALL
    SELECT event_type FROM order_events
    UNION ALL
    SELECT event_type FROM catalog_events
    UNION ALL
    SELECT event_type FROM identity_events
)
SELECT
    event_type,
    COUNT(*) AS event_count
FROM all_events
GROUP BY event_type
ORDER BY event_count DESC, event_type;

