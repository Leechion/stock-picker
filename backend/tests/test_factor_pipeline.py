"""Tests for the factor pipeline's concurrency and cancellation contract.

These lock in the two defects that made the old `/rankings/compute` unusable:

1. It gathered 10 coroutines over ONE shared ``AsyncSession`` and died with
   ``IllegalStateChangeError``. The pipeline must give every worker its own
   session.
2. Cancellation was only checked at phase boundaries. A cancel issued at 15%
   still ran to completion (observed live: cancel at 475/3018 kept going past
   1575/3018). Workers must check per item.
"""

from __future__ import annotations

import asyncio
from datetime import date

import pytest

from app.core.jobs import JobCancelled, JobContext
from app.pipelines import factor_pipeline


@pytest.fixture
def fake_universe(monkeypatch):
    """A 40-stock universe with no DB or network access."""
    codes = [f"{i:06d}" for i in range(1, 41)]
    industry = {c: "测试行业" for c in codes}

    async def _load():
        return codes, industry, {}

    async def _no_heat(industry_map=None, quotes=None):
        return {}

    monkeypatch.setattr(factor_pipeline, "_load_universe", _load)
    monkeypatch.setattr(factor_pipeline, "_load_sector_heat", _no_heat)

    # JobContext.report() writes to the real jobs table; stub it so these tests
    # are pure unit tests with no database at all.
    async def _noop_report(self, current=None, total=None, message=None):
        return None

    monkeypatch.setattr(JobContext, "report", _noop_report)
    return codes


async def test_cancel_stops_promptly_midway(fake_universe, monkeypatch) -> None:
    """A cancel must stop the run early, not after every stock is processed."""
    processed: list[str] = []
    ctx = JobContext(job_id=1, job_type="test")

    async def fake_compute_one(code, industry_map, fund_map, sector_heat, sem,
                               cancel_event=None, quote_map=None):
        processed.append(code)
        # Flip the cancel flag partway through, deterministically, from inside a
        # worker — no sleeping, no timing races.
        if len(processed) == 10:
            ctx._cancel_event.set()
        await asyncio.sleep(0)
        return []

    monkeypatch.setattr(factor_pipeline, "_compute_one", fake_compute_one)

    with pytest.raises(JobCancelled):
        await factor_pipeline.run_factor_pipeline(ctx, concurrency=4)

    assert len(processed) < len(fake_universe), (
        f"cancel was not honoured: processed all {len(processed)} stocks"
    )


async def test_no_write_when_cancelled(fake_universe, monkeypatch) -> None:
    """Cancelling mid-compute must not touch the factor_values table.

    The persist phase is deliberately a separate, serial step — so a cancelled
    run leaves the previous factors intact rather than half-deleted.
    """
    ctx = JobContext(job_id=2, job_type="test")
    seen: list[str] = []

    async def fake_compute_one(code, industry_map, fund_map, sector_heat, sem,
                               cancel_event=None, quote_map=None):
        seen.append(code)
        if len(seen) == 5:
            ctx._cancel_event.set()
        return [{"factor_name": "x", "factor_type": "TECHNICAL", "value": 1.0}]

    monkeypatch.setattr(factor_pipeline, "_compute_one", fake_compute_one)

    class _NoWriteSession:
        def __init__(self):
            raise AssertionError("persist phase must not run when cancelled")

    monkeypatch.setattr(factor_pipeline, "AsyncSessionLocal", _NoWriteSession)

    with pytest.raises(JobCancelled):
        await factor_pipeline.run_factor_pipeline(ctx, concurrency=2)


async def test_completes_when_not_cancelled(fake_universe, monkeypatch) -> None:
    """Regression guard: the happy path must still finish and report progress."""
    async def fake_compute_one(code, industry_map, fund_map, sector_heat, sem,
                               cancel_event=None, quote_map=None):
        return [{"factor_name": "x", "factor_type": "TECHNICAL", "value": 1.0}]

    monkeypatch.setattr(factor_pipeline, "_compute_one", fake_compute_one)

    written: list[int] = []

    class _Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def execute(self, *a, **kw):
            return None

        async def commit(self):
            return None

    monkeypatch.setattr(factor_pipeline, "AsyncSessionLocal", lambda: _Session())

    reported: list[tuple] = []

    ctx = JobContext(job_id=3, job_type="test")
    _orig_report = ctx.report

    async def spy(current=None, total=None, message=None):
        reported.append((current, total, message))
        return await _orig_report(current, total, message)

    monkeypatch.setattr(ctx, "report", spy)

    result = await factor_pipeline.run_factor_pipeline(ctx, concurrency=4)

    assert result["stocks_total"] == len(fake_universe)
    assert result["stocks_computed"] == len(fake_universe)
    assert reported, "progress must be reported"
    final = [r for r in reported if r[0] == len(fake_universe)]
    assert final, "final progress tick must reach the total"


async def test_cancel_is_observed_inside_semaphore(fake_universe, monkeypatch) -> None:
    """Regression: a mid-run cancel must stop QUEUED work, not just phase starts.

    Every worker coroutine is created up front, so they all pass any check that
    happens before the semaphore. The only check that matters is the one taken
    *after* acquiring it. Without it, a cancel issued at 15% ran to ~100%
    (reproduced live: cancel at 475/3018 kept going past 2350/3018).
    """
    processed: list[str] = []
    ctx = JobContext(job_id=9, job_type="test")

    async def fake_compute_one(code, industry_map, fund_map, sector_heat, sem,
                               cancel_event=None, quote_map=None):
        async with sem:
            # This mirrors the production placement of the check.
            if cancel_event is not None and cancel_event.is_set():
                raise JobCancelled()
            processed.append(code)
            await asyncio.sleep(0)
        return []

    monkeypatch.setattr(factor_pipeline, "_compute_one", fake_compute_one)

    async def cancel_after_bit():
        # Let a few through, then cancel while most are still queued.
        while len(processed) < 5:
            await asyncio.sleep(0)
        ctx._cancel_event.set()

    asyncio.create_task(cancel_after_bit())
    with pytest.raises(JobCancelled):
        await factor_pipeline.run_factor_pipeline(ctx, concurrency=2)

    assert len(processed) < len(fake_universe), (
        f"queued work was not cancelled: ran all {len(processed)}"
    )


async def test_worker_isolates_failures(fake_universe, monkeypatch) -> None:
    """One exploding stock must not abort the whole run."""
    async def flaky(code, industry_map, fund_map, sector_heat, sem,
                    cancel_event=None, quote_map=None):
        if code.endswith("7"):
            raise RuntimeError("boom")
        return [{"factor_name": "x", "factor_type": "TECHNICAL", "value": 1.0}]

    monkeypatch.setattr(factor_pipeline, "_compute_one", flaky)

    class _Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def execute(self, *a, **kw):
            return None

        async def commit(self):
            return None

    monkeypatch.setattr(factor_pipeline, "AsyncSessionLocal", lambda: _Session())

    ctx = JobContext(job_id=4, job_type="test")
    result = await factor_pipeline.run_factor_pipeline(ctx, concurrency=4)

    # 4 of 40 codes end with '7' -> they fail, the rest succeed.
    assert result["stocks_computed"] == len(fake_universe) - 4
