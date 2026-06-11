from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict


class ExtractedItem(BaseModel):
    item_name: str
    brand: str | None = None
    size: str | None = None
    color: str | None = None
    quantity: int = 1
    price: float | None = None
    image_url: str | None = None


class ExtractionResult(BaseModel):
    is_valid_apparel_purchase: bool
    is_refund_or_cancellation: bool = False
    vendor_name: str | None = None
    vendor_domain: str | None = None
    merchant_order_id: str | None = None
    purchase_date: datetime | None = None
    currency: str | None = None
    total_price: float | None = None
    items: list[ExtractedItem] = []
    confidence: float | None = None


# ── API response / request models ────────────────────────────────────────────


class ItemResponse(BaseModel):
    """Flattened item + order info for GET /items."""

    id: str
    order_id: str
    item_name: str
    brand: str | None
    size: str | None
    color: str | None
    quantity: int
    price: float | None
    status: str
    vendor_name: str
    vendor_domain: str
    purchase_date: datetime
    created_at: datetime


class ItemBriefResponse(BaseModel):
    """Item fields used inside OrderWithItemsResponse."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    item_name: str
    brand: str | None
    size: str | None
    color: str | None
    quantity: int
    price: float | None
    status: str
    image_path: str | None


class OrderWithItemsResponse(BaseModel):
    """Order with nested items for GET /orders."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    vendor_name: str
    vendor_domain: str
    merchant_order_id: str | None
    purchase_date: datetime
    currency: str | None
    total_price: float | None
    status: str
    items: list[ItemBriefResponse]


class JobStatusResponse(BaseModel):
    """Response for GET /sync/status/{job_id}."""

    job_id: str
    state: str
    scanned: int
    kept: int
    skipped: int
    errors: int
    done: bool


class SyncInitRequest(BaseModel):
    """Body for POST /sync/init."""

    stop_year: int = 2023


class ItemStatusUpdate(BaseModel):
    """Body for POST /items/{item_id}/status."""

    status: Literal["active", "returned", "cancelled"]
