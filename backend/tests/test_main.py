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
