from datetime import datetime, timezone

from sqlalchemy import select
from app.extraction.base import CleanedMessage
from app.schemas import ExtractedItem, ExtractionResult
from app.models import MessageResult, Order, ProcessedMessage
from app.providers.base import MessageRef, Page, RawMessage
from app.store import repo


def _raw_message(message_id: str = "msg-1") -> RawMessage:
    return RawMessage(
        message_id=message_id,
        account="test@gmail.com",
        from_addr="noreply@zara.com",
        subject="Your order confirmation #12345",
        date=datetime(2024, 1, 1, tzinfo=timezone.utc),
        text="Order confirmed!",
        html=None,
    )


def _good_extraction() -> ExtractionResult:
    return ExtractionResult(
        is_valid_apparel_purchase=True,
        vendor_name="Zara",
        vendor_domain="zara.com",
        merchant_order_id="12345",
        purchase_date=datetime(2024, 1, 1, tzinfo=timezone.utc),
        currency="USD",
        total_price=49.99,
        items=[ExtractedItem(item_name="Blue Jeans", quantity=1)],
    )


class FakeProvider:
    def __init__(self, refs: list[MessageRef], messages: dict[str, RawMessage]):
        self._refs = refs
        self._messages = messages

    async def search(self, query, cursor):
        if cursor is None:
            return Page(refs=self._refs, next_cursor=None)
        return Page(refs=[], next_cursor=None)

    async def fetch(self, message_id: str) -> RawMessage:
        return self._messages[message_id]


class FakeExtractor:
    def __init__(self, result: ExtractionResult):
        self._result = result

    async def extract(self, message: CleanedMessage) -> ExtractionResult:
        return self._result


async def test_run_initialize_processes_message_and_stores_order(session_factory):
    from app.ingestion.pipeline import run_initialize

    ref = MessageRef("msg-1", datetime(2024, 1, 1, tzinfo=timezone.utc))
    provider = FakeProvider([ref], {"msg-1": _raw_message()})
    extractor = FakeExtractor(_good_extraction())

    result = await run_initialize(
        provider,
        extractor,
        session_factory,
        provider_name="gmail",
        account="test@gmail.com",
    )

    assert result.scanned == 1
    assert result.kept == 1
    assert result.skipped == 0
    assert result.errors == 0

    async with session_factory() as session:
        orders = (await session.execute(select(Order))).scalars().all()
        assert len(orders) == 1
        assert orders[0].vendor_domain == "zara.com"


async def test_second_run_is_noop(session_factory):
    from app.ingestion.pipeline import run_initialize

    ref = MessageRef("msg-1", datetime(2024, 1, 1, tzinfo=timezone.utc))
    provider = FakeProvider([ref], {"msg-1": _raw_message()})
    extractor = FakeExtractor(_good_extraction())

    await run_initialize(
        provider,
        extractor,
        session_factory,
        provider_name="gmail",
        account="test@gmail.com",
    )
    result2 = await run_initialize(
        provider,
        extractor,
        session_factory,
        provider_name="gmail",
        account="test@gmail.com",
    )

    assert result2.scanned == 1
    assert result2.skipped == 1
    assert result2.kept == 0

    async with session_factory() as session:
        count = len((await session.execute(select(Order))).scalars().all())
        assert count == 1


async def test_prefilter_skip_records_skipped_prefilter(session_factory):
    from app.ingestion.pipeline import run_initialize

    promo_msg = RawMessage(
        message_id="promo-1",
        account="test@gmail.com",
        from_addr="news@unknown-brand.com",
        subject="Sale — 50% off everything today",
        date=datetime(2024, 1, 1, tzinfo=timezone.utc),
        text=None,
        html=None,
    )
    ref = MessageRef("promo-1", datetime(2024, 1, 1, tzinfo=timezone.utc))
    provider = FakeProvider([ref], {"promo-1": promo_msg})
    extractor = FakeExtractor(_good_extraction())

    result = await run_initialize(
        provider,
        extractor,
        session_factory,
        provider_name="gmail",
        account="test@gmail.com",
    )

    assert result.scanned == 1
    assert result.skipped == 1
    assert result.kept == 0

    async with session_factory() as session:
        pm = (
            await session.execute(
                select(ProcessedMessage).where(ProcessedMessage.message_id == "promo-1")
            )
        ).scalar_one()
        assert pm.result == MessageResult.skipped_prefilter


async def test_llm_rejected_records_skipped_llm(session_factory):
    from app.ingestion.pipeline import run_initialize

    ref = MessageRef("msg-1", datetime(2024, 1, 1, tzinfo=timezone.utc))
    provider = FakeProvider([ref], {"msg-1": _raw_message()})
    extractor = FakeExtractor(ExtractionResult(is_valid_apparel_purchase=False))

    result = await run_initialize(
        provider,
        extractor,
        session_factory,
        provider_name="gmail",
        account="test@gmail.com",
    )

    assert result.skipped == 1
    assert result.kept == 0

    async with session_factory() as session:
        pm = (
            await session.execute(
                select(ProcessedMessage).where(ProcessedMessage.message_id == "msg-1")
            )
        ).scalar_one()
        assert pm.result == MessageResult.skipped_llm


async def test_error_during_extraction_records_error(session_factory):
    from app.ingestion.pipeline import run_initialize

    class ErrorExtractor:
        async def extract(self, message):
            raise ValueError("LLM timeout")

    ref = MessageRef("msg-err", datetime(2024, 1, 1, tzinfo=timezone.utc))
    provider = FakeProvider([ref], {"msg-err": _raw_message("msg-err")})

    result = await run_initialize(
        provider,
        ErrorExtractor(),
        session_factory,
        provider_name="gmail",
        account="test@gmail.com",
    )

    assert result.errors == 1
    assert result.kept == 0

    async with session_factory() as session:
        pm = (
            await session.execute(
                select(ProcessedMessage).where(ProcessedMessage.message_id == "msg-err")
            )
        ).scalar_one()
        assert pm.result == MessageResult.error


async def test_sync_cursor_written_after_drain(session_factory):
    from app.ingestion.pipeline import run_initialize

    internal_date = datetime(2024, 6, 1, 12, 0, 0, tzinfo=timezone.utc)
    msg = RawMessage(
        message_id="msg-1",
        account="test@gmail.com",
        from_addr="noreply@zara.com",
        subject="Your order confirmation #12345",
        date=internal_date,
        text="Order confirmed!",
        html=None,
    )
    ref = MessageRef("msg-1", internal_date)
    provider = FakeProvider([ref], {"msg-1": msg})
    extractor = FakeExtractor(_good_extraction())

    await run_initialize(
        provider,
        extractor,
        session_factory,
        provider_name="gmail",
        account="test@gmail.com",
    )

    async with session_factory() as session:
        state = await repo.get_or_create_sync_state(session, "gmail", "test@gmail.com")
        assert state.cursor is not None
        dt = repo.cursor_to_datetime(state.cursor)
        assert dt is not None
        assert abs((dt - internal_date).total_seconds()) < 1


async def test_run_since_checkpoint_uses_stored_cursor(session_factory):
    from app.ingestion.pipeline import run_since_checkpoint
    from app.store.repo import update_sync_cursor

    epoch_ms = str(int(datetime(2024, 6, 1, tzinfo=timezone.utc).timestamp() * 1000))
    async with session_factory() as session:
        await update_sync_cursor(session, "gmail", "test@gmail.com", epoch_ms)
        await session.commit()

    received_query = {}

    class CapturingProvider:
        async def search(self, query, cursor):
            received_query["after"] = query.after
            return Page(refs=[], next_cursor=None)

        async def fetch(self, message_id):
            raise AssertionError("Should not be called")

    await run_since_checkpoint(
        CapturingProvider(),
        FakeExtractor(_good_extraction()),
        session_factory,
        provider_name="gmail",
        account="test@gmail.com",
    )

    assert received_query["after"] == datetime(2024, 6, 1, tzinfo=timezone.utc)
