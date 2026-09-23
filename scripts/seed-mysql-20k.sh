#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
cd "$ROOT_DIR"

SEED_COUNT=20000
FORCE_SEED=0

for argument in "$@"; do
  case "$argument" in
    --force) FORCE_SEED=1 ;;
    *[!0-9]*|'') echo "Uso: $0 [cantidad>=20000] [--force]" >&2; exit 2 ;;
    *) SEED_COUNT=$argument ;;
  esac
done

if (( SEED_COUNT < 20000 )); then
  echo "La cantidad mínima permitida es 20000" >&2
  exit 2
fi

docker compose up -d --wait mysql

docker compose exec -T -e MYSQL_PWD="${MYSQL_ROOT_PASSWORD:-root}" mysql \
  mysql --user=root hardtech_orders <<SQL
SET @seed_count = ${SEED_COUNT};
SET @force_seed = ${FORCE_SEED};

START TRANSACTION;

DELETE FROM orders
WHERE @force_seed = 1
  AND user_id LIKE 'fake_seed_%';

CREATE TEMPORARY TABLE seed_numbers (
    number INT PRIMARY KEY
) ENGINE=MEMORY;

INSERT INTO seed_numbers (number)
SELECT generated_numbers.number
FROM (
    SELECT
        ones.digit
        + tens.digit * 10
        + hundreds.digit * 100
        + thousands.digit * 1000
        + ten_thousands.digit * 10000
        + 1 AS number
    FROM
        (SELECT 0 digit UNION ALL SELECT 1 UNION ALL SELECT 2 UNION ALL SELECT 3 UNION ALL SELECT 4 UNION ALL SELECT 5 UNION ALL SELECT 6 UNION ALL SELECT 7 UNION ALL SELECT 8 UNION ALL SELECT 9) ones
    CROSS JOIN
        (SELECT 0 digit UNION ALL SELECT 1 UNION ALL SELECT 2 UNION ALL SELECT 3 UNION ALL SELECT 4 UNION ALL SELECT 5 UNION ALL SELECT 6 UNION ALL SELECT 7 UNION ALL SELECT 8 UNION ALL SELECT 9) tens
    CROSS JOIN
        (SELECT 0 digit UNION ALL SELECT 1 UNION ALL SELECT 2 UNION ALL SELECT 3 UNION ALL SELECT 4 UNION ALL SELECT 5 UNION ALL SELECT 6 UNION ALL SELECT 7 UNION ALL SELECT 8 UNION ALL SELECT 9) hundreds
    CROSS JOIN
        (SELECT 0 digit UNION ALL SELECT 1 UNION ALL SELECT 2 UNION ALL SELECT 3 UNION ALL SELECT 4 UNION ALL SELECT 5 UNION ALL SELECT 6 UNION ALL SELECT 7 UNION ALL SELECT 8 UNION ALL SELECT 9) thousands
    CROSS JOIN
        (SELECT 0 digit UNION ALL SELECT 1 UNION ALL SELECT 2 UNION ALL SELECT 3 UNION ALL SELECT 4 UNION ALL SELECT 5 UNION ALL SELECT 6 UNION ALL SELECT 7 UNION ALL SELECT 8 UNION ALL SELECT 9) ten_thousands
) generated_numbers
WHERE generated_numbers.number <= @seed_count;

INSERT INTO orders (
    user_id, status, subtotal, tax, shipping_cost, total_amount, created_at, updated_at
)
SELECT
    CONCAT('fake_seed_', LPAD(numbers.number, 6, '0')),
    ELT(1 + MOD(numbers.number, 4), 'PENDING', 'PAID', 'SHIPPED', 'CANCELLED'),
    ROUND(100 + MOD(numbers.number, 500000) / 100, 2),
    ROUND((100 + MOD(numbers.number, 500000) / 100) * 0.18, 2),
    25.00,
    ROUND((100 + MOD(numbers.number, 500000) / 100) * 1.18 + 25.00, 2),
    TIMESTAMP('2026-01-01 00:00:00') + INTERVAL MOD(numbers.number, 365) DAY,
    TIMESTAMP('2026-01-01 00:00:00') + INTERVAL MOD(numbers.number, 365) DAY
FROM seed_numbers numbers
WHERE NOT EXISTS (
    SELECT 1
    FROM orders existing
    WHERE existing.user_id = CONCAT('fake_seed_', LPAD(numbers.number, 6, '0'))
);

INSERT INTO order_items (
    order_id, product_id, product_sku, product_name, quantity, unit_price, subtotal
)
SELECT
    orders.id,
    numbers.number,
    CONCAT('FAKE-SEED-', LPAD(numbers.number, 6, '0')),
    CONCAT('Componente ficticio ', LPAD(numbers.number, 6, '0')),
    1,
    orders.subtotal,
    orders.subtotal
FROM seed_numbers numbers
JOIN orders
  ON orders.user_id = CONCAT('fake_seed_', LPAD(numbers.number, 6, '0'))
WHERE NOT EXISTS (
    SELECT 1
    FROM order_items existing
    WHERE existing.order_id = orders.id
      AND existing.product_sku = CONCAT('FAKE-SEED-', LPAD(numbers.number, 6, '0'))
);

DROP TEMPORARY TABLE seed_numbers;
COMMIT;
SQL

read -r orders_count items_count < <(
  docker compose exec -T -e MYSQL_PWD="${MYSQL_ROOT_PASSWORD:-root}" mysql \
    mysql --user=root --batch --skip-column-names hardtech_orders \
    --execute "SELECT COUNT(*), (SELECT COUNT(*) FROM order_items oi JOIN orders o ON o.id = oi.order_id WHERE o.user_id LIKE 'fake_seed_%') FROM orders WHERE user_id LIKE 'fake_seed_%';"
)

if (( orders_count < SEED_COUNT || items_count < SEED_COUNT )); then
  echo "MySQL incompleto: orders=$orders_count order_items=$items_count requested=$SEED_COUNT" >&2
  exit 1
fi

echo "OK database=mysql table=orders fake_rows=$orders_count table=order_items fake_rows=$items_count requested=$SEED_COUNT"
