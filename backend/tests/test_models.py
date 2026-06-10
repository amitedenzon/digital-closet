from datetime import datetime, timezone
from decimal import Decimal

import pytest
import sqlalchemy as sa
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings


def test_settings_accepts_database_url():
    s = Settings(DATABASE_URL="sqlite+aiosqlite:///./test.db")
    assert s.DATABASE_URL == "sqlite+aiosqlite:///./test.db"


def test_settings_has_default_database_url():
    s = Settings()
    assert s.DATABASE_URL.startswith("sqlite+aiosqlite://")


async def test_make_engine_connects():
    from app.db import make_engine

    engine = make_engine("sqlite+aiosqlite:///:memory:")
    async with engine.connect() as conn:
        result = await conn.execute(sa.text("SELECT 1"))
        assert result.scalar() == 1
    await engine.dispose()


async def test_make_session_factory_yields_async_session():
    from app.db import make_engine, make_session_factory

    engine = make_engine("sqlite+aiosqlite:///:memory:")
    factory = make_session_factory(engine)
    async with factory() as session:
        assert isinstance(session, AsyncSession)
    await engine.dispose()


def test_order_status_values():
    from app.models import OrderStatus

    assert set(e.value for e in OrderStatus) == {
        "active",
        "shipped",
        "partially_returned",
        "returned",
        "cancelled",
    }


def test_item_status_values():
    from app.models import ItemStatus

    assert set(e.value for e in ItemStatus) == {"active", "returned", "cancelled"}


def test_message_result_values():
    from app.models import MessageResult

    assert set(e.value for e in MessageResult) == {
        "extracted",
        "skipped_prefilter",
        "skipped_llm",
        "error",
    }


async def test_order_table_created(session: AsyncSession):
    result = await session.execute(
        text("SELECT name FROM sqlite_master WHERE type='table' AND name='orders'")
    )
    assert result.scalar() == "orders"


async def test_order_insert_and_retrieve(session: AsyncSession):
    from app.models import Order, OrderStatus

    order = Order(
        vendor_name="Zara",
        vendor_domain="zara.com",
        merchant_order_id="ORDER-001",
        purchase_date=datetime(2024, 1, 15, tzinfo=timezone.utc),
    )
    session.add(order)
    await session.commit()

    result = await session.execute(
        select(Order).where(Order.vendor_domain == "zara.com")
    )
    saved = result.scalar_one()
    assert saved.vendor_name == "Zara"
    assert saved.status == OrderStatus.active
    assert len(saved.id) == 36  # UUID string


async def test_duplicate_order_raises_integrity_error(session: AsyncSession):
    from app.models import Order

    order1 = Order(
        vendor_name="Nike",
        vendor_domain="nike.com",
        merchant_order_id="NIKE-001",
        purchase_date=datetime(2024, 5, 10, tzinfo=timezone.utc),
    )
    session.add(order1)
    await session.commit()

    order2 = Order(
        vendor_name="Nike",
        vendor_domain="nike.com",
        merchant_order_id="NIKE-001",
        purchase_date=datetime(2024, 5, 11, tzinfo=timezone.utc),
    )
    session.add(order2)
    with pytest.raises(IntegrityError):
        await session.commit()
    await session.rollback()


async def test_items_table_created(session: AsyncSession):
    result = await session.execute(
        text("SELECT name FROM sqlite_master WHERE type='table' AND name='items'")
    )
    assert result.scalar() == "items"


async def test_order_with_two_items(session: AsyncSession):
    from app.models import Item, Order

    order = Order(
        vendor_name="ASOS",
        vendor_domain="asos.com",
        merchant_order_id="ASOS-999",
        purchase_date=datetime(2024, 3, 1, tzinfo=timezone.utc),
        currency="GBP",
        total_price=Decimal("89.99"),
    )
    session.add(order)
    await session.flush()

    session.add_all(
        [
            Item(
                order_id=order.id,
                item_name="Blue Jeans",
                size="32",
                color="blue",
                quantity=1,
                price=Decimal("49.99"),
            ),
            Item(
                order_id=order.id,
                item_name="White T-Shirt",
                size="M",
                color="white",
                quantity=1,
                price=Decimal("19.99"),
            ),
        ]
    )
    await session.commit()

    result = await session.execute(
        select(Order).where(Order.vendor_domain == "asos.com")
    )
    saved_order = result.scalar_one()

    item_result = await session.execute(
        select(Item).where(Item.order_id == saved_order.id)
    )
    saved_items = item_result.scalars().all()
    assert len(saved_items) == 2
    assert {i.item_name for i in saved_items} == {"Blue Jeans", "White T-Shirt"}


async def test_processed_messages_table_created(session: AsyncSession):
    result = await session.execute(
        text(
            "SELECT name FROM sqlite_master WHERE type='table'"
            " AND name='processed_messages'"
        )
    )
    assert result.scalar() == "processed_messages"


async def test_processed_message_insert(session: AsyncSession):
    from app.models import MessageResult, ProcessedMessage

    msg = ProcessedMessage(
        message_id="gmail-abc123",
        provider="gmail",
        account="amit@gmail.com",
        result=MessageResult.extracted,
    )
    session.add(msg)
    await session.commit()

    result = await session.execute(
        select(ProcessedMessage).where(ProcessedMessage.message_id == "gmail-abc123")
    )
    saved = result.scalar_one()
    assert saved.provider == "gmail"
    assert saved.result == MessageResult.extracted
    assert saved.order_id is None


async def test_sync_state_table_created(session: AsyncSession):
    result = await session.execute(
        text("SELECT name FROM sqlite_master WHERE type='table' AND name='sync_state'")
    )
    assert result.scalar() == "sync_state"


async def test_sync_state_insert(session: AsyncSession):
    from app.models import SyncState

    state = SyncState(
        provider="gmail",
        account="amit@gmail.com",
        cursor="internalDate:1234567890",
    )
    session.add(state)
    await session.commit()

    result = await session.execute(
        select(SyncState).where(SyncState.provider == "gmail")
    )
    saved = result.scalar_one()
    assert saved.cursor == "internalDate:1234567890"
    assert saved.id is not None


async def test_sync_state_duplicate_provider_account_rejected(session: AsyncSession):
    from app.models import SyncState

    session.add(SyncState(provider="gmail", account="a@b.com", cursor="tok1"))
    await session.commit()

    session.add(SyncState(provider="gmail", account="a@b.com", cursor="tok2"))
    with pytest.raises(IntegrityError):
        await session.commit()
    await session.rollback()
