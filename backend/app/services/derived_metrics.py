"""Derived sentiment metrics computed from data we can actually obtain.

Why this exists
---------------
Four sentiment inputs were coming back empty because their upstream hosts are
unavailable, and the failure was silent — the factors simply returned 0.0,
which Z-scores to exactly zero and contributes nothing to the ranking:

===============  ==========================  ==============================
factor           source                      status measured 2026-09
===============  ==========================  ==============================
real_capital_    push2.eastmoney.com         blocked on this network
  flow_score
chip_concen-     datacenter-web RPT_COST_     report retired upstream
  tration_score    CONC                        (报表配置不存在, code 9501)
sector_heat_     push2.eastmoney.com         blocked (same host)
  score
===============  ==========================  ==============================

Measured impact: ``real_capital_flow_score``, ``chip_concentration_score`` and
``sector_heat_score`` were **3018/3018 values == 0.0** — three of nineteen
factors carrying literally zero information.

What this module does instead
-----------------------------
Derives equivalent signals from sources that DO work:

* **Tencent realtime quotes** (``app/services/quote_service.py``) — gives
  ``amount``, ``volume``, ``turnover_rate`` for the whole market in ~0.4 s.
* **Local daily history** (``stock_daily``) — gives volume/price baselines.
* **Local industry map** (``stocks.industry``, 3200/3207 populated) — lets us
  compute sector heat without the blocked sector API.

Every metric is a *proxy*, not the real order-flow breakdown, and each
docstring says so. They are deliberately scale-free (ratios, percentiles)
because the realtime feed's absolute units (手, 万元) differ from the daily
table's.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

#: Trading minutes in a full A-share session (09:30-11:30 + 13:00-15:00).
FULL_SESSION_MINUTES = 240
#: Intraday checkpoints at which a snapshot represents a known fraction of the
#: day. Used to annualise volume when the market is still open.
_SESSION_FRACTIONS = {
    9: 0.0, 10: 0.125, 11: 0.375, 12: 0.5, 13: 0.5, 14: 0.75, 15: 1.0,
}


def session_fraction(hour: int, minute: int) -> float:
    """Approximate fraction of the trading day elapsed, for volume scaling.

    Without this, a 10:00 snapshot looks like a catastrophic volume collapse
    (only 1/8 of a day traded) and every stock's volume-ratio factor reads as
    extreme. Scaling to a full-day equivalent makes intraday and end-of-day
    numbers comparable.
    """
    if hour < 9:
        return 1 / FULL_SESSION_MINUTES  # avoid division by zero pre-open
    if hour >= 15:
        return 1.0
    if hour == 12:
        return 0.5

    # Minutes elapsed since the open, honouring the lunch break.
    if hour < 12:
        elapsed = (hour - 9) * 60 + minute - 30
    else:
        elapsed = 120 + (hour - 13) * 60 + minute
    elapsed = max(elapsed, 0)
    return min(max(elapsed / FULL_SESSION_MINUTES, 1 / FULL_SESSION_MINUTES), 1.0)


@dataclass(slots=True)
class DerivedFlow:
    """Locally derived substitutes for the unavailable upstream metrics."""

    #: Today's traded amount vs its own 20-day average, scaled to a full day.
    #: > 1 means unusually heavy turnover (attention / participation).
    volume_ratio: float | None = None
    #: Turnover rate (%), straight from the quote feed when available.
    turnover_rate: float | None = None
    #: Close position within today's range: 1.0 = closed at the high.
    #: A crude stand-in for buying pressure, since real order flow is absent.
    close_strength: float | None = None
    #: Amount-weighted intraday drift: (close-open)/open, signed.
    intraday_drift: float | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "volume_ratio": self.volume_ratio,
            "turnover_rate": self.turnover_rate,
            "close_strength": self.close_strength,
            "intraday_drift": self.intraday_drift,
        }


def compute_derived_flow(
    df: pd.DataFrame,
    quote: dict[str, Any] | None = None,
    *,
    now_hour: int | None = None,
    now_minute: int | None = None,
) -> DerivedFlow:
    """Derive flow-like metrics from daily history plus an optional live quote.

    Parameters
    ----------
    df : pd.DataFrame
        Daily OHLCV history, sorted ascending by date.
    quote : dict | None
        A realtime quote (``Quote.to_dict()``) for today, if available.
    now_hour, now_minute : int | None
        Current exchange time; used to annualise an intraday volume snapshot.
    """
    out = DerivedFlow()

    if df is None or df.empty or "close" not in df.columns:
        return out

    close = df["close"].astype(float)
    volume = df["volume"].astype(float) if "volume" in df.columns else None

    # ---- close strength: where today closed within today's range ----
    if {"high", "low", "close"}.issubset(df.columns):
        high = float(df["high"].iloc[-1])
        low = float(df["low"].iloc[-1])
        last = float(close.iloc[-1])
        if high > low:
            out.close_strength = float(np.clip((last - low) / (high - low), 0.0, 1.0))
        else:
            out.close_strength = 0.5

    # ---- intraday drift from the quote's open, else the bar's own open ----
    if quote and quote.get("open") and quote.get("price"):
        o = float(quote["open"])
        if o > 0:
            out.intraday_drift = float((float(quote["price"]) - o) / o)
    elif {"open", "close"}.issubset(df.columns):
        o = float(df["open"].iloc[-1])
        if o > 0:
            out.intraday_drift = float((float(close.iloc[-1]) - o) / o)

    # ---- turnover rate: prefer the live figure ----
    if quote and quote.get("turnover_rate"):
        out.turnover_rate = float(quote["turnover_rate"])

    # ---- volume ratio: today vs 20-day average, annualised if intraday ----
    if volume is not None and len(volume) >= 5:
        # Prefer the live volume; fall back to the latest daily bar.
        if quote and quote.get("volume"):
            today_vol = float(quote["volume"])
            hist = volume.iloc[-21:-1] if len(volume) >= 21 else volume.iloc[:-1]
        else:
            today_vol = float(volume.iloc[-1])
            hist = volume.iloc[-21:-1] if len(volume) >= 21 else volume.iloc[:-1]

        avg = float(hist.mean()) if len(hist) else 0.0
        if avg > 0:
            scaled = today_vol
            # Only annualise when the quote is a live, partial-day snapshot.
            if quote and now_hour is not None and now_minute is not None:
                frac = session_fraction(now_hour, now_minute)
                scaled = today_vol / frac
            out.volume_ratio = float(scaled / avg)

    return out


def compute_sector_heat_local(
    quotes: dict[str, Any],
    industry_map: dict[str, str | None],
) -> dict[str, float]:
    """Sector heat from the realtime feed, replacing the blocked sector API.

    Heat = the sector's volume-weighted average change, mapped to 0-100 via a
    cross-sectional percentile so it is comparable across days.

    Uses every stock with a quote, so it needs no external sector endpoint.
    """
    def _field(q: Any, name: str) -> Any:
        """Read a field from either a Quote object or its dict form.

        The factor pipeline serialises quotes with ``.to_dict()`` before
        handing them over, while direct callers pass the objects. Supporting
        both avoids a silent zero-result (getattr on a dict returns None).
        """
        if isinstance(q, dict):
            return q.get(name)
        return getattr(q, name, None)

    buckets: dict[str, list[tuple[float, float]]] = {}
    for code, q in quotes.items():
        industry = industry_map.get(code)
        if not industry:
            continue
        change = _field(q, "change_pct")
        amount = _field(q, "amount") or 0.0
        if change is None:
            continue
        buckets.setdefault(industry, []).append((float(change), float(amount)))

    if not buckets:
        return {}

    # Volume-weighted mean change per sector.
    raw: dict[str, float] = {}
    for industry, rows in buckets.items():
        total_amount = sum(a for _, a in rows)
        if total_amount > 0:
            raw[industry] = sum(c * a for c, a in rows) / total_amount
        else:
            raw[industry] = float(np.mean([c for c, _ in rows]))

    # Map to 0-100 by rank so the scale is stable day to day.
    values = np.array(list(raw.values()), dtype=float)
    if len(values) < 2:
        return {k: 50.0 for k in raw}

    order = values.argsort().argsort()  # 0..n-1 ranks
    pct = order / (len(values) - 1) * 100.0
    return {industry: float(pct[i]) for i, industry in enumerate(raw)}


def score_capital_flow_proxy(
    volume_ratio: float | None,
    close_strength: float | None,
) -> float:
    """Stand-in for the real capital-flow score, in [-1, 1].

    Real order-flow data (main-force net inflow) is unavailable, so this blends
    two observable participation signals:

    * unusually heavy volume (attention / accumulation), and
    * closing near the day's high (buyers in control into the close).
    """
    if volume_ratio is None and close_strength is None:
        return 0.0

    vr = 1.0 if volume_ratio is None else float(volume_ratio)
    # 1.0x average -> 0; 2.5x -> +1; 0.4x -> -1. tanh keeps it bounded.
    volume_component = float(np.tanh((vr - 1.0) / 1.2))

    cs = 0.5 if close_strength is None else float(close_strength)
    # 0.5 -> 0; 1.0 -> +1; 0.0 -> -1.
    strength_component = float((cs - 0.5) * 2.0)

    return float(np.clip(0.6 * volume_component + 0.4 * strength_component, -1.0, 1.0))


def score_chip_concentration_proxy(
    volume_ratio: float | None,
    turnover_rate: float | None,
    close_strength: float | None,
) -> float:
    """Stand-in for chip-concentration, in [-1, 1].

    The real metric measured how tightly chips were held. Absent it, we use
    *low* turnover with *steady* price as the signature of a tightly held
    stock, and treat frantic turnover as dispersion (the opposite).
    """
    if turnover_rate is None and volume_ratio is None:
        return 0.0

    # Low turnover => concentrated. Typical A-share turnover is 1-5%.
    if turnover_rate is not None:
        conc = float(np.clip((3.0 - float(turnover_rate)) / 3.0, -1.0, 1.0))
    else:
        vr = float(volume_ratio or 1.0)
        conc = float(np.clip((1.0 - vr) / 1.0, -1.0, 1.0))

    cs = 0.5 if close_strength is None else float(close_strength)
    stability = float(1.0 - abs(cs - 0.5) * 2.0)  # 1.0 when it closed mid-range

    return float(np.clip(0.7 * conc + 0.3 * stability, -1.0, 1.0))
