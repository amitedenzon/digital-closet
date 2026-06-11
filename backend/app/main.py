from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator, Literal

from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.ext.asyncio import AsyncSession

from app import jobs
from app.config import Settings
from app.db import Base, make_engine, make_session_factory
from app.ingestion import pipeline
from app.providers.gmail import GmailProvider
from app.extraction.ollama_extractor import OllamaExtractor
from app.schemas import (
    JobStatusResponse,
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
