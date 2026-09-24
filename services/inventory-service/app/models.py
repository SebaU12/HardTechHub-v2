from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


PositiveProductId = Annotated[int, Field(gt=0)]


class StockResponse(BaseModel):
    product_id: int
    available_quantity: int
    reserved_quantity: int
    sellable_quantity: int
    minimum_quantity: int
    low_stock: bool
    updated_at: datetime


class LowStockResponse(BaseModel):
    items: list[StockResponse]
    limit: int
    offset: int


class AdjustmentRequest(BaseModel):
    product_id: PositiveProductId
    quantity_delta: int
    minimum_quantity: int | None = Field(default=None, ge=0)
    reason: str = Field(min_length=1, max_length=500)

    @field_validator("quantity_delta")
    @classmethod
    def delta_cannot_be_zero(cls, value: int) -> int:
        if value == 0:
            raise ValueError("quantity_delta must not be zero")
        return value

    @field_validator("reason")
    @classmethod
    def reason_cannot_be_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("reason must not be blank")
        return value


class ReservationItemRequest(BaseModel):
    product_id: PositiveProductId
    quantity: int = Field(ge=1, le=1000)


class CreateReservationRequest(BaseModel):
    user_id: str = Field(min_length=1, max_length=80)
    items: list[ReservationItemRequest] = Field(min_length=1)

    @field_validator("user_id")
    @classmethod
    def user_id_cannot_be_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("user_id must not be blank")
        return value


class ReservationItemResponse(BaseModel):
    product_id: int
    quantity: int


class ReservationResponse(BaseModel):
    reservation_id: UUID
    status: Literal["ACTIVE", "CONFIRMED", "RELEASED", "EXPIRED", "CANCELLED"]
    expires_at: datetime
    order_id: int | None = None
    items: list[ReservationItemResponse]


class ConfirmReservationRequest(BaseModel):
    order_id: int = Field(gt=0)


class CancelReservationRequest(BaseModel):
    order_id: int = Field(gt=0)
    reason: str = Field(min_length=1, max_length=500)

    @field_validator("reason")
    @classmethod
    def reason_cannot_be_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("reason must not be blank")
        return value
