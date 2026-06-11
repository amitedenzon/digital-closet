from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator, Literal

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
    ItemBriefResponse,
    ItemResponse,
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


async def get_session() -> AsyncIterator[AsyncSession]:
    async with _session_factory() as session:
        yield session


# ── background task wrapper ───────────────────────────────────────────────────


async def _run_sync_job(
    job: jobs.JobState,
    *,
    mode: Literal["init", "checkpoint"],
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
        stmt = stmt.where(Item.item_name.ilike(f"%{q}%") | Item.brand.ilike(f"%{q}%"))
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
