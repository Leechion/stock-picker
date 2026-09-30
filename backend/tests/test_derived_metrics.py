"""Tests for locally derived sentiment metrics and intraday bar archiving.

Both exist to close data gaps found by measurement:

* ``real_capital_flow_score``, ``chip_concentration_score`` and
  ``sector_heat_score`` were **3018/3018 values == 0.0** — three of nineteen
  factors carrying zero information, because their upstream hosts are blocked
  or the report was retired.
* ``stock_daily`` was only written at 15:05, so today's bar did not exist
  until after the close.
"""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
import pytest

from app.services.derived_metrics import (
    compute_derived_flow,
    compute_sector_heat_local,
    score_capital_flow_proxy,
    score_chip_concentration_proxy,
    session_fraction,
)


def _bars(n: int = 30, *, last_volume: float = 10_000.0) -> pd.DataFrame:
    """A synthetic daily frame: flat prices, constant volume."""
    return pd.DataFrame(
        {
            "trade_date": pd.date_range("2026-01-01", periods=n),
            "open": [10.0] * n,
            "close": [10.0] * (n - 1) + [10.5],
            "high": [10.6] * n,
            "low": [9.8] * n,
            "volume": [10_000.0] * (n - 1) + [last_volume],
            "amount": [1_000.0] * n,
        }
    )


# ----------------------------------------------------------------------
# Derived metrics
# ----------------------------------------------------------------------

def test_derived_flow_from_daily_bars_alone() -> None:
    """Must work with no quote at all — that is the fallback path."""
    out = compute_derived_flow(_bars(last_volume=20_000.0))
    assert out.volume_ratio == pytest.approx(2.0, rel=0.01)
    assert out.close_strength is not None
    assert 0.0 <= out.close_strength <= 1.0


def test_close_strength_reflects_position_in_range() -> None:
    df = _bars()
    df.loc[df.index[-1], "high"] = 11.0
    df.loc[df.index[-1], "low"] = 10.0
    df.loc[df.index[-1], "close"] = 11.0  # closed at the high
    out = compute_derived_flow(df)
    assert out.close_strength == pytest.approx(1.0)

    df.loc[df.index[-1], "close"] = 10.0  # closed at the low
    out = compute_derived_flow(df)
    assert out.close_strength == pytest.approx(0.0)


def test_intraday_volume_is_annualised() -> None:
    """A 10:00 snapshot must not look like a volume collapse.

    Without annualising, a stock trading 1/8 of a normal day at 10:00 shows a
    volume_ratio of ~0.125 and every volume factor reads as extreme.
    """
    df = _bars(last_volume=10_000.0)
    quote = {"volume": 1_250.0, "price": 10.5, "open": 10.2, "turnover_rate": 1.0}

    early = compute_derived_flow(df, quote, now_hour=10, now_minute=0)
    late = compute_derived_flow(df, quote, now_hour=15, now_minute=0)

    # Same raw volume, different time of day -> very different ratio.
    assert early.volume_ratio is not None and late.volume_ratio is not None
    assert early.volume_ratio > late.volume_ratio


def test_session_fraction_is_monotonic_and_bounded() -> None:
    points = [(9, 30), (10, 0), (11, 30), (13, 0), (14, 0), (15, 0)]
    fracs = [session_fraction(h, m) for h, m in points]
    assert fracs == sorted(fracs), "fraction must not decrease through the day"
    assert all(0.0 < f <= 1.0 for f in fracs)
    assert fracs[-1] == pytest.approx(1.0)


def test_capital_flow_proxy_is_not_constant() -> None:
    """The whole point: the old value was always 0.0, carrying no information."""
    values = {
        score_capital_flow_proxy(vr, cs)
        for vr in (0.3, 1.0, 2.0, 4.0)
        for cs in (0.0, 0.5, 1.0)
    }
    assert len(values) > 5, "proxy collapsed to too few distinct values"
    assert all(-1.0 <= v <= 1.0 for v in values)


def test_capital_flow_proxy_direction() -> None:
    """Heavy volume closing at the high should score above light volume at the low."""
    strong = score_capital_flow_proxy(3.0, 1.0)
    weak = score_capital_flow_proxy(0.3, 0.0)
    assert strong > weak
    assert strong > 0 > weak


def test_chip_proxy_prefers_low_turnover() -> None:
    """Tightly held = low turnover; frantic turnover = dispersion."""
    tight = score_chip_concentration_proxy(0.5, 0.3, 0.5)
    loose = score_chip_concentration_proxy(3.0, 8.0, 0.5)
    assert tight > loose


def test_chip_proxy_handles_missing_inputs() -> None:
    assert score_chip_concentration_proxy(None, None, None) == 0.0
    assert -1.0 <= score_chip_concentration_proxy(1.0, None, 0.7) <= 1.0


def test_sector_heat_from_quotes_and_industry_map(monkeypatch) -> None:
    """Replaces the blocked Eastmoney sector API using local data only."""
    class Q:
        def __init__(self, change, amount):
            self.change_pct = change
            self.amount = amount

    quotes = {
        "a1": Q(5.0, 100.0), "a2": Q(4.0, 100.0),   # strong sector
        "b1": Q(-3.0, 100.0), "b2": Q(-2.0, 100.0),  # weak sector
        "c1": Q(0.5, 100.0),                          # middling
    }
    industry = {"a1": "强", "a2": "强", "b1": "弱", "b2": "弱", "c1": "中"}

    heat = compute_sector_heat_local(quotes, industry)
    assert set(heat) == {"强", "弱", "中"}
    assert heat["强"] > heat["中"] > heat["弱"]
    assert all(0.0 <= v <= 100.0 for v in heat.values())


def test_sector_heat_ignores_unknown_industries() -> None:
    class Q:
        change_pct = 1.0
        amount = 10.0

    heat = compute_sector_heat_local({"x": Q()}, {"x": None})
    assert heat == {}


# ----------------------------------------------------------------------
# Intraday archiver
# ----------------------------------------------------------------------

def test_quote_date_parsing() -> None:
    """The bar must be dated by the QUOTE's timestamp, not the wall clock.

    Regression: on a holiday the feed still serves the previous close. Using
    today's date wrote a full 3207-row phantom bar for 2026-10-01 (a holiday)
    carrying 2026-09-30 prices.
    """
    from app.services.daily_archiver import _quote_date

    class Q:
        def __init__(self, ts):
            self.ts = ts

    assert _quote_date(Q("20260930161458")) == date(2026, 9, 30)
    assert _quote_date(Q("20261001090000")) == date(2026, 10, 1)
    assert _quote_date(Q("")) is None
    assert _quote_date(Q("garbage")) is None
    assert _quote_date(Q("20261301090000")) is None  # month 13
    assert _quote_date(Q(None)) is None


async def test_archive_once_writes_target_date_rows(monkeypatch) -> None:
    """Bars are keyed to the quote's date, and stale ticks are skipped."""
    from types import SimpleNamespace

    from app.services import daily_archiver as da

    fresh = SimpleNamespace(
        code="600519", price=10.5, open=10.2, high=10.6, low=10.0,
        volume=1000.0, amount=500.0, change_pct=1.0, prev_close=10.4,
        ts="20260930150000",
    )
    stale = SimpleNamespace(
        code="000001", price=9.9, open=9.8, high=10.0, low=9.7,
        volume=800.0, amount=400.0, change_pct=-1.0, prev_close=10.0,
        ts="20260929150000",  # previous session
    )
    suspended = SimpleNamespace(
        code="000002", price=0.0, open=0.0, high=0.0, low=0.0,
        volume=0.0, amount=0.0, change_pct=0.0, prev_close=5.0,
        ts="20260930150000",
    )

    # `archive_once` imports the poller lazily (`from app.services import
    # quote_poller`), so the patch must target the module object itself, not
    # an attribute on daily_archiver.
    import app.services.quote_poller as qp_mod

    monkeypatch.setattr(
        qp_mod, "get_latest",
        lambda: {"600519": fresh, "000001": stale, "000002": suspended},
    )

    written: list[dict] = []

    class FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def execute(self, stmt, rows=None):
            if rows:
                written.extend(rows)
            return None

        async def commit(self):
            return None

    monkeypatch.setattr(da, "AsyncSessionLocal", FakeSession)

    n = await da.archive_once()
    assert n == 1, f"expected only the fresh quote to be written, got {n}"
    assert written[0]["code"] == "600519"
    assert written[0]["trade_date"] == date(2026, 9, 30)
    assert written[0]["close"] == 10.5


def test_archiver_has_no_unique_constraint_assumption() -> None:
    """stock_daily has no UNIQUE(code, trade_date).

    The archiver must therefore DELETE-then-INSERT rather than rely on an
    upsert, otherwise every 5-minute tick would append 3207 duplicate rows.
    """
    import inspect

    from app.services import daily_archiver as da

    src = inspect.getsource(da.archive_once)
    assert "sql_delete" in src and "StockDaily.trade_date == target" in src


def test_sector_heat_accepts_dicts_as_well_as_objects() -> None:
    """Regression: the pipeline passes ``Quote.to_dict()``, not Quote objects.

    ``compute_sector_heat_local`` originally used ``getattr`` only. Serialised
    dicts therefore yielded None for every field, the bucket stayed empty, and
    it returned {} — silently leaving ``sector_heat_score`` at 0.0 for all 3018
    stocks even though the local computation itself worked fine.
    """
    industry = {"a": "强", "b": "弱"}
    as_dicts = {
        "a": {"change_pct": 5.0, "amount": 100.0},
        "b": {"change_pct": -5.0, "amount": 100.0},
    }
    heat = compute_sector_heat_local(as_dicts, industry)
    assert heat, "dict input produced no heat (regression)"
    assert heat["强"] > heat["弱"]


def test_sector_heat_dict_and_object_paths_agree() -> None:
    """Both input shapes must produce identical results."""
    class Q:
        def __init__(self, change, amount):
            self.change_pct = change
            self.amount = amount

    industry = {"a": "强", "b": "弱", "c": "中"}
    objs = {"a": Q(5.0, 100.0), "b": Q(-5.0, 100.0), "c": Q(0.0, 100.0)}
    dicts = {k: {"change_pct": v.change_pct, "amount": v.amount} for k, v in objs.items()}

    assert compute_sector_heat_local(objs, industry) == compute_sector_heat_local(dicts, industry)
