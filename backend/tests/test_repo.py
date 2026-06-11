from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas import ExtractedItem, ExtractionResult
from app.models import MessageResult, Order


def _extraction(
    vendor_domain: str = "zara.com",
    merchant_order_id: str | None = "ZR-001",
    **kwargs,
) -> ExtractionResult:
    defaults = dict(
        is_valid_apparel_purchase=True,
        vendor_name="Zara",
        vendor_domain=vendor_domain,
        merchant_order_id=merchant_order_id,
        purchase_date=datetime(2024, 1, 1, tzinfo=timezone.utc),
        currency="USD",
        total_price=99.99,
        items=[ExtractedItem(item_name="Blue Jeans", quantity=1)],
    )
    defaults.update(kwargs)
    return ExtractionResult(**defaults)


async def test_is_processed_false_for_new_message(session: AsyncSession):
    from app.store.repo import is_processed

    assert await is_processed(session, "msg-999") is False


async def test_is_processed_true_after_record(session: AsyncSession):
    from app.store.repo import is_processed, record_processed

    await record_processed(
        session,
        message_id="msg-1",
        provider="gmail",
        account="a@b.com",
        result=MessageResult.extracted,
    )
    await session.commit()

    assert await is_processed(session, "msg-1") is True


async def test_record_processed_stores_order_id(session: AsyncSession):
    from sqlalchemy import select

    from app.models import ProcessedMessage
    from app.store.repo import record_processed

    await record_processed(
        session,
        message_id="msg-2",
        provider="gmail",
        account="a@b.com",
        result=MessageResult.extracted,
        order_id="some-uuid",
    )
    await session.commit()

    row = (
        await session.execute(
            select(ProcessedMessage).where(ProcessedMessage.message_id == "msg-2")
        )
    ).scalar_one()
    assert row.order_id == "some-uuid"


async def test_upsert_order_inserts_new(session: AsyncSession):
    from sqlalchemy import select

    from app.store.repo import upsert_order

    order = await upsert_order(session, _extraction())
    await session.commit()

    saved = (
        await session.execute(select(Order).where(Order.id == order.id))
    ).scalar_one()
    assert saved.vendor_domain == "zara.com"
    assert saved.merchant_order_id == "ZR-001"


async def test_upsert_order_updates_existing_not_duplicate(session: AsyncSession):
    from sqlalchemy import func, select

    from app.store.repo import upsert_order

    await upsert_order(session, _extraction(total_price=50.0))
    await session.commit()

    await upsert_order(session, _extraction(total_price=75.0))
    await session.commit()

    count = (
        await session.execute(select(func.count()).select_from(Order))
    ).scalar_one()
    assert count == 1  # no duplicate

    saved = (await session.execute(select(Order))).scalar_one()
    assert saved.total_price == Decimal("75.00")


async def test_upsert_order_replaces_items_on_update(session: AsyncSession):
    from sqlalchemy import select

    from app.models import Item
    from app.store.repo import upsert_order

    first = _extraction(
        items=[
            ExtractedItem(item_name="Old Shirt"),
            ExtractedItem(item_name="Old Jeans"),
        ]
    )
    await upsert_order(session, first)
    await session.commit()

    second = _extraction(items=[ExtractedItem(item_name="New Coat")])
    order = await upsert_order(session, second)
    await session.commit()

    items = (
        (await session.execute(select(Item).where(Item.order_id == order.id)))
        .scalars()
        .all()
    )
    assert len(items) == 1
    assert items[0].item_name == "New Coat"


async def test_upsert_order_null_merchant_id_always_inserts(session: AsyncSession):
    from sqlalchemy import func, select

    from app.store.repo import upsert_order

    await upsert_order(session, _extraction(merchant_order_id=None))
    await session.commit()
    await upsert_order(session, _extraction(merchant_order_id=None))
    await session.commit()

    count = (
        await session.execute(select(func.count()).select_from(Order))
    ).scalar_one()
    assert count == 2


async def test_get_or_create_sync_state_creates_once(session: AsyncSession):
    from app.store.repo import get_or_create_sync_state

    state1 = await get_or_create_sync_state(session, "gmail", "a@b.com")
    await session.commit()
    state2 = await get_or_create_sync_state(session, "gmail", "a@b.com")
    await session.commit()

    assert state1.id == state2.id


async def test_update_sync_cursor_stores_and_updates(session: AsyncSession):
    from app.store.repo import get_or_create_sync_state, update_sync_cursor

    await update_sync_cursor(session, "gmail", "a@b.com", "1700000000000")
    await session.commit()

    state = await get_or_create_sync_state(session, "gmail", "a@b.com")
    assert state.cursor == "1700000000000"
    assert state.last_run_at is not None


def test_cursor_to_datetime_none():
    from app.store.repo import cursor_to_datetime

    assert cursor_to_datetime(None) is None


def test_cursor_to_datetime_round_trips():
    from app.store.repo import cursor_to_datetime

    epoch_ms = 1700000000000
    dt = cursor_to_datetime(str(epoch_ms))
    assert dt is not None
    assert dt.tzinfo is not None
    # Round-trip: epoch_ms → datetime → epoch_ms should be within rounding error
    assert abs(int(dt.timestamp() * 1000) - epoch_ms) < 1
