"""Job API — launch, inspect, and cancel background pipelines.

These endpoints return immediately. The client polls ``GET /jobs/{id}`` or
subscribes to the ``job_progress`` WebSocket channel for live updates.
"""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.jobs import get_job as _get_job
from app.core.jobs import launch, list_jobs, request_cancel, running_job_count

router = APIRouter()


def _ok(data, message="ok"):
    return JSONResponse({"code": 0, "message": message, "data": data})


def _err(message: str, code: int = 400):
    return JSONResponse({"code": code, "message": message, "data": None}, status_code=code)


#: Job types the API is allowed to launch, mapped to their pipeline.
def _resolve_runner(job_type: str):
    """Return the pipeline callable for a job type, or None if unknown."""
    if job_type == "full_ranking":
        from app.pipelines import run_full_ranking_pipeline

        return run_full_ranking_pipeline
    if job_type == "factors":
        from app.pipelines import run_factor_pipeline

        return run_factor_pipeline
    if job_type == "rankings":
        from app.pipelines import run_ranking_pipeline

        return run_ranking_pipeline
    return None


@router.post("/jobs/{job_type}")
async def create_job(
    job_type: str,
    trading_date: date = Query(default=None),
    concurrency: int = Query(default=12, ge=1, le=32),
    session: AsyncSession = Depends(get_db),
):
    """Launch a background pipeline and return its job id immediately."""
    runner = _resolve_runner(job_type)
    if runner is None:
        return _err(f"Unknown job type: {job_type}", 404)

    params = {
        "trading_date": str(trading_date or date.today()),
        "concurrency": concurrency,
    }

    # Bind pipeline kwargs explicitly so the runner signature stays uniform.
    if job_type == "full_ranking":
        async def _run(ctx, **_kw):
            return await runner(
                ctx,
                trading_date=trading_date or date.today(),
                concurrency=concurrency,
            )
    else:
        async def _run(ctx, **_kw):
            return await runner(ctx, trading_date=trading_date or date.today())

    job_id = await launch(job_type, _run, params)
    return _ok({"job_id": job_id, "job_type": job_type, "status": "pending", "params": params})


@router.get("/jobs/")
async def get_jobs(
    job_type: str = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
):
    """Recent jobs, newest first."""
    return _ok({"items": await list_jobs(job_type=job_type, limit=limit)})


@router.get("/jobs/status")
async def jobs_status():
    """Lightweight liveness probe for background work."""
    return _ok({"running": running_job_count()})


@router.get("/jobs/{job_id}")
async def get_job_detail(job_id: int):
    """Current state of a single job (this is what the UI polls)."""
    job = await _get_job(job_id)
    if job is None:
        return _err(f"Job not found: {job_id}", 404)
    return _ok(job)


@router.post("/jobs/{job_id}/cancel")
async def cancel_job(job_id: int):
    """Request cooperative cancellation of a running job."""
    job = await _get_job(job_id)
    if job is None:
        return _err(f"Job not found: {job_id}", 404)

    signalled = await request_cancel(job_id)
    if job["status"] in {"succeeded", "failed", "cancelled"}:
        return _ok({"job_id": job_id, "status": job["status"], "cancelled": False,
                    "message": "任务已结束，无需取消"})

    return _ok({
        "job_id": job_id,
        "cancelled": True,
        "signalled": signalled,
        "message": "已请求取消，任务将在下一个检查点停止",
    })
