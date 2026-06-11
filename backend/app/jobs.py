from __future__ import annotations

import uuid
from dataclasses import dataclass, field

__all__ = [
    "JobState",
    "create_job",
    "get_job",
    "get_active_job",
    "complete_job",
    "fail_job",
    "clear",
]


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
