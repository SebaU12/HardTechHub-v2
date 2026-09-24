from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


@dataclass
class InventoryClientError(Exception):
    status_code: int
    detail: dict[str, Any]

    @property
    def code(self) -> str:
        return str(self.detail.get("code", "INVENTORY_ERROR"))


class InventoryUnavailable(Exception):
    pass


class InventoryClient:
    def __init__(self) -> None:
        self.base_url = os.getenv(
            "INVENTORY_SERVICE_URL", "http://inventory-service:8006"
        ).rstrip("/")
        self.timeout = float(os.getenv("INVENTORY_TIMEOUT_SECONDS", "3"))
        self.retry_delays = (0.1, 0.3)

    def reserve(
        self,
        idempotency_key: str,
        user_id: str,
        items: list[dict[str, int]],
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            "/api/inventory/reservations",
            payload={"user_id": user_id, "items": items},
            headers={"Idempotency-Key": idempotency_key},
        )

    def get_reservation(self, reservation_id: str) -> dict[str, Any]:
        return self._request("GET", f"/api/inventory/reservations/{reservation_id}")

    def confirm(self, reservation_id: str, order_id: int) -> dict[str, Any]:
        return self._request(
            "POST",
            f"/api/inventory/reservations/{reservation_id}/confirm",
            payload={"order_id": order_id},
        )

    def release(self, reservation_id: str) -> dict[str, Any]:
        return self._request(
            "DELETE", f"/api/inventory/reservations/{reservation_id}"
        )

    def cancel(self, reservation_id: str, order_id: int, reason: str) -> dict[str, Any]:
        return self._request(
            "POST",
            f"/api/inventory/reservations/{reservation_id}/cancel",
            payload={"order_id": order_id, "reason": reason},
        )

    def _request(
        self,
        method: str,
        path: str,
        *,
        payload: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        request_headers = {"Accept": "application/json"}
        request_headers.update(headers or {})
        body = None
        if payload is not None:
            body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
            request_headers["Content-Type"] = "application/json"

        last_error: Exception | None = None
        attempts = len(self.retry_delays) + 1
        for attempt in range(attempts):
            request = Request(
                f"{self.base_url}{path}",
                data=body,
                headers=request_headers,
                method=method,
            )
            try:
                with urlopen(request, timeout=self.timeout) as response:
                    response_body = response.read().decode("utf-8")
                    return json.loads(response_body) if response_body else {}
            except HTTPError as exc:
                detail = self._error_detail(exc)
                if exc.code < 500:
                    raise InventoryClientError(exc.code, detail) from exc
                last_error = exc
            except (URLError, TimeoutError, OSError) as exc:
                last_error = exc

            if attempt < len(self.retry_delays):
                time.sleep(self.retry_delays[attempt])

        raise InventoryUnavailable("Inventory Service is unavailable") from last_error

    @staticmethod
    def _error_detail(error: HTTPError) -> dict[str, Any]:
        try:
            body = json.loads(error.read().decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return {
                "code": "INVENTORY_ERROR",
                "message": "Inventory Service returned an invalid error response",
            }
        detail = body.get("detail", body)
        if isinstance(detail, dict):
            return detail
        return {"code": "INVENTORY_ERROR", "message": str(detail)}
