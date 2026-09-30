"""add jobs table

Introduces the ``jobs`` table backing the background-job model. Long pipelines
(factor computation, ranking, full sync) no longer run inline inside an HTTP
request; they are launched as jobs whose progress is polled or pushed over the
``job_progress`` WebSocket channel.

Like the baseline, ``upgrade()`` is idempotent: a database that already got this
table from ``Base.metadata.create_all`` is skipped rather than failing.

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-29

"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = '0002'
down_revision: Union[str, None] = '0001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    existing = set(sa.inspect(op.get_bind()).get_table_names())
    if 'jobs' in existing:
        return

    op.create_table(
        'jobs',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('job_type', sa.String(length=50), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('progress_current', sa.Integer(), nullable=False),
        sa.Column('progress_total', sa.Integer(), nullable=False),
        sa.Column('progress_message', sa.String(length=200), nullable=True),
        sa.Column('progress_pct', sa.Float(), nullable=False),
        sa.Column('params', sa.Text(), nullable=True),
        sa.Column('result', sa.Text(), nullable=True),
        sa.Column('error', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('started_at', sa.DateTime(), nullable=True),
        sa.Column('finished_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_jobs_job_type', 'jobs', ['job_type'])
    op.create_index('ix_jobs_status', 'jobs', ['status'])
    op.create_index('ix_jobs_created_at', 'jobs', ['created_at'])
    op.create_index('ix_jobs_type_created', 'jobs', ['job_type', 'created_at'])


def downgrade() -> None:
    op.drop_index('ix_jobs_type_created', table_name='jobs')
    op.drop_index('ix_jobs_created_at', table_name='jobs')
    op.drop_index('ix_jobs_status', table_name='jobs')
    op.drop_index('ix_jobs_job_type', table_name='jobs')
    op.drop_table('jobs')
