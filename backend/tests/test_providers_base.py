from datetime import datetime, timezone


def test_provider_query_construction():
    from app.providers.base import ProviderQuery

    q = ProviderQuery(
        after=datetime(2023, 1, 1, tzinfo=timezone.utc),
        before=datetime(2026, 1, 1, tzinfo=timezone.utc),
        subject_any=["order", "receipt"],
        category_purchases=True,
        sender_domains=["zara.com"],
    )
    assert q.after.year == 2023
    assert q.sender_domains == ["zara.com"]


def test_message_ref_construction():
    from app.providers.base import MessageRef

    ref = MessageRef(
        message_id="abc123",
        internal_date=datetime(2024, 6, 1, tzinfo=timezone.utc),
    )
    assert ref.message_id == "abc123"


def test_page_construction():
    from app.providers.base import MessageRef, Page

    page = Page(
        refs=[MessageRef("m1", datetime(2024, 1, 1, tzinfo=timezone.utc))],
        next_cursor="tok_abc",
    )
    assert len(page.refs) == 1
    assert page.next_cursor == "tok_abc"


def test_raw_message_image_srcs_defaults_to_empty():
    from datetime import datetime, timezone

    from app.providers.base import RawMessage

    msg = RawMessage(
        message_id="m1",
        account="a@b.com",
        from_addr="store@brand.com",
        subject="Order confirmed",
        date=datetime(2024, 1, 1, tzinfo=timezone.utc),
        text="Thanks for your order",
        html=None,
    )
    assert msg.image_srcs == []


def test_extraction_result_defaults():
    from app.extraction.base import ExtractionResult

    r = ExtractionResult(is_valid_apparel_purchase=False)
    assert r.vendor_name is None
    assert r.items == []


def test_extracted_item_defaults():
    from app.extraction.base import ExtractedItem

    item = ExtractedItem(item_name="Blue Jeans")
    assert item.brand is None
    assert item.quantity == 1


def test_extractor_protocol_is_structural():
    from app.extraction.base import Extractor
    from app.providers.base import RawMessage

    class MyExtractor:
        async def extract(self, message: RawMessage):
            from app.extraction.base import ExtractionResult

            return ExtractionResult(is_valid_apparel_purchase=False)

    # Structural subtyping: no explicit inheritance needed
    assert issubclass(MyExtractor, Extractor)


def test_mail_provider_protocol_is_structural():
    from app.providers.base import MailProvider, Page

    class MyProvider:
        async def search(self, query, cursor):
            return Page(refs=[], next_cursor=None)

        async def fetch(self, message_id):
            pass

    assert issubclass(MyProvider, MailProvider)
