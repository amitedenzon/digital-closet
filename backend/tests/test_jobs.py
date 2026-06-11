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
