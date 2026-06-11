from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas import ExtractionResult
from app.models import (
    Item,
    ItemStatus,  # noqa: F401 — used by apply_refund_or_cancellation (Task 5)
    MessageResult,
    Order,
    OrderStatus,  # noqa: F401 — used by apply_refund_or_cancellation (Task 5)
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
) -> tuple[Order, list[Item], list[str | None]]:
    """
    Insert a new order or update the existing one.

    Dedup priority:
    1. (vendor_domain, merchant_order_id) — explicit order ID match
    2. (vendor_domain, date(purchase_date), total_price) — fallback when order_id is NULL
    3. Always insert — if neither fires, log that message_id is the effective key

    Items are guarded by (item_name, size, color): an item already stored for this order
    is never re-inserted (protects against confirmation + shipping duplicate processing).

    Returns (order, new_items, new_image_urls) — only items inserted in this call.
    """
    existing: Order | None = None

    if extraction.vendor_domain and extraction.merchant_order_id:
        stmt = select(Order).where(
            Order.vendor_domain == extraction.vendor_domain,
            Order.merchant_order_id == extraction.merchant_order_id,
        )
        existing = (await session.execute(stmt)).scalar_one_or_none()
    elif (
        extraction.vendor_domain
        and extraction.purchase_date is not None
        and extraction.total_price is not None
    ):
        target_date = str(extraction.purchase_date.date())
        stmt = select(Order).where(
            Order.vendor_domain == extraction.vendor_domain,
            Order.merchant_order_id.is_(None),
            func.date(Order.purchase_date) == target_date,
            Order.total_price == extraction.total_price,
        )
        existing = (await session.execute(stmt)).scalar_one_or_none()
        if existing is not None:
            logger.info(
                "upsert_order: dedup_key=fallback vendor=%s date=%s price=%s",
                extraction.vendor_domain,
                target_date,
                extraction.total_price,
            )
        else:
            logger.info(
                "upsert_order: dedup_key=none vendor=%s — inserting new row",
                extraction.vendor_domain,
            )
    else:
        logger.warning(
            "upsert_order: dedup_key=none (insufficient fields) vendor=%r merchant_order_id=%r",
            extraction.vendor_domain,
            extraction.merchant_order_id,
        )

    if existing is not None:
        if extraction.total_price is not None:
            existing.total_price = extraction.total_price
        if extraction.currency:
            existing.currency = extraction.currency
        existing_items = (
            (await session.execute(select(Item).where(Item.order_id == existing.id)))
            .scalars()
            .all()
        )
        existing_keys: set[tuple[str, str | None, str | None]] = {
            (i.item_name.lower(), i.size, i.color) for i in existing_items
        }
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
        existing_keys = set()

    new_items: list[Item] = []
    new_image_urls: list[str | None] = []
    for item_data in extraction.items:
        natural_key = (item_data.item_name.lower(), item_data.size, item_data.color)
        if natural_key in existing_keys:
            logger.debug(
                "upsert_order: skip_duplicate_item item=%r order=%s",
                item_data.item_name,
                order.id,
            )
            continue
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
        new_image_urls.append(item_data.image_url)
    await session.flush()
    return order, new_items, new_image_urls


async def apply_refund_or_cancellation(
    session: AsyncSession,
    extraction: ExtractionResult,
) -> Order:
    """
    Stub — full implementation in Task 5 (returns/cancellations).
    Raises NotImplementedError until Task 5 is implemented.
    """
    raise NotImplementedError("apply_refund_or_cancellation not yet implemented")


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
