SELECT
    DATE(FROM_ISO8601_TIMESTAMP(payload.registered_at)) AS registration_day,
    COUNT(*) AS registered_users
FROM identity_events
WHERE event_type = 'USER_REGISTERED'
GROUP BY 1
ORDER BY registration_day;

