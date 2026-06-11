from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import httpx
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.extraction.base import Extractor
from app.extraction.cleaner import clean_message
from app.ingestion import images
from app.ingestion.prefilter import should_keep
from app.jobs import JobState
from app.models import MessageResult
from app.providers.base import MailProvider, ProviderQuery
from app.store import repo

logger = logging.getLogger(__name__)
_settings = Settings()

_SUBJECT_KEYWORDS = [
    "order",
    "receipt",
    "invoice",
    "confirmation",
    "shipped",
    "dispatched",
    "on its way",
    "delivered",
    "refund",
    "return",
    "order confirmation",
]

DEFAULT_STOP_YEAR = 2023


@dataclass
class JobResult:
    scanned: int = 0
    kept: int = 0
    skipped: int = 0
    errors: int = 0


async def run_initialize(
    provider: MailProvider,
    extractor: Extractor,
    session_factory: async_sessionmaker[AsyncSession],
    *,
    provider_name: str,
    account: str,
    stop_year: int = DEFAULT_STOP_YEAR,
    job_state: JobState | None = None,
) -> JobResult:
    query = ProviderQuery(
        after=datetime(stop_year, 1, 1, tzinfo=timezone.utc),
        before=datetime.now(timezone.utc),
        subject_any=_SUBJECT_KEYWORDS,
        category_purchases=True,
    )
    return await _drain(
        provider,
        extractor,
        session_factory,
        query=query,
        provider_name=provider_name,
        account=account,
        job_state=job_state,
    )


async def run_since_checkpoint(
    provider: MailProvider,
    extractor: Extractor,
    session_factory: async_sessionmaker[AsyncSession],
    *,
    provider_name: str,
    account: str,
    stop_year: int = DEFAULT_STOP_YEAR,
    job_state: JobState | None = None,
) -> JobResult:
    async with session_factory() as session:
        state = await repo.get_or_create_sync_state(session, provider_name, account)
        cursor_date = repo.cursor_to_datetime(state.cursor)
        await session.commit()

    after = cursor_date or datetime(stop_year, 1, 1, tzinfo=timezone.utc)
    query = ProviderQuery(
        after=after,
        before=datetime.now(timezone.utc),
        subject_any=_SUBJECT_KEYWORDS,
        category_purchases=True,
    )
    return await _drain(
        provider,
        extractor,
        session_factory,
        query=query,
        provider_name=provider_name,
        account=account,
        job_state=job_state,
    )


async def _drain(
    provider: MailProvider,
    extractor: Extractor,
    session_factory: async_sessionmaker[AsyncSession],
    *,
    query: ProviderQuery,
    provider_name: str,
    account: str,
    job_state: JobState | None = None,
) -> JobResult:
    result = JobResult()
    page_cursor: str | None = None
    max_internal_date: datetime | None = None

    async with httpx.AsyncClient() as http_client:
        while True:
            page = await provider.search(query, page_cursor)

            for ref in page.refs:
                result.scanned += 1
                if job_state is not None:
                    job_state.scanned += 1

                async with session_factory() as session:
                    if await repo.is_processed(session, ref.message_id):
                        result.skipped += 1
                        if job_state is not None:
                            job_state.skipped += 1
                        logger.debug(
                            "skip:already_processed message_id=%s", ref.message_id
                        )
                        continue

                    try:
                        message = await provider.fetch(ref.message_id)
                        if (
                            max_internal_date is None
                            or message.date > max_internal_date
                        ):
                            max_internal_date = message.date

                        if not should_keep(message):
                            await repo.record_processed(
                                session,
                                message_id=ref.message_id,
                                provider=provider_name,
                                account=account,
                                result=MessageResult.skipped_prefilter,
                            )
                            await session.commit()
                            result.skipped += 1
                            if job_state is not None:
                                job_state.skipped += 1
                            logger.info(
                                "skip:prefilter message_id=%s subject=%r",
                                ref.message_id,
                                message.subject,
                            )
                            continue

                        cleaned = clean_message(
                            message, max_chars=_settings.BODY_TEXT_MAX_CHARS
                        )
                        extraction = await extractor.extract(cleaned)

                        if not extraction.is_valid_apparel_purchase:
                            await repo.record_processed(
                                session,
                                message_id=ref.message_id,
                                provider=provider_name,
                                account=account,
                                result=MessageResult.skipped_llm,
                            )
                            await session.commit()
                            result.skipped += 1
                            if job_state is not None:
                                job_state.skipped += 1
                            logger.info("skip:llm message_id=%s", ref.message_id)
                            continue

                        order, db_items = await repo.upsert_order(session, extraction)
                        await images.download_order_images(
                            db_items,
                            [item.image_url for item in extraction.items],
                            vendor_domain=extraction.vendor_domain or "",
                            order_id=order.id,
                            store_dir=Path(_settings.IMAGE_STORE_DIR),
                            client=http_client,
                            min_dimension=_settings.IMAGE_MIN_DIMENSION,
                        )
                        await repo.record_processed(
                            session,
                            message_id=ref.message_id,
                            provider=provider_name,
                            account=account,
                            result=MessageResult.extracted,
                            order_id=order.id,
                        )
                        await session.commit()
                        result.kept += 1
                        if job_state is not None:
                            job_state.kept += 1
                        logger.info(
                            "extracted message_id=%s order_id=%s",
                            ref.message_id,
                            order.id,
                        )

                    except Exception as exc:
                        await session.rollback()
                        try:
                            async with session_factory() as err_session:
                                await repo.record_processed(
                                    err_session,
                                    message_id=ref.message_id,
                                    provider=provider_name,
                                    account=account,
                                    result=MessageResult.error,
                                )
                                await err_session.commit()
                        except Exception as record_exc:
                            logger.exception(
                                "error:failed_to_record_error message_id=%s",
                                ref.message_id,
                                exc_info=record_exc,
                            )
                        result.errors += 1
                        if job_state is not None:
                            job_state.errors += 1
                        logger.exception(
                            "error:processing message_id=%s",
                            ref.message_id,
                            exc_info=exc,
                        )

            if page.next_cursor is None:
                break
            page_cursor = page.next_cursor

    if max_internal_date is not None:
        new_ms = int(max_internal_date.timestamp() * 1000)
        async with session_factory() as session:
            state = await repo.get_or_create_sync_state(session, provider_name, account)
            old_ms = int(state.cursor) if state.cursor else 0
            cursor_str = str(max(new_ms, old_ms))
            await repo.update_sync_cursor(session, provider_name, account, cursor_str)
            await session.commit()

    return result
