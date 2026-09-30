"""Pipeline layer — orchestration of multi-step domain operations.

Why this layer exists
---------------------
Before, the "compute factors then rank" sequence lived inside both
``app/api/ranking.py`` and ``app/core/scheduler.py``. The two copies drifted:
one shared a single ``AsyncSession`` across concurrent workers (and crashed with
``IllegalStateChangeError``), the other did not. Fixing a bug in one copy left
the other broken.

Rules for this layer
--------------------
* A pipeline is the **only** place that sequences multiple domain services.
* Pipelines depend on ``app.services`` and ``app.core`` — never on FastAPI.
* Every pipeline takes a ``JobContext`` for progress + cancellation.
* No pipeline holds a long-lived session; each phase opens its own.
"""

from app.pipelines.factor_pipeline import (
    run_factor_pipeline,
    run_ranking_pipeline,
)
from app.pipelines.full_pipeline import run_full_ranking_pipeline

__all__ = [
    "run_factor_pipeline",
    "run_ranking_pipeline",
    "run_full_ranking_pipeline",
]
