"""Factor computation engine - orchestrates all factor calculations.

Computes technical, fundamental (simulated), and sentiment factors
for a single stock's daily price/volume data, then standardizes
them within each category using Z-score across the stock universe.
"""

from __future__ import annotations

import math
from datetime import date
from typing import Any

import numpy as np
import pandas as pd
from loguru import logger
from sqlalchemy import delete as sql_delete, insert, select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.stock import (
    FactorValue,
    FactorType,
    StockInfo,
    StockRanking,
    StockDaily,
)
from app.services.factor_config import (
    CATEGORY_WEIGHTS,
    FACTOR_CONFIG,
    CAPITAL_FLOW_WINDOW,
)
from app.services.strategy_loader import strategy_loader
from app.services.factor_computation import (
    compute_ma,
    compute_ema,
    compute_rsi,
    compute_macd,
    compute_kdj,
    compute_bollinger_bands,
    standardize_series,
    standardize_cross_sectional,
)


# ======================================================================
# Technical factor raw score computation (per stock)
# ======================================================================


def _ma_crossover_score(close: pd.Series) -> float:
    """MA Crossover: MA5 > MA20 > MA60 = 1; MA5 < MA20 < MA60 = -1."""
    ma5 = compute_ma(close.to_frame(), 5)
    ma20 = compute_ma(close.to_frame(), 20)
    ma60 = compute_ma(close.to_frame(), 60)
    last5 = ma5.iloc[-1] if not ma5.empty else 0
    last20 = ma20.iloc[-1] if not ma20.empty else 0
    last60 = ma60.iloc[-1] if not ma60.empty else 0
    if last5 > last20 > last60 and last20 > last60:
        return 1.0
    elif last5 < last20 < last60:
        return -1.0
    return 0.0


def _macd_histogram_direction_score(close: pd.Series) -> float:
    """MACD: histogram trend. Positive histogram increasing = bullish."""
    dif, dea, hist = compute_macd(close.to_frame())
    if len(hist) < 2:
        return 0.0
    last_hist = hist.iloc[-1]
    prev_hist = hist.iloc[-2]
    if last_hist > 0 and last_hist > prev_hist:
        return 1.0
    elif last_hist < 0 and last_hist < prev_hist:
        return -1.0
    if last_hist > 0:
        return 0.5
    return -0.5


def _rsi_score(close: pd.Series) -> float:
    """RSI: below 20 = oversold (bullish, 1), above 80 = overbought (bearish, -1)."""
    rsi_series = compute_rsi(close.to_frame())
    rsi_val = rsi_series.iloc[-1] if not rsi_series.empty and not np.isnan(rsi_series.iloc[-1]) else 50.0
    if rsi_val <= 20:
        return 1.0
    elif rsi_val >= 80:
        return -1.0
    # Linear interpolation in [20, 80], clamped to [-1, 1]
    return float(np.clip((1.0 - (rsi_val - 30) / 40.0) * 2.0, -1.0, 1.0))


def _kdj_score(close: pd.Series, high: pd.Series, low: pd.Series) -> float:
    """KDJ: J < 20 = bullish, J > 80 = bearish."""
    df = pd.DataFrame({"close": close, "high": high, "low": low})
    k, d, j = compute_kdj(df)
    j_val = j.iloc[-1] if not j.empty and not np.isnan(j.iloc[-1]) else 50.0
    return 1.0 - (j_val / 100.0)


def _bollinger_position_score(close: pd.Series, high: pd.Series, low: pd.Series) -> float:
    """Bollinger Position: close position within bands. Near upper = bullish."""
    df = pd.DataFrame({"close": close})
    upper, middle, lower = compute_bollinger_bands(df)
    width = upper.iloc[-1] - lower.iloc[-1] if not upper.empty and not lower.empty else 0
    if width == 0:
        return 0.0
    if pd.isna(lower.iloc[-1]) or pd.isna(upper.iloc[-1]):
        return 0.0
    pos = (close.iloc[-1] - lower.iloc[-1]) / width
    # Map [0, 1] -> [-1, 1], cap at ±0.9
    return np.clip(pos * 2.0 - 1.0, -0.9, 0.9).item()


def _volume_ratio_score(volume: pd.Series) -> float:
    """Volume Ratio: Vol5/Vol20. > 1.5 strong buying, < 0.5 weak selling."""
    vol5 = volume.rolling(5, min_periods=5).mean()
    vol20 = volume.rolling(20, min_periods=20).mean()
    ratio = vol5.iloc[-1] / vol20.iloc[-1] if vol20.iloc[-1] > 0 else 1.0
    if ratio >= 3.0:
        return 1.0
    # Linear mapping: ratio in [0.3, 2.0] → score in [-0.5, 0.8]
    score = (ratio - 0.3) / 1.7 * 1.3 - 0.5
    return float(np.clip(score, -0.5, 0.8))


def _momentum_score(close: pd.Series) -> float:
    """Momentum: weighted 5d + 20d returns with clamping."""
    n = len(close)
    r5 = float((close.iloc[-1] / close.iloc[-6] - 1) * 100) if n >= 6 else 0.0
    r20 = float((close.iloc[-1] / close.iloc[-21] - 1) * 100) if n >= 21 else 0.0
    score = 0.6 * r5 + 0.4 * r20
    # Tanh squashing to (-1, 1)
    return float(np.tanh(score / 20.0))


def _real_capital_flow_score(main_net_ratio: float | None) -> float:
    """Real capital flow score: based on main force net inflow ratio (%).

    Positive ratio = bullish (institution buying), negative = bearish.
    """
    if main_net_ratio is None:
        return 0.0
    # main_net_ratio is in percentage, e.g. 5.2 means 5.2% net inflow
    return float(np.clip(main_net_ratio / 10.0, -1.0, 1.0))


def _chip_concentration_score(concentration: float | None, profit_ratio: float | None) -> float:
    """Chip concentration score.

    Higher concentration = more chips in fewer hands = potential breakout.
    Combined with profit_ratio to avoid chasing high-cost stocks.
    """
    if concentration is None:
        return 0.0
    # concentration: lower value = more concentrated (typical range 5-30)
    # Map: 5 → 1.0, 30 → -0.5
    conc_score = 1.0 - (concentration - 5.0) / 25.0 * 1.5
    conc_score = float(np.clip(conc_score, -0.5, 1.0))

    if profit_ratio is not None:
        # profit_ratio: 0-100%, higher = more profitable holders
        # Moderate profit_ratio (40-70%) is best (not too many trapped, not too much profit-taking pressure)
        prof_score = 1.0 - abs(profit_ratio - 55.0) / 55.0
        prof_score = float(np.clip(prof_score, -0.5, 1.0))
        return 0.6 * conc_score + 0.4 * prof_score

    return conc_score


def _sector_heat_score(heat: float | None) -> float:
    """Sector heat score: maps 0-100 heat to -1 to 1.

    50 = neutral (0.0), 100 = hottest (1.0), 0 = coldest (-1.0).
    """
    if heat is None:
        return 0.0
    return float(np.clip((heat - 50.0) / 50.0, -1.0, 1.0))


def _turnover_score(volume: pd.Series, close: pd.Series) -> float:
    """Turnover Rate Z-score (estimated from volume + price)."""
    turnover = volume * close  # approximate turnover amount
    if len(turnover) < 20:
        return 0.0
    mean_t = turnover.tail(20).mean()
    std_t = turnover.tail(20).std()
    if pd.isna(std_t) or std_t == 0:
        return 0.0
    z = (turnover.iloc[-1] - mean_t) / std_t
    # Map to (-1, 1)
    return float(np.clip(z / 3.0, -0.8, 0.8))


def _capital_flow_score(close: pd.Series, volume: pd.Series, high: pd.Series, low: pd.Series) -> float:
    """Capital Flow: estimated from price direction + volume.
    Large price move + high volume = strong capital flow.
    """
    n = len(close)
    if n < CAPITAL_FLOW_WINDOW:
        return 0.0
    recent_close = close.tail(CAPITAL_FLOW_WINDOW)
    recent_volume = volume.tail(CAPITAL_FLOW_WINDOW)
    recent_high = high.tail(CAPITAL_FLOW_WINDOW)
    recent_low = low.tail(CAPITAL_FLOW_WINDOW)

    # Price direction: positive if recent close > recent open equivalent
    price_change = (recent_close.iloc[-1] - recent_close.iloc[0]) / recent_close.iloc[0] if recent_close.iloc[0] > 0 else 0

    # Volume intensity: ratio of recent avg to prior avg
    if n >= CAPITAL_FLOW_WINDOW * 2:
        prior_vol = volume.iloc[-(CAPITAL_FLOW_WINDOW * 2):-CAPITAL_FLOW_WINDOW].mean()
    else:
        prior_vol = volume.mean()
    recent_vol = recent_volume.mean()
    vol_intensity = recent_vol / prior_vol if prior_vol > 0 else 1.0

    # Composite: direction * volume intensity
    score = price_change * np.sqrt(vol_intensity)
    return float(np.clip(score, -1.0, 1.0))


def _pe_score(pe_ttm: float | None, close: pd.Series) -> float:
    """PE score: lower PE = better (relative to absolute value)."""
    if pe_ttm is None or pe_ttm <= 0:
        return 0.0
    score = -pe_ttm / 50.0  # PE=50 → -1, PE=0 → 0
    return float(np.clip(score, -1.0, 1.0))


def _pb_score(pb: float | None) -> float:
    """PB score: lower PB = better."""
    if pb is None or pb <= 0:
        return 0.0
    score = -pb / 5.0  # PB=5 → -1, PB=0 → 0
    return float(np.clip(score, -1.0, 1.0))


def _roe_score(roe: float | None) -> float:
    """ROE score: higher ROE = better."""
    if roe is None:
        return 0.0
    score = roe / 20.0  # ROE=20% → 1, ROE=-20% → -1
    return float(np.clip(score, -1.0, 1.0))


def _revenue_growth_score_func(growth: float | None) -> float:
    """Revenue growth score: higher growth = better."""
    if growth is None:
        return 0.0
    score = growth / 30.0  # 30% growth → 1, -30% → -1
    return float(np.clip(score, -1.0, 1.0))


def _profit_growth_score_func(growth: float | None) -> float:
    """Profit growth score: higher growth = better."""
    if growth is None:
        return 0.0
    score = growth / 50.0  # 50% growth → 1, -50% → -1
    return float(np.clip(score, -1.0, 1.0))


def _debt_ratio_score_func(debt_ratio: float | None) -> float:
    """Debt ratio score: ~50% is optimal (inverted U)."""
    if debt_ratio is None:
        return 0.0
    dist = abs(debt_ratio - 50.0) / 50.0  # 0 at 50%, 1 at 0/100%
    score = 1.0 - 2.0 * dist
    return float(np.clip(score, -1.0, 1.0))


# ======================================================================
# Factor weights (from config)
# ======================================================================

TECHNICAL_FACTORS = {
    "ma_crossover": FACTOR_CONFIG["technical"]["ma_crossover"]["weight"],
    "macd": FACTOR_CONFIG["technical"]["macd"]["weight"],
    "rsi": FACTOR_CONFIG["technical"]["rsi"]["weight"],
    "kdj": FACTOR_CONFIG["technical"]["kdj"]["weight"],
    "bollinger": FACTOR_CONFIG["technical"]["bollinger"]["weight"],
    "volume_ratio": FACTOR_CONFIG["technical"]["volume_ratio"]["weight"],
}

FUNDAMENTAL_FACTORS = {
    "pe_score": FACTOR_CONFIG["fundamental"]["pe_score"]["weight"],
    "pb_score": FACTOR_CONFIG["fundamental"]["pb_score"]["weight"],
    "roe_score": FACTOR_CONFIG["fundamental"]["roe_score"]["weight"],
    "revenue_growth_score": FACTOR_CONFIG["fundamental"]["revenue_growth_score"]["weight"],
    "profit_growth_score": FACTOR_CONFIG["fundamental"]["profit_growth_score"]["weight"],
    "debt_ratio_score": FACTOR_CONFIG["fundamental"]["debt_ratio_score"]["weight"],
}

SENTIMENT_FACTORS = {
    "turnover_score": FACTOR_CONFIG["sentiment"]["turnover_score"]["weight"],
    "capital_flow_score": FACTOR_CONFIG["sentiment"]["capital_flow_score"]["weight"],
    "real_capital_flow_score": FACTOR_CONFIG["sentiment"]["real_capital_flow_score"]["weight"],
    "chip_concentration_score": FACTOR_CONFIG["sentiment"]["chip_concentration_score"]["weight"],
    "sector_heat_score": FACTOR_CONFIG["sentiment"]["sector_heat_score"]["weight"],
    "momentum_5d_score": FACTOR_CONFIG["sentiment"]["momentum_5d_score"]["weight"],
    "momentum_20d_score": FACTOR_CONFIG["sentiment"]["momentum_20d_score"]["weight"],
}

# ======================================================================
# Compute factors for a single stock
# ======================================================================


def compute_factors_for_stock(
    df: pd.DataFrame,
    code: str,
    fundamentals: dict[str, float | None] | None = None,
    flow_data: dict[str, float | None] | None = None,
    sector_heat: float | None = None,
) -> list[dict[str, Any]]:
    """Compute all raw factor values for a single stock.

    Parameters
    ----------
    df : pd.DataFrame
        Daily OHLCV data with columns: close, high, low, volume (sorted by date).
    code : str
        Stock code string.
    fundamentals : dict | None
        ``{pe_ttm, pb, roe, revenue_growth, profit_growth, debt_ratio}`` from
        StockFundamental. Falls back to hash-based simulation when absent.
    flow_data : dict | None
        ``{main_net_ratio, chip_concentration, profit_ratio}`` from Eastmoney.
    sector_heat : float | None
        Sector heat score (0-100) for this stock's industry.

    Returns
    -------
    list[dict]
        List of ``{factor_name, factor_type, value}`` dicts.
    """
    if df.empty or "close" not in df.columns:
        logger.warning(f"No usable data for {code}")
        return []

    close = df["close"]
    high = df.get("high", close)
    low = df.get("low", close)
    volume = df.get("volume", pd.Series([0.0] * len(df)))

    raw_factors: list[dict[str, Any]] = []

    # Technical factors
    raw_factors.append({
        "factor_name": "ma_crossover",
        "factor_type": FactorType.TECHNICAL,
        "value": _ma_crossover_score(close),
    })
    raw_factors.append({
        "factor_name": "macd",
        "factor_type": FactorType.TECHNICAL,
        "value": _macd_histogram_direction_score(close),
    })
    raw_factors.append({
        "factor_name": "rsi",
        "factor_type": FactorType.TECHNICAL,
        "value": _rsi_score(close),
    })
    raw_factors.append({
        "factor_name": "kdj",
        "factor_type": FactorType.TECHNICAL,
        "value": _kdj_score(close, high, low),
    })
    raw_factors.append({
        "factor_name": "bollinger",
        "factor_type": FactorType.TECHNICAL,
        "value": _bollinger_position_score(close, high, low),
    })
    raw_factors.append({
        "factor_name": "volume_ratio",
        "factor_type": FactorType.TECHNICAL,
        "value": _volume_ratio_score(volume),
    })

    # Fundamental factors — use real data when available, fall back to simulation
    fd = fundamentals or {}
    raw_factors.append({
        "factor_name": "pe_score",
        "factor_type": FactorType.FUNDAMENTAL,
        "value": _pe_score(fd.get("pe_ttm"), close),
    })
    raw_factors.append({
        "factor_name": "pb_score",
        "factor_type": FactorType.FUNDAMENTAL,
        "value": _pb_score(fd.get("pb")),
    })
    raw_factors.append({
        "factor_name": "roe_score",
        "factor_type": FactorType.FUNDAMENTAL,
        "value": _roe_score(fd.get("roe")),
    })
    raw_factors.append({
        "factor_name": "revenue_growth_score",
        "factor_type": FactorType.FUNDAMENTAL,
        "value": _revenue_growth_score_func(fd.get("revenue_growth")),
    })
    raw_factors.append({
        "factor_name": "profit_growth_score",
        "factor_type": FactorType.FUNDAMENTAL,
        "value": _profit_growth_score_func(fd.get("profit_growth")),
    })
    raw_factors.append({
        "factor_name": "debt_ratio_score",
        "factor_type": FactorType.FUNDAMENTAL,
        "value": _debt_ratio_score_func(fd.get("debt_ratio")),
    })

    # Sentiment factors
    raw_factors.append({
        "factor_name": "turnover_score",
        "factor_type": FactorType.SENTIMENT,
        "value": _turnover_score(volume, close),
    })
    raw_factors.append({
        "factor_name": "capital_flow_score",
        "factor_type": FactorType.SENTIMENT,
        "value": _capital_flow_score(close, volume, high, low),
    })

    # Real capital flow (from Eastmoney money flow data)
    flow = flow_data or {}
    raw_factors.append({
        "factor_name": "real_capital_flow_score",
        "factor_type": FactorType.SENTIMENT,
        "value": _real_capital_flow_score(flow.get("main_net_ratio")),
    })
    raw_factors.append({
        "factor_name": "chip_concentration_score",
        "factor_type": FactorType.SENTIMENT,
        "value": _chip_concentration_score(flow.get("chip_concentration"), flow.get("profit_ratio")),
    })

    # Sector heat score (how hot is this stock's industry)
    raw_factors.append({
        "factor_name": "sector_heat_score",
        "factor_type": FactorType.SENTIMENT,
        "value": _sector_heat_score(sector_heat),
    })

    # Momentum split into 5d and 20d
    r5 = float((close.iloc[-1] / close.iloc[-6] - 1) * 100) if len(close) >= 6 else 0.0
    r20 = float((close.iloc[-1] / close.iloc[-21] - 1) * 100) if len(close) >= 21 else 0.0
    raw_factors.append({
        "factor_name": "momentum_5d_score",
        "factor_type": FactorType.SENTIMENT,
        "value": float(np.tanh(r5 / 30.0)),
    })
    raw_factors.append({
        "factor_name": "momentum_20d_score",
        "factor_type": FactorType.SENTIMENT,
        "value": float(np.tanh(r20 / 20.0)),
    })

    return raw_factors


# ======================================================================
# Standardisation + aggregation (per cross-section)
# ======================================================================


def standardize_factors_cross_sectional(
    stock_factors: dict[str, list[dict[str, Any]]],
) -> dict[str, list[dict[str, Any]]]:
    """Z-score standardize factor values across all stocks per factor name.

    For each factor_name, computes the cross-sectional mean and standard
    deviation across all stocks, then replaces each stock's raw score with
    its Z-score.  Factors whose std == 0 are left unchanged (all identical).

    Parameters
    ----------
    stock_factors : dict
        ``{code: [{factor_name, factor_type, value}, ...], ...}``.

    Returns
    -------
    dict
        Same structure with ``value`` replaced by Z-score.
    """
    if not stock_factors:
        return stock_factors

    # Collect all raw values per factor_name
    factor_values: dict[str, list[float]] = {}
    for factors in stock_factors.values():
        for f in factors:
            factor_values.setdefault(f["factor_name"], []).append(f["value"])

    # Compute mean and std per factor
    factor_stats: dict[str, tuple[float, float]] = {}
    for fname, values in factor_values.items():
        mean = float(np.mean(values))
        std = float(np.std(values))
        factor_stats[fname] = (mean, std if std > 1e-8 else 0.0)

    # Apply Z-score per stock, per factor
    result: dict[str, list[dict[str, Any]]] = {}
    for code, factors in stock_factors.items():
        std_factors: list[dict[str, Any]] = []
        for f in factors:
            mean, std = factor_stats[f["factor_name"]]
            z = (f["value"] - mean) / std if std > 0 else 0.0
            std_factors.append({**f, "value": float(z)})
        result[code] = std_factors

    return result


def compute_category_score(
    factor_values: list[dict[str, Any]],
    category: str,
    category_weight: float,
    factor_config: dict | None = None,
) -> float:
    """Compute weighted category score.

    Parameters
    ----------
    factor_values : list[dict]
        All factor rows for one stock.
    category : str
        Category name (technical/fundamental/sentiment).
    category_weight : float
        Category weight (e.g. 0.4 for technical).
    factor_config : dict | None
        Override factor config (from strategy). Falls back to FACTOR_CONFIG.

    Returns
    -------
    float
        Category-weighted score in [-100, 100].
    """
    cat_factors = [f for f in factor_values if f["factor_type"].value == category]
    if not cat_factors:
        return 0.0

    cfg = factor_config or FACTOR_CONFIG
    cat_cfg = cfg.get(category, {})

    # Weighted average of factor scores
    total_weight = 0.0
    weighted_sum = 0.0
    for f in cat_factors:
        weight_key = f["factor_name"]
        weight = cat_cfg.get(weight_key, {}).get("weight", 1.0)
        weighted_sum += f["value"] * weight
        total_weight += weight

    if total_weight == 0:
        return 0.0

    cat_raw = weighted_sum / total_weight
    return float(cat_raw * category_weight * 100.0)


def compute_total_score(factor_values: list[dict[str, Any]]) -> float:
    """Compute total weighted score from all factors.

    Uses active strategy weights from strategy_loader.
    When a category has no real data (all factors are zero), its weight
    is redistributed proportionally to the remaining categories.

    Returns
    -------
    float
        Total score in 0-100 range.
    """
    cat_weights = strategy_loader.get_category_weights()
    factor_config = strategy_loader.get_factor_config()

    # Check which categories have real (non-zero) data
    has_data: dict[str, bool] = {}
    for cat in ("technical", "fundamental", "sentiment"):
        cat_vals = [f["value"] for f in factor_values if f["factor_type"].value == cat]
        has_data[cat] = any(v != 0.0 for v in cat_vals)

    # Compute effective weights — redistribute missing categories
    active_cats = [c for c in ("technical", "fundamental", "sentiment") if has_data[c]]
    if not active_cats:
        return 50.0  # no data at all → neutral

    raw_total = sum(cat_weights[c] for c in active_cats)
    effective_weights = {c: cat_weights[c] / raw_total for c in active_cats}

    tech_w = effective_weights.get("technical", 0.0)
    fund_w = effective_weights.get("fundamental", 0.0)
    sent_w = effective_weights.get("sentiment", 0.0)

    tech_score = compute_category_score(factor_values, "technical", tech_w, factor_config)
    fund_score = compute_category_score(factor_values, "fundamental", fund_w, factor_config)
    sent_score = compute_category_score(factor_values, "sentiment", sent_w, factor_config)

    # Map from [-100, 100] to [0, 100]
    total_raw = tech_score + fund_score + sent_score
    total_score = (total_raw + 100.0) / 2.0
    return float(np.clip(total_score, 0.0, 100.0))


# ======================================================================
# Persistence: save factors to DB
# ======================================================================


async def compute_all_factors(
    session: AsyncSession,
    code: str,
    df: pd.DataFrame,
    sector_heat_map: dict[str, float] | None = None,
) -> list[dict[str, Any]]:
    """Compute raw factors, save to DB, return results.

    Parameters
    ----------
    session : AsyncSession
        Async database session.
    code : str
        Stock code.
    df : pd.DataFrame
        Daily data with OHLCV columns.
    sector_heat_map : dict | None
        Pre-fetched {industry_name: heat_score} mapping.

    Returns
    -------
    list[dict]
        Factor results with ``value`` = raw score, plus ``total_score``.
    """
    from app.models.stock import StockFundamental

    # Load cached fundamental data if available
    fund_row = await session.get(StockFundamental, code)
    fundamentals: dict[str, float | None] | None = None
    if fund_row is not None:
        fundamentals = {
            "pe_ttm": fund_row.pe_ttm,
            "pb": fund_row.pb,
            "roe": fund_row.roe,
            "revenue_growth": fund_row.revenue_growth,
            "profit_growth": fund_row.profit_growth,
            "debt_ratio": fund_row.debt_ratio,
        }

    # Fetch real capital flow data (cached per run, fast Eastmoney API)
    from app.services.capital_flow import fetch_flow_and_chip
    import asyncio
    loop = asyncio.get_running_loop()
    flow_data = await loop.run_in_executor(None, lambda: fetch_flow_and_chip(code))

    # Get sector heat for this stock's industry
    sector_heat: float | None = None
    if sector_heat_map:
        info_row = await session.get(StockInfo, code)
        if info_row and info_row.industry:
            sector_heat = sector_heat_map.get(info_row.industry)

    raw_factors = compute_factors_for_stock(df, code, fundamentals, flow_data, sector_heat)
    if not raw_factors:
        logger.warning(f"No factors computed for {code}")
        return []

    # Delete existing factors for this stock
    await session.execute(sql_delete(FactorValue).where(FactorValue.code == code))

    now = pd.Timestamp.now()
    records = []
    for f in raw_factors:
        records.append({
            "code": code,
            "factor_name": f["factor_name"],
            "factor_type": f["factor_type"],
            "value": f["value"],
            "computed_at": now,
        })

    await session.execute(insert(FactorValue), records)
    await session.commit()

    logger.info(f"Computed {len(records)} raw factors for {code}")
    return raw_factors


async def compute_factors_for_all_stocks(session: AsyncSession) -> int:
    """Fetch all stocks from DB, compute factors for each.

    Excludes ST stocks and stocks with price > 100.

    Returns
    -------
    int
        Number of stocks for which factors were computed.
    """
    from app.services.ranking_service import get_eligible_codes
    codes = sorted(await get_eligible_codes(session))
    logger.info(f"Eligible stocks for factor computation: {len(codes)} (excluded ST & price>100)")
    if not codes:
        logger.warning("No stocks in DB, cannot compute factors")
        return 0

    # We need daily data for each stock - fetch from DB
    from app.services.data_service import get_history

    total = 0
    for i, code in enumerate(codes):
        if (i + 1) % 50 == 0:
            await session.commit()
            logger.info(f"Factor computation progress: {i + 1}/{len(codes)} stocks")
        df = await get_history(session, code, days=80)
        if not df.empty:
            await compute_all_factors(session, code, df)
            total += 1
        else:
            logger.debug(f"Insufficient data for {code}, skipping")

    # Delete stale rankings (will be recomputed later)
    await session.execute(sql_delete(StockRanking))
    await session.commit()

    logger.info(f"Factor computation complete: {total}/{len(codes)} stocks")
    return total
