from __future__ import annotations

from datetime import datetime, timezone

import pytest  # noqa: F401 — used by future tests in this file
from sqlalchemy import func, select  # noqa: F401 — func used by future tests
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Item, ItemStatus, Order, OrderStatus  # noqa: F401 — future tests
from app.schemas import ExtractedItem, ExtractionResult
from app.store.repo import upsert_order


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


# ── DoD 4: missing order-id uses fallback key ─────────────────────────────────


async def test_missing_order_id_uses_date_price_fallback_key(session: AsyncSession):
    first = ExtractionResult(
        is_valid_apparel_purchase=True,
        vendor_name="Zara",
        vendor_domain="zara.com",
        merchant_order_id=None,
        purchase_date=datetime(2024, 5, 15, 12, 0, 0, tzinfo=timezone.utc),
        total_price=89.99,
        items=[ExtractedItem(item_name="Blue Jeans")],
    )
    order, _, _ = await upsert_order(session, first)
    await session.commit()

    second = ExtractionResult(
        is_valid_apparel_purchase=True,
        vendor_name="Zara",
        vendor_domain="zara.com",
        merchant_order_id=None,
        # Same date (different time within same UTC day) + same price → same order
        purchase_date=datetime(2024, 5, 15, 18, 0, 0, tzinfo=timezone.utc),
        total_price=89.99,
        items=[ExtractedItem(item_name="Blue Jeans")],
    )
    order2, new_items, _ = await upsert_order(session, second)
    await session.commit()

    assert order2.id == order.id, "fallback key must match the same order"
    assert new_items == [], "item already exists, must not be re-inserted"

    count = (
        await session.execute(select(func.count()).select_from(Order))
    ).scalar_one()
    assert count == 1


async def test_different_date_creates_new_order(session: AsyncSession):
    first = ExtractionResult(
        is_valid_apparel_purchase=True,
        vendor_name="Zara",
        vendor_domain="zara.com",
        merchant_order_id=None,
        purchase_date=datetime(2024, 5, 15, tzinfo=timezone.utc),
        total_price=89.99,
        items=[ExtractedItem(item_name="Blue Jeans")],
    )
    await upsert_order(session, first)
    await session.commit()

    second = ExtractionResult(
        is_valid_apparel_purchase=True,
        vendor_name="Zara",
        vendor_domain="zara.com",
        merchant_order_id=None,
        purchase_date=datetime(2024, 5, 16, tzinfo=timezone.utc),  # different date
        total_price=89.99,
        items=[ExtractedItem(item_name="Blue Jeans")],
    )
    await upsert_order(session, second)
    await session.commit()

    count = (
        await session.execute(select(func.count()).select_from(Order))
    ).scalar_one()
    assert count == 2


# ── DoD 2: marketplace per-item brand ────────────────────────────────────────


async def test_marketplace_per_item_brand_not_defaulted_to_vendor(
    session: AsyncSession,
):
    extraction = ExtractionResult(
        is_valid_apparel_purchase=True,
        vendor_name="ASOS",
        vendor_domain="asos.com",
        merchant_order_id="ASOS-500",
        purchase_date=datetime(2024, 4, 1, tzinfo=timezone.utc),
        items=[
            ExtractedItem(item_name="Slim Fit Jeans", brand="Levi's"),
            ExtractedItem(item_name="Graphic Tee", brand="Nike"),
        ],
    )
    order, items, _ = await upsert_order(session, extraction)
    await session.commit()

    assert order.vendor_domain == "asos.com"
    assert len(items) == 2
    brands = {i.brand for i in items}
    assert "Levi's" in brands
    assert "Nike" in brands
    # Brands must never be defaulted to the vendor domain or vendor name
    assert "asos.com" not in brands
    assert "ASOS" not in brands


# ── DoD 3: refund flips item status ──────────────────────────────────────────


async def test_refund_flips_items_to_returned_and_updates_order_status(
    session: AsyncSession,
):
    purchase = _make_extraction(
        items=[
            ExtractedItem(item_name="Blue Jeans"),
            ExtractedItem(item_name="White Tee"),
        ]
    )
    order, items, _ = await upsert_order(session, purchase)
    await session.commit()

    assert all(i.status == ItemStatus.active for i in items)
    assert order.status == OrderStatus.active

    refund = ExtractionResult(
        is_valid_apparel_purchase=True,
        is_refund_or_cancellation=True,
        vendor_name="Zara",
        vendor_domain="zara.com",
        merchant_order_id="ZR-001",
        purchase_date=datetime(2024, 1, 1, tzinfo=timezone.utc),
    )
    from app.store.repo import apply_refund_or_cancellation

    returned_order = await apply_refund_or_cancellation(session, refund)
    await session.commit()

    assert returned_order.id == order.id

    refreshed_items = (
        (await session.execute(select(Item).where(Item.order_id == order.id)))
        .scalars()
        .all()
    )
    assert all(i.status == ItemStatus.returned for i in refreshed_items)

    refreshed_order = (
        await session.execute(select(Order).where(Order.id == order.id))
    ).scalar_one()
    assert refreshed_order.status == OrderStatus.returned


async def test_refund_seen_before_order_creates_returned_stub(session: AsyncSession):
    refund = ExtractionResult(
        is_valid_apparel_purchase=True,
        is_refund_or_cancellation=True,
        vendor_name="Zara",
        vendor_domain="zara.com",
        merchant_order_id="ZR-999",
        purchase_date=datetime(2024, 2, 1, tzinfo=timezone.utc),
    )
    from app.store.repo import apply_refund_or_cancellation

    order = await apply_refund_or_cancellation(session, refund)
    await session.commit()

    assert order.status == OrderStatus.returned
    assert order.merchant_order_id == "ZR-999"
