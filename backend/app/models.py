from __future__ import annotations

import enum
import uuid
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import (
    DateTime,
    Enum,
    ForeignKey,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class OrderStatus(str, enum.Enum):
    active = "active"
    shipped = "shipped"
    partially_returned = "partially_returned"
    returned = "returned"
    cancelled = "cancelled"


class ItemStatus(str, enum.Enum):
    active = "active"
    returned = "returned"
    cancelled = "cancelled"


class MessageResult(str, enum.Enum):
    extracted = "extracted"
    skipped_prefilter = "skipped_prefilter"
    skipped_llm = "skipped_llm"
    error = "error"


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Order(Base):
    __tablename__ = "orders"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    vendor_name: Mapped[str] = mapped_column(Text)
    vendor_domain: Mapped[str] = mapped_column(Text)
    merchant_order_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    purchase_date: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    currency: Mapped[str | None] = mapped_column(Text, nullable=True)
    total_price: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    status: Mapped[OrderStatus] = mapped_column(
        Enum(OrderStatus), default=OrderStatus.active
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )

    items: Mapped[list[Item]] = relationship("Item", back_populates="order")

    __table_args__ = (
        # NULL merchant_order_id bypasses this constraint (SQL NULL != NULL semantics).
        # repo.py UPSERT must handle the NULL case explicitly via a fallback key.
        UniqueConstraint("vendor_domain", "merchant_order_id", name="uq_order_dedup"),
    )


class Item(Base):
    __tablename__ = "items"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    order_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("orders.id"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    order: Mapped[Order] = relationship("Order", back_populates="items")
