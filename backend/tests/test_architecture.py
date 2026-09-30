"""Architecture guards — tests that enforce module boundaries.

These do not test behaviour; they test *structure*. They exist because the
factor/ranking pipeline was previously implemented three times
(``api/ranking.py``, ``api/factors.py``, ``core/scheduler.py``), each copy
drifting and each carrying a different defect. Fixing one left the others
broken.

The rule these enforce: **orchestration lives in ``app.pipelines``, and only
there.** API modules may launch a pipeline; the scheduler may schedule one;
neither may sequence the steps itself.
"""

from __future__ import annotations

import inspect

from app.pipelines import (
    run_factor_pipeline,
    run_full_ranking_pipeline,
    run_ranking_pipeline,
)


def _code_only(fn) -> str:
    """Source of `fn` with comments and docstrings stripped.

    The guards below assert on code, not prose. Docstrings legitimately *name*
    the very functions we forbid calling (to explain why they are forbidden),
    which would otherwise make these tests fail on their own documentation.
    """
    import ast
    import textwrap

    tree = ast.parse(textwrap.dedent(inspect.getsource(fn)))
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Module)):
            body = node.body
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) \
                    and isinstance(body[0].value.value, str):
                node.body = body[1:] or [ast.Pass()]
    return ast.unparse(tree)


def test_api_ranking_does_not_reimplement_pipeline() -> None:
    """`/rankings/compute` must launch a job, not run the steps inline."""
    from app.api import ranking

    src = _code_only(ranking.compute_ranking)
    assert "launch" in src, "endpoint must launch a background job"
    assert "compute_factors_for_stock" not in src, "must not re-implement factor compute"
    assert "asyncio.gather" not in src, "concurrency belongs to the pipeline"
    assert "get_history" not in src, "data access belongs to the pipeline"


def test_api_factors_does_not_reimplement_pipeline() -> None:
    """`/factors/compute` was the third copy — a fully serial loop."""
    from app.api import factors

    src = _code_only(factors.compute_factors)
    assert "launch" in src, "endpoint must launch a background job"
    assert "compute_all_factors" not in src, "must not re-implement factor compute"
    assert "get_history" not in src, "data access belongs to the pipeline"


def test_scheduler_delegates_to_pipeline() -> None:
    """The cron path must reuse the same pipeline as the API path."""
    from app.core import scheduler

    src = _code_only(scheduler.run_daily_ranking)
    assert "run_full_ranking_pipeline" in src
    assert "compute_factors_for_stock" not in src
    assert "get_history" not in src


def test_pipeline_layer_has_no_fastapi_dependency() -> None:
    """Pipelines must stay HTTP-agnostic so the scheduler can share them."""
    import app.pipelines.factor_pipeline as fp
    import app.pipelines.full_pipeline as fl

    for mod in (fp, fl):
        src = inspect.getsource(mod)
        assert "from fastapi" not in src, f"{mod.__name__} must not import FastAPI"
        assert "APIRouter" not in src, f"{mod.__name__} must not define routes"


def test_pipelines_are_job_context_driven() -> None:
    """Every pipeline takes a JobContext — that is how progress/cancel work."""
    for fn in (run_factor_pipeline, run_ranking_pipeline, run_full_ranking_pipeline):
        params = list(inspect.signature(fn).parameters)
        assert params and params[0] == "ctx", (
            f"{fn.__name__} must take a JobContext as its first parameter"
        )


def test_no_shared_session_across_gather() -> None:
    """Guard the original crash: a shared AsyncSession under gather.

    Every concurrent worker must open its own session. This is asserted on the
    source because the failure mode (IllegalStateChangeError) is timing
    dependent and would otherwise pass CI intermittently.
    """
    import app.pipelines.factor_pipeline as fp

    src = inspect.getsource(fp)
    # The worker must open its own session rather than be handed one.
    assert "async def _compute_one(" in src
    compute_src = inspect.getsource(fp._compute_one)
    assert "AsyncSessionLocal()" in compute_src
    assert "session: AsyncSession" not in compute_src
