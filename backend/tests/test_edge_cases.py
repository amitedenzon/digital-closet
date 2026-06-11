from __future__ import annotations

from datetime import datetime, timezone

import pytest  # noqa: F401 — used by future tests in this file
from sqlalchemy import func, select  # noqa: F401 — func used by future tests
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Item, ItemStatus, Order, OrderStatus  # noqa: F401 — future tests
from app.schemas import ExtractedItem, ExtractionResult
from app.store.repo import apply_refund_or_cancellation, upsert_order  # noqa: F401


def _make_extraction(**kwargs) -> ExtractionResult:
    defaults = dict(
        is_valid_apparel_purchase=True,
        vendor_name="Zara",
        vendor_domain="zara.com",
        merchant_order_id="ZR-001",
        purchase_date=datetime(2024, 1, 1, tzinfo=timezone.utc),
        currency="USD",
        total_price=99.99,
        items=[ExtractedItem(item_name="Blue Jeans", quantity=1)],
    )
    defaults.update(kwargs)
    return ExtractionResult(**defaults)


# ── DoD 1: duplicate order across two emails — no dup items ───────────────────


async def test_duplicate_order_across_two_emails_no_dup_items(session: AsyncSession):
    confirmation = _make_extraction(
        items=[
            ExtractedItem(item_name="Slim Fit Jeans", size="M", color="blue"),
            ExtractedItem(item_name="Cotton Tee", size="S", color="white"),
        ]
    )
    order, _, _ = await upsert_order(session, confirmation)
    await session.commit()

    shipping_notice = _make_extraction(
        items=[
            ExtractedItem(item_name="Slim Fit Jeans", size="M", color="blue"),
            ExtractedItem(item_name="Cotton Tee", size="S", color="white"),
        ]
    )
    _, new_items, _ = await upsert_order(session, shipping_notice)
    await session.commit()

    assert new_items == [], "shipping notice must not re-insert existing items"

    all_items = (
        (await session.execute(select(Item).where(Item.order_id == order.id)))
        .scalars()
        .all()
    )
    assert len(all_items) == 2
