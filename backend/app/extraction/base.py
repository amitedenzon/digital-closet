from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Protocol, runtime_checkable

from app.providers.base import RawMessage


@dataclass
class ExtractedItem:
    item_name: str
    brand: str | None = None
    size: str | None = None
    color: str | None = None
    quantity: int = 1
    price: Decimal | None = None
    image_url_src: str | None = None


@dataclass
class ExtractionResult:
    is_valid_apparel_purchase: bool
    vendor_name: str | None = None
    vendor_domain: str | None = None
    merchant_order_id: str | None = None
    purchase_date: datetime | None = None
    currency: str | None = None
    total_price: Decimal | None = None
    items: list[ExtractedItem] = field(default_factory=list)


@runtime_checkable
class Extractor(Protocol):
    async def extract(self, message: RawMessage) -> ExtractionResult: ...
