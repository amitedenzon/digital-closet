# Phase 01 — Data Model Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create SQLAlchemy 2.0 async models for the four database tables (orders, items, processed_messages, sync_state), plus pytest tests that insert an order with two items and reject a duplicate dedup key.

**Architecture:** SQLite via `aiosqlite` for the POC. All models use `DeclarativeBase` with `Mapped` / `mapped_column` typed columns (SQLAlchemy 2.0 style). UUID strings as PKs except `sync_state` which uses an auto-increment int. A `(vendor_domain, merchant_order_id)` unique constraint on `orders` enforces dedup.

**Tech Stack:** Python 3.11, SQLAlchemy 2.0 async (`aiosqlite`), Pydantic-settings v2, pytest + pytest-asyncio 0.26.

---

## File Structure

| File | Action | Responsibility |
|------|--------|----------------|
| `backend/app/__init__.py` | Create | Package marker |
| `backend/app/config.py` | Create | Pydantic `Settings` (DATABASE_URL) |
| `backend/app/db.py` | Create | `Base`, `make_engine`, `make_session_factory` |
| `backend/app/models.py` | Create | Enums + all four ORM models |
| `backend/tests/__init__.py` | Create | Package marker |
| `backend/tests/conftest.py` | Create | Async in-memory SQLite session fixture |
| `backend/tests/test_models.py` | Create | All model tests including DoD tests |
| `backend/pytest.ini` | Create | `asyncio_mode=auto`, `pythonpath=.` |
| `backend/.env.example` | Create | `DATABASE_URL` template |

---

### Task 1: Scaffolding — package markers, pytest config, env example

**Files:**
- Create: `backend/app/__init__.py`
- Create: `backend/tests/__init__.py`
- Create: `backend/pytest.ini`
- Create: `backend/.env.example`

- [ ] **Step 1: Create empty package markers**

Run:
```bash
touch backend/app/__init__.py backend/tests/__init__.py
```
Expected: no output.

- [ ] **Step 2: Create pytest.ini**

Create `backend/pytest.ini`:
```ini
[pytest]
asyncio_mode = auto
testpaths = tests
pythonpath = .
```

- [ ] **Step 3: Create .env.example**

Create `backend/.env.example`:
```
DATABASE_URL=sqlite+aiosqlite:///./closet.db
```

- [ ] **Step 4: Verify pytest runs with no errors (zero tests)**

Run:
```bash
cd backend && conda run -n closet pytest -q
```
Expected:
```
no tests ran
```
(or `0 passed, 0 warnings`)

- [ ] **Step 5: Commit**

```bash
git add backend/app/__init__.py backend/tests/__init__.py backend/pytest.ini backend/.env.example
git commit -m "feat: scaffold backend package structure and pytest config"
```

---

### Task 2: Config — Pydantic Settings

**Files:**
- Create: `backend/app/config.py`
- Create: `backend/tests/test_models.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_models.py`:
```python
from app.config import Settings


def test_settings_accepts_database_url():
    s = Settings(DATABASE_URL="sqlite+aiosqlite:///./test.db")
    assert s.DATABASE_URL == "sqlite+aiosqlite:///./test.db"


def test_settings_has_default_database_url():
    s = Settings()
    assert s.DATABASE_URL.startswith("sqlite+aiosqlite://")
```

- [ ] **Step 2: Run to confirm failure**

Run:
```bash
cd backend && conda run -n closet pytest tests/test_models.py::test_settings_accepts_database_url -v
```
Expected: `FAILED` — `ModuleNotFoundError: No module named 'app.config'`

- [ ] **Step 3: Implement config.py**

Create `backend/app/config.py`:
```python
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    DATABASE_URL: str = "sqlite+aiosqlite:///./closet.db"

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}
```

- [ ] **Step 4: Run to confirm pass**

Run:
```bash
cd backend && conda run -n closet pytest tests/test_models.py::test_settings_accepts_database_url tests/test_models.py::test_settings_has_default_database_url -v
```
Expected: `2 passed`

- [ ] **Step 5: Commit**

```bash
git add backend/app/config.py backend/tests/test_models.py
git commit -m "feat: add Pydantic Settings for DATABASE_URL"
```

---

### Task 3: Database layer — Base, engine, session factory

**Files:**
- Create: `backend/app/db.py`
- Modify: `backend/tests/test_models.py`

- [ ] **Step 1: Append failing tests to test_models.py**

Add to the **bottom** of `backend/tests/test_models.py`:
```python
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession


async def test_make_engine_connects():
    from app.db import make_engine
    engine = make_engine("sqlite+aiosqlite:///:memory:")
    async with engine.connect() as conn:
        result = await conn.execute(sa.text("SELECT 1"))
        assert result.scalar() == 1
    await engine.dispose()


async def test_make_session_factory_yields_async_session():
    from app.db import make_engine, make_session_factory
    engine = make_engine("sqlite+aiosqlite:///:memory:")
    factory = make_session_factory(engine)
    async with factory() as session:
        assert isinstance(session, AsyncSession)
    await engine.dispose()
```

- [ ] **Step 2: Run to confirm failure**

Run:
```bash
cd backend && conda run -n closet pytest tests/test_models.py::test_make_engine_connects -v
```
Expected: `FAILED` — `ImportError: cannot import name 'make_engine' from 'app.db'`

- [ ] **Step 3: Implement db.py**

Create `backend/app/db.py`:
```python
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


def make_engine(url: str) -> AsyncEngine:
    return create_async_engine(url, echo=False)


def make_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)
```

- [ ] **Step 4: Run to confirm pass**

Run:
```bash
cd backend && conda run -n closet pytest tests/test_models.py::test_make_engine_connects tests/test_models.py::test_make_session_factory_yields_async_session -v
```
Expected: `2 passed`

- [ ] **Step 5: Commit**

```bash
git add backend/app/db.py backend/tests/test_models.py
git commit -m "feat: add Base, make_engine, make_session_factory to db.py"
```

---

### Task 4: Enums — OrderStatus, ItemStatus, MessageResult

**Files:**
- Create: `backend/app/models.py`
- Modify: `backend/tests/test_models.py`

- [ ] **Step 1: Append failing tests**

Add to the **bottom** of `backend/tests/test_models.py`:
```python
def test_order_status_values():
    from app.models import OrderStatus
    assert set(e.value for e in OrderStatus) == {
        "active", "shipped", "partially_returned", "returned", "cancelled"
    }


def test_item_status_values():
    from app.models import ItemStatus
    assert set(e.value for e in ItemStatus) == {"active", "returned", "cancelled"}


def test_message_result_values():
    from app.models import MessageResult
    assert set(e.value for e in MessageResult) == {
        "extracted", "skipped_prefilter", "skipped_llm", "error"
    }
```

- [ ] **Step 2: Run to confirm failure**

Run:
```bash
cd backend && conda run -n closet pytest tests/test_models.py::test_order_status_values -v
```
Expected: `FAILED` — `ImportError: cannot import name 'OrderStatus' from 'app.models'`

- [ ] **Step 3: Create models.py with enums**

Create `backend/app/models.py`:
```python
import enum
import uuid
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import (
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class OrderStatus(str, enum.Enum):
    active = "active"
    shipped = "shipped"
    partially_returned = "partially_returned"
    returned = "returned"
    cancelled = "cancelled"


class ItemStatus(str, enum.Enum):
    active = "active"
    returned = "returned"
    cancelled = "cancelled"


class MessageResult(str, enum.Enum):
    extracted = "extracted"
    skipped_prefilter = "skipped_prefilter"
    skipped_llm = "skipped_llm"
    error = "error"
```

- [ ] **Step 4: Run to confirm pass**

Run:
```bash
cd backend && conda run -n closet pytest tests/test_models.py::test_order_status_values tests/test_models.py::test_item_status_values tests/test_models.py::test_message_result_values -v
```
Expected: `3 passed`

- [ ] **Step 5: Commit**

```bash
git add backend/app/models.py backend/tests/test_models.py
git commit -m "feat: define OrderStatus, ItemStatus, MessageResult enums"
```

---

### Task 5: Order model + async session fixture

**Files:**
- Modify: `backend/app/models.py`
- Create: `backend/tests/conftest.py`
- Modify: `backend/tests/test_models.py`

- [ ] **Step 1: Create the async session fixture**

Create `backend/tests/conftest.py`:
```python
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db import Base

TEST_DB_URL = "sqlite+aiosqlite:///:memory:"


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    engine = create_async_engine(TEST_DB_URL)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        yield s
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()
```

- [ ] **Step 2: Append failing tests**

Add to the **bottom** of `backend/tests/test_models.py`:
```python
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
import pytest


async def test_order_table_created(session: AsyncSession):
    result = await session.execute(
        text("SELECT name FROM sqlite_master WHERE type='table' AND name='orders'")
    )
    assert result.scalar() == "orders"


async def test_order_insert_and_retrieve(session: AsyncSession):
    from app.models import Order, OrderStatus
    order = Order(
        vendor_name="Zara",
        vendor_domain="zara.com",
        merchant_order_id="ORDER-001",
        purchase_date=datetime(2024, 1, 15, tzinfo=timezone.utc),
    )
    session.add(order)
    await session.commit()

    result = await session.execute(
        select(Order).where(Order.vendor_domain == "zara.com")
    )
    saved = result.scalar_one()
    assert saved.vendor_name == "Zara"
    assert saved.status == OrderStatus.active
    assert len(saved.id) == 36  # UUID string


async def test_duplicate_order_raises_integrity_error(session: AsyncSession):
    from app.models import Order
    order1 = Order(
        vendor_name="Nike",
        vendor_domain="nike.com",
        merchant_order_id="NIKE-001",
        purchase_date=datetime(2024, 5, 10, tzinfo=timezone.utc),
    )
    session.add(order1)
    await session.commit()

    order2 = Order(
        vendor_name="Nike",
        vendor_domain="nike.com",
        merchant_order_id="NIKE-001",
        purchase_date=datetime(2024, 5, 11, tzinfo=timezone.utc),
    )
    session.add(order2)
    with pytest.raises(IntegrityError):
        await session.commit()
```

Also add these imports near the top of the file (after the existing imports):
```python
from datetime import datetime, timezone
from decimal import Decimal
```

- [ ] **Step 3: Run to confirm failure**

Run:
```bash
cd backend && conda run -n closet pytest tests/test_models.py::test_order_table_created -v
```
Expected: `FAILED` — `ImportError: cannot import name 'Order'` (Order not defined yet)

- [ ] **Step 4: Add Order model — append to models.py**

Add after the enum classes in `backend/app/models.py`:
```python

def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Order(Base):
    __tablename__ = "orders"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    vendor_name: Mapped[str] = mapped_column(Text)
    vendor_domain: Mapped[str] = mapped_column(Text)
    merchant_order_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    purchase_date: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    currency: Mapped[str | None] = mapped_column(Text, nullable=True)
    total_price: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    status: Mapped[OrderStatus] = mapped_column(
        Enum(OrderStatus), default=OrderStatus.active
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )

    items: Mapped[list["Item"]] = relationship("Item", back_populates="order")

    __table_args__ = (
        UniqueConstraint("vendor_domain", "merchant_order_id", name="uq_order_dedup"),
    )
```

- [ ] **Step 5: Run to confirm pass**

Run:
```bash
cd backend && conda run -n closet pytest tests/test_models.py::test_order_table_created tests/test_models.py::test_order_insert_and_retrieve tests/test_models.py::test_duplicate_order_raises_integrity_error -v
```
Expected: `3 passed`

- [ ] **Step 6: Commit**

```bash
git add backend/app/models.py backend/tests/conftest.py backend/tests/test_models.py
git commit -m "feat: add Order model with UniqueConstraint dedup anchor"
```

---

### Task 6: Item model

**Files:**
- Modify: `backend/app/models.py`
- Modify: `backend/tests/test_models.py`

- [ ] **Step 1: Append failing tests**

Add to the **bottom** of `backend/tests/test_models.py`:
```python
async def test_items_table_created(session: AsyncSession):
    result = await session.execute(
        text("SELECT name FROM sqlite_master WHERE type='table' AND name='items'")
    )
    assert result.scalar() == "items"


async def test_order_with_two_items(session: AsyncSession):
    from app.models import Order, Item
    order = Order(
        vendor_name="ASOS",
        vendor_domain="asos.com",
        merchant_order_id="ASOS-999",
        purchase_date=datetime(2024, 3, 1, tzinfo=timezone.utc),
        currency="GBP",
        total_price=Decimal("89.99"),
    )
    session.add(order)
    await session.flush()  # get order.id without committing

    session.add_all([
        Item(
            order_id=order.id,
            item_name="Blue Jeans",
            size="32",
            color="blue",
            quantity=1,
            price=Decimal("49.99"),
        ),
        Item(
            order_id=order.id,
            item_name="White T-Shirt",
            size="M",
            color="white",
            quantity=1,
            price=Decimal("19.99"),
        ),
    ])
    await session.commit()

    result = await session.execute(
        select(Order).where(Order.vendor_domain == "asos.com")
    )
    saved_order = result.scalar_one()

    item_result = await session.execute(
        select(Item).where(Item.order_id == saved_order.id)
    )
    saved_items = item_result.scalars().all()
    assert len(saved_items) == 2
    assert {i.item_name for i in saved_items} == {"Blue Jeans", "White T-Shirt"}
```

- [ ] **Step 2: Run to confirm failure**

Run:
```bash
cd backend && conda run -n closet pytest tests/test_models.py::test_items_table_created -v
```
Expected: `FAILED` — `ImportError: cannot import name 'Item'`

- [ ] **Step 3: Add Item model — append to models.py**

Add after the `Order` class in `backend/app/models.py`:
```python

class Item(Base):
    __tablename__ = "items"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    order_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("orders.id", ondelete="CASCADE")
    )
    item_name: Mapped[str] = mapped_column(Text)
    brand: Mapped[str | None] = mapped_column(Text, nullable=True)
    size: Mapped[str | None] = mapped_column(Text, nullable=True)
    color: Mapped[str | None] = mapped_column(Text, nullable=True)
    quantity: Mapped[int] = mapped_column(Integer, default=1)
    price: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    image_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    image_url_src: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[ItemStatus] = mapped_column(
        Enum(ItemStatus), default=ItemStatus.active
    )
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    order: Mapped["Order"] = relationship("Order", back_populates="items")
```

- [ ] **Step 4: Run to confirm pass**

Run:
```bash
cd backend && conda run -n closet pytest tests/test_models.py::test_items_table_created tests/test_models.py::test_order_with_two_items -v
```
Expected: `2 passed`

- [ ] **Step 5: Commit**

```bash
git add backend/app/models.py backend/tests/test_models.py
git commit -m "feat: add Item model with FK to orders"
```

---

### Task 7: ProcessedMessage + SyncState models

**Files:**
- Modify: `backend/app/models.py`
- Modify: `backend/tests/test_models.py`

- [ ] **Step 1: Append failing tests**

Add to the **bottom** of `backend/tests/test_models.py`:
```python
async def test_processed_messages_table_created(session: AsyncSession):
    result = await session.execute(
        text(
            "SELECT name FROM sqlite_master WHERE type='table'"
            " AND name='processed_messages'"
        )
    )
    assert result.scalar() == "processed_messages"


async def test_processed_message_insert(session: AsyncSession):
    from app.models import ProcessedMessage, MessageResult
    msg = ProcessedMessage(
        message_id="gmail-abc123",
        provider="gmail",
        account="amit@gmail.com",
        result=MessageResult.extracted,
    )
    session.add(msg)
    await session.commit()

    result = await session.execute(
        select(ProcessedMessage).where(
            ProcessedMessage.message_id == "gmail-abc123"
        )
    )
    saved = result.scalar_one()
    assert saved.provider == "gmail"
    assert saved.result == MessageResult.extracted
    assert saved.order_id is None


async def test_sync_state_table_created(session: AsyncSession):
    result = await session.execute(
        text(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='sync_state'"
        )
    )
    assert result.scalar() == "sync_state"


async def test_sync_state_insert(session: AsyncSession):
    from app.models import SyncState
    state = SyncState(
        provider="gmail",
        account="amit@gmail.com",
        cursor="internalDate:1234567890",
    )
    session.add(state)
    await session.commit()

    result = await session.execute(
        select(SyncState).where(SyncState.provider == "gmail")
    )
    saved = result.scalar_one()
    assert saved.cursor == "internalDate:1234567890"
    assert saved.id is not None  # auto-increment assigned
```

- [ ] **Step 2: Run to confirm failure**

Run:
```bash
cd backend && conda run -n closet pytest tests/test_models.py::test_processed_messages_table_created -v
```
Expected: `FAILED` — `ImportError: cannot import name 'ProcessedMessage'`

- [ ] **Step 3: Add ProcessedMessage and SyncState — append to models.py**

Add after the `Item` class in `backend/app/models.py`:
```python

class ProcessedMessage(Base):
    __tablename__ = "processed_messages"

    message_id: Mapped[str] = mapped_column(Text, primary_key=True)
    provider: Mapped[str] = mapped_column(Text)
    account: Mapped[str] = mapped_column(Text)
    result: Mapped[MessageResult] = mapped_column(Enum(MessageResult))
    order_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    processed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class SyncState(Base):
    __tablename__ = "sync_state"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    provider: Mapped[str] = mapped_column(Text)
    account: Mapped[str] = mapped_column(Text)
    cursor: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_run_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        UniqueConstraint("provider", "account", name="uq_sync_state_provider_account"),
    )
```

- [ ] **Step 4: Run to confirm pass**

Run:
```bash
cd backend && conda run -n closet pytest tests/test_models.py::test_processed_messages_table_created tests/test_models.py::test_processed_message_insert tests/test_models.py::test_sync_state_table_created tests/test_models.py::test_sync_state_insert -v
```
Expected: `4 passed`

- [ ] **Step 5: Commit**

```bash
git add backend/app/models.py backend/tests/test_models.py
git commit -m "feat: add ProcessedMessage and SyncState models"
```

---

### Task 8: Full verification — all tests + linting (Definition of Done)

**Files:**
- No changes — this task verifies everything passes together.

The spec DoD requires: "Models created, `Base.metadata.create_all` produces the schema, a quick pytest inserts an order with two items and rejects a duplicate `(vendor_domain, merchant_order_id)`."

Both conditions are covered by `test_order_with_two_items` and `test_duplicate_order_raises_integrity_error` above.

- [ ] **Step 1: Run the full test suite**

Run:
```bash
cd backend && conda run -n closet pytest -v
```
Expected: All tests pass. Output will include at minimum:
```
tests/test_models.py::test_settings_accepts_database_url PASSED
tests/test_models.py::test_settings_has_default_database_url PASSED
tests/test_models.py::test_make_engine_connects PASSED
tests/test_models.py::test_make_session_factory_yields_async_session PASSED
tests/test_models.py::test_order_status_values PASSED
tests/test_models.py::test_item_status_values PASSED
tests/test_models.py::test_message_result_values PASSED
tests/test_models.py::test_order_table_created PASSED
tests/test_models.py::test_order_insert_and_retrieve PASSED
tests/test_models.py::test_duplicate_order_raises_integrity_error PASSED
tests/test_models.py::test_items_table_created PASSED
tests/test_models.py::test_order_with_two_items PASSED
tests/test_models.py::test_processed_messages_table_created PASSED
tests/test_models.py::test_processed_message_insert PASSED
tests/test_models.py::test_sync_state_table_created PASSED
tests/test_models.py::test_sync_state_insert PASSED
```

- [ ] **Step 2: Run ruff + black (per CLAUDE.md verification requirement)**

Run:
```bash
cd backend && conda run -n closet sh -c "ruff check . && black --check ."
```
Expected:
```
All checks passed!
All files would be left unchanged.
```
If `black --check` reports formatting issues, fix them:
```bash
conda run -n closet black .
```
Then re-run the check.

- [ ] **Step 3: Run the combined check from CLAUDE.md**

Run:
```bash
cd backend && conda run -n closet sh -c "ruff check . && black --check . && pytest -q"
```
Expected:
```
All checks passed!
All files would be left unchanged.
16 passed in X.XXs
```

- [ ] **Step 4: Final commit**

```bash
git add -p  # stage any formatting fixes only
git commit -m "chore: phase 01 data model complete — all tests passing, linting clean"
```
If there are no outstanding changes, skip this commit.
