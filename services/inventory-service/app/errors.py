from __future__ import annotations

from typing import Any


class InventoryError(Exception):
    """Expected API/business error with a stable public code."""

    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        **details: Any,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details

    def body(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message, **self.details}


def not_found(code: str, message: str, **details: Any) -> InventoryError:
    return InventoryError(404, code, message, **details)


def conflict(code: str, message: str, **details: Any) -> InventoryError:
    return InventoryError(409, code, message, **details)


class DatabaseUnavailable(InventoryError):
    def __init__(self) -> None:
        super().__init__(
            503,
            "INVENTORY_DATABASE_UNAVAILABLE",
            "Inventory database is unavailable",
        )
