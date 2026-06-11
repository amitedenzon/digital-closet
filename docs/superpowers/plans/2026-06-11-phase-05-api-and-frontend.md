# Phase 05 — API & Frontend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Expose a FastAPI JSON API for sync control and closet data, and build a single-page React+Vite frontend that drives an email backfill, shows a progress bar, and renders a filterable grid of purchased items with images.

**Architecture:** Backend adds `jobs.py` for in-memory job state, updates `pipeline.py` to report incremental progress, and wires all endpoints in `main.py` with CORS and dependency-injected DB sessions. The React frontend polls `/sync/status` during a sync run, renders item cards from `/items`, and serves images via `/images/{id}`. Phase-04 cleanup (remove unused `session` param from `download_order_images`) is done first.

**Tech Stack:** FastAPI 0.115, SQLAlchemy 2.0 async, httpx (ASGI test transport), React 18, Vite 6, TypeScript 5.

---

## File Map

| Action | Path | Responsibility |
|--------|------|----------------|
| **Modify** | `backend/app/ingestion/images.py` | Remove unused `session` param (phase-04 cleanup) |
| **Modify** | `backend/app/ingestion/pipeline.py` | Drop `session` from `download_order_images` call; add `job_state` progress tracking |
| **Modify** | `backend/tests/test_images.py` | Drop `session` arg from 6 test calls |
| **Modify** | `backend/app/schemas.py` | Add `ItemResponse`, `OrderWithItemsResponse`, `JobStatusResponse`, `SyncInitRequest`, `ItemStatusUpdate` |
| **Modify** | `backend/app/config.py` | Add `FRONTEND_ORIGIN` setting |
| **Modify** | `backend/.env.example` | Document `FRONTEND_ORIGIN` |
| **Create** | `backend/app/jobs.py` | In-memory job registry |
| **Create** | `backend/tests/test_jobs.py` | Job registry tests |
| **Create** | `backend/app/main.py` | FastAPI app — all routes + CORS + lifespan |
| **Create** | `backend/tests/test_main.py` | API endpoint tests |
| **Create** | `frontend/package.json` | Vite+React+TypeScript deps |
| **Create** | `frontend/vite.config.ts` | Vite config (proxy to backend) |
| **Create** | `frontend/tsconfig.json` | TypeScript config |
| **Create** | `frontend/index.html` | HTML shell |
| **Create** | `frontend/src/main.tsx` | React entry point |
| **Create** | `frontend/src/index.css` | Global styles |
| **Create** | `frontend/src/types.ts` | Shared TypeScript types |
| **Create** | `frontend/src/api.ts` | All `fetch` calls |
| **Create** | `frontend/src/App.tsx` | Root component — state, polling, layout |
| **Create** | `frontend/src/components/Header.tsx` | Init/Sync buttons |
| **Create** | `frontend/src/components/ProgressBar.tsx` | Sync progress display |
| **Create** | `frontend/src/components/Filters.tsx` | Vendor/brand/status/search filters |
| **Create** | `frontend/src/components/ItemCard.tsx` | Single item card |
| **Create** | `frontend/src/components/ClosetGrid.tsx` | Grid of ItemCards + empty state |

---

### Task 1: Phase-04 cleanup — remove unused `session` param from `download_order_images`

**Files:**
- Modify: `backend/app/ingestion/images.py`
- Modify: `backend/app/ingestion/pipeline.py`
- Modify: `backend/tests/test_images.py`

- [ ] **Step 1: Run current tests to establish baseline**

```bash
cd backend && pytest tests/test_images.py tests/test_pipeline.py -q
```

Expected: all tests PASS (confirm baseline before changing anything).

- [ ] **Step 2: Remove `session` param from `download_order_images` in `images.py`**

In `backend/app/ingestion/images.py`, change the function signature (line 75–84):

Old:
```python
async def download_order_images(
    session: AsyncSession,
    items: list,
    image_urls: list[str | None],
    vendor_domain: str,
    order_id: str,
    *,
    store_dir: Path,
    client: httpx.AsyncClient,
    min_dimension: int = 100,
) -> None:
```

New:
```python
async def download_order_images(
    items: list,
    image_urls: list[str | None],
    vendor_domain: str,
    order_id: str,
    *,
    store_dir: Path,
    client: httpx.AsyncClient,
    min_dimension: int = 100,
) -> None:
```

Also remove the now-unused import at the top of `images.py`:

Old:
```python
from sqlalchemy.ext.asyncio import AsyncSession
```

Delete that line entirely. The full imports block becomes:

```python
from __future__ import annotations

import hashlib
import io
import logging
import re
from pathlib import Path

import httpx
from PIL import Image
```

- [ ] **Step 3: Fix pipeline.py call site**

In `backend/app/ingestion/pipeline.py`, find the `download_order_images` call (around line 176):

Old:
```python
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
```

New:
```python
                        await images.download_order_images(
                            db_items,
                            [item.image_url for item in extraction.items],
                            vendor_domain=extraction.vendor_domain or "",
                            order_id=order.id,
                            store_dir=Path(_settings.IMAGE_STORE_DIR),
                            client=http_client,
                            min_dimension=_settings.IMAGE_MIN_DIMENSION,
                        )
```

- [ ] **Step 4: Fix all 6 test calls in `test_images.py`**

There are 6 test functions that pass `session` to `download_order_images`. For each, remove the `session = MagicMock()` line and the `session,` first argument.

The 6 tests to fix (grep confirms exact locations):
- `test_download_order_images_saves_image` (around line 235)
- `test_download_order_images_skips_junk_url` (around line 258)
- `test_download_order_images_skips_none_url` (around line 279)
- `test_download_order_images_skips_tiny_image` (around line 300)
- `test_download_order_images_dedup_identical_bytes` (around line 322)
- `test_download_order_images_continues_on_download_failure` (around line 351)

For each test, make these two changes:
1. Delete the line `session = MagicMock()`
2. In the `await download_order_images(...)` call, remove `session,` (the first positional argument)

Example — `test_download_order_images_saves_image` before:
```python
async def test_download_order_images_saves_image(tmp_path):
    png_bytes = _make_png(200, 200)
    client = _mock_client_with_content(png_bytes)
    item = _mock_item("item-abc")
    session = MagicMock()

    await download_order_images(
        session,
        items=[item],
        ...
    )
```

After:
```python
async def test_download_order_images_saves_image(tmp_path):
    png_bytes = _make_png(200, 200)
    client = _mock_client_with_content(png_bytes)
    item = _mock_item("item-abc")

    await download_order_images(
        items=[item],
        ...
    )
```

Also remove the `from sqlalchemy.ext.asyncio import AsyncSession` import at the top of `test_images.py` if it was added solely for the `session` parameter. Check the import block — if `AsyncSession` appears only in the `session = MagicMock(spec=AsyncSession)` lines that you're deleting, remove the import too.

- [ ] **Step 5: Run the tests and confirm they pass**

```bash
cd backend && pytest tests/test_images.py tests/test_pipeline.py -v
```

Expected: all tests PASS (same count as before, no failures).

- [ ] **Step 6: Commit**

```bash
git add backend/app/ingestion/images.py backend/app/ingestion/pipeline.py backend/tests/test_images.py
git commit -m "refactor: remove unused session param from download_order_images"
```

---

### Task 2: Add API response schemas and config

**Files:**
- Modify: `backend/app/schemas.py`
- Modify: `backend/app/config.py`
- Modify: `backend/.env.example`

- [ ] **Step 1: Add API schemas to `backend/app/schemas.py`**

Append after the existing `ExtractionResult` model:

```python
from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import ConfigDict


# ── API response / request models ────────────────────────────────────────────


class ItemResponse(BaseModel):
    """Flattened item + order info for GET /items."""
    id: str
    order_id: str
    item_name: str
    brand: str | None
    size: str | None
    color: str | None
    quantity: int
    price: float | None
    status: str
    vendor_name: str
    vendor_domain: str
    purchase_date: datetime
    created_at: datetime


class ItemBriefResponse(BaseModel):
    """Item fields used inside OrderWithItemsResponse."""
    model_config = ConfigDict(from_attributes=True)

    id: str
    item_name: str
    brand: str | None
    size: str | None
    color: str | None
    quantity: int
    price: float | None
    status: str
    image_path: str | None


class OrderWithItemsResponse(BaseModel):
    """Order with nested items for GET /orders."""
    model_config = ConfigDict(from_attributes=True)

    id: str
    vendor_name: str
    vendor_domain: str
    merchant_order_id: str | None
    purchase_date: datetime
    currency: str | None
    total_price: float | None
    status: str
    items: list[ItemBriefResponse]


class JobStatusResponse(BaseModel):
    """Response for GET /sync/status/{job_id}."""
    job_id: str
    state: str
    scanned: int
    kept: int
    skipped: int
    errors: int
    done: bool


class SyncInitRequest(BaseModel):
    """Body for POST /sync/init."""
    stop_year: int = 2023


class ItemStatusUpdate(BaseModel):
    """Body for POST /items/{item_id}/status."""
    status: Literal["active", "returned", "cancelled"]
```

**Note:** `datetime` is already imported at the top of `schemas.py`. Add `Decimal`, `Literal`, and `ConfigDict` to the imports block. The full imports block for `schemas.py`:

```python
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict
```

- [ ] **Step 2: Add `FRONTEND_ORIGIN` to `backend/app/config.py`**

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
    FRONTEND_ORIGIN: str = "http://localhost:5173"

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}
```

- [ ] **Step 3: Append to `backend/.env.example`**

Add after the `IMAGE_*` section:

```
# Frontend (for CORS)
FRONTEND_ORIGIN=http://localhost:5173
```

- [ ] **Step 4: Verify schemas import cleanly**

```bash
cd backend && python -c "from app.schemas import ItemResponse, OrderWithItemsResponse, JobStatusResponse, SyncInitRequest, ItemStatusUpdate; print('OK')"
```

Expected: `OK`

- [ ] **Step 5: Commit**

```bash
git add backend/app/schemas.py backend/app/config.py backend/.env.example
git commit -m "feat: add API response schemas and FRONTEND_ORIGIN config"
```

---

### Task 3: Job registry — `jobs.py` with TDD

**Files:**
- Create: `backend/app/jobs.py`
- Create: `backend/tests/test_jobs.py`

- [ ] **Step 1: Write `backend/tests/test_jobs.py`**

```python
from __future__ import annotations

import pytest
from app import jobs


@pytest.fixture(autouse=True)
def clear_jobs():
    jobs.clear()
    yield
    jobs.clear()


def test_create_job_returns_unique_ids():
    j1 = jobs.create_job()
    j2 = jobs.create_job()
    assert j1.job_id != j2.job_id


def test_new_job_is_running_and_not_done():
    j = jobs.create_job()
    assert j.state == "running"
    assert j.done is False
    assert j.scanned == 0
    assert j.kept == 0
    assert j.skipped == 0
    assert j.errors == 0


def test_get_job_returns_created_job():
    j = jobs.create_job()
    found = jobs.get_job(j.job_id)
    assert found is j


def test_get_job_returns_none_for_unknown_id():
    assert jobs.get_job("does-not-exist") is None


def test_get_active_job_returns_running_job():
    j = jobs.create_job()
    assert jobs.get_active_job() is j


def test_get_active_job_returns_none_when_all_done():
    j = jobs.create_job()
    jobs.complete_job(j)
    assert jobs.get_active_job() is None


def test_complete_job_sets_done_and_state():
    j = jobs.create_job()
    jobs.complete_job(j)
    assert j.done is True
    assert j.state == "done"


def test_fail_job_sets_done_and_error_state():
    j = jobs.create_job()
    jobs.fail_job(j)
    assert j.done is True
    assert j.state == "error"


def test_clear_removes_all_jobs():
    jobs.create_job()
    jobs.create_job()
    jobs.clear()
    assert jobs.get_active_job() is None


def test_progress_fields_are_mutable():
    j = jobs.create_job()
    j.scanned += 1
    j.kept += 1
    j.skipped += 1
    j.errors += 1
    found = jobs.get_job(j.job_id)
    assert found.scanned == 1
    assert found.kept == 1
    assert found.skipped == 1
    assert found.errors == 1
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd backend && pytest tests/test_jobs.py -v
```

Expected: `ModuleNotFoundError: No module named 'app.jobs'`

- [ ] **Step 3: Create `backend/app/jobs.py`**

```python
from __future__ import annotations

import uuid
from dataclasses import dataclass, field

__all__ = ["JobState", "create_job", "get_job", "get_active_job", "complete_job", "fail_job", "clear"]


@dataclass
class JobState:
    job_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    state: str = "running"
    scanned: int = 0
    kept: int = 0
    skipped: int = 0
    errors: int = 0
    done: bool = False


_jobs: dict[str, JobState] = {}


def create_job() -> JobState:
    job = JobState()
    _jobs[job.job_id] = job
    return job


def get_job(job_id: str) -> JobState | None:
    return _jobs.get(job_id)


def get_active_job() -> JobState | None:
    for job in _jobs.values():
        if not job.done:
            return job
    return None


def complete_job(job: JobState) -> None:
    job.done = True
    job.state = "done"


def fail_job(job: JobState) -> None:
    job.done = True
    job.state = "error"


def clear() -> None:
    _jobs.clear()
```

- [ ] **Step 4: Run tests**

```bash
cd backend && pytest tests/test_jobs.py -v
```

Expected: all 10 tests PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/jobs.py backend/tests/test_jobs.py
git commit -m "feat: add in-memory job registry for sync progress tracking"
```

---

### Task 4: Add job progress tracking to pipeline

**Files:**
- Modify: `backend/app/ingestion/pipeline.py`

- [ ] **Step 1: Add `JobState` import and update `_drain` signature in `pipeline.py`**

At the top of `backend/app/ingestion/pipeline.py`, add the jobs import after the existing app imports:

```python
from app.jobs import JobState
```

The full imports block becomes:

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
from app.jobs import JobState
from app.models import MessageResult
from app.providers.base import MailProvider, ProviderQuery
from app.store import repo
```

- [ ] **Step 2: Add `job_state` parameter to `run_initialize`, `run_since_checkpoint`, and `_drain`**

Update all three function signatures to accept `job_state: JobState | None = None`:

`run_initialize`:
```python
async def run_initialize(
    provider: MailProvider,
    extractor: Extractor,
    session_factory: async_sessionmaker[AsyncSession],
    *,
    provider_name: str,
    account: str,
    stop_year: int = DEFAULT_STOP_YEAR,
    job_state: JobState | None = None,
) -> JobResult:
    query = ProviderQuery(
        after=datetime(stop_year, 1, 1, tzinfo=timezone.utc),
        before=datetime.now(timezone.utc),
        subject_any=_SUBJECT_KEYWORDS,
        category_purchases=True,
    )
    return await _drain(
        provider,
        extractor,
        session_factory,
        query=query,
        provider_name=provider_name,
        account=account,
        job_state=job_state,
    )
```

`run_since_checkpoint`:
```python
async def run_since_checkpoint(
    provider: MailProvider,
    extractor: Extractor,
    session_factory: async_sessionmaker[AsyncSession],
    *,
    provider_name: str,
    account: str,
    stop_year: int = DEFAULT_STOP_YEAR,
    job_state: JobState | None = None,
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
        provider,
        extractor,
        session_factory,
        query=query,
        provider_name=provider_name,
        account=account,
        job_state=job_state,
    )
```

`_drain`:
```python
async def _drain(
    provider: MailProvider,
    extractor: Extractor,
    session_factory: async_sessionmaker[AsyncSession],
    *,
    query: ProviderQuery,
    provider_name: str,
    account: str,
    job_state: JobState | None = None,
) -> JobResult:
```

Inside `_drain`, after every line that increments `result.scanned`, `result.skipped`, `result.kept`, or `result.errors`, add a corresponding update to `job_state` if it's not None. The four locations to update:

After `result.scanned += 1`:
```python
                result.scanned += 1
                if job_state is not None:
                    job_state.scanned += 1
```

After `result.skipped += 1` (the already-processed path — only one such line before the `continue`):
```python
                        result.skipped += 1
                        if job_state is not None:
                            job_state.skipped += 1
```

After each remaining `result.skipped += 1` (prefilter and LLM skip paths):
```python
                            result.skipped += 1
                            if job_state is not None:
                                job_state.skipped += 1
```

After `result.kept += 1`:
```python
                        result.kept += 1
                        if job_state is not None:
                            job_state.kept += 1
```

After `result.errors += 1`:
```python
                        result.errors += 1
                        if job_state is not None:
                            job_state.errors += 1
```

- [ ] **Step 3: Run existing pipeline tests to verify no regressions**

```bash
cd backend && pytest tests/test_pipeline.py -v
```

Expected: all 7 tests PASS (the `job_state=None` default means existing tests are unaffected).

- [ ] **Step 4: Commit**

```bash
git add backend/app/ingestion/pipeline.py
git commit -m "feat: add job_state progress tracking to pipeline _drain"
```

---

### Task 5: FastAPI app — write tests first, then implement sync endpoints

**Files:**
- Create: `backend/tests/test_main.py`
- Create: `backend/app/main.py`

- [ ] **Step 1: Write sync endpoint tests in `backend/tests/test_main.py`**

```python
from __future__ import annotations

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from unittest.mock import AsyncMock, patch
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app import jobs
from app.db import Base

TEST_DB_URL = "sqlite+aiosqlite:///:memory:"


@pytest_asyncio.fixture
async def test_session_factory():
    engine = create_async_engine(TEST_DB_URL)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    yield factory
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest_asyncio.fixture
async def client(test_session_factory):
    from app.main import app, get_session

    async def override_get_session():
        async with test_session_factory() as session:
            yield session

    app.dependency_overrides[get_session] = override_get_session
    jobs.clear()

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        yield c

    app.dependency_overrides.clear()
    jobs.clear()


# ── /sync/init ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_sync_init_returns_202_and_job_id(client):
    with patch("app.main._run_sync_job", new_callable=AsyncMock) as mock_run:
        response = await client.post("/sync/init", json={"stop_year": 2023})
    assert response.status_code == 202
    data = response.json()
    assert "job_id" in data
    assert isinstance(data["job_id"], str)


@pytest.mark.asyncio
async def test_sync_init_rejects_second_request_with_409(client):
    active = jobs.create_job()  # active, not done

    response = await client.post("/sync/init", json={"stop_year": 2023})

    assert response.status_code == 409
    jobs.complete_job(active)


# ── /sync/checkpoint ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_sync_checkpoint_returns_202_and_job_id(client):
    with patch("app.main._run_sync_job", new_callable=AsyncMock):
        response = await client.post("/sync/checkpoint")
    assert response.status_code == 202
    data = response.json()
    assert "job_id" in data


@pytest.mark.asyncio
async def test_sync_checkpoint_rejects_when_active(client):
    active = jobs.create_job()

    response = await client.post("/sync/checkpoint")

    assert response.status_code == 409
    jobs.complete_job(active)


# ── /sync/status/{job_id} ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_sync_status_returns_job_state(client):
    j = jobs.create_job()
    j.scanned = 5
    j.kept = 2

    response = await client.get(f"/sync/status/{j.job_id}")

    assert response.status_code == 200
    data = response.json()
    assert data["job_id"] == j.job_id
    assert data["scanned"] == 5
    assert data["kept"] == 2
    assert data["done"] is False


@pytest.mark.asyncio
async def test_sync_status_returns_404_for_unknown_job(client):
    response = await client.get("/sync/status/does-not-exist")
    assert response.status_code == 404
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd backend && pytest tests/test_main.py -v
```

Expected: `ModuleNotFoundError: No module named 'app.main'`

- [ ] **Step 3: Create `backend/app/main.py` with sync endpoints**

```python
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncGenerator

from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import jobs
from app.config import Settings
from app.db import Base, make_engine, make_session_factory
from app.ingestion import pipeline
from app.models import Item, ItemStatus, Order
from app.providers.gmail import GmailProvider
from app.extraction.ollama_extractor import OllamaExtractor
from app.schemas import (
    ItemResponse,
    ItemBriefResponse,
    ItemStatusUpdate,
    JobStatusResponse,
    OrderWithItemsResponse,
    SyncInitRequest,
)

logger = logging.getLogger(__name__)

_settings = Settings()
_engine = make_engine(_settings.DATABASE_URL)
_session_factory = make_session_factory(_engine)

_provider: GmailProvider | None = None
_extractor: OllamaExtractor | None = None


def _get_provider() -> GmailProvider:
    global _provider
    if _provider is None:
        _provider = GmailProvider.from_credentials_files(
            _settings.GMAIL_CREDENTIALS_FILE,
            _settings.GMAIL_TOKEN_FILE,
            _settings.GMAIL_ACCOUNT,
        )
    return _provider


def _get_extractor() -> OllamaExtractor:
    global _extractor
    if _extractor is None:
        _extractor = OllamaExtractor(
            base_url=_settings.OLLAMA_BASE_URL,
            model=_settings.OLLAMA_MODEL,
        )
    return _extractor


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with _engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield


app = FastAPI(title="Digital Closet", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[_settings.FRONTEND_ORIGIN],
    allow_methods=["*"],
    allow_headers=["*"],
)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    async with _session_factory() as session:
        yield session


# ── background task wrapper ───────────────────────────────────────────────────


async def _run_sync_job(
    job: jobs.JobState,
    *,
    mode: str,  # "init" | "checkpoint"
    stop_year: int = 2023,
) -> None:
    try:
        if mode == "init":
            await pipeline.run_initialize(
                _get_provider(),
                _get_extractor(),
                _session_factory,
                provider_name="gmail",
                account=_settings.GMAIL_ACCOUNT,
                stop_year=stop_year,
                job_state=job,
            )
        else:
            await pipeline.run_since_checkpoint(
                _get_provider(),
                _get_extractor(),
                _session_factory,
                provider_name="gmail",
                account=_settings.GMAIL_ACCOUNT,
                job_state=job,
            )
        jobs.complete_job(job)
    except Exception as exc:
        jobs.fail_job(job)
        logger.exception("sync job failed job_id=%s", job.job_id, exc_info=exc)


# ── sync endpoints ────────────────────────────────────────────────────────────


@app.post("/sync/init", status_code=202)
async def sync_init(
    body: SyncInitRequest,
    background_tasks: BackgroundTasks,
) -> dict:
    if jobs.get_active_job() is not None:
        raise HTTPException(status_code=409, detail="Sync already in progress")
    job = jobs.create_job()
    background_tasks.add_task(_run_sync_job, job, mode="init", stop_year=body.stop_year)
    return {"job_id": job.job_id}


@app.post("/sync/checkpoint", status_code=202)
async def sync_checkpoint(background_tasks: BackgroundTasks) -> dict:
    if jobs.get_active_job() is not None:
        raise HTTPException(status_code=409, detail="Sync already in progress")
    job = jobs.create_job()
    background_tasks.add_task(_run_sync_job, job, mode="checkpoint")
    return {"job_id": job.job_id}


@app.get("/sync/status/{job_id}", response_model=JobStatusResponse)
async def sync_status(job_id: str) -> JobStatusResponse:
    job = jobs.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return JobStatusResponse(
        job_id=job.job_id,
        state=job.state,
        scanned=job.scanned,
        kept=job.kept,
        skipped=job.skipped,
        errors=job.errors,
        done=job.done,
    )
```

- [ ] **Step 4: Run the sync endpoint tests**

```bash
cd backend && pytest tests/test_main.py -v
```

Expected: the 7 sync tests PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/main.py backend/tests/test_main.py
git commit -m "feat: add FastAPI app with sync endpoints and job registry integration"
```

---

### Task 6: FastAPI data endpoints — test first, then implement

**Files:**
- Modify: `backend/tests/test_main.py`
- Modify: `backend/app/main.py`

- [ ] **Step 1: Add data endpoint tests to `backend/tests/test_main.py`**

Append after the existing sync tests:

```python
# ── /items ────────────────────────────────────────────────────────────────────

from datetime import datetime, timezone

from app.schemas import ExtractionResult, ExtractedItem
from app.store import repo


def _extraction(
    vendor="nike.com",
    order_id="ord-1",
    item_name="Air Max",
    brand="Nike",
) -> ExtractionResult:
    return ExtractionResult(
        is_valid_apparel_purchase=True,
        vendor_name="Nike",
        vendor_domain=vendor,
        merchant_order_id=order_id,
        purchase_date=datetime(2024, 3, 1, tzinfo=timezone.utc),
        currency="USD",
        total_price=120.0,
        items=[ExtractedItem(item_name=item_name, brand=brand, price=120.0)],
    )


@pytest.mark.asyncio
async def test_items_empty(client):
    response = await client.get("/items")
    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.asyncio
async def test_items_returns_inserted_item(client, test_session_factory):
    async with test_session_factory() as session:
        await repo.upsert_order(session, _extraction())
        await session.commit()

    response = await client.get("/items")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    item = data[0]
    assert item["item_name"] == "Air Max"
    assert item["brand"] == "Nike"
    assert item["vendor_name"] == "Nike"
    assert item["vendor_domain"] == "nike.com"
    assert item["status"] == "active"


@pytest.mark.asyncio
async def test_items_filter_by_brand(client, test_session_factory):
    async with test_session_factory() as session:
        await repo.upsert_order(session, _extraction(item_name="Air Max", brand="Nike"))
        await repo.upsert_order(
            session,
            _extraction(vendor="adidas.com", order_id="ord-2", item_name="Ultraboost", brand="Adidas"),
        )
        await session.commit()

    response = await client.get("/items?brand=Nike")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["brand"] == "Nike"


@pytest.mark.asyncio
async def test_items_filter_by_vendor(client, test_session_factory):
    async with test_session_factory() as session:
        await repo.upsert_order(session, _extraction(vendor="nike.com", order_id="ord-1"))
        await repo.upsert_order(
            session,
            _extraction(vendor="adidas.com", order_id="ord-2", item_name="Ultraboost", brand="Adidas"),
        )
        await session.commit()

    response = await client.get("/items?vendor=adidas")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["vendor_domain"] == "adidas.com"


@pytest.mark.asyncio
async def test_items_filter_by_q(client, test_session_factory):
    async with test_session_factory() as session:
        await repo.upsert_order(session, _extraction(item_name="Air Max", brand="Nike"))
        await repo.upsert_order(
            session,
            _extraction(vendor="adidas.com", order_id="ord-2", item_name="Ultraboost", brand="Adidas"),
        )
        await session.commit()

    response = await client.get("/items?q=ultra")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["item_name"] == "Ultraboost"


# ── /orders ───────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_orders_empty(client):
    response = await client.get("/orders")
    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.asyncio
async def test_orders_returns_order_with_items(client, test_session_factory):
    async with test_session_factory() as session:
        await repo.upsert_order(session, _extraction())
        await session.commit()

    response = await client.get("/orders")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    order = data[0]
    assert order["vendor_domain"] == "nike.com"
    assert len(order["items"]) == 1
    assert order["items"][0]["item_name"] == "Air Max"


# ── /images/{item_id} ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_images_returns_404_for_no_image(client, test_session_factory):
    async with test_session_factory() as session:
        order, db_items = await repo.upsert_order(session, _extraction())
        item_id = db_items[0].id
        await session.commit()

    response = await client.get(f"/images/{item_id}")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_images_returns_404_for_unknown_item(client):
    response = await client.get("/images/does-not-exist")
    assert response.status_code == 404


# ── /items/{item_id}/status ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_update_item_status_to_returned(client, test_session_factory):
    async with test_session_factory() as session:
        order, db_items = await repo.upsert_order(session, _extraction())
        item_id = db_items[0].id
        await session.commit()

    response = await client.post(
        f"/items/{item_id}/status", json={"status": "returned"}
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "returned"


@pytest.mark.asyncio
async def test_update_item_status_returns_404_for_unknown(client):
    response = await client.post(
        "/items/does-not-exist/status", json={"status": "returned"}
    )
    assert response.status_code == 404
```

- [ ] **Step 2: Run new tests to verify they fail**

```bash
cd backend && pytest tests/test_main.py -k "items or orders or images or status" -v
```

Expected: tests fail with `404` or assertion errors because the endpoints don't exist yet.

- [ ] **Step 3: Add data endpoints to `backend/app/main.py`**

Append after the `sync_status` route handler:

```python
# ── data endpoints ────────────────────────────────────────────────────────────


@app.get("/items", response_model=list[ItemResponse])
async def list_items(
    vendor: str | None = None,
    brand: str | None = None,
    status: str | None = None,
    q: str | None = None,
    page: int = 1,
    per_page: int = 50,
    session: AsyncSession = Depends(get_session),
) -> list[ItemResponse]:
    stmt = select(Item, Order).join(Order, Item.order_id == Order.id)
    if vendor:
        stmt = stmt.where(Order.vendor_domain.ilike(f"%{vendor}%"))
    if brand:
        stmt = stmt.where(Item.brand.ilike(f"%{brand}%"))
    if status:
        stmt = stmt.where(Item.status == status)
    if q:
        stmt = stmt.where(
            Item.item_name.ilike(f"%{q}%") | Item.brand.ilike(f"%{q}%")
        )
    stmt = stmt.offset((page - 1) * per_page).limit(per_page)
    rows = (await session.execute(stmt)).all()
    return [
        ItemResponse(
            id=item.id,
            order_id=item.order_id,
            item_name=item.item_name,
            brand=item.brand,
            size=item.size,
            color=item.color,
            quantity=item.quantity,
            price=float(item.price) if item.price is not None else None,
            status=item.status.value,
            vendor_name=order.vendor_name,
            vendor_domain=order.vendor_domain,
            purchase_date=order.purchase_date,
            created_at=item.created_at,
        )
        for item, order in rows
    ]


@app.get("/orders", response_model=list[OrderWithItemsResponse])
async def list_orders(
    session: AsyncSession = Depends(get_session),
) -> list[OrderWithItemsResponse]:
    from sqlalchemy.orm import selectinload

    stmt = select(Order).options(selectinload(Order.items))
    orders = (await session.execute(stmt)).scalars().all()
    return [
        OrderWithItemsResponse(
            id=o.id,
            vendor_name=o.vendor_name,
            vendor_domain=o.vendor_domain,
            merchant_order_id=o.merchant_order_id,
            purchase_date=o.purchase_date,
            currency=o.currency,
            total_price=float(o.total_price) if o.total_price is not None else None,
            status=o.status.value,
            items=[
                ItemBriefResponse(
                    id=i.id,
                    item_name=i.item_name,
                    brand=i.brand,
                    size=i.size,
                    color=i.color,
                    quantity=i.quantity,
                    price=float(i.price) if i.price is not None else None,
                    status=i.status.value,
                    image_path=i.image_path,
                )
                for i in o.items
            ],
        )
        for o in orders
    ]


@app.get("/images/{item_id}")
async def get_image(
    item_id: str,
    session: AsyncSession = Depends(get_session),
) -> FileResponse:
    stmt = select(Item.image_path).where(Item.id == item_id)
    path_str = (await session.execute(stmt)).scalar_one_or_none()
    if path_str is None or not Path(path_str).exists():
        raise HTTPException(status_code=404, detail="Image not found")
    return FileResponse(path_str)


@app.post("/items/{item_id}/status")
async def update_item_status(
    item_id: str,
    body: ItemStatusUpdate,
    session: AsyncSession = Depends(get_session),
) -> dict:
    stmt = select(Item).where(Item.id == item_id)
    item = (await session.execute(stmt)).scalar_one_or_none()
    if item is None:
        raise HTTPException(status_code=404, detail="Item not found")
    item.status = ItemStatus(body.status)
    await session.commit()
    return {"id": item_id, "status": item.status.value}
```

Also add the `sqlalchemy.orm` import at the top of `main.py` (with the other sqlalchemy imports):

```python
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
```

The `selectinload` is imported inline inside the function (to keep the top-level imports clean).

- [ ] **Step 4: Run all main tests**

```bash
cd backend && pytest tests/test_main.py -v
```

Expected: all tests PASS.

- [ ] **Step 5: Run full suite**

```bash
cd backend && ruff check . && black --check . && pytest -q
```

Expected: all checks pass, all tests pass. Paste actual output.

- [ ] **Step 6: Commit**

```bash
git add backend/app/main.py backend/tests/test_main.py
git commit -m "feat: add /items, /orders, /images, and /items/{id}/status endpoints"
```

---

### Task 7: Frontend scaffolding — package.json, vite.config, tsconfig, index.html

**Files:**
- Create: `frontend/package.json`
- Create: `frontend/vite.config.ts`
- Create: `frontend/tsconfig.json`
- Create: `frontend/index.html`

- [ ] **Step 1: Create `frontend/package.json`**

```json
{
  "name": "digital-closet",
  "version": "0.0.1",
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "tsc && vite build",
    "preview": "vite preview"
  },
  "dependencies": {
    "react": "^18.3.1",
    "react-dom": "^18.3.1"
  },
  "devDependencies": {
    "@types/react": "^18.3.1",
    "@types/react-dom": "^18.3.1",
    "@vitejs/plugin-react": "^4.3.4",
    "typescript": "^5.7.3",
    "vite": "^6.0.7"
  }
}
```

- [ ] **Step 2: Create `frontend/vite.config.ts`**

```typescript
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/sync": "http://localhost:8000",
      "/items": "http://localhost:8000",
      "/orders": "http://localhost:8000",
      "/images": "http://localhost:8000",
    },
  },
});
```

- [ ] **Step 3: Create `frontend/tsconfig.json`**

```json
{
  "compilerOptions": {
    "target": "ES2020",
    "useDefineForClassFields": true,
    "lib": ["ES2020", "DOM", "DOM.Iterable"],
    "module": "ESNext",
    "skipLibCheck": true,
    "moduleResolution": "bundler",
    "allowImportingTsExtensions": true,
    "resolveJsonModule": true,
    "isolatedModules": true,
    "noEmit": true,
    "jsx": "react-jsx",
    "strict": true,
    "noUnusedLocals": true,
    "noUnusedParameters": true,
    "noFallthroughCasesInSwitch": true
  },
  "include": ["src"]
}
```

- [ ] **Step 4: Create `frontend/index.html`**

```html
<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>Digital Closet</title>
  </head>
  <body>
    <div id="root"></div>
    <script type="module" src="/src/main.tsx"></script>
  </body>
</html>
```

- [ ] **Step 5: Install frontend dependencies**

```bash
cd frontend && npm install
```

Expected: `node_modules/` created, no errors.

- [ ] **Step 6: Commit**

```bash
git add frontend/package.json frontend/vite.config.ts frontend/tsconfig.json frontend/index.html frontend/package-lock.json
git commit -m "feat: scaffold Vite+React frontend project"
```

---

### Task 8: Frontend core — types, api.ts, App.tsx, main.tsx

**Files:**
- Create: `frontend/src/types.ts`
- Create: `frontend/src/api.ts`
- Create: `frontend/src/main.tsx`
- Create: `frontend/src/index.css`
- Create: `frontend/src/App.tsx`

- [ ] **Step 1: Create `frontend/src/types.ts`**

```typescript
export interface Item {
  id: string;
  order_id: string;
  item_name: string;
  brand: string | null;
  size: string | null;
  color: string | null;
  quantity: number;
  price: number | null;
  status: "active" | "returned" | "cancelled";
  vendor_name: string;
  vendor_domain: string;
  purchase_date: string;
  created_at: string;
}

export interface JobStatus {
  job_id: string;
  state: "running" | "done" | "error";
  scanned: number;
  kept: number;
  skipped: number;
  errors: number;
  done: boolean;
}

export interface Filters {
  vendor: string;
  brand: string;
  status: string;
  q: string;
}
```

- [ ] **Step 2: Create `frontend/src/api.ts`**

```typescript
import type { Item, JobStatus } from "./types";

const BASE = "";  // Vite proxy routes /sync, /items, /images to localhost:8000

export async function startInit(stopYear: number): Promise<{ job_id: string }> {
  const res = await fetch("/sync/init", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ stop_year: stopYear }),
  });
  if (!res.ok) throw new Error(`sync/init failed: ${res.status}`);
  return res.json();
}

export async function startCheckpoint(): Promise<{ job_id: string }> {
  const res = await fetch("/sync/checkpoint", { method: "POST" });
  if (!res.ok) throw new Error(`sync/checkpoint failed: ${res.status}`);
  return res.json();
}

export async function getJobStatus(jobId: string): Promise<JobStatus> {
  const res = await fetch(`/sync/status/${jobId}`);
  if (!res.ok) throw new Error(`sync/status failed: ${res.status}`);
  return res.json();
}

export async function fetchItems(params: {
  vendor?: string;
  brand?: string;
  status?: string;
  q?: string;
}): Promise<Item[]> {
  const qs = new URLSearchParams();
  if (params.vendor) qs.set("vendor", params.vendor);
  if (params.brand) qs.set("brand", params.brand);
  if (params.status) qs.set("status", params.status);
  if (params.q) qs.set("q", params.q);
  const res = await fetch(`/items?${qs}`);
  if (!res.ok) throw new Error(`/items failed: ${res.status}`);
  return res.json();
}

export function imageUrl(itemId: string): string {
  return `/images/${itemId}`;
}
```

- [ ] **Step 3: Create `frontend/src/main.tsx`**

```typescript
import React from "react";
import ReactDOM from "react-dom/client";
import "./index.css";
import App from "./App";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);
```

- [ ] **Step 4: Create `frontend/src/index.css`**

```css
*, *::before, *::after { box-sizing: border-box; }

body {
  margin: 0;
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
  background: #f5f5f5;
  color: #1a1a1a;
}

#root {
  max-width: 1200px;
  margin: 0 auto;
  padding: 0 16px;
}
```

- [ ] **Step 5: Create `frontend/src/App.tsx`**

```typescript
import { useState, useEffect, useCallback, useRef } from "react";
import type { Item, JobStatus, Filters } from "./types";
import { startInit, startCheckpoint, getJobStatus, fetchItems } from "./api";
import Header from "./components/Header";
import ProgressBar from "./components/ProgressBar";
import FiltersBar from "./components/Filters";
import ClosetGrid from "./components/ClosetGrid";

export default function App() {
  const [items, setItems] = useState<Item[]>([]);
  const [jobStatus, setJobStatus] = useState<JobStatus | null>(null);
  const [filters, setFilters] = useState<Filters>({ vendor: "", brand: "", status: "", q: "" });
  const [error, setError] = useState<string | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const loadItems = useCallback(async () => {
    try {
      const data = await fetchItems({
        vendor: filters.vendor || undefined,
        brand: filters.brand || undefined,
        status: filters.status || undefined,
        q: filters.q || undefined,
      });
      setItems(data);
    } catch (e) {
      setError(String(e));
    }
  }, [filters]);

  useEffect(() => {
    loadItems();
  }, [loadItems]);

  const stopPolling = useCallback(() => {
    if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
  }, []);

  const startPolling = useCallback(
    (jobId: string) => {
      stopPolling();
      pollRef.current = setInterval(async () => {
        try {
          const status = await getJobStatus(jobId);
          setJobStatus(status);
          if (status.done) {
            stopPolling();
            await loadItems();
          }
        } catch {
          stopPolling();
        }
      }, 1000);
    },
    [stopPolling, loadItems]
  );

  const handleInit = useCallback(async (stopYear: number) => {
    setError(null);
    try {
      const { job_id } = await startInit(stopYear);
      const initial = await getJobStatus(job_id);
      setJobStatus(initial);
      startPolling(job_id);
    } catch (e) {
      setError(String(e));
    }
  }, [startPolling]);

  const handleSync = useCallback(async () => {
    setError(null);
    try {
      const { job_id } = await startCheckpoint();
      const initial = await getJobStatus(job_id);
      setJobStatus(initial);
      startPolling(job_id);
    } catch (e) {
      setError(String(e));
    }
  }, [startPolling]);

  const isSyncing = jobStatus !== null && !jobStatus.done;

  return (
    <>
      <Header onInit={handleInit} onSync={handleSync} syncing={isSyncing} />
      {jobStatus && <ProgressBar status={jobStatus} />}
      {error && (
        <p style={{ color: "red", padding: "8px 0" }}>{error}</p>
      )}
      <FiltersBar filters={filters} onChange={setFilters} />
      <ClosetGrid items={items} />
    </>
  );
}
```

- [ ] **Step 6: Verify TypeScript compiles**

```bash
cd frontend && npx tsc --noEmit
```

Expected: may have errors because components don't exist yet — that's OK for now, continue.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/
git commit -m "feat: add frontend types, API layer, and App root component"
```

---

### Task 9: Frontend components

**Files:**
- Create: `frontend/src/components/Header.tsx`
- Create: `frontend/src/components/ProgressBar.tsx`
- Create: `frontend/src/components/Filters.tsx`
- Create: `frontend/src/components/ItemCard.tsx`
- Create: `frontend/src/components/ClosetGrid.tsx`

- [ ] **Step 1: Create `frontend/src/components/Header.tsx`**

```typescript
import { useState } from "react";

interface Props {
  onInit: (stopYear: number) => void;
  onSync: () => void;
  syncing: boolean;
}

export default function Header({ onInit, onSync, syncing }: Props) {
  const [showYearPrompt, setShowYearPrompt] = useState(false);
  const [stopYear, setStopYear] = useState("2023");

  const handleInitClick = () => {
    if (syncing) return;
    setShowYearPrompt(true);
  };

  const handleInitConfirm = () => {
    const year = parseInt(stopYear, 10);
    if (!isNaN(year) && year >= 2000 && year <= new Date().getFullYear()) {
      setShowYearPrompt(false);
      onInit(year);
    }
  };

  return (
    <header style={{ padding: "16px 0", display: "flex", alignItems: "center", gap: "12px", borderBottom: "1px solid #ddd", marginBottom: "16px" }}>
      <h1 style={{ margin: 0, fontSize: "1.5rem", flex: 1 }}>Digital Closet</h1>
      {showYearPrompt ? (
        <div style={{ display: "flex", gap: "8px", alignItems: "center" }}>
          <label style={{ fontSize: "0.9rem" }}>
            Scan back to year:
            <input
              type="number"
              value={stopYear}
              min={2000}
              max={new Date().getFullYear()}
              onChange={(e) => setStopYear(e.target.value)}
              style={{ marginLeft: "8px", width: "70px", padding: "4px" }}
            />
          </label>
          <button onClick={handleInitConfirm} style={btnStyle}>Start</button>
          <button onClick={() => setShowYearPrompt(false)} style={{ ...btnStyle, background: "#999" }}>Cancel</button>
        </div>
      ) : (
        <>
          <button onClick={handleInitClick} disabled={syncing} style={btnStyle}>
            Initialize closet
          </button>
          <button onClick={onSync} disabled={syncing} style={btnStyle}>
            Sync since last check
          </button>
        </>
      )}
    </header>
  );
}

const btnStyle: React.CSSProperties = {
  padding: "8px 16px",
  background: "#1a1a1a",
  color: "#fff",
  border: "none",
  borderRadius: "4px",
  cursor: "pointer",
  fontSize: "0.9rem",
};
```

- [ ] **Step 2: Create `frontend/src/components/ProgressBar.tsx`**

```typescript
import type { JobStatus } from "../types";

interface Props {
  status: JobStatus;
}

export default function ProgressBar({ status }: Props) {
  return (
    <div style={{ background: "#fff", border: "1px solid #ddd", borderRadius: "6px", padding: "12px 16px", marginBottom: "16px" }}>
      <div style={{ display: "flex", gap: "24px", fontSize: "0.85rem", color: "#555", marginBottom: "8px" }}>
        <span>Scanned: <strong>{status.scanned}</strong></span>
        <span>Kept: <strong style={{ color: "#16a34a" }}>{status.kept}</strong></span>
        <span>Skipped: <strong>{status.skipped}</strong></span>
        {status.errors > 0 && <span>Errors: <strong style={{ color: "#dc2626" }}>{status.errors}</strong></span>}
        <span style={{ marginLeft: "auto" }}>{status.done ? (status.state === "error" ? "Failed" : "Done") : "Running..."}</span>
      </div>
      {!status.done && (
        <div style={{ height: "4px", background: "#e5e7eb", borderRadius: "2px", overflow: "hidden" }}>
          <div
            style={{
              height: "100%",
              background: "#1a1a1a",
              width: status.scanned > 0 ? `${Math.min(100, (status.kept + status.skipped) / status.scanned * 100)}%` : "10%",
              transition: "width 0.3s ease",
            }}
          />
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 3: Create `frontend/src/components/Filters.tsx`**

```typescript
import type { Filters } from "../types";

interface Props {
  filters: Filters;
  onChange: (f: Filters) => void;
}

export default function FiltersBar({ filters, onChange }: Props) {
  const set = (key: keyof Filters) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) =>
    onChange({ ...filters, [key]: e.target.value });

  return (
    <div style={{ display: "flex", gap: "12px", flexWrap: "wrap", marginBottom: "16px" }}>
      <input
        placeholder="Search items..."
        value={filters.q}
        onChange={set("q")}
        style={inputStyle}
      />
      <input
        placeholder="Vendor domain"
        value={filters.vendor}
        onChange={set("vendor")}
        style={{ ...inputStyle, maxWidth: "160px" }}
      />
      <input
        placeholder="Brand"
        value={filters.brand}
        onChange={set("brand")}
        style={{ ...inputStyle, maxWidth: "140px" }}
      />
      <select value={filters.status} onChange={set("status")} style={{ ...inputStyle, maxWidth: "140px" }}>
        <option value="">All statuses</option>
        <option value="active">Active</option>
        <option value="returned">Returned</option>
        <option value="cancelled">Cancelled</option>
      </select>
    </div>
  );
}

const inputStyle: React.CSSProperties = {
  padding: "8px 12px",
  border: "1px solid #ddd",
  borderRadius: "4px",
  fontSize: "0.9rem",
  flex: 1,
  minWidth: "120px",
};
```

- [ ] **Step 4: Create `frontend/src/components/ItemCard.tsx`**

```typescript
import { useState } from "react";
import type { Item } from "../types";
import { imageUrl } from "../api";

interface Props {
  item: Item;
}

export default function ItemCard({ item }: Props) {
  const [imgError, setImgError] = useState(false);
  const dimmed = item.status !== "active";

  return (
    <article
      style={{
        background: "#fff",
        borderRadius: "8px",
        overflow: "hidden",
        border: "1px solid #e5e7eb",
        opacity: dimmed ? 0.55 : 1,
        display: "flex",
        flexDirection: "column",
      }}
    >
      <div style={{ aspectRatio: "1", background: "#f9fafb", position: "relative" }}>
        {!imgError ? (
          <img
            src={imageUrl(item.id)}
            alt={item.item_name}
            onError={() => setImgError(true)}
            style={{ width: "100%", height: "100%", objectFit: "cover" }}
          />
        ) : (
          <div style={{ width: "100%", height: "100%", display: "flex", alignItems: "center", justifyContent: "center", color: "#aaa", fontSize: "0.8rem" }}>
            No image
          </div>
        )}
        {dimmed && (
          <span style={{
            position: "absolute",
            top: "8px",
            right: "8px",
            background: item.status === "returned" ? "#dc2626" : "#6b7280",
            color: "#fff",
            fontSize: "0.7rem",
            fontWeight: 600,
            padding: "2px 6px",
            borderRadius: "4px",
            textTransform: "uppercase",
          }}>
            {item.status}
          </span>
        )}
      </div>
      <div style={{ padding: "12px", flex: 1, display: "flex", flexDirection: "column", gap: "4px" }}>
        <p style={{ margin: 0, fontWeight: 600, fontSize: "0.95rem", lineHeight: 1.3 }}>{item.item_name}</p>
        {item.brand && <p style={{ margin: 0, fontSize: "0.8rem", color: "#6b7280" }}>{item.brand}</p>}
        <div style={{ display: "flex", gap: "8px", fontSize: "0.8rem", color: "#9ca3af", flexWrap: "wrap" }}>
          {item.size && <span>Size: {item.size}</span>}
          {item.color && <span>{item.color}</span>}
        </div>
        <div style={{ marginTop: "auto", display: "flex", justifyContent: "space-between", alignItems: "center", paddingTop: "8px" }}>
          {item.price != null ? (
            <span style={{ fontWeight: 600 }}>${item.price.toFixed(2)}</span>
          ) : (
            <span />
          )}
          <span style={{ fontSize: "0.75rem", color: "#9ca3af" }}>
            {item.vendor_domain} · {new Date(item.purchase_date).toLocaleDateString()}
          </span>
        </div>
      </div>
    </article>
  );
}
```

- [ ] **Step 5: Create `frontend/src/components/ClosetGrid.tsx`**

```typescript
import type { Item } from "../types";
import ItemCard from "./ItemCard";

interface Props {
  items: Item[];
}

export default function ClosetGrid({ items }: Props) {
  if (items.length === 0) {
    return (
      <div style={{ textAlign: "center", padding: "80px 0", color: "#9ca3af" }}>
        <p style={{ fontSize: "1.1rem", margin: "0 0 8px" }}>Your closet is empty</p>
        <p style={{ fontSize: "0.9rem", margin: 0 }}>Click "Initialize closet" to scan your purchase emails</p>
      </div>
    );
  }

  return (
    <div
      style={{
        display: "grid",
        gridTemplateColumns: "repeat(auto-fill, minmax(200px, 1fr))",
        gap: "16px",
        paddingBottom: "32px",
      }}
    >
      {items.map((item) => (
        <ItemCard key={item.id} item={item} />
      ))}
    </div>
  );
}
```

- [ ] **Step 6: TypeScript check**

```bash
cd frontend && npx tsc --noEmit
```

Expected: 0 errors.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/components/
git commit -m "feat: add Header, ProgressBar, Filters, ItemCard, ClosetGrid components"
```

---

### Task 10: Full verification

**Files:** none — verification only

- [ ] **Step 1: Run full backend suite**

```bash
cd backend && ruff check . && black --check . && pytest -q
```

Expected: all checks pass. Paste actual output.

If ruff or black finds issues:
```bash
cd backend && ruff check . --fix && black . && ruff check . && black --check .
```

Then commit any fixes:
```bash
git add -u && git commit -m "style: ruff/black fixes for phase 05"
```

- [ ] **Step 2: Build the frontend**

```bash
cd frontend && npm run build
```

Expected: `dist/` created, 0 TypeScript errors, 0 Vite build errors. Paste output.

- [ ] **Step 3: Start both servers**

In one terminal:
```bash
cd backend && uvicorn app.main:app --reload
```

In another:
```bash
cd frontend && npm run dev
```

Both should start without errors.

- [ ] **Step 4: Verify API endpoints manually**

```bash
curl -s http://localhost:8000/items | python3 -m json.tool
curl -s http://localhost:8000/orders | python3 -m json.tool
curl -s -w "\n%{http_code}" http://localhost:8000/sync/status/bad-id
```

Expected:
- `/items` → `[]`
- `/orders` → `[]`
- `/sync/status/bad-id` → `404`

- [ ] **Step 5: Verify frontend loads**

Open `http://localhost:5173` in a browser. Check:
- [ ] Page loads with "Digital Closet" header
- [ ] Two buttons: "Initialize closet" and "Sync since last check"
- [ ] Empty state message: "Your closet is empty"
- [ ] Filter inputs are visible
- [ ] No console errors

- [ ] **Step 6: Final commit — phase complete**

```bash
git add -u
git commit -m "chore: phase 05 complete — API + frontend verified"
```

---

## Definition of Done Checklist

- [ ] `session` param removed from `download_order_images` signature and all 6 test calls
- [ ] `jobs.py` has `create_job`, `get_job`, `get_active_job`, `complete_job`, `fail_job`, `clear`
- [ ] Pipeline `_drain` updates `job_state` counters incrementally when `job_state` is not None
- [ ] `POST /sync/init` creates a job, starts background task, returns `{ job_id }` with 202
- [ ] `POST /sync/checkpoint` same as above
- [ ] `GET /sync/status/{job_id}` returns live progress; 404 for unknown IDs
- [ ] Second sync request while one is running returns 409
- [ ] `GET /items` returns items with flat order info; supports `vendor`, `brand`, `status`, `q`, `page`, `per_page`
- [ ] `GET /orders` returns orders with nested items
- [ ] `GET /images/{item_id}` serves image file; 404 when `image_path` is null or file missing
- [ ] `POST /items/{item_id}/status` updates item status; 404 for unknown item
- [ ] CORS middleware allows `FRONTEND_ORIGIN`
- [ ] Frontend builds without errors (`npm run build`)
- [ ] "Initialize closet" asks for stop year, starts sync, shows progress bar
- [ ] "Sync since last check" starts incremental sync
- [ ] Closet grid renders item cards with image, name, brand, size, color, price, vendor, date
- [ ] Returned/cancelled items appear dimmed with a status badge
- [ ] Empty state shows "Initialize closet" prompt
- [ ] `ruff check . && black --check . && pytest -q` all pass (backend)
