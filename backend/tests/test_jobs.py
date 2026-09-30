"""Tests for the background job model (app/core/jobs.py).

These cover the contract the API and UI depend on:
  * POST returns a job id immediately instead of blocking for minutes
  * progress is persisted and monotonic
  * cooperative cancellation stops a job at a step boundary
  * failures are recorded with a traceback rather than lost
  * the job table is the source of truth even when nothing is live in-process
"""

from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.database import Base
from app.models.job import Job, JobStatus


async def _await_job(jobs_mod, job_id: int, status: str, timeout: float = 5.0) -> dict:
    """Poll until `job_id` reaches `status`, with a hard timeout.

    A bounded helper beats an inline loop: it fails loudly with the observed
    status instead of silently falling through to a confusing assertion.
    """
    deadline = asyncio.get_running_loop().time() + timeout
    job = None
    while asyncio.get_running_loop().time() < deadline:
        job = await jobs_mod.get_job(job_id)
        if job and job["status"] == status:
            return job
        await asyncio.sleep(0.02)
    observed = job["status"] if job else "<missing>"
    raise AssertionError(f"job {job_id} never reached {status!r} (last: {observed!r})")


@pytest.fixture
async def job_db(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    import app.core.jobs as jobs_mod

    monkeypatch.setattr(jobs_mod, "AsyncSessionLocal", factory)
    # Progress broadcast needs a running loop; stub it so tests are deterministic.
    monkeypatch.setattr(jobs_mod, "_broadcast_job", lambda payload: None)

    # The cancel-event / task registries are MODULE-LEVEL. Without clearing
    # them, a job launched by one test keeps running into the next one, where
    # it competes for the event loop and occasionally starves that test's own
    # job until its timeout (~5s). Observed as a flake that moved between
    # tests and only appeared in the full suite.
    jobs_mod._cancel_events.clear()
    jobs_mod._running_tasks.clear()

    yield factory

    # Drain anything still running before tearing the engine down.
    pending = [t for t in jobs_mod._running_tasks.values() if not t.done()]
    for t in pending:
        t.cancel()
    if pending:
        await asyncio.gather(*pending, return_exceptions=True)
    jobs_mod._cancel_events.clear()
    jobs_mod._running_tasks.clear()
    await engine.dispose()


async def test_launch_returns_immediately_and_job_completes(job_db) -> None:
    """The whole point: the caller gets an id, not a 16-minute wait."""
    import app.core.jobs as jobs_mod

    started = asyncio.Event()
    release = asyncio.Event()

    async def slow_runner(ctx):
        started.set()
        await release.wait()
        return {"ok": True}

    job_id = await jobs_mod.launch("test_slow", slow_runner, {"a": 1})
    assert isinstance(job_id, int)

    # The call returned while the job is still blocked.
    await asyncio.wait_for(started.wait(), timeout=2)
    assert not release.is_set()

    release.set()
    await _await_job(jobs_mod, job_id, JobStatus.SUCCEEDED.value)

    job = await jobs_mod.get_job(job_id)
    assert job["status"] == JobStatus.SUCCEEDED.value
    assert job["result"] == {"ok": True}
    assert job["params"] == {"a": 1}


async def test_progress_is_persisted_and_reaches_100(job_db) -> None:
    import app.core.jobs as jobs_mod

    async def runner(ctx):
        total = 10
        for i in range(1, total + 1):
            await ctx.report(i, total, f"step {i}")
        return {"done": total}

    job_id = await jobs_mod.launch("test_progress", runner)
    await _await_job(jobs_mod, job_id, JobStatus.SUCCEEDED.value)

    job = await jobs_mod.get_job(job_id)
    assert job["progress"]["total"] == 10
    assert job["progress"]["current"] == 10
    assert job["progress"]["pct"] == 100.0


async def test_cancel_stops_job_cooperatively(job_db) -> None:
    """Cancel must be honoured at the next step boundary, not ignored."""
    import app.core.jobs as jobs_mod

    ticks = 0

    async def runner(ctx):
        nonlocal ticks
        for i in range(200):
            ctx.raise_if_cancelled()
            ticks += 1
            await ctx.report(i, 200, "working")
            await asyncio.sleep(0.005)
        return {"ticks": ticks}

    job_id = await jobs_mod.launch("test_cancel", runner)
    await asyncio.sleep(0.08)  # let it get going

    signalled = await jobs_mod.request_cancel(job_id)
    assert signalled is True

    await _await_job(jobs_mod, job_id, JobStatus.CANCELLED.value)

    job = await jobs_mod.get_job(job_id)
    assert job["status"] == JobStatus.CANCELLED.value
    assert ticks < 200, "job must have stopped early"


async def test_failure_is_recorded_with_traceback(job_db) -> None:
    import app.core.jobs as jobs_mod

    async def boom(ctx):
        raise ValueError("intentional failure")

    job_id = await jobs_mod.launch("test_fail", boom)
    await _await_job(jobs_mod, job_id, JobStatus.FAILED.value)

    job = await jobs_mod.get_job(job_id)
    assert job["status"] == JobStatus.FAILED.value
    assert "ValueError" in job["error"]
    assert "intentional failure" in job["error"]


async def test_cancel_terminal_job_reports_not_cancelled(job_db) -> None:
    """Cancelling a finished job must not claim success."""
    import app.core.jobs as jobs_mod

    async def quick(ctx):
        return {"ok": True}

    job_id = await jobs_mod.launch("test_quick", quick)
    await _await_job(jobs_mod, job_id, JobStatus.SUCCEEDED.value)

    assert await jobs_mod.request_cancel(job_id) is False


async def test_list_jobs_filters_by_type(job_db) -> None:
    import app.core.jobs as jobs_mod

    async def quick(ctx):
        return {}

    a = await jobs_mod.launch("type_a", quick)
    b = await jobs_mod.launch("type_b", quick)
    await _await_job(jobs_mod, a, JobStatus.SUCCEEDED.value)
    await _await_job(jobs_mod, b, JobStatus.SUCCEEDED.value)

    only_a = await jobs_mod.list_jobs(job_type="type_a")
    assert [j["id"] for j in only_a] == [a]
    assert len(await jobs_mod.list_jobs()) == 2


async def test_registry_cleaned_up_after_completion(job_db) -> None:
    """No leak: cancel events and task handles are dropped once done."""
    import app.core.jobs as jobs_mod

    async def quick(ctx):
        return {}

    job_id = await jobs_mod.launch("test_cleanup", quick)
    await _await_job(jobs_mod, job_id, JobStatus.SUCCEEDED.value)

    assert jobs_mod.get_cancel_event(job_id) is None
    assert jobs_mod.running_job_count() == 0
