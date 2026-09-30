"""Job model — durable record of a long-running background task.

Long pipelines (factor computation, full data sync, AI picks) previously ran
inline inside the HTTP request that triggered them. That meant a 16-minute
factor run held an HTTP connection open, could not report progress, could not be
cancelled, and hit the frontend's 30s axios timeout long before finishing.

Every such pipeline is now launched as a *job*: the API returns a job id
immediately, progress is pushed over WebSocket, and the job can be polled or
cancelled independently of the client connection.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from sqlalchemy import DateTime, Float, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class JobStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


#: Statuses from which a job will never transition again.
TERMINAL_STATUSES = frozenset(
    {JobStatus.SUCCEEDED, JobStatus.FAILED, JobStatus.CANCELLED}
)


class Job(Base):
    """A single background task execution.

    ``job_type`` identifies the pipeline (see ``app.pipelines.registry``), and
    ``params`` holds the JSON-encoded arguments it was launched with.
    """

    __tablename__ = "jobs"
    __table_args__ = (
        # The two hot queries are "newest jobs of a type" and "list recent
        # jobs"; a composite index serves both without a filesort.
        Index("ix_jobs_type_created", "job_type", "created_at"),
        Index("ix_jobs_status", "status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    job_type: Mapped[str] = mapped_column(String(50), index=True)
    status: Mapped[str] = mapped_column(String(20), default=JobStatus.PENDING.value)

    # Progress: `progress_current` / `progress_total` drive the UI progress bar.
    # `progress_message` carries the human-readable current step.
    progress_current: Mapped[int] = mapped_column(Integer, default=0)
    progress_total: Mapped[int] = mapped_column(Integer, default=0)
    progress_message: Mapped[str | None] = mapped_column(String(200), nullable=True)
    progress_pct: Mapped[float] = mapped_column(Float, default=0.0)

    params: Mapped[str | None] = mapped_column(Text, nullable=True)
    result: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, index=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
