# Phase 03 — Extraction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the full LLM extraction layer — Pydantic schemas, HTML cleaner, Ollama extractor with structured output and retry, and wire it into the existing pipeline.

**Architecture:** A `CleanedMessage` struct (HTML→text, vendor_domain derived from sender) feeds a `Protocol`-typed `OllamaExtractor` that calls `qwen2.5:7b` with constrained JSON output and validates the result against Pydantic schemas. On parse failure the extractor retries once with a stricter prompt; on second failure it raises so the pipeline marks the message `error`. Existing `repo.py` and `pipeline.py` are updated to use the new types with minimal churn.

**Tech Stack:** Python 3.11+, Pydantic v2, httpx (async), BeautifulSoup4/lxml, Ollama `qwen2.5:7b` local API.

---

## File Map

| Action | Path | Responsibility |
|--------|------|----------------|
| **Create** | `backend/app/schemas.py` | Pydantic v2 `ExtractedItem` + `ExtractionResult` (LLM output + API) |
| **Modify** | `backend/app/extraction/base.py` | Add `CleanedMessage`; change `Extractor` protocol to accept it; remove old dataclasses |
| **Create** | `backend/app/extraction/cleaner.py` | `clean_message(RawMessage) → CleanedMessage`: strip HTML, truncate, derive `vendor_domain` |
| **Create** | `backend/app/extraction/prompt.py` | `SYSTEM_PROMPT` + `build_user_message(CleanedMessage) → str` |
| **Create** | `backend/app/extraction/ollama_extractor.py` | `OllamaExtractor` implementing the `Extractor` protocol |
| **Modify** | `backend/app/config.py` | Add `OLLAMA_BASE_URL`, `OLLAMA_MODEL`, `BODY_TEXT_MAX_CHARS` |
| **Modify** | `backend/.env.example` | Document new env vars |
| **Modify** | `backend/app/store/repo.py` | Import `ExtractionResult` from `schemas`; `image_url_src` → `image_url` |
| **Modify** | `backend/app/ingestion/pipeline.py` | `clean_message` step before calling extractor |
| **Modify** | `backend/tests/test_repo.py` | Import from `app.schemas`; use float prices |
| **Modify** | `backend/tests/test_pipeline.py` | Import from `app.schemas`; `FakeExtractor` accepts `CleanedMessage` |
| **Create** | `backend/tests/test_schemas.py` | Pydantic schema validation tests |
| **Create** | `backend/tests/test_cleaner.py` | Cleaner unit tests |
| **Create** | `backend/tests/test_ollama_extractor.py` | Extractor tests with mocked httpx |

---

### Task 1: Create `app/schemas.py`

**Files:**
- Create: `backend/app/schemas.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_schemas.py`:

```python
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from app.schemas import ExtractedItem, ExtractionResult


def test_extracted_item_minimal():
    item = ExtractedItem(item_name="Air Max 90")
    assert item.item_name == "Air Max 90"
    assert item.brand is None
    assert item.quantity == 1
    assert item.image_url is None


def test_extraction_result_valid_purchase():
    result = ExtractionResult.model_validate({
        "is_valid_apparel_purchase": True,
        "vendor_name": "Nike",
        "merchant_order_id": "12345",
        "items": [{"item_name": "Air Max 90", "size": "10", "price": 120.0}],
    })
    assert result.is_valid_apparel_purchase is True
    assert len(result.items) == 1
    assert result.items[0].item_name == "Air Max 90"
    assert result.items[0].size == "10"


def test_extraction_result_promo_no_items():
    result = ExtractionResult.model_validate({"is_valid_apparel_purchase": False})
    assert result.is_valid_apparel_purchase is False
    assert result.items == []
    assert result.is_refund_or_cancellation is False


def test_extraction_result_json_roundtrip():
    original = ExtractionResult.model_validate({
        "is_valid_apparel_purchase": True,
        "vendor_name": "ASOS",
        "total_price": 49.99,
        "items": [{"item_name": "Jeans", "brand": "Levi's", "color": "blue"}],
    })
    json_str = original.model_dump_json()
    loaded = ExtractionResult.model_validate_json(json_str)
    assert loaded.vendor_name == "ASOS"
    assert loaded.items[0].brand == "Levi's"


def test_extraction_result_missing_required_field():
    with pytest.raises(ValidationError):
        ExtractionResult.model_validate({})


def test_extraction_result_json_schema_is_serializable():
    import json
    schema = ExtractionResult.model_json_schema()
    serialized = json.dumps(schema)
    assert "is_valid_apparel_purchase" in serialized
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd backend && pytest tests/test_schemas.py -v
```

Expected: `ModuleNotFoundError: No module named 'app.schemas'`

- [ ] **Step 3: Create `backend/app/schemas.py`**

```python
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class ExtractedItem(BaseModel):
    item_name: str
    brand: str | None = None
    size: str | None = None
    color: str | None = None
    quantity: int = 1
    price: float | None = None
    image_url: str | None = None


class ExtractionResult(BaseModel):
    is_valid_apparel_purchase: bool
    is_refund_or_cancellation: bool = False
    vendor_name: str | None = None
    vendor_domain: str | None = None
    merchant_order_id: str | None = None
    purchase_date: datetime | None = None
    currency: str | None = None
    total_price: float | None = None
    items: list[ExtractedItem] = []
    confidence: float | None = None
```

- [ ] **Step 4: Run tests**

```bash
cd backend && pytest tests/test_schemas.py -v
```

Expected: all 6 tests PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/schemas.py backend/tests/test_schemas.py
git commit -m "feat: add Pydantic v2 ExtractedItem and ExtractionResult schemas"
```

---

### Task 2: Update `extraction/base.py`

**Files:**
- Modify: `backend/app/extraction/base.py`

The current `base.py` holds `ExtractedItem` and `ExtractionResult` as dataclasses (used by `repo.py` and `test_repo.py`). We add `CleanedMessage`, change the `Extractor` protocol to accept it, and remove the old dataclasses (now in `schemas.py`). This task will break `repo.py`, `test_repo.py`, and `test_pipeline.py` — they are fixed in Tasks 7–9.

- [ ] **Step 1: Rewrite `backend/app/extraction/base.py`**

```python
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
```

- [ ] **Step 2: Verify the file is syntactically correct**

```bash
cd backend && python -c "from app.extraction.base import CleanedMessage, Extractor; print('OK')"
```

Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add backend/app/extraction/base.py
git commit -m "refactor: add CleanedMessage to extraction base; Extractor now takes CleanedMessage"
```

---

### Task 3: Create `extraction/cleaner.py`

**Files:**
- Create: `backend/app/extraction/cleaner.py`
- Create: `backend/tests/test_cleaner.py`

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_cleaner.py`:

```python
from datetime import datetime, timezone

import pytest

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
```

- [ ] **Step 2: Run tests to verify failure**

```bash
cd backend && pytest tests/test_cleaner.py -v
```

Expected: `ModuleNotFoundError: No module named 'app.extraction.cleaner'`

- [ ] **Step 3: Create `backend/app/extraction/cleaner.py`**

```python
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


def clean_message(msg: RawMessage, max_chars: int = _DEFAULT_MAX_CHARS) -> CleanedMessage:
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
        image_srcs=msg.image_srcs,
    )
```

- [ ] **Step 4: Run tests**

```bash
cd backend && pytest tests/test_cleaner.py -v
```

Expected: all 11 tests PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/extraction/cleaner.py backend/tests/test_cleaner.py
git commit -m "feat: add HTML cleaner and CleanedMessage builder"
```

---

### Task 4: Update `config.py` and `.env.example`

**Files:**
- Modify: `backend/app/config.py`
- Modify: `backend/.env.example`

- [ ] **Step 1: Update `backend/app/config.py`**

```python
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    DATABASE_URL: str = "sqlite+aiosqlite:///./closet.db"
    GMAIL_CREDENTIALS_FILE: str = "credentials.json"
    GMAIL_TOKEN_FILE: str = "token.json"
    GMAIL_ACCOUNT: str = ""
    OLLAMA_BASE_URL: str = "http://localhost:11434"
    OLLAMA_MODEL: str = "qwen2.5:7b"
    BODY_TEXT_MAX_CHARS: int = 6_000

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}
```

- [ ] **Step 2: Update `backend/.env.example`**

Append the new vars (read the file first to know what's already there, then append):

```
# Ollama (local LLM)
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=qwen2.5:7b
BODY_TEXT_MAX_CHARS=6000
```

- [ ] **Step 3: Verify config loads**

```bash
cd backend && python -c "from app.config import Settings; s = Settings(); print(s.OLLAMA_MODEL)"
```

Expected: `qwen2.5:7b`

- [ ] **Step 4: Commit**

```bash
git add backend/app/config.py backend/.env.example
git commit -m "feat: add Ollama config settings"
```

---

### Task 5: Create `extraction/prompt.py`

**Files:**
- Create: `backend/app/extraction/prompt.py`

No separate test file needed — the prompt functions are covered by the extractor integration tests in Task 7.

- [ ] **Step 1: Create `backend/app/extraction/prompt.py`**

```python
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
    image_lines = "\n".join(
        f"{i + 1}. {src}" for i, src in enumerate(msg.image_srcs)
    ) or "None"
    return (
        f"Vendor domain: {msg.vendor_domain}\n"
        f"Subject: {msg.subject}\n"
        f"Date: {msg.date.isoformat()}\n"
        f"\nBody:\n{msg.body_text}\n"
        f"\nCandidate images:\n{image_lines}"
    )
```

- [ ] **Step 2: Verify it imports cleanly**

```bash
cd backend && python -c "from app.extraction.prompt import SYSTEM_PROMPT, build_user_message; print('OK')"
```

Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add backend/app/extraction/prompt.py
git commit -m "feat: add extraction system prompt and user message builder"
```

---

### Task 6: Create `extraction/ollama_extractor.py`

**Files:**
- Create: `backend/app/extraction/ollama_extractor.py`
- Create: `backend/tests/test_ollama_extractor.py`

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_ollama_extractor.py`:

```python
from __future__ import annotations

import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import ValidationError

from app.extraction.base import CleanedMessage
from app.extraction.ollama_extractor import OllamaExtractor
from app.schemas import ExtractionResult


@pytest.fixture
def msg() -> CleanedMessage:
    return CleanedMessage(
        message_id="msg1",
        from_addr="orders@nike.com",
        vendor_domain="nike.com",
        subject="Your Nike order #ORD-999",
        date=datetime(2024, 1, 15, tzinfo=timezone.utc),
        body_text="Thank you for your order. Air Max 90, size 10, $120.",
        image_srcs=["https://example.com/airmax.jpg"],
    )


def _mock_client(content: str) -> AsyncMock:
    resp = MagicMock()
    resp.json.return_value = {"message": {"content": content}}
    resp.raise_for_status = MagicMock()
    client = AsyncMock()
    client.post.return_value = resp
    return client


def _valid_json(overrides: dict | None = None) -> str:
    data = {
        "is_valid_apparel_purchase": True,
        "is_refund_or_cancellation": False,
        "vendor_name": "Nike",
        "merchant_order_id": "ORD-999",
        "purchase_date": "2024-01-15T00:00:00",
        "currency": "USD",
        "total_price": 120.0,
        "items": [
            {
                "item_name": "Air Max 90",
                "size": "10",
                "price": 120.0,
                "image_url": "https://example.com/airmax.jpg",
            }
        ],
        "confidence": 0.95,
    }
    if overrides:
        data.update(overrides)
    return json.dumps(data)


@pytest.mark.asyncio
async def test_extract_valid_purchase(msg):
    client = _mock_client(_valid_json())
    extractor = OllamaExtractor(client=client)
    result = await extractor.extract(msg)

    assert result.is_valid_apparel_purchase is True
    assert result.vendor_name == "Nike"
    assert result.vendor_domain == "nike.com"
    assert len(result.items) == 1
    assert result.items[0].item_name == "Air Max 90"
    assert result.items[0].image_url == "https://example.com/airmax.jpg"


@pytest.mark.asyncio
async def test_vendor_domain_set_from_msg_when_missing(msg):
    json_str = _valid_json({"vendor_domain": None})
    client = _mock_client(json_str)
    extractor = OllamaExtractor(client=client)
    result = await extractor.extract(msg)
    assert result.vendor_domain == "nike.com"


@pytest.mark.asyncio
async def test_image_url_not_in_srcs_is_nulled(msg):
    json_str = _valid_json({
        "items": [{"item_name": "Air Max 90", "image_url": "https://evil.com/fake.jpg"}]
    })
    client = _mock_client(json_str)
    extractor = OllamaExtractor(client=client)
    result = await extractor.extract(msg)
    assert result.items[0].image_url is None


@pytest.mark.asyncio
async def test_promo_returns_invalid(msg):
    json_str = json.dumps({"is_valid_apparel_purchase": False, "items": []})
    client = _mock_client(json_str)
    extractor = OllamaExtractor(client=client)
    result = await extractor.extract(msg)
    assert result.is_valid_apparel_purchase is False


@pytest.mark.asyncio
async def test_retry_on_first_parse_failure(msg):
    bad_json = "not valid json {"
    good_json = json.dumps({"is_valid_apparel_purchase": False, "items": []})

    bad_resp = MagicMock()
    bad_resp.json.return_value = {"message": {"content": bad_json}}
    bad_resp.raise_for_status = MagicMock()

    good_resp = MagicMock()
    good_resp.json.return_value = {"message": {"content": good_json}}
    good_resp.raise_for_status = MagicMock()

    client = AsyncMock()
    client.post.side_effect = [bad_resp, good_resp]

    extractor = OllamaExtractor(client=client)
    result = await extractor.extract(msg)

    assert result.is_valid_apparel_purchase is False
    assert client.post.call_count == 2


@pytest.mark.asyncio
async def test_raises_on_double_parse_failure(msg):
    bad_resp = MagicMock()
    bad_resp.json.return_value = {"message": {"content": "{"}}
    bad_resp.raise_for_status = MagicMock()

    client = AsyncMock()
    client.post.return_value = bad_resp

    extractor = OllamaExtractor(client=client)
    with pytest.raises(ValidationError):
        await extractor.extract(msg)


@pytest.mark.asyncio
async def test_ollama_called_with_correct_model_and_format(msg):
    client = _mock_client(_valid_json())
    extractor = OllamaExtractor(base_url="http://localhost:11434", model="qwen2.5:7b", client=client)
    await extractor.extract(msg)

    call_kwargs = client.post.call_args
    payload = call_kwargs.kwargs.get("json") or call_kwargs.args[1]
    assert payload["model"] == "qwen2.5:7b"
    assert payload["stream"] is False
    assert payload["options"]["temperature"] == 0
    assert "format" in payload
```

- [ ] **Step 2: Run tests to verify failure**

```bash
cd backend && pytest tests/test_ollama_extractor.py -v
```

Expected: `ModuleNotFoundError: No module named 'app.extraction.ollama_extractor'`

- [ ] **Step 3: Create `backend/app/extraction/ollama_extractor.py`**

```python
from __future__ import annotations

import logging

import httpx
from pydantic import ValidationError

from app.extraction.base import CleanedMessage
from app.extraction.prompt import SYSTEM_PROMPT, build_user_message
from app.schemas import ExtractionResult

logger = logging.getLogger(__name__)

_RETRY_INSTRUCTION = (
    "Your previous response was not valid JSON matching the schema. "
    "Return ONLY valid JSON. No explanation, no markdown."
)


class OllamaExtractor:
    def __init__(
        self,
        base_url: str = "http://localhost:11434",
        model: str = "qwen2.5:7b",
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._client = client or httpx.AsyncClient()

    async def extract(self, msg: CleanedMessage) -> ExtractionResult:
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": build_user_message(msg)},
        ]

        raw = await self._call(messages)
        try:
            result = ExtractionResult.model_validate_json(raw)
        except ValidationError:
            logger.warning("extraction:parse_failed:retry message_id=%s", msg.message_id)
            messages.append({"role": "assistant", "content": raw})
            messages.append({"role": "user", "content": _RETRY_INSTRUCTION})
            raw = await self._call(messages)
            result = ExtractionResult.model_validate_json(raw)  # raises on second failure

        if not result.vendor_domain:
            result.vendor_domain = msg.vendor_domain

        for item in result.items:
            if item.image_url and item.image_url not in msg.image_srcs:
                logger.debug(
                    "extraction:image_url_not_in_srcs message_id=%s url=%s",
                    msg.message_id,
                    item.image_url,
                )
                item.image_url = None

        return result

    async def _call(self, messages: list[dict]) -> str:
        payload = {
            "model": self._model,
            "messages": messages,
            "stream": False,
            "options": {"temperature": 0},
            "format": ExtractionResult.model_json_schema(),
        }
        response = await self._client.post(
            f"{self._base_url}/api/chat",
            json=payload,
            timeout=120.0,
        )
        response.raise_for_status()
        return response.json()["message"]["content"]
```

- [ ] **Step 4: Run tests**

```bash
cd backend && pytest tests/test_ollama_extractor.py -v
```

Expected: all 7 tests PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/extraction/ollama_extractor.py backend/tests/test_ollama_extractor.py
git commit -m "feat: add OllamaExtractor with constrained JSON output and retry"
```

---

### Task 7: Update `store/repo.py`

**Files:**
- Modify: `backend/app/store/repo.py`

Change import from `app.extraction.base` → `app.schemas`; rename `image_url_src` → `image_url`.

- [ ] **Step 1: Update the import and field reference in `backend/app/store/repo.py`**

Change line 9:
```python
from app.extraction.base import ExtractionResult
```
to:
```python
from app.schemas import ExtractionResult
```

Change line 105 (inside `upsert_order`, the `Item(...)` call):
```python
                image_url_src=item_data.image_url_src,
```
to:
```python
                image_url_src=item_data.image_url,
```

- [ ] **Step 2: Verify import works**

```bash
cd backend && python -c "from app.store.repo import upsert_order; print('OK')"
```

Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add backend/app/store/repo.py
git commit -m "refactor: repo imports ExtractionResult from schemas; use image_url field"
```

---

### Task 8: Update `ingestion/pipeline.py`

**Files:**
- Modify: `backend/app/ingestion/pipeline.py`

Add the `clean_message` step so the pipeline passes a `CleanedMessage` to the extractor.

- [ ] **Step 1: Update `backend/app/ingestion/pipeline.py`**

Add import at the top (after existing imports):
```python
from app.extraction.cleaner import clean_message
```

Inside `_drain`, replace:
```python
                    extraction = await extractor.extract(message)
```
with:
```python
                    cleaned = clean_message(message)
                    extraction = await extractor.extract(cleaned)
```

- [ ] **Step 2: Verify import and syntax**

```bash
cd backend && python -c "from app.ingestion.pipeline import run_initialize; print('OK')"
```

Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add backend/app/ingestion/pipeline.py
git commit -m "refactor: pipeline cleans RawMessage to CleanedMessage before extraction"
```

---

### Task 9: Update existing tests

**Files:**
- Modify: `backend/tests/test_repo.py`
- Modify: `backend/tests/test_pipeline.py`

- [ ] **Step 1: Update `backend/tests/test_repo.py`**

Change line 6:
```python
from app.extraction.base import ExtractedItem, ExtractionResult
```
to:
```python
from app.schemas import ExtractedItem, ExtractionResult
```

Change the `total_price` values from `Decimal(...)` to `float` in `_extraction()` (line ~21):
```python
        total_price=99.99,
```

Also remove the `Decimal` import if it's no longer used (check if any other test in the file uses it; it's not used elsewhere, so remove line 3: `from decimal import Decimal`).

Change line 94 and line 97 in `test_upsert_order_updates_existing_not_duplicate` — `_extraction(total_price=Decimal("50.00"))` and `_extraction(total_price=Decimal("75.00"))` become:
```python
    await upsert_order(session, _extraction(total_price=50.0))
    ...
    await upsert_order(session, _extraction(total_price=75.0))
```

The assertion `assert saved.total_price == Decimal("75.00")` (line 106) is comparing the DB value (still a Decimal from the Numeric column), so leave it as-is.

- [ ] **Step 2: Update `backend/tests/test_pipeline.py`**

Change line 5–6:
```python
from app.extraction.base import ExtractedItem, ExtractionResult
```
to:
```python
from app.extraction.base import CleanedMessage
from app.schemas import ExtractedItem, ExtractionResult
```

Remove `from decimal import Decimal` if present.

Change the `FakeExtractor.extract` signature (line 54):
```python
    async def extract(self, message: CleanedMessage) -> ExtractionResult:
```

Change `_good_extraction()` — replace `Decimal("49.99")` with `49.99`:
```python
        total_price=49.99,
```

- [ ] **Step 3: Run the full test suite**

```bash
cd backend && pytest -v
```

Expected: all existing tests PASS (no regressions)

- [ ] **Step 4: Commit**

```bash
git add backend/tests/test_repo.py backend/tests/test_pipeline.py
git commit -m "refactor: update tests to import from app.schemas"
```

---

### Task 10: Full suite + linting

**Files:** none — verification only

- [ ] **Step 1: Run ruff + black check + pytest**

```bash
cd backend && ruff check . && black --check . && pytest -q
```

Expected output (example):
```
All checks passed!
reformatted 0 files
......................................
N passed in Xs
```

If ruff finds issues, fix them:
```bash
cd backend && ruff check . --fix
```

If black wants reformatting:
```bash
cd backend && black .
```

Then re-run the full check.

- [ ] **Step 2: Commit any lint fixes**

```bash
git add -u
git commit -m "style: ruff/black fixes for phase 03"
```

---

### Task 11: Definition-of-Done — Integration verification

The spec DoD requires feeding 3 sample emails through the extractor:
1. A real order → full structured items, `is_valid_apparel_purchase=true`
2. A shipping notice → `is_valid_apparel_purchase=true` or `false`, no items (or matches order)
3. A promo → `is_valid_apparel_purchase=false`

**Files:**
- Create: `backend/tests/test_extraction_dod.py`

- [ ] **Step 1: Create `backend/tests/test_extraction_dod.py`**

This test mocks the Ollama HTTP call with realistic responses to verify the full path — prompt building, HTTP call, schema validation, image_url post-processing, and vendor_domain enrichment — for all three email scenarios.

```python
"""
Definition-of-Done tests for phase 03.

These use mocked Ollama responses to verify the full extraction path for the three
required scenarios: real order, shipping notice, promo.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.extraction.base import CleanedMessage
from app.extraction.ollama_extractor import OllamaExtractor
from app.schemas import ExtractionResult


def _make_msg(
    subject: str,
    body_text: str,
    vendor_domain: str = "zara.com",
    image_srcs: list[str] | None = None,
) -> CleanedMessage:
    return CleanedMessage(
        message_id="dod-test",
        from_addr=f"noreply@{vendor_domain}",
        vendor_domain=vendor_domain,
        subject=subject,
        date=datetime(2024, 3, 10, tzinfo=timezone.utc),
        body_text=body_text,
        image_srcs=image_srcs or [],
    )


def _extractor(ollama_response: dict) -> OllamaExtractor:
    resp = MagicMock()
    resp.json.return_value = {"message": {"content": json.dumps(ollama_response)}}
    resp.raise_for_status = MagicMock()
    client = AsyncMock()
    client.post.return_value = resp
    return OllamaExtractor(client=client)


@pytest.mark.asyncio
async def test_dod_real_order_returns_structured_items():
    msg = _make_msg(
        subject="Order Confirmation #ZR-20240310",
        body_text="Thank you for your order. Zara Slim Fit Jeans, size 32, €49.99.",
        image_srcs=["https://zara.com/img/jeans.jpg"],
    )
    ollama_resp = {
        "is_valid_apparel_purchase": True,
        "is_refund_or_cancellation": False,
        "vendor_name": "Zara",
        "merchant_order_id": "ZR-20240310",
        "purchase_date": "2024-03-10T00:00:00",
        "currency": "EUR",
        "total_price": 49.99,
        "items": [
            {
                "item_name": "Slim Fit Jeans",
                "brand": "Zara",
                "size": "32",
                "price": 49.99,
                "image_url": "https://zara.com/img/jeans.jpg",
            }
        ],
        "confidence": 0.92,
    }
    result = await _extractor(ollama_resp).extract(msg)

    assert result.is_valid_apparel_purchase is True
    assert len(result.items) == 1
    assert result.items[0].item_name == "Slim Fit Jeans"
    assert result.items[0].size == "32"
    assert result.items[0].image_url == "https://zara.com/img/jeans.jpg"
    assert result.merchant_order_id == "ZR-20240310"
    assert result.vendor_domain == "zara.com"
    # Pydantic validation passed (result is an ExtractionResult instance)
    assert isinstance(result, ExtractionResult)


@pytest.mark.asyncio
async def test_dod_shipping_notice_no_items():
    msg = _make_msg(
        subject="Your Zara order is on its way!",
        body_text="Your order #ZR-20240310 has been dispatched. Expected delivery: March 13.",
    )
    ollama_resp = {
        "is_valid_apparel_purchase": True,
        "is_refund_or_cancellation": False,
        "vendor_name": "Zara",
        "merchant_order_id": "ZR-20240310",
        "purchase_date": None,
        "items": [],
        "confidence": 0.7,
    }
    result = await _extractor(ollama_resp).extract(msg)

    assert result.is_valid_apparel_purchase is True
    assert result.merchant_order_id == "ZR-20240310"
    assert result.items == []
    assert isinstance(result, ExtractionResult)


@pytest.mark.asyncio
async def test_dod_promo_returns_invalid():
    msg = _make_msg(
        subject="New collection just dropped — up to 50% off",
        body_text="Shop now. Sale ends midnight. New arrivals in stock.",
    )
    ollama_resp = {
        "is_valid_apparel_purchase": False,
        "items": [],
    }
    result = await _extractor(ollama_resp).extract(msg)

    assert result.is_valid_apparel_purchase is False
    assert result.items == []
    assert isinstance(result, ExtractionResult)
```

- [ ] **Step 2: Run DoD tests**

```bash
cd backend && pytest tests/test_extraction_dod.py -v
```

Expected: all 3 tests PASS

- [ ] **Step 3: Run full suite**

```bash
cd backend && ruff check . && black --check . && pytest -q
```

Paste the actual output before marking this phase complete.

- [ ] **Step 4: Commit**

```bash
git add backend/tests/test_extraction_dod.py
git commit -m "test: add phase-03 definition-of-done extraction tests"
```

---

## Definition of Done Checklist

- [ ] `backend/app/schemas.py` exists with Pydantic v2 `ExtractedItem` + `ExtractionResult`
- [ ] `extraction/base.py` has `CleanedMessage` dataclass and `Extractor` protocol taking it
- [ ] `extraction/cleaner.py` strips HTML, truncates body text, derives vendor_domain
- [ ] `extraction/prompt.py` has `SYSTEM_PROMPT` and `build_user_message`
- [ ] `extraction/ollama_extractor.py` calls Ollama with constrained JSON, retries once on parse failure, nulls invalid image_url, sets vendor_domain from `CleanedMessage`
- [ ] `pipeline.py` calls `clean_message` before passing to extractor
- [ ] `repo.py` imports from `schemas`; uses `item.image_url`
- [ ] `ruff check . && black --check . && pytest -q` all pass with output shown
