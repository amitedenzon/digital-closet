# Phase 04 — Images Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Download and store product images at ingest time, filtering out tracking pixels and tiny logos, and populate `items.image_path` in the database.

**Architecture:** A new `ingestion/images.py` module provides URL filtering (junk URLs, tracking pixel filenames), post-download size filtering (Pillow), per-order hash-based dedup, and an async orchestrator `download_order_images` that updates `Item.image_path` on the ORM objects already in-session. `repo.upsert_order` is changed to return `(Order, list[Item])` so the pipeline can pass the new DB items directly to the image downloader. The pipeline creates one `httpx.AsyncClient` per `_drain` run and passes it through.

**Tech Stack:** Python 3.11+, httpx (async), Pillow (image dimensions + magic bytes), pathlib, asyncio, SQLAlchemy 2.0 async session.

---

## File Map

| Action | Path | Responsibility |
|--------|------|----------------|
| **Create** | `backend/app/ingestion/images.py` | URL junk filter, pixel filter, download with retry, save to disk, dedup, orchestrator |
| **Create** | `backend/tests/test_images.py` | All tests for `images.py` |
| **Modify** | `backend/app/store/repo.py` | `upsert_order` returns `tuple[Order, list[Item]]` |
| **Modify** | `backend/tests/test_repo.py` | Unpack tuple from `upsert_order` calls |
| **Modify** | `backend/app/ingestion/pipeline.py` | Import httpx + images; add client context manager; call `download_order_images` after upsert |
| **Modify** | `backend/app/config.py` | Add `IMAGE_STORE_DIR`, `IMAGE_MIN_DIMENSION`, `IMAGE_CONCURRENCY` |
| **Modify** | `backend/.env.example` | Document new image config vars |

---

### Task 1: URL filter and pixel filter — pure functions in `images.py`

**Files:**
- Create: `backend/app/ingestion/images.py`
- Create: `backend/tests/test_images.py`

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_images.py`:

```python
from __future__ import annotations

import io

import pytest
from PIL import Image

from app.ingestion.images import (
    _image_ext_from_bytes,
    content_hash,
    is_junk_url,
    is_tiny_image,
)


def _make_png(w: int, h: int) -> bytes:
    img = Image.new("RGB", (w, h), color=(255, 0, 0))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _make_jpeg(w: int, h: int) -> bytes:
    img = Image.new("RGB", (w, h), color=(0, 0, 255))
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    return buf.getvalue()


# --- is_junk_url ---

def test_junk_data_uri():
    assert is_junk_url("data:image/png;base64,abc123") is True


def test_junk_cid_ref():
    assert is_junk_url("cid:image001.jpg@01D5ABC") is True


def test_junk_pixel_filename():
    assert is_junk_url("https://example.com/pixel.gif") is True


def test_junk_tracking_open():
    assert is_junk_url("https://track.example.com/open.aspx?id=123") is True


def test_junk_spacer():
    assert is_junk_url("https://cdn.example.com/spacer.png") is True


def test_junk_1x1():
    assert is_junk_url("https://img.example.com/1x1.gif") is True


def test_junk_beacon():
    assert is_junk_url("https://mail.example.com/beacon?u=abc") is True


def test_not_junk_normal_product_url():
    assert is_junk_url("https://cdn.zara.com/img/products/12345.jpg") is False


def test_not_junk_https_with_query():
    assert is_junk_url("https://example.com/images/shoe.jpg?w=800") is False


# --- _image_ext_from_bytes ---

def test_ext_jpeg():
    content = _make_jpeg(10, 10)
    assert _image_ext_from_bytes(content) == "jpg"


def test_ext_png():
    content = _make_png(10, 10)
    assert _image_ext_from_bytes(content) == "png"


def test_ext_unknown():
    assert _image_ext_from_bytes(b"not an image at all") is None


# --- is_tiny_image ---

def test_not_tiny_200x200():
    assert is_tiny_image(_make_png(200, 200), min_dimension=100) is False


def test_tiny_1x1():
    assert is_tiny_image(_make_png(1, 1), min_dimension=100) is True


def test_tiny_width_only():
    assert is_tiny_image(_make_png(50, 200), min_dimension=100) is True


def test_tiny_height_only():
    assert is_tiny_image(_make_png(200, 50), min_dimension=100) is True


def test_tiny_on_garbage_bytes():
    assert is_tiny_image(b"garbage", min_dimension=100) is True


def test_exactly_at_boundary_is_not_tiny():
    assert is_tiny_image(_make_png(100, 100), min_dimension=100) is False


# --- content_hash ---

def test_content_hash_is_deterministic():
    b = b"hello world"
    assert content_hash(b) == content_hash(b)


def test_content_hash_differs_for_different_content():
    assert content_hash(b"aaa") != content_hash(b"bbb")


def test_content_hash_is_64_hex_chars():
    h = content_hash(b"test")
    assert len(h) == 64
    assert all(c in "0123456789abcdef" for c in h)
```

- [ ] **Step 2: Run tests to verify failure**

```bash
cd backend && pytest tests/test_images.py -v
```

Expected: `ModuleNotFoundError: No module named 'app.ingestion.images'`

- [ ] **Step 3: Create `backend/app/ingestion/images.py` with the pure filter functions**

```python
from __future__ import annotations

import hashlib
import io
import logging
import re

from PIL import Image

logger = logging.getLogger(__name__)

_TRACKING_NAMES = re.compile(r"pixel|open|track|spacer|1x1|beacon", re.IGNORECASE)
_JUNK_PREFIXES = ("data:", "cid:")
_MAGIC_JPEG = b"\xff\xd8\xff"
_MAGIC_PNG = b"\x89PNG\r\n\x1a\n"


def is_junk_url(url: str) -> bool:
    for prefix in _JUNK_PREFIXES:
        if url.startswith(prefix):
            return True
    filename = url.split("?")[0].split("/")[-1]
    return bool(_TRACKING_NAMES.search(filename))


def _image_ext_from_bytes(content: bytes) -> str | None:
    if content[:3] == _MAGIC_JPEG:
        return "jpg"
    if content[:8] == _MAGIC_PNG:
        return "png"
    return None


def is_tiny_image(content: bytes, min_dimension: int = 100) -> bool:
    try:
        img = Image.open(io.BytesIO(content))
        w, h = img.size
        return w < min_dimension or h < min_dimension
    except Exception:
        return True


def content_hash(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()
```

- [ ] **Step 4: Run tests**

```bash
cd backend && pytest tests/test_images.py -v
```

Expected: all 22 tests PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/ingestion/images.py backend/tests/test_images.py
git commit -m "feat: add image URL filter and pixel filter pure functions"
```

---

### Task 2: Add `_download_image` to `images.py`

**Files:**
- Modify: `backend/app/ingestion/images.py`
- Modify: `backend/tests/test_images.py`

- [ ] **Step 1: Add download tests to `backend/tests/test_images.py`**

Append after the existing tests:

```python
# --- _download_image ---

import httpx
from unittest.mock import AsyncMock, MagicMock

from app.ingestion.images import _download_image


@pytest.mark.asyncio
async def test_download_image_success():
    jpeg_bytes = _make_jpeg(200, 200)
    mock_resp = MagicMock()
    mock_resp.content = jpeg_bytes
    mock_resp.headers = {"content-type": "image/jpeg"}
    mock_resp.raise_for_status = MagicMock()
    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.get.return_value = mock_resp

    result = await _download_image(
        "https://example.com/shoe.jpg", "example.com", mock_client
    )

    assert result is not None
    content, ct = result
    assert content == jpeg_bytes
    assert "jpeg" in ct
    mock_client.get.assert_called_once()


@pytest.mark.asyncio
async def test_download_image_sends_user_agent_and_referer():
    mock_resp = MagicMock()
    mock_resp.content = _make_jpeg(200, 200)
    mock_resp.headers = {"content-type": "image/jpeg"}
    mock_resp.raise_for_status = MagicMock()
    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.get.return_value = mock_resp

    await _download_image("https://example.com/shoe.jpg", "example.com", mock_client)

    call_kwargs = mock_client.get.call_args
    headers = call_kwargs.kwargs.get("headers") or call_kwargs.args[1]
    assert "User-Agent" in headers
    assert headers["Referer"] == "https://example.com/"


@pytest.mark.asyncio
async def test_download_image_retries_once_on_failure():
    jpeg_bytes = _make_jpeg(200, 200)

    mock_fail = MagicMock()
    mock_fail.raise_for_status.side_effect = Exception("HTTP 500")

    mock_ok = MagicMock()
    mock_ok.content = jpeg_bytes
    mock_ok.headers = {"content-type": "image/jpeg"}
    mock_ok.raise_for_status = MagicMock()

    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.get.side_effect = [mock_fail, mock_ok]

    result = await _download_image(
        "https://example.com/shoe.jpg", "example.com", mock_client
    )

    assert result is not None
    assert mock_client.get.call_count == 2


@pytest.mark.asyncio
async def test_download_image_returns_none_after_two_failures():
    mock_resp = MagicMock()
    mock_resp.raise_for_status.side_effect = Exception("HTTP 500")
    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.get.return_value = mock_resp

    result = await _download_image(
        "https://example.com/shoe.jpg", "example.com", mock_client
    )

    assert result is None
    assert mock_client.get.call_count == 2
```

- [ ] **Step 2: Run new tests to verify failure**

```bash
cd backend && pytest tests/test_images.py -k "download_image" -v
```

Expected: `ImportError: cannot import name '_download_image'`

- [ ] **Step 3: Add `_download_image` to `backend/app/ingestion/images.py`**

Add after the `content_hash` function (before the end of file):

```python
import httpx


async def _download_image(
    url: str,
    vendor_domain: str,
    client: httpx.AsyncClient,
    timeout: float = 10.0,
) -> tuple[bytes, str] | None:
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; digital-closet/1.0)",
        "Referer": f"https://{vendor_domain}/",
    }
    for attempt in range(2):
        try:
            resp = await client.get(
                url, headers=headers, timeout=timeout, follow_redirects=True
            )
            resp.raise_for_status()
            return resp.content, resp.headers.get("content-type", "")
        except Exception as exc:
            if attempt == 0:
                logger.debug("image:download_retry url=%s", url)
            else:
                logger.warning("image:download_failed url=%s exc=%s", url, exc)
    return None
```

Note: `import httpx` goes at the top of the file with the other imports.

The full top-of-file imports section should be:

```python
from __future__ import annotations

import hashlib
import io
import logging
import re

import httpx
from PIL import Image
```

- [ ] **Step 4: Run all image tests**

```bash
cd backend && pytest tests/test_images.py -v
```

Expected: all 26 tests PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/ingestion/images.py backend/tests/test_images.py
git commit -m "feat: add _download_image with retry and User-Agent/Referer headers"
```

---

### Task 3: Add `download_order_images` orchestrator

**Files:**
- Modify: `backend/app/ingestion/images.py`
- Modify: `backend/tests/test_images.py`

- [ ] **Step 1: Add orchestrator tests to `backend/tests/test_images.py`**

Add these imports at the top of `test_images.py` (alongside existing imports):

```python
from pathlib import Path
from sqlalchemy.ext.asyncio import AsyncSession
from app.ingestion.images import download_order_images
```

Append tests at the end of `test_images.py`:

```python
# --- download_order_images ---


def _mock_item(item_id: str) -> MagicMock:
    item = MagicMock()
    item.id = item_id
    item.image_path = None
    return item


def _mock_client_with_content(content: bytes, ct: str = "image/png") -> AsyncMock:
    mock_resp = MagicMock()
    mock_resp.content = content
    mock_resp.headers = {"content-type": ct}
    mock_resp.raise_for_status = MagicMock()
    client = AsyncMock(spec=httpx.AsyncClient)
    client.get.return_value = mock_resp
    return client


@pytest.mark.asyncio
async def test_download_order_images_saves_image(tmp_path):
    png_bytes = _make_png(200, 200)
    client = _mock_client_with_content(png_bytes)
    item = _mock_item("item-abc")
    session = MagicMock(spec=AsyncSession)

    await download_order_images(
        session,
        items=[item],
        image_urls=["https://example.com/shoe.png"],
        vendor_domain="example.com",
        order_id="order-xyz",
        store_dir=tmp_path,
        client=client,
        min_dimension=100,
    )

    expected = tmp_path / "example.com" / "order-xyz" / "item-abc.png"
    assert expected.exists()
    assert expected.read_bytes() == png_bytes
    assert item.image_path == str(expected)


@pytest.mark.asyncio
async def test_download_order_images_skips_junk_url(tmp_path):
    client = AsyncMock(spec=httpx.AsyncClient)
    item = _mock_item("item-1")
    session = MagicMock(spec=AsyncSession)

    await download_order_images(
        session,
        items=[item],
        image_urls=["data:image/png;base64,abc"],
        vendor_domain="example.com",
        order_id="order-xyz",
        store_dir=tmp_path,
        client=client,
        min_dimension=100,
    )

    client.get.assert_not_called()
    assert item.image_path is None


@pytest.mark.asyncio
async def test_download_order_images_skips_none_url(tmp_path):
    client = AsyncMock(spec=httpx.AsyncClient)
    item = _mock_item("item-1")
    session = MagicMock(spec=AsyncSession)

    await download_order_images(
        session,
        items=[item],
        image_urls=[None],
        vendor_domain="example.com",
        order_id="order-xyz",
        store_dir=tmp_path,
        client=client,
        min_dimension=100,
    )

    client.get.assert_not_called()
    assert item.image_path is None


@pytest.mark.asyncio
async def test_download_order_images_skips_tiny_image(tmp_path):
    tiny_bytes = _make_png(1, 1)
    client = _mock_client_with_content(tiny_bytes)
    item = _mock_item("item-1")
    session = MagicMock(spec=AsyncSession)

    await download_order_images(
        session,
        items=[item],
        image_urls=["https://example.com/pixel.png"],
        vendor_domain="example.com",
        order_id="order-xyz",
        store_dir=tmp_path,
        client=client,
        min_dimension=100,
    )

    assert item.image_path is None
    assert not any(tmp_path.rglob("*.png"))


@pytest.mark.asyncio
async def test_download_order_images_dedup_identical_bytes(tmp_path):
    png_bytes = _make_png(200, 200)
    client = _mock_client_with_content(png_bytes)
    item1 = _mock_item("item-1")
    item2 = _mock_item("item-2")
    session = MagicMock(spec=AsyncSession)

    await download_order_images(
        session,
        items=[item1, item2],
        image_urls=[
            "https://example.com/img.png",
            "https://example.com/img.png",
        ],
        vendor_domain="example.com",
        order_id="order-xyz",
        store_dir=tmp_path,
        client=client,
        min_dimension=100,
    )

    assert item1.image_path is not None
    assert item2.image_path == item1.image_path
    saved = list(tmp_path.rglob("*.png"))
    assert len(saved) == 1


@pytest.mark.asyncio
async def test_download_order_images_continues_on_download_failure(tmp_path):
    client = AsyncMock(spec=httpx.AsyncClient)
    client.get.side_effect = Exception("network error")
    item = _mock_item("item-1")
    session = MagicMock(spec=AsyncSession)

    await download_order_images(
        session,
        items=[item],
        image_urls=["https://example.com/shoe.jpg"],
        vendor_domain="example.com",
        order_id="order-xyz",
        store_dir=tmp_path,
        client=client,
        min_dimension=100,
    )

    assert item.image_path is None
```

- [ ] **Step 2: Run new tests to verify failure**

```bash
cd backend && pytest tests/test_images.py -k "download_order_images" -v
```

Expected: `ImportError: cannot import name 'download_order_images'`

- [ ] **Step 3: Add `download_order_images` to `backend/app/ingestion/images.py`**

Add these imports at the top of `images.py`:

```python
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Item
```

Append the function after `_download_image`:

```python
async def download_order_images(
    session: AsyncSession,
    items: list[Item],
    image_urls: list[str | None],
    vendor_domain: str,
    order_id: str,
    *,
    store_dir: Path,
    client: httpx.AsyncClient,
    min_dimension: int = 100,
) -> None:
    seen_hashes: dict[str, str] = {}

    for item, url in zip(items, image_urls):
        if not url or is_junk_url(url):
            continue
        try:
            downloaded = await _download_image(url, vendor_domain, client)
            if downloaded is None:
                continue

            content, content_type = downloaded

            ext = _image_ext_from_bytes(content)
            if ext is None:
                if "png" in content_type:
                    ext = "png"
                elif "jpeg" in content_type or "jpg" in content_type:
                    ext = "jpg"
                else:
                    logger.warning(
                        "image:unknown_type item_id=%s url=%s ct=%s",
                        item.id, url, content_type,
                    )
                    continue

            if is_tiny_image(content, min_dimension):
                logger.debug("image:too_small item_id=%s url=%s", item.id, url)
                continue

            h = content_hash(content)
            if h in seen_hashes:
                item.image_path = seen_hashes[h]
                logger.debug("image:dedup item_id=%s path=%s", item.id, item.image_path)
                continue

            dest = store_dir / vendor_domain / order_id / f"{item.id}.{ext}"
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(content)

            item.image_path = str(dest)
            seen_hashes[h] = item.image_path
            logger.info("image:saved item_id=%s path=%s", item.id, item.image_path)

        except Exception as exc:
            logger.warning("image:error item_id=%s url=%s exc=%s", item.id, url, exc)
```

The full imports section at the top of `images.py` after this task:

```python
from __future__ import annotations

import hashlib
import io
import logging
import re
from pathlib import Path

import httpx
from PIL import Image
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Item
```

- [ ] **Step 4: Run all image tests**

```bash
cd backend && pytest tests/test_images.py -v
```

Expected: all 32 tests PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/ingestion/images.py backend/tests/test_images.py
git commit -m "feat: add download_order_images orchestrator with filter, dedup, and error resilience"
```

---

### Task 4: Update `repo.upsert_order` to return `(Order, list[Item])` and fix `test_repo.py`

**Files:**
- Modify: `backend/app/store/repo.py`
- Modify: `backend/tests/test_repo.py`

- [ ] **Step 1: Update `backend/app/store/repo.py`**

Change the `upsert_order` function signature return annotation and body. The full updated function (replace everything from `async def upsert_order` to the end of its body):

```python
async def upsert_order(
    session: AsyncSession,
    extraction: ExtractionResult,
) -> tuple[Order, list[Item]]:
    """
    Insert a new order or update the existing one matched by (vendor_domain, merchant_order_id).
    Items are always replaced wholesale (delete-all then re-insert) since we trust the
    latest extraction to be the most complete view of the order.
    NULL merchant_order_id bypasses dedup and always inserts a new row.
    Returns the order and the freshly-inserted Item ORM objects (with IDs populated).
    """
    existing: Order | None = None
    if extraction.vendor_domain and extraction.merchant_order_id:
        stmt = select(Order).where(
            Order.vendor_domain == extraction.vendor_domain,
            Order.merchant_order_id == extraction.merchant_order_id,
        )
        result = await session.execute(stmt)
        existing = result.scalar_one_or_none()
    else:
        logger.warning(
            "upsert_order: skipping dedup (vendor_domain=%r, merchant_order_id=%r) — will always insert new row",
            extraction.vendor_domain,
            extraction.merchant_order_id,
        )

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

    new_items: list[Item] = []
    for item_data in extraction.items:
        item = Item(
            order_id=order.id,
            item_name=item_data.item_name,
            brand=item_data.brand,
            size=item_data.size,
            color=item_data.color,
            quantity=item_data.quantity,
            price=item_data.price,
            image_url_src=item_data.image_url,
        )
        session.add(item)
        new_items.append(item)
    await session.flush()
    return order, new_items
```

- [ ] **Step 2: Update `backend/tests/test_repo.py`**

Every call to `await upsert_order(session, ...)` must unpack the tuple. There are 5 such calls. Change each one:

Line 79:
```python
order = await upsert_order(session, _extraction())
```
→
```python
order, _ = await upsert_order(session, _extraction())
```

Line 94:
```python
await upsert_order(session, _extraction(total_price=50.0))
```
→
```python
await upsert_order(session, _extraction(total_price=50.0))
```
(no change — return value not used)

Line 97:
```python
await upsert_order(session, _extraction(total_price=75.0))
```
(no change — return value not used)

Lines 121–122:
```python
await upsert_order(session, first)
```
(no change — return value not used)

Line 125:
```python
order = await upsert_order(session, second)
```
→
```python
order, _ = await upsert_order(session, second)
```

Lines 142–145:
```python
await upsert_order(session, _extraction(merchant_order_id=None))
await upsert_order(session, _extraction(merchant_order_id=None))
```
(no change — return values not used)

- [ ] **Step 3: Run repo tests**

```bash
cd backend && pytest tests/test_repo.py -v
```

Expected: all 10 tests PASS

- [ ] **Step 4: Commit**

```bash
git add backend/app/store/repo.py backend/tests/test_repo.py
git commit -m "refactor: upsert_order returns (Order, list[Item]) for image download wiring"
```

---

### Task 5: Update `config.py` and `.env.example`

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
    IMAGE_STORE_DIR: str = "data/images"
    IMAGE_MIN_DIMENSION: int = 100
    IMAGE_CONCURRENCY: int = 5

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}
```

- [ ] **Step 2: Append to `backend/.env.example`**

```
# Image storage
IMAGE_STORE_DIR=data/images
IMAGE_MIN_DIMENSION=100
IMAGE_CONCURRENCY=5
```

- [ ] **Step 3: Verify config loads**

```bash
cd backend && python -c "from app.config import Settings; s = Settings(); print(s.IMAGE_STORE_DIR, s.IMAGE_MIN_DIMENSION)"
```

Expected: `data/images 100`

- [ ] **Step 4: Commit**

```bash
git add backend/app/config.py backend/.env.example
git commit -m "feat: add image config settings (IMAGE_STORE_DIR, IMAGE_MIN_DIMENSION, IMAGE_CONCURRENCY)"
```

---

### Task 6: Wire `download_order_images` into `pipeline.py`

**Files:**
- Modify: `backend/app/ingestion/pipeline.py`

- [ ] **Step 1: Update imports at top of `backend/app/ingestion/pipeline.py`**

Add `httpx` and `Path` imports and import the images module. Change the imports block to:

```python
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import httpx
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.extraction.base import Extractor
from app.extraction.cleaner import clean_message
from app.ingestion import images
from app.ingestion.prefilter import should_keep
from app.models import MessageResult
from app.providers.base import MailProvider, ProviderQuery
from app.store import repo
```

- [ ] **Step 2: Wrap the `_drain` while-loop with an `httpx.AsyncClient` context manager**

In `_drain`, change the body so it reads:

```python
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

    async with httpx.AsyncClient() as http_client:
        while True:
            page = await provider.search(query, page_cursor)

            for ref in page.refs:
                result.scanned += 1

                async with session_factory() as session:
                    if await repo.is_processed(session, ref.message_id):
                        result.skipped += 1
                        logger.debug("skip:already_processed message_id=%s", ref.message_id)
                        continue

                    try:
                        message = await provider.fetch(ref.message_id)
                        if max_internal_date is None or message.date > max_internal_date:
                            max_internal_date = message.date

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
                                ref.message_id,
                                message.subject,
                            )
                            continue

                        cleaned = clean_message(
                            message, max_chars=_settings.BODY_TEXT_MAX_CHARS
                        )
                        extraction = await extractor.extract(cleaned)

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

                        order, db_items = await repo.upsert_order(session, extraction)
                        await images.download_order_images(
                            session,
                            db_items,
                            [item.image_url for item in extraction.items],
                            vendor_domain=extraction.vendor_domain or "",
                            order_id=order.id,
                            store_dir=Path(_settings.IMAGE_STORE_DIR),
                            client=http_client,
                            min_dimension=_settings.IMAGE_MIN_DIMENSION,
                        )
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
                        try:
                            async with session_factory() as err_session:
                                await repo.record_processed(
                                    err_session,
                                    message_id=ref.message_id,
                                    provider=provider_name,
                                    account=account,
                                    result=MessageResult.error,
                                )
                                await err_session.commit()
                        except Exception as record_exc:
                            logger.exception(
                                "error:failed_to_record_error message_id=%s",
                                ref.message_id,
                                exc_info=record_exc,
                            )
                        result.errors += 1
                        logger.exception(
                            "error:processing message_id=%s", ref.message_id, exc_info=exc
                        )

            if page.next_cursor is None:
                break
            page_cursor = page.next_cursor

    if max_internal_date is not None:
        new_ms = int(max_internal_date.timestamp() * 1000)
        async with session_factory() as session:
            state = await repo.get_or_create_sync_state(session, provider_name, account)
            old_ms = int(state.cursor) if state.cursor else 0
            cursor_str = str(max(new_ms, old_ms))
            await repo.update_sync_cursor(session, provider_name, account, cursor_str)
            await session.commit()

    return result
```

- [ ] **Step 3: Verify pipeline imports cleanly**

```bash
cd backend && python -c "from app.ingestion.pipeline import run_initialize; print('OK')"
```

Expected: `OK`

- [ ] **Step 4: Run the existing pipeline tests (no changes needed — extraction items have no image_url so download is a no-op)**

```bash
cd backend && pytest tests/test_pipeline.py -v
```

Expected: all 7 tests PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/ingestion/pipeline.py
git commit -m "feat: wire download_order_images into ingestion pipeline"
```

---

### Task 7: Full suite, linting, and Definition-of-Done verification

**Files:** none — verification only

- [ ] **Step 1: Run ruff + black + full pytest**

```bash
cd backend && ruff check . && black --check . && pytest -q
```

Expected: all checks pass, all tests pass. Paste the actual output.

If ruff finds issues:
```bash
cd backend && ruff check . --fix && ruff check .
```

If black wants reformatting:
```bash
cd backend && black .
```

Then re-run the full check.

- [ ] **Step 2: Commit any lint fixes**

```bash
git add -u
git commit -m "style: ruff/black fixes for phase 04"
```

- [ ] **Step 3: Manual DoD verification**

The spec DoD: "For a sample order email, the genuine product image is downloaded to `data/images/...`, tracking pixels and header logos are rejected, and `items.image_path` is populated."

Run a manual end-to-end check using a real extraction result fixture. Create a temporary script (do NOT commit it) to verify the image pipeline in isolation:

```python
# tmp_test_images_dod.py (run from backend/, delete after)
import asyncio
import io
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from PIL import Image

from app.ingestion.images import download_order_images, is_junk_url


def make_png(w, h):
    img = Image.new("RGB", (w, h), (0, 128, 255))
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


async def main():
    product_bytes = make_png(300, 400)
    pixel_bytes = make_png(1, 1)

    class Item:
        def __init__(self, id_):
            self.id = id_
            self.image_path = None

    items = [Item("item-product"), Item("item-logo")]
    image_urls = [
        "https://cdn.nike.com/products/airmax.png",  # should save
        "https://track.nike.com/pixel.gif",           # junk URL, should skip
    ]

    def side_effect(url, **kwargs):
        resp = MagicMock()
        if "airmax" in url:
            resp.content = product_bytes
            resp.headers = {"content-type": "image/png"}
        else:
            resp.content = pixel_bytes
            resp.headers = {"content-type": "image/png"}
        resp.raise_for_status = MagicMock()
        return resp

    client = AsyncMock()
    client.get.side_effect = side_effect

    store = Path("/tmp/closet_dod_test")
    store.mkdir(exist_ok=True)

    session = MagicMock()
    await download_order_images(
        session, items, image_urls,
        vendor_domain="nike.com", order_id="order-test",
        store_dir=store, client=client, min_dimension=100,
    )

    print("item-product image_path:", items[0].image_path)
    print("item-logo image_path (should be None):", items[1].image_path)
    assert items[0].image_path is not None
    assert items[1].image_path is None
    assert Path(items[0].image_path).exists()
    print("DoD PASSED")


asyncio.run(main())
```

Run it:
```bash
cd backend && python tmp_test_images_dod.py
```

Expected output:
```
item-product image_path: /tmp/closet_dod_test/nike.com/order-test/item-product.png
item-logo image_path (should be None): None
DoD PASSED
```

Delete the script:
```bash
rm backend/tmp_test_images_dod.py
```

- [ ] **Step 4: Final full suite run — paste actual output**

```bash
cd backend && ruff check . && black --check . && pytest -q
```

Paste the actual terminal output before marking phase 04 complete.

---

## Definition of Done Checklist

- [ ] `backend/app/ingestion/images.py` exists with: `is_junk_url`, `_image_ext_from_bytes`, `is_tiny_image`, `content_hash`, `_download_image`, `download_order_images`
- [ ] `data:` and `cid:` URIs, and filenames matching `pixel|open|track|spacer|1x1|beacon` are rejected by `is_junk_url`
- [ ] Images smaller than `min_dimension × min_dimension` are rejected after download
- [ ] Identical images (same bytes) are stored once; subsequent items reuse the path
- [ ] `repo.upsert_order` returns `(Order, list[Item])`; items have IDs populated post-flush
- [ ] Pipeline creates one `httpx.AsyncClient` per `_drain` run and passes it to `download_order_images`
- [ ] `items.image_path` is updated in-session; persisted by the pipeline's `session.commit()`
- [ ] `IMAGE_STORE_DIR`, `IMAGE_MIN_DIMENSION`, `IMAGE_CONCURRENCY` in `Settings`
- [ ] `ruff check . && black --check . && pytest -q` all pass with output shown
