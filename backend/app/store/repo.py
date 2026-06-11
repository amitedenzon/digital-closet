from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas import ExtractionResult
from app.models import (
    Item,
    MessageResult,
    Order,
    ProcessedMessage,
    SyncState,
)

logger = logging.getLogger(__name__)


async def is_processed(session: AsyncSession, message_id: str) -> bool:
    stmt = select(ProcessedMessage.message_id).where(
        ProcessedMessage.message_id == message_id
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none() is not None


async def record_processed(
    session: AsyncSession,
    *,
    message_id: str,
    provider: str,
    account: str,
    result: MessageResult,
    order_id: str | None = None,
) -> None:
    session.add(
        ProcessedMessage(
            message_id=message_id,
            provider=provider,
            account=account,
            result=result,
            order_id=order_id,
        )
    )
    await session.flush()


async def upsert_order(
    session: AsyncSession,
    extraction: ExtractionResult,
) -> tuple[Order, list[Item]]:
    """
    Insert a new order or update the existing one matched by (vendor_domain, merchant_order_id).
    Items are always replaced wholesale (delete-all then re-insert) since we trust the
    latest extraction to be the most complete view of the order.
    NULL merchant_order_id bypasses dedup and always inserts a new row.
    Returns the order and the freshly-inserted Item ORM objects (with IDs populated).
    """
    existing: Order | None = None
    if extraction.vendor_domain and extraction.merchant_order_id:
        stmt = select(Order).where(
            Order.vendor_domain == extraction.vendor_domain,
            Order.merchant_order_id == extraction.merchant_order_id,
        )
        result = await session.execute(stmt)
        existing = result.scalar_one_or_none()
    else:
        logger.warning(
            "upsert_order: skipping dedup (vendor_domain=%r, merchant_order_id=%r) — will always insert new row",
            extraction.vendor_domain,
            extraction.merchant_order_id,
        )

    if existing is not None:
        if extraction.total_price is not None:
            existing.total_price = extraction.total_price
        if extraction.currency:
            existing.currency = extraction.currency
        # vendor_name and purchase_date are first-write-wins: later emails for the same
        # order (e.g. shipping notices) don't carry more accurate values than the original
        # confirmation, so we don't overwrite them.
        await session.execute(delete(Item).where(Item.order_id == existing.id))
        await session.flush()
        order = existing
    else:
        order = Order(
            vendor_name=extraction.vendor_name or "",
            vendor_domain=extraction.vendor_domain or "",
            merchant_order_id=extraction.merchant_order_id,
            purchase_date=extraction.purchase_date or datetime.now(timezone.utc),
            currency=extraction.currency,
            total_price=extraction.total_price,
        )
        session.add(order)
        await session.flush()

    new_items: list[Item] = []
    for item_data in extraction.items:
        item = Item(
            order_id=order.id,
            item_name=item_data.item_name,
            brand=item_data.brand,
            size=item_data.size,
            color=item_data.color,
            quantity=item_data.quantity,
            price=item_data.price,
            image_url_src=item_data.image_url,
        )
        session.add(item)
        new_items.append(item)
    await session.flush()
    return order, new_items


async def get_or_create_sync_state(
    session: AsyncSession, provider: str, account: str
) -> SyncState:
    stmt = select(SyncState).where(
        SyncState.provider == provider,
        SyncState.account == account,
    )
    result = await session.execute(stmt)
    state = result.scalar_one_or_none()
    if state is None:
        # TOCTOU race: concurrent callers could both see None and both attempt INSERT,
        # hitting uq_sync_state_provider_account with an IntegrityError. For the POC
        # this is acceptable since ingestion runs serially. A production fix would use
        # INSERT OR IGNORE + re-SELECT or move to INSERT RETURNING with ON CONFLICT.
        state = SyncState(provider=provider, account=account)
        session.add(state)
        await session.flush()
    return state


async def update_sync_cursor(
    session: AsyncSession, provider: str, account: str, cursor: str
) -> None:
    state = await get_or_create_sync_state(session, provider, account)
    state.cursor = cursor
    state.last_run_at = datetime.now(timezone.utc)
    await session.flush()


def cursor_to_datetime(cursor: str | None) -> datetime | None:
    """Convert epoch-ms string cursor to UTC datetime."""
    if cursor is None:
        return None
    return datetime.fromtimestamp(int(cursor) / 1000, tz=timezone.utc)
