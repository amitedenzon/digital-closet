from __future__ import annotations

from datetime import datetime, timezone

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from unittest.mock import AsyncMock, patch
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app import jobs
from app.db import Base
from app.schemas import ExtractionResult, ExtractedItem
from app.store import repo

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
    with patch("app.main._run_sync_job", new_callable=AsyncMock):
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


# ── /items ────────────────────────────────────────────────────────────────────


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
            _extraction(
                vendor="adidas.com",
                order_id="ord-2",
                item_name="Ultraboost",
                brand="Adidas",
            ),
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
        await repo.upsert_order(
            session, _extraction(vendor="nike.com", order_id="ord-1")
        )
        await repo.upsert_order(
            session,
            _extraction(
                vendor="adidas.com",
                order_id="ord-2",
                item_name="Ultraboost",
                brand="Adidas",
            ),
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
            _extraction(
                vendor="adidas.com",
                order_id="ord-2",
                item_name="Ultraboost",
                brand="Adidas",
            ),
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
