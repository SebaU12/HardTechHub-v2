SELECT
    failed_rule,
    COUNT(*) AS failure_count
FROM compatibility_events
CROSS JOIN UNNEST(payload.failed_rules) AS rules(failed_rule)
WHERE event_type = 'COMPATIBILITY_CHECKED'
GROUP BY failed_rule
ORDER BY failure_count DESC, failed_rule;

