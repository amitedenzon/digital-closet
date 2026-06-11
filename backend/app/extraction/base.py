from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol, runtime_checkable

from app.schemas import ExtractionResult


@dataclass
class CleanedMessage:
    message_id: str
    from_addr: str
    vendor_domain: str
    subject: str
    date: datetime
    body_text: str
    image_srcs: list[str] = field(default_factory=list)


@runtime_checkable
class Extractor(Protocol):
    async def extract(self, msg: CleanedMessage) -> ExtractionResult: ...
