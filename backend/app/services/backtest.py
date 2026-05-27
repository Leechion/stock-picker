"""Backtest engine - simulates historical ranking performance.

For each ranking date in the given range, picks top N stocks and
calculates their forward returns over a holding period.
"""

from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd
from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.stock import StockDaily, StockRanking


async def run_backtest(
    session: AsyncSession,
    start_date: date,
    end_date: date,
    top_n: int = 10,
    hold_days: int = 5,
) -> dict:
    """Run a simple ranking-based backtest.

    For each ranking date with data, picks top N stocks and measures
    their average return after hold_days trading days.

    Parameters
    ----------
    session : AsyncSession
    start_date : date
        Backtest start date.
    end_date : date
        Backtest end date.
    top_n : int
        Number of top stocks to pick each period.
    hold_days : int
        Number of trading days to hold.

    Returns
    -------
    dict
        Backtest results with metrics.
    """
    # Get all ranking dates in range
    stmt = (
        select(StockRanking.rank_date)
        .where(StockRanking.rank_date >= start_date, StockRanking.rank_date <= end_date)
        .distinct()
        .order_by(StockRanking.rank_date)
    )
    result = await session.execute(stmt)
    ranking_dates = [row[0] for row in result.all()]

    if not ranking_dates:
        return {
            "status": "no_data",
            "message": f"No ranking data between {start_date} and {end_date}",
        }

    # Filter out recent dates that don't have enough future trading days.
    # Get the most recent trading dates; the (hold_days+1)-th is the latest
    # date that still has hold_days of future price data available.
    check_stmt = (
        select(StockDaily.trade_date)
        .distinct()
        .order_by(StockDaily.trade_date.desc())
        .limit(hold_days + 1)
    )
    check_result = await session.execute(check_stmt)
    available_dates = [row[0] for row in check_result.all()]

    if len(available_dates) > hold_days:
        latest_valid_date = available_dates[-1]
        before_filter = len(ranking_dates)
        ranking_dates = [d for d in ranking_dates if d <= latest_valid_date]
        logger.info(f"Backtest: filtered {before_filter} → {len(ranking_dates)} ranking dates (cutoff={latest_valid_date})")

    if not ranking_dates:
        return {
            "status": "no_data",
            "message": f"Not enough future data for {hold_days}-day hold period. Try a shorter hold period.",
        }

    period_returns: list[float] = []
    period_details: list[dict] = []

    for rdate in ranking_dates:
        # Get top N stocks for this date
        top_stmt = (
            select(StockRanking)
            .where(StockRanking.rank_date == rdate)
            .order_by(StockRanking.rank_position)
            .limit(top_n)
        )
        top_result = await session.execute(top_stmt)
        top_stocks = top_result.scalars().all()

        if not top_stocks:
            continue

        codes = [s.code for s in top_stocks]

        # Calculate forward returns for each stock
        stock_returns = []
        for code in codes:
            fwd_return = await _calc_forward_return(session, code, rdate, hold_days)
            if fwd_return is not None:
                stock_returns.append(fwd_return)

        if stock_returns:
            avg_return = float(np.mean(stock_returns))
            period_returns.append(avg_return)
            period_details.append({
                "date": str(rdate),
                "top_codes": codes[:5],
                "avg_return": round(avg_return, 4),
                "n_with_data": len(stock_returns),
            })

    if not period_returns:
        return {
            "status": "no_returns",
            "message": "Could not compute forward returns for any period",
        }

    # Compute metrics
    returns = np.array(period_returns)
    win_rate = float(np.mean(returns > 0))
    avg_return = float(np.mean(returns))
    std_return = float(np.std(returns))

    # Sharpe (annualized, assuming ~252 trading days / hold_days periods per year)
    periods_per_year = 252 / hold_days
    sharpe = (avg_return / std_return * np.sqrt(periods_per_year)) if std_return > 0 else 0.0

    # Max drawdown
    cumulative = np.cumprod(1 + returns / 100)
    peak = np.maximum.accumulate(cumulative)
    drawdown = (cumulative - peak) / peak
    max_drawdown = float(np.min(drawdown)) * 100

    # Total return
    total_return = float((cumulative[-1] - 1) * 100)

    # Enrich period details with cumulative return and drawdown
    for i, detail in enumerate(period_details):
        detail["cumulative_return"] = round((cumulative[i] - 1) * 100, 2)
        detail["drawdown"] = round(float(drawdown[i]) * 100, 2)

    return {
        "status": "success",
        "period": {"start": str(start_date), "end": str(end_date)},
        "config": {"top_n": top_n, "hold_days": hold_days},
        "metrics": {
            "total_return_pct": round(total_return, 2),
            "avg_period_return_pct": round(avg_return, 4),
            "win_rate": round(win_rate, 4),
            "sharpe_ratio": round(sharpe, 2),
            "max_drawdown_pct": round(max_drawdown, 2),
            "num_periods": len(period_returns),
        },
        "periods": period_details,
    }


async def _calc_forward_return(
    session: AsyncSession,
    code: str,
    from_date: date,
    hold_days: int,
) -> float | None:
    """Calculate the return from from_date to from_date + hold_days trading days."""
    # Get the close price on from_date
    stmt_today = (
        select(StockDaily.close)
        .where(StockDaily.code == code, StockDaily.trade_date == from_date)
    )
    result_today = await session.execute(stmt_today)
    close_today = result_today.scalar_one_or_none()

    if close_today is None or close_today <= 0:
        return None

    # Get the close price after hold_days
    stmt_future = (
        select(StockDaily.close, StockDaily.trade_date)
        .where(StockDaily.code == code, StockDaily.trade_date > from_date)
        .order_by(StockDaily.trade_date)
        .limit(hold_days)
    )
    result_future = await session.execute(stmt_future)
    future_rows = result_future.all()

    if len(future_rows) < hold_days:
        return None

    close_future = future_rows[-1][0]
    if close_future is None or close_future <= 0:
        return None

    return (close_future / close_today - 1) * 100
