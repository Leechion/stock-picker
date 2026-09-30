"""Job manager — launch, track, report on, and cancel background pipelines.

Design notes
------------
* **One session per job, never shared.** Each coroutine that touches the DB
  opens its own ``AsyncSessionLocal()``. Sharing an ``AsyncSession`` across
  ``asyncio.gather`` is what caused ``IllegalStateChangeError`` in the old
  ``/rankings/compute`` endpoint.

* **Progress is written through a dedicated short-lived session.** The progress
  callback fires from inside the working pipeline, so it must not touch the
  pipeline's own session (that would interleave commits). It opens, writes, and
  closes its own session each time.

* **Cancellation is cooperative.** A cancel request sets an ``asyncio.Event``
  keyed by job id; the pipeline checks it at step boundaries. We never
  ``task.cancel()`` blindly, because that would leave partial DB writes without
  a chance to commit or roll back deliberately.

* **Single-process scope.** The in-memory registry below is per-process. Under
  multiple uvicorn workers, a cancel issued to worker A cannot stop a job
  running in worker B. Run a single worker, or move the registry to Redis.
  The DB row remains the source of truth for status either way.
"""

from __future__ import annotations

import asyncio
import json
import traceback
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from loguru import logger
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.models.job import TERMINAL_STATUSES, Job, JobStatus


class JobCancelled(Exception):
    """Raised inside a pipeline when its job has been cancelled."""


@dataclass
class JobContext:
    """Handed to a pipeline so it can report progress and honour cancellation.

    Pipelines must not import the manager directly; they receive this context.
    """

    job_id: int
    job_type: str
    params: dict[str, Any] = field(default_factory=dict)
    _cancel_event: asyncio.Event = field(default_factory=asyncio.Event, repr=False)

    @property
    def cancelled(self) -> bool:
        return self._cancel_event.is_set()

    def raise_if_cancelled(self) -> None:
        """Call at step boundaries — including inside per-item loops."""
        if self._cancel_event.is_set():
            raise JobCancelled()

    async def report(
        self,
        current: int | None = None,
        total: int | None = None,
        message: str | None = None,
    ) -> None:
        """Persist progress and push it to WebSocket subscribers."""
        await _update_progress(self.job_id, current, total, message)


# ----------------------------------------------------------------------
# In-process registry
# ----------------------------------------------------------------------

#: job_id -> cancel event, for jobs currently running in THIS process.
_cancel_events: dict[int, asyncio.Event] = {}
#: job_id -> asyncio.Task, so we can report whether it is still alive.
_running_tasks: dict[int, asyncio.Task] = {}


def get_cancel_event(job_id: int) -> asyncio.Event | None:
    return _cancel_events.get(job_id)


async def _update_progress(
    job_id: int,
    current: int | None,
    total: int | None,
    message: str | None,
) -> None:
    """Write progress to the job row and broadcast it.

    Uses its own session on purpose — see module docstring.
    """
    payload: dict[str, Any] = {}
    try:
        async with AsyncSessionLocal() as session:
            job = await session.get(Job, job_id)
            if job is None:
                return
            if current is not None:
                job.progress_current = current
            if total is not None:
                job.progress_total = total
            if message is not None:
                job.progress_message = message

            if job.progress_total > 0:
                job.progress_pct = round(
                    min(job.progress_current / job.progress_total, 1.0) * 100, 1
                )
            payload = {
                "job_id": job.id,
                "job_type": job.job_type,
                "status": job.status,
                "current": job.progress_current,
                "total": job.progress_total,
                "pct": job.progress_pct,
                "message": job.progress_message,
            }
            await session.commit()
    except Exception as exc:  # progress reporting must never kill the job
        logger.warning(f"Job {job_id}: failed to persist progress: {exc}")
        return

    if payload:
        _broadcast_job(payload)


def _broadcast_job(payload: dict) -> None:
    """Fire-and-forget push to WebSocket clients on the ``jobs`` channel."""
    try:
        from app.core.websocket import monitor_hub

        loop = asyncio.get_running_loop()
        loop.create_task(monitor_hub.broadcast("job_progress", payload))
    except RuntimeError:
        pass  # no running loop (e.g. called from a sync test) — skip broadcast


async def launch(
    job_type: str,
    runner: Callable[[JobContext], Awaitable[dict[str, Any] | None]],
    params: dict[str, Any] | None = None,
) -> int:
    """Create a job row and schedule ``runner`` as a detached asyncio task.

    Returns the job id immediately; the caller does not wait for completion.
    """
    params = params or {}

    async with AsyncSessionLocal() as session:
        job = Job(
            job_type=job_type,
            status=JobStatus.PENDING.value,
            params=json.dumps(params, ensure_ascii=False, default=str),
            progress_message="排队中",
        )
        session.add(job)
        await session.commit()
        await session.refresh(job)
        job_id = job.id

    cancel_event = asyncio.Event()
    _cancel_events[job_id] = cancel_event
    ctx = JobContext(
        job_id=job_id, job_type=job_type, params=params, _cancel_event=cancel_event
    )

    task = asyncio.create_task(_run_job(ctx, runner), name=f"job-{job_id}-{job_type}")
    _running_tasks[job_id] = task
    logger.info(f"Job {job_id} ({job_type}) launched")
    return job_id


async def _run_job(
    ctx: JobContext,
    runner: Callable[[JobContext], Awaitable[dict[str, Any] | None]],
) -> None:
    """Execute a pipeline, recording terminal state and cleaning up."""
    job_id = ctx.job_id
    try:
        async with AsyncSessionLocal() as session:
            job = await session.get(Job, job_id)
            if job is not None:
                job.status = JobStatus.RUNNING.value
                job.started_at = datetime.now()
                job.progress_message = "启动中"
                await session.commit()

        await _update_progress(job_id, 0, 0, "开始执行")

        result = await runner(ctx)

        async with AsyncSessionLocal() as session:
            job = await session.get(Job, job_id)
            if job is not None:
                job.status = JobStatus.SUCCEEDED.value
                job.progress_message = "已完成"
                job.result = json.dumps(result or {}, ensure_ascii=False, default=str)
                job.finished_at = datetime.now()
                if job.progress_total > 0:
                    job.progress_current = job.progress_total
                    job.progress_pct = 100.0
                await session.commit()
        logger.info(f"Job {job_id} ({ctx.job_type}) succeeded")

    except JobCancelled:
        async with AsyncSessionLocal() as session:
            job = await session.get(Job, job_id)
            if job is not None:
                job.status = JobStatus.CANCELLED.value
                job.progress_message = "已取消"
                job.finished_at = datetime.now()
                await session.commit()
        logger.info(f"Job {job_id} ({ctx.job_type}) cancelled")

    except asyncio.CancelledError:
        # Process shutdown or explicit task cancellation.
        async with AsyncSessionLocal() as session:
            job = await session.get(Job, job_id)
            if job is not None:
                job.status = JobStatus.CANCELLED.value
                job.progress_message = "中断"
                job.finished_at = datetime.now()
                await session.commit()
        logger.warning(f"Job {job_id} ({ctx.job_type}) interrupted")
        raise

    except Exception as exc:
        detail = f"{type(exc).__name__}: {exc}"
        async with AsyncSessionLocal() as session:
            job = await session.get(Job, job_id)
            if job is not None:
                job.status = JobStatus.FAILED.value
                job.error = f"{detail}\n{traceback.format_exc()}"[:8000]
                job.progress_message = "失败"
                job.finished_at = datetime.now()
                await session.commit()
        logger.error(f"Job {job_id} ({ctx.job_type}) failed: {detail}")

    finally:
        _cancel_events.pop(job_id, None)
        _running_tasks.pop(job_id, None)


async def request_cancel(job_id: int) -> bool:
    """Ask a running job to stop at its next step boundary.

    Returns True if a live job was signalled. A job in a terminal state, or one
    running in another process, returns False.
    """
    event = _cancel_events.get(job_id)
    if event is not None:
        event.set()
        logger.info(f"Job {job_id}: cancellation requested")
        await _update_progress(job_id, None, None, "取消中…")
        return True

    # Not live in this process — report the stored truth.
    async with AsyncSessionLocal() as session:
        job = await session.get(Job, job_id)
        if job is None:
            return False
        return JobStatus(job.status) not in TERMINAL_STATUSES


async def get_job(job_id: int) -> dict[str, Any] | None:
    """Serialise a single job for the API."""
    async with AsyncSessionLocal() as session:
        job = await session.get(Job, job_id)
        return _serialise(job) if job else None


async def list_jobs(
    job_type: str | None = None,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """Most recent jobs, newest first."""
    async with AsyncSessionLocal() as session:
        stmt = select(Job).order_by(Job.created_at.desc(), Job.id.desc()).limit(limit)
        if job_type:
            stmt = stmt.where(Job.job_type == job_type)
        rows = (await session.execute(stmt)).scalars().all()
        return [_serialise(j) for j in rows]


def _serialise(job: Job) -> dict[str, Any]:
    def _loads(raw: str | None) -> Any:
        if not raw:
            return None
        try:
            return json.loads(raw)
        except (ValueError, TypeError):
            return raw

    return {
        "id": job.id,
        "job_type": job.job_type,
        "status": job.status,
        "progress": {
            "current": job.progress_current,
            "total": job.progress_total,
            "pct": job.progress_pct,
            "message": job.progress_message,
        },
        "params": _loads(job.params),
        "result": _loads(job.result),
        "error": job.error,
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "started_at": job.started_at.isoformat() if job.started_at else None,
        "finished_at": job.finished_at.isoformat() if job.finished_at else None,
    }


def running_job_count() -> int:
    """Number of jobs alive in this process (diagnostics / health)."""
    return len(_running_tasks)
