from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol, runtime_checkable


@dataclass
class ProviderQuery:
    after: datetime | None
    before: datetime | None
    subject_any: list[str]
    category_purchases: bool
    sender_domains: list[str] | None = None


@dataclass
class MessageRef:
    message_id: str
    internal_date: datetime


@dataclass
class Page:
    refs: list[MessageRef]
    next_cursor: str | None


@dataclass
class RawMessage:
    message_id: str
    account: str
    from_addr: str
    subject: str
    date: datetime
    text: str | None
    html: str | None
    image_srcs: list[str] = field(default_factory=list)


@runtime_checkable
class MailProvider(Protocol):
    async def search(self, query: ProviderQuery, cursor: str | None) -> Page: ...
    async def fetch(self, message_id: str) -> RawMessage: ...
