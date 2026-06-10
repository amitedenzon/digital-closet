from __future__ import annotations

import pathlib

from app.providers.base import RawMessage

PROMO_KEYWORDS: tuple[str, ...] = (
    "now available",
    "new collection",
    "back in stock",
    "% off",
    "last chance",
    "wishlist",
    "you left",
    "recommended for you",
    " drop",
    "sale",
)

TRANSACTIONAL_KEYWORDS: tuple[str, ...] = (
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
    # Hebrew variants
    "הזמנה",
    "קבלה",
    "חשבונית",
)

_VENDOR_DOMAINS_FILE = (
    pathlib.Path(__file__).parent.parent.parent / "data" / "vendor_domains.txt"
)

_cached_domains: frozenset[str] | None = None


def _load_vendor_domains() -> frozenset[str]:
    global _cached_domains
    if _cached_domains is None:
        if _VENDOR_DOMAINS_FILE.exists():
            _cached_domains = frozenset(
                line.strip().lower()
                for line in _VENDOR_DOMAINS_FILE.read_text(
                    encoding="utf-8"
                ).splitlines()
                if line.strip() and not line.startswith("#")
            )
        else:
            _cached_domains = frozenset()
    return _cached_domains


def _extract_sender_domain(from_addr: str) -> str:
    """Return the domain portion of an RFC 5322 From header value."""
    addr = from_addr
    if "<" in addr:
        addr = addr.split("<", 1)[1].rstrip(">")
    if "@" in addr:
        return addr.split("@", 1)[1].lower().strip()
    return addr.lower().strip()


def should_keep(
    message: RawMessage,
    *,
    vendor_domains: frozenset[str] | None = None,
) -> bool:
    """
    Return True if the message should be sent to the LLM extractor.

    Steps (in order):
    1. Hard promo exclusion — subject + first 200 chars of body.
    2. Positive transactional signal in subject → keep.
    3. Sender is a known apparel domain → keep.
    Otherwise drop.

    Pass `vendor_domains` to override the file-loaded set (useful in tests).
    """
    domains = vendor_domains if vendor_domains is not None else _load_vendor_domains()

    body_preview = (message.text or message.html or "")[:200]
    haystack = (message.subject + " " + body_preview).lower()

    # Step 1: hard promo exclusion
    if any(kw in haystack for kw in PROMO_KEYWORDS):
        return False

    # Step 2: positive transactional signal (subject only)
    subject_lower = message.subject.lower()
    if any(kw in subject_lower for kw in TRANSACTIONAL_KEYWORDS):
        return True

    # Step 3: sender domain hint
    sender_domain = _extract_sender_domain(message.from_addr)
    return sender_domain in domains
