# Phase 02 — Ingestion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the full ingestion pipeline: `MailProvider` interface, Gmail implementation, heuristic prefilter, UPSERT repository layer, and pipeline orchestrator (`run_initialize` / `run_since_checkpoint`).

**Architecture:** Three clean layers — (1) provider interface + Gmail adapter that encapsulates all Gmail SDK calls, (2) pure-logic prefilter that runs cheaply before any LLM call, (3) pipeline orchestrator that wires provider → prefilter → extractor (interface only; Ollama implementation comes in Phase 3) → repo UPSERT → checkpoint. Each message is processed in its own DB transaction; `processed_messages` ensures idempotency across crashed/resumed runs.

**Tech Stack:** Python 3.11 asyncio, SQLAlchemy 2.0 async, `google-api-python-client` (Gmail SDK, sync — wrapped in executor), `beautifulsoup4`/`lxml` (HTML parsing), `httpx` (image downloads, Phase 4), `aiofiles`, `pathlib`.

> **Note on Definition of Done:** The spec's DoD ("walks real Gmail, populates orders/items, second run is no-op") is fully met only after Phase 3 (Ollama extractor). Phase 2 delivers: provider interface, prefilter, repo, pipeline skeleton, and Gmail query/MIME logic — all tested with mocks. Running against live Gmail is a Phase 3 integration milestone.

---

## File Structure

| File | Action | Responsibility |
|------|--------|----------------|
| `backend/app/providers/__init__.py` | Create | Package marker |
| `backend/app/providers/base.py` | Create | `ProviderQuery`, `MessageRef`, `Page`, `RawMessage` dataclasses + `MailProvider` Protocol |
| `backend/app/extraction/__init__.py` | Create | Package marker |
| `backend/app/extraction/base.py` | Create | `ExtractedItem`, `ExtractionResult` dataclasses + `Extractor` Protocol (interface only; implemented in Phase 3) |
| `backend/data/vendor_domains.txt` | Create | Known apparel sender domains — keep/skip hint for prefilter |
| `backend/app/ingestion/__init__.py` | Create | Package marker |
| `backend/app/ingestion/prefilter.py` | Create | Pure-logic heuristic filter (promo exclusion, transactional keywords, sender-domain hint) |
| `backend/app/store/__init__.py` | Create | Package marker |
| `backend/app/store/repo.py` | Create | `is_processed`, `record_processed`, `upsert_order`, `get_or_create_sync_state`, `update_sync_cursor`, `cursor_to_datetime` |
| `backend/app/ingestion/pipeline.py` | Create | `run_initialize`, `run_since_checkpoint`, `_drain`, `JobResult` |
| `backend/app/providers/gmail.py` | Create | `GmailProvider` (OAuth, search, fetch, MIME walk, img-src extraction) — Gmail SDK imports stay inside this file only |
| `backend/app/config.py` | Modify | Add `GMAIL_CREDENTIALS_FILE`, `GMAIL_TOKEN_FILE`, `GMAIL_ACCOUNT` settings |
| `backend/.env.example` | Modify | Add Gmail config vars |
| `backend/tests/conftest.py` | Modify | Add `session_factory` fixture (pipeline tests need the factory, not a bare session) |
| `backend/tests/test_providers_base.py` | Create | Dataclass construction + Protocol structural check |
| `backend/tests/test_prefilter.py` | Create | All four filter steps with good/bad inputs |
| `backend/tests/test_repo.py` | Create | UPSERT, dedup, idempotency, cursor round-trip |
| `backend/tests/test_pipeline.py` | Create | Mock-provider + mock-extractor end-to-end, idempotency, prefilter skip, error path |
| `backend/tests/test_gmail_provider.py` | Create | Query string building, MIME walk, img-src extraction (no real API calls) |

---

### Task 1: MailProvider + Extractor interfaces

**Files:**
- Create: `backend/app/providers/__init__.py`
- Create: `backend/app/providers/base.py`
- Create: `backend/app/extraction/__init__.py`
- Create: `backend/app/extraction/base.py`
- Create: `backend/tests/test_providers_base.py`

- [ ] **Step 1: Create package markers**

```
touch backend/app/providers/__init__.py
touch backend/app/extraction/__init__.py
```

(Both are empty files — just package markers.)

- [ ] **Step 2: Write `providers/base.py`**

```python
# backend/app/providers/base.py
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol


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


class MailProvider(Protocol):
    async def search(self, query: ProviderQuery, cursor: str | None) -> Page: ...
    async def fetch(self, message_id: str) -> RawMessage: ...
```

- [ ] **Step 3: Write `extraction/base.py`**

```python
# backend/app/extraction/base.py
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Protocol

from app.providers.base import RawMessage


@dataclass
class ExtractedItem:
    item_name: str
    brand: str | None = None
    size: str | None = None
    color: str | None = None
    quantity: int = 1
    price: Decimal | None = None
    image_url_src: str | None = None


@dataclass
class ExtractionResult:
    is_valid_apparel_purchase: bool
    vendor_name: str | None = None
    vendor_domain: str | None = None
    merchant_order_id: str | None = None
    purchase_date: datetime | None = None
    currency: str | None = None
    total_price: Decimal | None = None
    items: list[ExtractedItem] = field(default_factory=list)


class Extractor(Protocol):
    async def extract(self, message: RawMessage) -> ExtractionResult: ...
```

- [ ] **Step 4: Write the test**

```python
# backend/tests/test_providers_base.py
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
```

- [ ] **Step 5: Run tests and verify they pass**

```bash
cd backend && pytest tests/test_providers_base.py -v
```

Expected: 8 tests pass.

- [ ] **Step 6: Commit**

```bash
git add backend/app/providers/ backend/app/extraction/ backend/tests/test_providers_base.py
git commit -m "feat: add MailProvider and Extractor interfaces"
```

---

### Task 2: Prefilter + vendor domains

**Files:**
- Create: `backend/data/vendor_domains.txt`
- Create: `backend/app/ingestion/__init__.py`
- Create: `backend/app/ingestion/prefilter.py`
- Create: `backend/tests/test_prefilter.py`

- [ ] **Step 1: Create `backend/data/vendor_domains.txt`**

```
# Known apparel vendor domains — edit to add more.
# Lines starting with # are ignored. Lowercase only.
zara.com
asos.com
nike.com
adidas.com
hm.com
uniqlo.com
gap.com
farfetch.com
net-a-porter.com
matchesfashion.com
selfridges.com
nordstrom.com
bloomingdales.com
macys.com
revolve.com
ssense.com
mytheresa.com
levi.com
ralphlaufen.com
tommyhilfiger.com
calvinklein.com
guess.com
mango.com
urbanoutfitters.com
anthropologie.com
freepeople.com
americaneagle.com
abercrombie.com
forever21.com
shein.com
boohoo.com
prettylittlething.com
patagonia.com
lululemon.com
allbirds.com
vans.com
converse.com
puma.com
newbalance.com
underarmour.com
skechers.com
stevemadden.com
aldo.com
```

- [ ] **Step 2: Create package marker**

```
touch backend/app/ingestion/__init__.py
```

- [ ] **Step 3: Write `ingestion/prefilter.py`**

```python
# backend/app/ingestion/prefilter.py
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
                for line in _VENDOR_DOMAINS_FILE.read_text(encoding="utf-8").splitlines()
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
```

- [ ] **Step 4: Write the tests**

```python
# backend/tests/test_prefilter.py
from datetime import datetime, timezone

import pytest

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
        # "order" only in body — step 3 checks subject; body is only for promo exclusion
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
```

- [ ] **Step 5: Run tests**

```bash
cd backend && pytest tests/test_prefilter.py -v
```

Expected: 14 tests pass.

- [ ] **Step 6: Commit**

```bash
git add backend/data/ backend/app/ingestion/ backend/tests/test_prefilter.py
git commit -m "feat: add prefilter heuristic and vendor domain list"
```

---

### Task 3: Repo — UPSERT + checkpoint

**Files:**
- Create: `backend/app/store/__init__.py`
- Create: `backend/app/store/repo.py`
- Create: `backend/tests/test_repo.py`

- [ ] **Step 1: Create package marker**

```
touch backend/app/store/__init__.py
```

- [ ] **Step 2: Write `store/repo.py`**

```python
# backend/app/store/repo.py
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.extraction.base import ExtractionResult
from app.models import (
    Item,
    MessageResult,
    Order,
    ProcessedMessage,
    SyncState,
)


async def is_processed(session: AsyncSession, message_id: str) -> bool:
    stmt = select(ProcessedMessage.message_id).where(
        ProcessedMessage.message_id == message_id
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none() is not None


async def record_processed(
    session: AsyncSession,
    *,
    message_id: str,
    provider: str,
    account: str,
    result: MessageResult,
    order_id: str | None = None,
) -> None:
    session.add(
        ProcessedMessage(
            message_id=message_id,
            provider=provider,
            account=account,
            result=result,
            order_id=order_id,
        )
    )
    await session.flush()


async def upsert_order(
    session: AsyncSession,
    extraction: ExtractionResult,
) -> Order:
    """
    Insert a new order or update the existing one matched by (vendor_domain, merchant_order_id).
    Items are always replaced wholesale (delete-all then re-insert) since we trust the
    latest extraction to be the most complete view of the order.
    NULL merchant_order_id bypasses dedup and always inserts a new row.
    """
    existing: Order | None = None
    if extraction.vendor_domain and extraction.merchant_order_id:
        stmt = select(Order).where(
            Order.vendor_domain == extraction.vendor_domain,
            Order.merchant_order_id == extraction.merchant_order_id,
        )
        result = await session.execute(stmt)
        existing = result.scalar_one_or_none()

    if existing is not None:
        if extraction.total_price is not None:
            existing.total_price = extraction.total_price
        if extraction.currency:
            existing.currency = extraction.currency
        await session.execute(delete(Item).where(Item.order_id == existing.id))
        await session.flush()
        order = existing
    else:
        order = Order(
            vendor_name=extraction.vendor_name or "",
            vendor_domain=extraction.vendor_domain or "",
            merchant_order_id=extraction.merchant_order_id,
            purchase_date=extraction.purchase_date or datetime.now(timezone.utc),
            currency=extraction.currency,
            total_price=extraction.total_price,
        )
        session.add(order)
        await session.flush()

    for item_data in extraction.items:
        session.add(
            Item(
                order_id=order.id,
                item_name=item_data.item_name,
                brand=item_data.brand,
                size=item_data.size,
                color=item_data.color,
                quantity=item_data.quantity,
                price=item_data.price,
                image_url_src=item_data.image_url_src,
            )
        )
    await session.flush()
    return order


async def get_or_create_sync_state(
    session: AsyncSession, provider: str, account: str
) -> SyncState:
    stmt = select(SyncState).where(
        SyncState.provider == provider,
        SyncState.account == account,
    )
    result = await session.execute(stmt)
    state = result.scalar_one_or_none()
    if state is None:
        state = SyncState(provider=provider, account=account)
        session.add(state)
        await session.flush()
    return state


async def update_sync_cursor(
    session: AsyncSession, provider: str, account: str, cursor: str
) -> None:
    state = await get_or_create_sync_state(session, provider, account)
    state.cursor = cursor
    state.last_run_at = datetime.now(timezone.utc)
    await session.flush()


def cursor_to_datetime(cursor: str | None) -> datetime | None:
    """Convert epoch-ms string cursor to UTC datetime."""
    if cursor is None:
        return None
    return datetime.fromtimestamp(int(cursor) / 1000, tz=timezone.utc)
```

- [ ] **Step 3: Write the tests**

```python
# backend/tests/test_repo.py
from datetime import datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.extraction.base import ExtractedItem, ExtractionResult
from app.models import MessageResult, Order


def _extraction(
    vendor_domain: str = "zara.com",
    merchant_order_id: str | None = "ZR-001",
    **kwargs,
) -> ExtractionResult:
    defaults = dict(
        is_valid_apparel_purchase=True,
        vendor_name="Zara",
        vendor_domain=vendor_domain,
        merchant_order_id=merchant_order_id,
        purchase_date=datetime(2024, 1, 1, tzinfo=timezone.utc),
        currency="USD",
        total_price=Decimal("99.99"),
        items=[ExtractedItem(item_name="Blue Jeans", quantity=1)],
    )
    defaults.update(kwargs)
    return ExtractionResult(**defaults)


async def test_is_processed_false_for_new_message(session: AsyncSession):
    from app.store.repo import is_processed

    assert await is_processed(session, "msg-999") is False


async def test_is_processed_true_after_record(session: AsyncSession):
    from app.store.repo import is_processed, record_processed

    await record_processed(
        session,
        message_id="msg-1",
        provider="gmail",
        account="a@b.com",
        result=MessageResult.extracted,
    )
    await session.commit()

    assert await is_processed(session, "msg-1") is True


async def test_record_processed_stores_order_id(session: AsyncSession):
    from sqlalchemy import select

    from app.models import ProcessedMessage
    from app.store.repo import record_processed

    await record_processed(
        session,
        message_id="msg-2",
        provider="gmail",
        account="a@b.com",
        result=MessageResult.extracted,
        order_id="some-uuid",
    )
    await session.commit()

    row = (
        await session.execute(
            select(ProcessedMessage).where(ProcessedMessage.message_id == "msg-2")
        )
    ).scalar_one()
    assert row.order_id == "some-uuid"


async def test_upsert_order_inserts_new(session: AsyncSession):
    from sqlalchemy import select

    from app.store.repo import upsert_order

    order = await upsert_order(session, _extraction())
    await session.commit()

    saved = (await session.execute(select(Order).where(Order.id == order.id))).scalar_one()
    assert saved.vendor_domain == "zara.com"
    assert saved.merchant_order_id == "ZR-001"


async def test_upsert_order_updates_existing_not_duplicate(session: AsyncSession):
    from sqlalchemy import func, select

    from app.store.repo import upsert_order

    await upsert_order(session, _extraction(total_price=Decimal("50.00")))
    await session.commit()

    await upsert_order(session, _extraction(total_price=Decimal("75.00")))
    await session.commit()

    count = (await session.execute(select(func.count()).select_from(Order))).scalar_one()
    assert count == 1  # no duplicate

    saved = (await session.execute(select(Order))).scalar_one()
    assert saved.total_price == Decimal("75.00")


async def test_upsert_order_replaces_items_on_update(session: AsyncSession):
    from sqlalchemy import select

    from app.models import Item
    from app.store.repo import upsert_order

    first = _extraction(
        items=[ExtractedItem(item_name="Old Shirt"), ExtractedItem(item_name="Old Jeans")]
    )
    await upsert_order(session, first)
    await session.commit()

    second = _extraction(
        items=[ExtractedItem(item_name="New Coat")]
    )
    order = await upsert_order(session, second)
    await session.commit()

    items = (
        await session.execute(select(Item).where(Item.order_id == order.id))
    ).scalars().all()
    assert len(items) == 1
    assert items[0].item_name == "New Coat"


async def test_upsert_order_null_merchant_id_always_inserts(session: AsyncSession):
    from sqlalchemy import func, select

    from app.store.repo import upsert_order

    await upsert_order(session, _extraction(merchant_order_id=None))
    await session.commit()
    await upsert_order(session, _extraction(merchant_order_id=None))
    await session.commit()

    count = (await session.execute(select(func.count()).select_from(Order))).scalar_one()
    assert count == 2


async def test_get_or_create_sync_state_creates_once(session: AsyncSession):
    from app.store.repo import get_or_create_sync_state

    state1 = await get_or_create_sync_state(session, "gmail", "a@b.com")
    await session.commit()
    state2 = await get_or_create_sync_state(session, "gmail", "a@b.com")
    await session.commit()

    assert state1.id == state2.id


async def test_update_sync_cursor_stores_and_updates(session: AsyncSession):
    from app.store.repo import get_or_create_sync_state, update_sync_cursor

    await update_sync_cursor(session, "gmail", "a@b.com", "1700000000000")
    await session.commit()

    state = await get_or_create_sync_state(session, "gmail", "a@b.com")
    assert state.cursor == "1700000000000"
    assert state.last_run_at is not None


def test_cursor_to_datetime_none():
    from app.store.repo import cursor_to_datetime

    assert cursor_to_datetime(None) is None


def test_cursor_to_datetime_round_trips():
    from app.store.repo import cursor_to_datetime

    epoch_ms = 1700000000000
    dt = cursor_to_datetime(str(epoch_ms))
    assert dt is not None
    assert dt.tzinfo is not None
    # Round-trip: epoch_ms → datetime → epoch_ms should be within rounding error
    assert abs(int(dt.timestamp() * 1000) - epoch_ms) < 1
```

- [ ] **Step 4: Run tests**

```bash
cd backend && pytest tests/test_repo.py -v
```

Expected: 11 tests pass.

- [ ] **Step 5: Commit**

```bash
git add backend/app/store/ backend/tests/test_repo.py
git commit -m "feat: add repo layer — upsert, dedup, checkpoint"
```

---

### Task 4: Pipeline + conftest session_factory

**Files:**
- Modify: `backend/tests/conftest.py` (add `session_factory` fixture)
- Create: `backend/app/ingestion/pipeline.py`
- Create: `backend/tests/test_pipeline.py`

- [ ] **Step 1: Update `tests/conftest.py` to add `session_factory` fixture**

Add this fixture after the existing `session` fixture:

```python
# Add to backend/tests/conftest.py

@pytest_asyncio.fixture
async def session_factory():
    engine = create_async_engine(TEST_DB_URL)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    yield factory
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()
```

The import for `async_sessionmaker` is already present. No new imports needed.

Full updated `conftest.py`:

```python
from collections.abc import AsyncGenerator

import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.models  # noqa: F401 — registers all ORM models on Base.metadata
from app.db import Base

TEST_DB_URL = "sqlite+aiosqlite:///:memory:"


@pytest_asyncio.fixture
async def session() -> AsyncGenerator[AsyncSession, None]:
    engine = create_async_engine(TEST_DB_URL)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        yield s
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest_asyncio.fixture
async def session_factory():
    engine = create_async_engine(TEST_DB_URL)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    yield factory
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()
```

- [ ] **Step 2: Write the failing pipeline tests first**

```python
# backend/tests/test_pipeline.py
from datetime import datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.extraction.base import ExtractedItem, ExtractionResult
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
        total_price=Decimal("49.99"),
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

    async def extract(self, message: RawMessage) -> ExtractionResult:
        return self._result


async def test_run_initialize_processes_message_and_stores_order(session_factory):
    from app.ingestion.pipeline import run_initialize

    ref = MessageRef("msg-1", datetime(2024, 1, 1, tzinfo=timezone.utc))
    provider = FakeProvider([ref], {"msg-1": _raw_message()})
    extractor = FakeExtractor(_good_extraction())

    result = await run_initialize(
        provider, extractor, session_factory,
        provider_name="gmail", account="test@gmail.com",
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
        provider, extractor, session_factory,
        provider_name="gmail", account="test@gmail.com",
    )
    # Second run with the same provider (same refs)
    result2 = await run_initialize(
        provider, extractor, session_factory,
        provider_name="gmail", account="test@gmail.com",
    )

    assert result2.scanned == 1
    assert result2.skipped == 1  # already processed
    assert result2.kept == 0

    async with session_factory() as session:
        count = len((await session.execute(select(Order))).scalars().all())
        assert count == 1  # no duplicate order


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
        provider, extractor, session_factory,
        provider_name="gmail", account="test@gmail.com",
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
        provider, extractor, session_factory,
        provider_name="gmail", account="test@gmail.com",
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
        provider, ErrorExtractor(), session_factory,
        provider_name="gmail", account="test@gmail.com",
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
    ref = MessageRef("msg-1", internal_date)
    provider = FakeProvider([ref], {"msg-1": _raw_message()})
    extractor = FakeExtractor(_good_extraction())

    await run_initialize(
        provider, extractor, session_factory,
        provider_name="gmail", account="test@gmail.com",
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

    # Store a cursor from 2024-06-01
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
        CapturingProvider(), FakeExtractor(_good_extraction()), session_factory,
        provider_name="gmail", account="test@gmail.com",
    )

    assert received_query["after"] == datetime(2024, 6, 1, tzinfo=timezone.utc)
```

- [ ] **Step 3: Run tests and verify they fail**

```bash
cd backend && pytest tests/test_pipeline.py -v
```

Expected: `ModuleNotFoundError: No module named 'app.ingestion.pipeline'` (or similar).

- [ ] **Step 4: Write `ingestion/pipeline.py`**

```python
# backend/app/ingestion/pipeline.py
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.extraction.base import Extractor
from app.ingestion.prefilter import should_keep
from app.models import MessageResult
from app.providers.base import MailProvider, ProviderQuery
from app.store import repo

logger = logging.getLogger(__name__)

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
) -> JobResult:
    query = ProviderQuery(
        after=datetime(stop_year, 1, 1, tzinfo=timezone.utc),
        before=datetime.now(timezone.utc),
        subject_any=_SUBJECT_KEYWORDS,
        category_purchases=True,
    )
    return await _drain(
        provider, extractor, session_factory,
        query=query, provider_name=provider_name, account=account,
    )


async def run_since_checkpoint(
    provider: MailProvider,
    extractor: Extractor,
    session_factory: async_sessionmaker[AsyncSession],
    *,
    provider_name: str,
    account: str,
    stop_year: int = DEFAULT_STOP_YEAR,
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
        provider, extractor, session_factory,
        query=query, provider_name=provider_name, account=account,
    )


async def _drain(
    provider: MailProvider,
    extractor: Extractor,
    session_factory: async_sessionmaker[AsyncSession],
    *,
    query: ProviderQuery,
    provider_name: str,
    account: str,
) -> JobResult:
    result = JobResult()
    page_cursor: str | None = None
    max_internal_date: datetime | None = None

    while True:
        page = await provider.search(query, page_cursor)

        for ref in page.refs:
            result.scanned += 1
            if max_internal_date is None or ref.internal_date > max_internal_date:
                max_internal_date = ref.internal_date

            async with session_factory() as session:
                if await repo.is_processed(session, ref.message_id):
                    result.skipped += 1
                    logger.debug("skip:already_processed message_id=%s", ref.message_id)
                    continue

                try:
                    message = await provider.fetch(ref.message_id)

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
                        logger.info(
                            "skip:prefilter message_id=%s subject=%r",
                            ref.message_id, message.subject,
                        )
                        continue

                    extraction = await extractor.extract(message)

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
                        logger.info("skip:llm message_id=%s", ref.message_id)
                        continue

                    order = await repo.upsert_order(session, extraction)
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
                    logger.info(
                        "extracted message_id=%s order_id=%s", ref.message_id, order.id
                    )

                except Exception as exc:
                    await session.rollback()
                    async with session_factory() as err_session:
                        await repo.record_processed(
                            err_session,
                            message_id=ref.message_id,
                            provider=provider_name,
                            account=account,
                            result=MessageResult.error,
                        )
                        await err_session.commit()
                    result.errors += 1
                    logger.exception(
                        "error:processing message_id=%s", ref.message_id, exc_info=exc
                    )

        if page.next_cursor is None:
            break
        page_cursor = page.next_cursor

    if max_internal_date is not None:
        cursor_str = str(int(max_internal_date.timestamp() * 1000))
        async with session_factory() as session:
            await repo.update_sync_cursor(session, provider_name, account, cursor_str)
            await session.commit()

    return result
```

- [ ] **Step 5: Run all pipeline tests**

```bash
cd backend && pytest tests/test_pipeline.py -v
```

Expected: 7 tests pass.

- [ ] **Step 6: Run full test suite to check for regressions**

```bash
cd backend && ruff check . && black --check . && pytest -q
```

Expected: all tests pass, no linting errors.

- [ ] **Step 7: Commit**

```bash
git add backend/tests/conftest.py backend/app/ingestion/pipeline.py backend/tests/test_pipeline.py
git commit -m "feat: add ingestion pipeline with run_initialize and run_since_checkpoint"
```

---

### Task 5: Gmail provider + config updates

**Files:**
- Create: `backend/app/providers/gmail.py`
- Modify: `backend/app/config.py`
- Modify: `backend/.env.example`
- Create: `backend/tests/test_gmail_provider.py`

- [ ] **Step 1: Update `config.py`**

```python
# backend/app/config.py
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    DATABASE_URL: str = "sqlite+aiosqlite:///./closet.db"
    GMAIL_CREDENTIALS_FILE: str = "credentials.json"
    GMAIL_TOKEN_FILE: str = "token.json"
    GMAIL_ACCOUNT: str = ""

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}
```

- [ ] **Step 2: Update `.env.example`**

```
DATABASE_URL=sqlite+aiosqlite:///./closet.db
GMAIL_CREDENTIALS_FILE=credentials.json
GMAIL_TOKEN_FILE=token.json
GMAIL_ACCOUNT=you@gmail.com
```

- [ ] **Step 3: Write the failing Gmail provider tests**

```python
# backend/tests/test_gmail_provider.py
"""
Unit tests for GmailProvider helper functions.
No real OAuth or network calls — we test the pure logic.
"""
from datetime import datetime, timezone


class TestBuildQueryString:
    def test_date_range_only(self):
        from app.providers.gmail import _build_query_string
        from app.providers.base import ProviderQuery

        q = ProviderQuery(
            after=datetime(2023, 1, 1, tzinfo=timezone.utc),
            before=datetime(2026, 6, 11, tzinfo=timezone.utc),
            subject_any=[],
            category_purchases=False,
        )
        qs = _build_query_string(q)
        assert "after:2023/01/01" in qs
        assert "before:2026/06/11" in qs

    def test_category_purchases(self):
        from app.providers.gmail import _build_query_string
        from app.providers.base import ProviderQuery

        q = ProviderQuery(
            after=None, before=None,
            subject_any=[],
            category_purchases=True,
        )
        qs = _build_query_string(q)
        assert "category:purchases" in qs

    def test_subject_keywords_joined_with_or(self):
        from app.providers.gmail import _build_query_string
        from app.providers.base import ProviderQuery

        q = ProviderQuery(
            after=None, before=None,
            subject_any=["order", "receipt", "invoice"],
            category_purchases=False,
        )
        qs = _build_query_string(q)
        assert "subject:" in qs
        assert "order" in qs
        assert "receipt" in qs
        assert "invoice" in qs

    def test_category_and_subjects_are_or_grouped(self):
        from app.providers.gmail import _build_query_string
        from app.providers.base import ProviderQuery

        q = ProviderQuery(
            after=None, before=None,
            subject_any=["order"],
            category_purchases=True,
        )
        qs = _build_query_string(q)
        # Both should be inside a single OR group
        assert "category:purchases OR" in qs or "OR category:purchases" in qs

    def test_no_category_no_subjects_produces_no_or_group(self):
        from app.providers.gmail import _build_query_string
        from app.providers.base import ProviderQuery

        q = ProviderQuery(
            after=datetime(2024, 1, 1, tzinfo=timezone.utc),
            before=None,
            subject_any=[],
            category_purchases=False,
        )
        qs = _build_query_string(q)
        assert "category:" not in qs
        assert "subject:" not in qs


class TestWalkMimeParts:
    def test_simple_text_plain(self):
        from app.providers.gmail import _walk_parts

        payload = {
            "mimeType": "text/plain",
            "body": {"data": _b64("Hello plain text")},
        }
        text, html = _walk_parts(payload)
        assert text == "Hello plain text"
        assert html is None

    def test_simple_text_html(self):
        from app.providers.gmail import _walk_parts

        payload = {
            "mimeType": "text/html",
            "body": {"data": _b64("<p>Hello HTML</p>")},
        }
        text, html = _walk_parts(payload)
        assert text is None
        assert html == "<p>Hello HTML</p>"

    def test_multipart_alternative(self):
        from app.providers.gmail import _walk_parts

        payload = {
            "mimeType": "multipart/alternative",
            "body": {},
            "parts": [
                {
                    "mimeType": "text/plain",
                    "body": {"data": _b64("Plain version")},
                },
                {
                    "mimeType": "text/html",
                    "body": {"data": _b64("<p>HTML version</p>")},
                },
            ],
        }
        text, html = _walk_parts(payload)
        assert text == "Plain version"
        assert html == "<p>HTML version</p>"

    def test_deeply_nested_multipart(self):
        from app.providers.gmail import _walk_parts

        payload = {
            "mimeType": "multipart/mixed",
            "body": {},
            "parts": [
                {
                    "mimeType": "multipart/alternative",
                    "body": {},
                    "parts": [
                        {
                            "mimeType": "text/plain",
                            "body": {"data": _b64("Nested plain")},
                        }
                    ],
                }
            ],
        }
        text, html = _walk_parts(payload)
        assert text == "Nested plain"

    def test_empty_payload_returns_none_none(self):
        from app.providers.gmail import _walk_parts

        text, html = _walk_parts({"mimeType": "multipart/mixed", "body": {}})
        assert text is None
        assert html is None


class TestExtractImageSrcs:
    def test_extracts_img_srcs(self):
        from app.providers.gmail import _extract_image_srcs

        html = '<html><body><img src="https://cdn.zara.com/img1.jpg"><img src="https://cdn.zara.com/img2.jpg"></body></html>'
        srcs = _extract_image_srcs(html)
        assert len(srcs) == 2
        assert "https://cdn.zara.com/img1.jpg" in srcs

    def test_skips_imgs_without_src(self):
        from app.providers.gmail import _extract_image_srcs

        html = '<html><body><img alt="logo"><img src="https://cdn.zara.com/img.jpg"></body></html>'
        srcs = _extract_image_srcs(html)
        assert len(srcs) == 1

    def test_empty_html_returns_empty_list(self):
        from app.providers.gmail import _extract_image_srcs

        assert _extract_image_srcs("") == []


def _b64(text: str) -> str:
    import base64
    return base64.urlsafe_b64encode(text.encode()).decode()
```

- [ ] **Step 4: Run tests and verify they fail**

```bash
cd backend && pytest tests/test_gmail_provider.py -v
```

Expected: `ModuleNotFoundError: No module named 'app.providers.gmail'`.

- [ ] **Step 5: Write `providers/gmail.py`**

```python
# backend/app/providers/gmail.py
"""
Gmail implementation of MailProvider.

All google-api-python-client imports are confined to this file.
The rest of the app uses only app.providers.base types.
"""
from __future__ import annotations

import asyncio
import base64
import logging
import os
from datetime import datetime, timezone
from typing import Any

from bs4 import BeautifulSoup

from app.providers.base import MailProvider, MessageRef, Page, ProviderQuery, RawMessage

logger = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]


def _build_query_string(query: ProviderQuery) -> str:
    parts: list[str] = []

    if query.after:
        parts.append(f"after:{query.after.strftime('%Y/%m/%d')}")
    if query.before:
        parts.append(f"before:{query.before.strftime('%Y/%m/%d')}")

    or_clauses: list[str] = []
    if query.category_purchases:
        or_clauses.append("category:purchases")
    if query.subject_any:
        kws = " OR ".join(query.subject_any)
        or_clauses.append(f"subject:({kws})")
    if or_clauses:
        parts.append(f"({' OR '.join(or_clauses)})")

    if query.sender_domains:
        senders = " OR ".join(f"from:{d}" for d in query.sender_domains)
        parts.append(f"({senders})")

    return " ".join(parts)


def _decode_b64(data: str) -> str:
    padded = data + "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(padded).decode("utf-8", errors="replace")


def _walk_parts(payload: dict[str, Any]) -> tuple[str | None, str | None]:
    """Recursively walk a MIME payload tree, return (text/plain, text/html)."""
    mime_type = payload.get("mimeType", "")
    body_data = payload.get("body", {}).get("data", "")

    if mime_type == "text/plain" and body_data:
        return _decode_b64(body_data), None
    if mime_type == "text/html" and body_data:
        return None, _decode_b64(body_data)

    text: str | None = None
    html: str | None = None
    for part in payload.get("parts", []):
        t, h = _walk_parts(part)
        text = text or t
        html = html or h
    return text, html


def _extract_image_srcs(html: str) -> list[str]:
    if not html:
        return []
    soup = BeautifulSoup(html, "lxml")
    return [img["src"] for img in soup.find_all("img") if img.get("src")]


def _get_header(headers: list[dict], name: str) -> str:
    for h in headers:
        if h.get("name", "").lower() == name.lower():
            return h.get("value", "")
    return ""


def _build_service(credentials_file: str, token_file: str) -> Any:
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build

    creds: Credentials | None = None
    if os.path.exists(token_file):
        creds = Credentials.from_authorized_user_file(token_file, SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(credentials_file, SCOPES)
            creds = flow.run_local_server(port=0)
        with open(token_file, "w") as f:
            f.write(creds.to_json())

    return build("gmail", "v1", credentials=creds)


class GmailProvider:
    """
    MailProvider backed by the Gmail API.

    The underlying google-api-python-client calls are synchronous;
    they are dispatched to the default ThreadPoolExecutor so the event
    loop is never blocked.
    """

    def __init__(self, service: Any, account: str) -> None:
        self._service = service
        self._account = account

    @classmethod
    def from_credentials_files(
        cls, credentials_file: str, token_file: str, account: str
    ) -> "GmailProvider":
        service = _build_service(credentials_file, token_file)
        return cls(service, account)

    async def search(self, query: ProviderQuery, cursor: str | None) -> Page:
        q_str = _build_query_string(query)
        loop = asyncio.get_event_loop()

        def _list():
            kwargs: dict[str, Any] = {
                "userId": "me",
                "q": q_str,
                "maxResults": 500,
            }
            if cursor:
                kwargs["pageToken"] = cursor
            return self._service.users().messages().list(**kwargs).execute()

        raw = await loop.run_in_executor(None, _list)
        messages = raw.get("messages", [])
        next_cursor: str | None = raw.get("nextPageToken")

        refs: list[MessageRef] = []
        for m in messages:
            refs.append(
                MessageRef(
                    message_id=m["id"],
                    # internalDate not available from list(); populated in fetch()
                    # Use epoch 0 as placeholder — prefilter and pipeline don't sort on this
                    internal_date=datetime.fromtimestamp(0, tz=timezone.utc),
                )
            )

        return Page(refs=refs, next_cursor=next_cursor)

    async def fetch(self, message_id: str) -> RawMessage:
        loop = asyncio.get_event_loop()

        def _get():
            return (
                self._service.users()
                .messages()
                .get(userId="me", id=message_id, format="full")
                .execute()
            )

        raw = await loop.run_in_executor(None, _get)
        payload = raw.get("payload", {})
        headers = payload.get("headers", [])
        internal_ms = int(raw.get("internalDate", "0"))

        text, html = _walk_parts(payload)
        image_srcs = _extract_image_srcs(html) if html else []

        return RawMessage(
            message_id=message_id,
            account=self._account,
            from_addr=_get_header(headers, "From"),
            subject=_get_header(headers, "Subject"),
            date=datetime.fromtimestamp(internal_ms / 1000, tz=timezone.utc),
            text=text,
            html=html,
            image_srcs=image_srcs,
        )
```

> **Note on `internal_date` in `search()`:** Gmail's `messages.list` endpoint does not return `internalDate` — only `messages.get` does. Rather than making a separate metadata request per message (expensive), we populate `internal_date` with a placeholder in `search()` and with the real value in `fetch()`. The pipeline tracks `max_internal_date` from the *fetched* messages (via the `RawMessage.date` field on kept messages). If this turns out to be wrong, the fix is in `pipeline.py` — update `max_internal_date` from `message.date` instead of `ref.internal_date`. See "Cursor note" in pipeline.py.

> **Pipeline cursor fix needed:** After writing `GmailProvider`, update `pipeline._drain` to track `max_internal_date` from `message.date` (set on kept messages) rather than `ref.internal_date`, since the Gmail `search()` returns placeholder dates. This is a one-line change in `pipeline.py` — add `max_date` tracking inside the `try` block after a successful `fetch()`.

- [ ] **Step 6: Run Gmail provider tests**

```bash
cd backend && pytest tests/test_gmail_provider.py -v
```

Expected: all tests pass.

- [ ] **Step 7: Fix pipeline cursor tracking for real Gmail internal dates**

In `backend/app/ingestion/pipeline.py`, update `_drain` to track the max date from fetched messages (not refs, since Gmail search returns placeholder dates):

Find this block inside `_drain`:
```python
            async with session_factory() as session:
                if await repo.is_processed(session, ref.message_id):
                    result.skipped += 1
                    logger.debug("skip:already_processed message_id=%s", ref.message_id)
                    continue

                try:
                    message = await provider.fetch(ref.message_id)
```

Add the date update right after the `message = await provider.fetch(...)` line:
```python
                    message = await provider.fetch(ref.message_id)
                    if max_internal_date is None or message.date > max_internal_date:
                        max_internal_date = message.date
```

And remove the `max_internal_date` update that was on `ref.internal_date` (in the header of the for loop):
```python
            # Remove these two lines:
            if max_internal_date is None or ref.internal_date > max_internal_date:
                max_internal_date = ref.internal_date
```

- [ ] **Step 8: Run the full test suite**

```bash
cd backend && ruff check . && black --check . && pytest -q
```

Expected: all tests pass. If ruff or black report issues, fix them before proceeding.

- [ ] **Step 9: Commit**

```bash
git add backend/app/providers/gmail.py backend/app/config.py backend/.env.example \
        backend/tests/test_gmail_provider.py backend/app/ingestion/pipeline.py
git commit -m "feat: add Gmail provider, config vars, pipeline cursor fix"
```

---

## Self-Review

### Spec coverage check

| Spec requirement | Covered by |
|-----------------|------------|
| `MailProvider` Protocol with `search`/`fetch` | Task 1: `providers/base.py` |
| `ProviderQuery`, `MessageRef`, `Page`, `RawMessage` dataclasses | Task 1: `providers/base.py` |
| Gmail OAuth desktop flow, `gmail.readonly` scope | Task 5: `gmail.py::_build_service` |
| Gmail `search()` builds query from `ProviderQuery` | Task 5: `gmail.py::_build_query_string` |
| Gmail `fetch()` walks MIME, decodes base64url, extracts `<img src>` | Task 5: `gmail.py::_walk_parts`, `_extract_image_srcs` |
| `run_initialize(stop_year)` | Task 4: `pipeline.py::run_initialize` |
| `run_since_checkpoint()` uses stored cursor | Task 4: `pipeline.py::run_since_checkpoint` |
| `_drain` pages through search, prefilters, records every message | Task 4: `pipeline.py::_drain` |
| Prefilter: promo exclusion (step 2) | Task 2: `prefilter.py` |
| Prefilter: transactional signal (step 3) | Task 2: `prefilter.py` |
| Prefilter: sender domain hint (step 4) | Task 2: `prefilter.py` |
| `processed_messages` checked first (step 1) | Task 4: `pipeline.py` calls `repo.is_processed` |
| Every processed `message_id` recorded (kept or skipped) | Task 3+4: `repo.record_processed` called for all paths |
| `vendor_domains.txt` configurable allowlist | Task 2: `data/vendor_domains.txt` |
| Hebrew transactional keywords | Task 2: `prefilter.py::TRANSACTIONAL_KEYWORDS` |
| UPSERT: second email for same order updates, never duplicates | Task 3: `repo.upsert_order` |
| `sync_state.cursor` updated after successful drain | Task 4: `pipeline.py` end of `_drain` |
| `run_since_checkpoint` uses cursor date as `after:` | Task 4 + Task 5 query string |
| Error → mark `error`, continue (never crash whole run) | Task 4: `pipeline.py` except block |
| Cursor = epoch-ms of newest message | Task 3: `repo.cursor_to_datetime`, Task 4: pipeline |

### Placeholder scan

No TBD, TODO, or "implement later" placeholders. All steps include complete code.

### Type consistency check

- `MailProvider.search` returns `Page` — used consistently in `pipeline._drain`
- `MailProvider.fetch` returns `RawMessage` — `prefilter.should_keep(message: RawMessage)` ✓
- `Extractor.extract(message: RawMessage) -> ExtractionResult` — `pipeline` calls `extractor.extract(message)` ✓
- `repo.upsert_order(session, extraction: ExtractionResult) -> Order` — `pipeline` calls `await repo.upsert_order(session, extraction)` ✓
- `repo.record_processed(..., result: MessageResult, ...)` — all call sites pass `MessageResult.X` enum members ✓
- `JobResult` fields (`scanned`, `kept`, `skipped`, `errors`) — all incremented correctly in `_drain` ✓

### Known gaps / deferred to Phase 3

- `extraction/base.py` defines the `Extractor` interface; no real implementation until Phase 3 (Ollama).
- The full DoD ("walks real Gmail, populates orders/items, second run is no-op") requires Phase 3.
- Gmail batch endpoint (spec mentions batching `get` calls) — deferred; current impl fetches one at a time. Add batching in Phase 6 (edge cases / hardening) if needed.
- Image download / pixel filter — Phase 4.
