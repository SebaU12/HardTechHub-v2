WITH viewed AS (
    SELECT user_id, MIN(FROM_ISO8601_TIMESTAMP("timestamp")) AS viewed_at
    FROM navigation_events
    WHERE event_type = 'PRODUCT_VIEW' AND user_id IS NOT NULL
    GROUP BY user_id
),
checked AS (
    SELECT user_id, MIN(FROM_ISO8601_TIMESTAMP("timestamp")) AS checked_at
    FROM compatibility_events
    WHERE event_type = 'COMPATIBILITY_CHECKED' AND user_id IS NOT NULL
    GROUP BY user_id
),
ordered AS (
    SELECT user_id, MIN(FROM_ISO8601_TIMESTAMP("timestamp")) AS ordered_at
    FROM order_events
    WHERE event_type = 'ORDER_CREATED' AND user_id IS NOT NULL
    GROUP BY user_id
),
funnel AS (
    SELECT
        v.user_id,
        c.user_id AS checked_user,
        o.user_id AS ordered_user
    FROM viewed v
    LEFT JOIN checked c
        ON c.user_id = v.user_id
       AND c.checked_at >= v.viewed_at
    LEFT JOIN ordered o
        ON o.user_id = v.user_id
       AND c.user_id IS NOT NULL
       AND o.ordered_at >= c.checked_at
)
SELECT
    COUNT(*) AS users_with_view,
    COUNT(checked_user) AS users_with_compatibility_check,
    COUNT(ordered_user) AS users_with_order,
    ROUND(100.0 * COUNT(checked_user) / NULLIF(COUNT(*), 0), 2) AS view_to_check_pct,
    ROUND(100.0 * COUNT(ordered_user) / NULLIF(COUNT(checked_user), 0), 2) AS check_to_order_pct
FROM funnel;
