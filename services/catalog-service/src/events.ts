import { randomUUID } from "node:crypto";

export type EventPayload = Record<string, unknown>;

export interface DomainEvent {
  event_id: string;
  event_type: string;
  timestamp: string;
  source: string;
  user_id: string | null;
  session_id: string | null;
  product_id: number | null;
  order_id: number | null;
  payload: EventPayload;
}

export interface EventContext {
  userId?: string;
  sessionId?: string;
  productId?: number;
  orderId?: number;
  occurredAt?: Date;
}

export function buildEvent(
  eventType: string,
  source: string,
  payload: EventPayload,
  context: EventContext = {}
): DomainEvent {
  const occurredAt = context.occurredAt ?? new Date();
  return {
    event_id: `evt_${randomUUID().replace(/-/g, "").slice(0, 8)}`,
    event_type: eventType,
    timestamp: occurredAt.toISOString().replace(/\.\d{3}Z$/, "Z"),
    source,
    user_id: context.userId ?? null,
    session_id: context.sessionId ?? null,
    product_id: context.productId ?? null,
    order_id: context.orderId ?? null,
    payload,
  };
}

export function buildEventKey(prefix: string, event: DomainEvent): string {
  const occurredAt = new Date(event.timestamp);
  const year = occurredAt.getUTCFullYear();
  const month = String(occurredAt.getUTCMonth() + 1).padStart(2, "0");
  const day = String(occurredAt.getUTCDate()).padStart(2, "0");
  const normalizedPrefix = prefix.replace(/^\/+|\/+$/g, "");
  return (
    `${normalizedPrefix}/year=${year}/month=${month}/day=${day}/` +
    `${event.event_type.toLowerCase()}_${event.event_id}.json`
  );
}

export function serializeEvent(event: DomainEvent): string {
  return JSON.stringify(event);
}
