SELECT
    COUNT(*) AS checked_builds,
    COUNT_IF(payload.compatible) AS compatible_builds,
    ROUND(100.0 * COUNT_IF(payload.compatible) / NULLIF(COUNT(*), 0), 2) AS compatible_rate_pct
FROM compatibility_events
WHERE event_type = 'COMPATIBILITY_CHECKED';

