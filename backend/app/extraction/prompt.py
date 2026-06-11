from __future__ import annotations

from app.extraction.base import CleanedMessage

SYSTEM_PROMPT = """\
You are a structured data extractor for an apparel purchase tracker.

Rules:
- Extract data ONLY about clothing, footwear, or accessories the user PURCHASED in this email.
- Set is_valid_apparel_purchase=false for: promotions, newsletters, "back in stock" notices, \
wishlist emails, shipping-only notices with no items, or non-apparel orders (electronics, \
food, etc.).
- Extract ONLY what is literally present in the email. Missing field → null. Never guess or invent.
- image_url must be copied verbatim from the provided candidate image list, or null if not present.
- Per-item brand may differ from vendor_name on multi-brand marketplaces (e.g. ASOS, Farfetch).
- If this is a refund or cancellation, set is_refund_or_cancellation=true and still return \
the order id and affected items.
- Return ONLY valid JSON conforming to the schema. No explanation, no markdown.
"""


def build_user_message(msg: CleanedMessage) -> str:
    image_lines = (
        "\n".join(f"{i + 1}. {src}" for i, src in enumerate(msg.image_srcs)) or "None"
    )
    return (
        f"Vendor domain: {msg.vendor_domain}\n"
        f"Subject: {msg.subject}\n"
        f"Date: {msg.date.isoformat()}\n"
        f"\nBody:\n{msg.body_text}\n"
        f"\nCandidate images:\n{image_lines}"
    )
