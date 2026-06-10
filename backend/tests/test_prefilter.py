from datetime import datetime, timezone

from app.providers.base import RawMessage


def _msg(**kwargs) -> RawMessage:
    defaults = dict(
        message_id="test-id",
        account="me@gmail.com",
        from_addr="noreply@unknown-brand.com",
        subject="Hello",
        date=datetime(2024, 1, 1, tzinfo=timezone.utc),
        text=None,
        html=None,
    )
    defaults.update(kwargs)
    return RawMessage(**defaults)


KNOWN = frozenset(["zara.com", "asos.com"])
NO_DOMAINS: frozenset[str] = frozenset()


class TestPromoExclusion:
    def test_now_available_drops(self):
        from app.ingestion.prefilter import should_keep

        msg = _msg(subject="Now available: new arrivals", from_addr="news@zara.com")
        assert should_keep(msg, vendor_domains=KNOWN) is False

    def test_sale_in_subject_drops(self):
        from app.ingestion.prefilter import should_keep

        msg = _msg(subject="Summer sale — 40% off everything")
        assert should_keep(msg, vendor_domains=NO_DOMAINS) is False

    def test_promo_keyword_in_body_preview_drops(self):
        from app.ingestion.prefilter import should_keep

        msg = _msg(
            subject="Special for you",
            text="back in stock " + "x" * 200,
        )
        assert should_keep(msg, vendor_domains=NO_DOMAINS) is False

    def test_promo_keyword_beyond_200_chars_does_not_drop(self):
        from app.ingestion.prefilter import should_keep

        # promo keyword starts after the 200-char window
        msg = _msg(
            subject="Your order confirmation",
            text="x" * 205 + " sale happening now",
        )
        # Transactional subject means keep, even though body has "sale" after 200 chars
        assert should_keep(msg, vendor_domains=NO_DOMAINS) is True

    def test_case_insensitive_promo(self):
        from app.ingestion.prefilter import should_keep

        msg = _msg(subject="BACK IN STOCK: your fave item")
        assert should_keep(msg, vendor_domains=NO_DOMAINS) is False


class TestTransactionalSignal:
    def test_order_in_subject_keeps(self):
        from app.ingestion.prefilter import should_keep

        msg = _msg(subject="Your order #12345 is confirmed")
        assert should_keep(msg, vendor_domains=NO_DOMAINS) is True

    def test_receipt_in_subject_keeps(self):
        from app.ingestion.prefilter import should_keep

        msg = _msg(subject="Your receipt from Nike")
        assert should_keep(msg, vendor_domains=NO_DOMAINS) is True

    def test_shipped_in_subject_keeps(self):
        from app.ingestion.prefilter import should_keep

        msg = _msg(subject="Your package has been shipped")
        assert should_keep(msg, vendor_domains=NO_DOMAINS) is True

    def test_refund_in_subject_keeps(self):
        from app.ingestion.prefilter import should_keep

        msg = _msg(subject="Refund processed for order #999")
        assert should_keep(msg, vendor_domains=NO_DOMAINS) is True

    def test_hebrew_order_keeps(self):
        from app.ingestion.prefilter import should_keep

        msg = _msg(subject="הזמנה #45678 אושרה")
        assert should_keep(msg, vendor_domains=NO_DOMAINS) is True

    def test_transactional_in_body_only_does_not_keep(self):
        from app.ingestion.prefilter import should_keep

        # "order" only in body — step 2 checks subject; body is only for promo exclusion
        msg = _msg(subject="Hello there", text="Thanks for your order")
        assert should_keep(msg, vendor_domains=NO_DOMAINS) is False


class TestSenderHint:
    def test_known_apparel_domain_keeps_even_without_transactional_subject(self):
        from app.ingestion.prefilter import should_keep

        msg = _msg(subject="Hello from Zara", from_addr="news@zara.com")
        assert should_keep(msg, vendor_domains=KNOWN) is True

    def test_unknown_domain_without_transactional_drops(self):
        from app.ingestion.prefilter import should_keep

        msg = _msg(subject="Your monthly bill", from_addr="billing@electric-co.com")
        assert should_keep(msg, vendor_domains=KNOWN) is False

    def test_domain_extracted_from_display_name_format(self):
        from app.ingestion.prefilter import _extract_sender_domain

        domain = _extract_sender_domain("Zara Store <noreply@zara.com>")
        assert domain == "zara.com"

    def test_domain_extracted_from_bare_email(self):
        from app.ingestion.prefilter import _extract_sender_domain

        domain = _extract_sender_domain("noreply@asos.com")
        assert domain == "asos.com"

    def test_promo_from_known_domain_still_dropped(self):
        from app.ingestion.prefilter import should_keep

        # Step 1 (promo exclusion) runs before step 3 (sender hint)
        msg = _msg(subject="Sale — 50% off", from_addr="deals@zara.com")
        assert should_keep(msg, vendor_domains=KNOWN) is False
