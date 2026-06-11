from __future__ import annotations

from email.utils import parseaddr

from bs4 import BeautifulSoup

from app.extraction.base import CleanedMessage
from app.providers.base import RawMessage

_DEFAULT_MAX_CHARS = 6_000
_STRIP_TAGS = ["script", "style", "nav", "footer", "header"]


def _vendor_domain_from_addr(from_addr: str) -> str:
    _, addr = parseaddr(from_addr)
    addr = addr or from_addr
    if "@" in addr:
        return addr.split("@")[1].lower()
    return addr.lower()


def _html_to_text(html: str) -> str:
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(_STRIP_TAGS):
        tag.decompose()
    return soup.get_text(separator=" ", strip=True)


def clean_message(
    msg: RawMessage, max_chars: int = _DEFAULT_MAX_CHARS
) -> CleanedMessage:
    if msg.html:
        body_text = _html_to_text(msg.html)
    elif msg.text:
        body_text = msg.text
    else:
        body_text = ""
    return CleanedMessage(
        message_id=msg.message_id,
        from_addr=msg.from_addr,
        vendor_domain=_vendor_domain_from_addr(msg.from_addr),
        subject=msg.subject,
        date=msg.date,
        body_text=body_text[:max_chars],
        image_srcs=list(msg.image_srcs),
    )
