#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
cd "$ROOT_DIR"

MINIMUM_COUNT=${1:-20000}
if [[ ! "$MINIMUM_COUNT" =~ ^[0-9]+$ ]] || (( MINIMUM_COUNT < 20000 )); then
  echo "Uso: $0 [cantidad>=20000]" >&2
  exit 2
fi

docker compose up -d --wait postgres mysql mongodb

IFS='|' read -r postgres_count postgres_orphans < <(
  docker compose exec -T postgres psql \
    --username hardtech --dbname hardtech_catalog --tuples-only --no-align \
    --field-separator='|' \
    --command "
      SELECT
        count(*),
        count(*) FILTER (WHERE categories.id IS NULL OR brands.id IS NULL)
      FROM products
      LEFT JOIN categories ON categories.id = products.category_id
      LEFT JOIN brands ON brands.id = products.brand_id
      WHERE products.sku LIKE 'FAKE-SEED-%';
    "
)

read -r mysql_orders mysql_items mysql_orphans < <(
  docker compose exec -T -e MYSQL_PWD="${MYSQL_ROOT_PASSWORD:-root}" mysql \
    mysql --user=root --batch --skip-column-names hardtech_orders \
    --execute "
      SELECT
        COUNT(*),
        (SELECT COUNT(*) FROM order_items oi JOIN orders o ON o.id = oi.order_id WHERE o.user_id LIKE 'fake_seed_%'),
        (SELECT COUNT(*) FROM order_items oi LEFT JOIN orders o ON o.id = oi.order_id WHERE o.id IS NULL)
      FROM orders
      WHERE user_id LIKE 'fake_seed_%';
    "
)

mongo_count=$(docker compose exec -T mongodb mongosh --quiet \
  --host localhost \
  --port 27017 \
  --username "${MONGO_READER_USER:-hardtech_reader}" \
  --password "${MONGO_READER_PASSWORD:-hardtech_reader}" \
  --authenticationDatabase hardtech_identity \
  hardtech_identity \
  --eval 'db.users.countDocuments({user_id: {$regex: "^fake_seed_"}})')

if (( postgres_count < MINIMUM_COUNT )); then
  echo "FALLO PostgreSQL products=$postgres_count mínimo=$MINIMUM_COUNT" >&2
  exit 1
fi
if (( postgres_orphans != 0 )); then
  echo "FALLO PostgreSQL productos_huérfanos=$postgres_orphans" >&2
  exit 1
fi
if (( mysql_orders < MINIMUM_COUNT || mysql_items < MINIMUM_COUNT )); then
  echo "FALLO MySQL orders=$mysql_orders order_items=$mysql_items mínimo=$MINIMUM_COUNT" >&2
  exit 1
fi
if (( mysql_orphans != 0 )); then
  echo "FALLO MySQL items_huérfanos=$mysql_orphans" >&2
  exit 1
fi
if (( mongo_count < MINIMUM_COUNT )); then
  echo "FALLO MongoDB users=$mongo_count mínimo=$MINIMUM_COUNT" >&2
  exit 1
fi

echo "OK PostgreSQL products=$postgres_count orphan_products=$postgres_orphans"
echo "OK MySQL orders=$mysql_orders order_items=$mysql_items orphan_items=$mysql_orphans"
echo "OK MongoDB users=$mongo_count"
