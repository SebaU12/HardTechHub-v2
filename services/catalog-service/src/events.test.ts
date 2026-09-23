import assert from "node:assert/strict";
import test from "node:test";

import { buildEvent, buildEventKey, serializeEvent } from "./events";


test("buildEvent creates the common envelope", () => {
  const event = buildEvent(
    "PRODUCT_PRICE_CHANGED",
    "catalog-service",
    { previous_price: "100.00", new_price: "90.00" },
    { productId: 3, occurredAt: new Date("2026-09-23T15:30:00Z") }
  );

  assert.match(event.event_id, /^evt_[0-9a-f]{8}$/);
  assert.equal(event.timestamp, "2026-09-23T15:30:00Z");
  assert.equal(event.product_id, 3);
  assert.equal(event.user_id, null);
  assert.deepEqual(JSON.parse(serializeEvent(event)), event);
});

test("buildEventKey normalizes the prefix and partitions by UTC date", () => {
  const event = buildEvent(
    "PRODUCT_UPDATED",
    "catalog-service",
    { sku: "CPU-1" },
    { occurredAt: new Date("2026-01-02T23:59:59Z") }
  );
  assert.equal(
    buildEventKey("/raw/events/catalog/", event),
    `raw/events/catalog/year=2026/month=01/day=02/product_updated_${event.event_id}.json`
  );
});
