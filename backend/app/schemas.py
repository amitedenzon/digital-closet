from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


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
