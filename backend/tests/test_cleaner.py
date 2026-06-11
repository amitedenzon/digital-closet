from datetime import datetime, timezone

from app.extraction.cleaner import _vendor_domain_from_addr, clean_message
from app.providers.base import RawMessage


def _make_raw(**kwargs) -> RawMessage:
    defaults = dict(
        message_id="id1",
        account="user@gmail.com",
        from_addr="orders@nike.com",
        subject="Your Nike order",
        date=datetime(2024, 1, 1, tzinfo=timezone.utc),
        text=None,
        html=None,
        image_srcs=[],
    )
    defaults.update(kwargs)
    return RawMessage(**defaults)


def test_vendor_domain_plain_addr():
    assert _vendor_domain_from_addr("orders@nike.com") == "nike.com"


def test_vendor_domain_display_name():
    assert _vendor_domain_from_addr("Nike <orders@nike.com>") == "nike.com"


def test_vendor_domain_lowercased():
    assert _vendor_domain_from_addr("noreply@ZARA.COM") == "zara.com"


def test_vendor_domain_fallback_no_at():
    # raw addr with no @-sign falls back to lowercased input
    result = _vendor_domain_from_addr("noemail")
    assert result == "noemail"


def test_html_stripped_to_text():
    html = "<html><body><p>Thank you for your order!</p><script>alert(1)</script></body></html>"
    msg = _make_raw(html=html)
    cleaned = clean_message(msg)
    assert "Thank you for your order!" in cleaned.body_text
    assert "<p>" not in cleaned.body_text
    assert "alert" not in cleaned.body_text


def test_plain_text_used_when_no_html():
    msg = _make_raw(text="Order confirmed. Item: Jeans.")
    cleaned = clean_message(msg)
    assert "Order confirmed" in cleaned.body_text


def test_html_preferred_over_text():
    msg = _make_raw(
        html="<p>HTML body</p>",
        text="Plain text body",
    )
    cleaned = clean_message(msg)
    assert "HTML body" in cleaned.body_text
    assert "Plain text body" not in cleaned.body_text


def test_body_text_truncated():
    msg = _make_raw(text="x" * 10_000)
    cleaned = clean_message(msg, max_chars=100)
    assert len(cleaned.body_text) == 100


def test_empty_body_when_no_content():
    msg = _make_raw(text=None, html=None)
    cleaned = clean_message(msg)
    assert cleaned.body_text == ""


def test_image_srcs_preserved():
    msg = _make_raw(image_srcs=["https://example.com/img.jpg"])
    cleaned = clean_message(msg)
    assert cleaned.image_srcs == ["https://example.com/img.jpg"]


def test_cleaned_message_fields():
    msg = _make_raw(from_addr="Nike <orders@nike.com>")
    cleaned = clean_message(msg)
    assert cleaned.message_id == "id1"
    assert cleaned.from_addr == "Nike <orders@nike.com>"
    assert cleaned.vendor_domain == "nike.com"
    assert cleaned.subject == "Your Nike order"
