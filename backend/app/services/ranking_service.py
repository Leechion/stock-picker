"""Ranking service - computes and queries stock rankings.

Uses category-weighted scoring from computed factor values.
"""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
from loguru import logger
from sqlalchemy import and_, func, select
from sqlalchemy import delete as sql_delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.stock import FactorValue, StockRanking, StockInfo
from app.services.factor_config import CATEGORY_WEIGHTS, FACTOR_CONFIG
from app.services.strategy_loader import strategy_loader


# ======================================================================
# Category-weighted scoring helpers
# ======================================================================


def _compute_category_score(
    cat_factors: list[tuple[float, float]],
    category: str,
    category_weight: float,
) -> float:
    """Compute weighted category score.

    Parameters
    ----------
    cat_factors : list[tuple]
        List of (factor_raw_value, factor_weight) tuples.
    category : str
        Category name (technical/fundamental/sentiment).
    category_weight : float
        Category weight (e.g. 0.4 for technical).

    Returns
    -------
    float
        Weighted average in [-100, 100].
    """
    if not cat_factors:
        return 0.0

    total_weight = 0.0
    weighted_sum = 0.0
    for raw_val, f_weight in cat_factors:
        weighted_sum += raw_val * f_weight
        total_weight += f_weight

    if total_weight == 0:
        return 0.0

    avg = weighted_sum / total_weight
    return float(avg * category_weight * 100.0)  # scale from [-1, 1] to [-100, 100]


# ======================================================================
# Ranking computation
# ======================================================================


async def compute_rankings(
    session: AsyncSession,
    trading_date: date,
    strategy_name: str | None = None,
) -> dict:
    """Compute stock rankings using category-weighted scoring.

    1. Load all factor values grouped by stock code.
    2. Compute category scores (= weighted average within category).
    3. Aggregate categories with category weights.
    4. Sort and rank.
    5. Persist rankings (with industry info from StockInfo).

    Parameters
    ----------
    strategy_name : str | None
        Strategy slug to use. If None, uses the currently active strategy.
    """
    # Resolve strategy
    if strategy_name is None:
        strategy_name = strategy_loader.active_name

    # Save & temporarily set active strategy
    orig_active = strategy_loader.active_name
    strategy_loader.set_active(strategy_name)

    try:
        # 1. Load factor values
        stmt = select(FactorValue.code, FactorValue.factor_name, FactorValue.value, FactorValue.factor_type)
        result = await session.execute(stmt)
        rows = result.all()

        if not rows:
            logger.warning("No factor values found, skipping ranking")
            return {"status": "no_factors", "date": str(trading_date), "stocks_computed": 0, "strategy": strategy_name}

        # Group by stock code
        stock_factors: dict[str, list[tuple[str, float, str]]] = {}
        for code, f_name, f_val, f_type in rows:
            stock_factors.setdefault(code, []).append((f_name, float(f_val), f_type.value))

        # 1.5 Cross-sectional Z-score standardization per factor_name
        factor_name_values: dict[str, list[float]] = {}
        for factors in stock_factors.values():
            for f_name, f_val, _f_type in factors:
                factor_name_values.setdefault(f_name, []).append(f_val)

        factor_stats: dict[str, tuple[float, float]] = {}
        for fname, values in factor_name_values.items():
            mean = float(np.mean(values))
            std = float(np.std(values))
            factor_stats[fname] = (mean, std if std > 1e-8 else 0.0)

        stock_factors_std: dict[str, list[tuple[str, float, str]]] = {}
        for code, factors in stock_factors.items():
            std_factors = []
            for f_name, f_val, f_type in factors:
                mean, std = factor_stats[f_name]
                z_val = (f_val - mean) / std if std > 0 else f_val
                std_factors.append((f_name, float(z_val), f_type))
            stock_factors_std[code] = std_factors

        stock_factors = stock_factors_std

        # 2. Compute category scores for each stock
        results: list[dict] = []
        cat_weights = strategy_loader.get_category_weights()
        factor_config = strategy_loader.get_factor_config()

        for code, factors in stock_factors.items():
            cat_technical: list[tuple[float, float]] = []
            cat_fundamental: list[tuple[float, float]] = []
            cat_sentiment: list[tuple[float, float]] = []

            for f_name, f_val, f_type in factors:
                if f_type == "technical":
                    w = factor_config["technical"].get(f_name, {}).get("weight", 1.0)
                    cat_technical.append((f_val, w))
                elif f_type == "fundamental":
                    w = factor_config["fundamental"].get(f_name, {}).get("weight", 1.0)
                    cat_fundamental.append((f_val, w))
                elif f_type == "sentiment":
                    w = factor_config["sentiment"].get(f_name, {}).get("weight", 1.0)
                    cat_sentiment.append((f_val, w))

            tech_score = _compute_category_score(cat_technical, "technical", cat_weights["technical"])
            fund_score = _compute_category_score(cat_fundamental, "fundamental", cat_weights["fundamental"])
            sent_score = _compute_category_score(cat_sentiment, "sentiment", cat_weights["sentiment"])

            # Redistribute weights when a category has no real data (all zeros)
            has_tech = any(v != 0.0 for v, _ in cat_technical)
            has_fund = any(v != 0.0 for v, _ in cat_fundamental)
            has_sent = any(v != 0.0 for v, _ in cat_sentiment)

            active = []
            if has_tech:
                active.append("technical")
            if has_fund:
                active.append("fundamental")
            if has_sent:
                active.append("sentiment")

            if active and len(active) < 3:
                raw_total = sum(cat_weights[c] for c in active)
                eff = {c: cat_weights[c] / raw_total for c in active}
                if not has_fund:
                    fund_score = 0.0
                if has_tech:
                    tech_score = _compute_category_score(cat_technical, "technical", eff.get("technical", 0))
                if has_sent:
                    sent_score = _compute_category_score(cat_sentiment, "sentiment", eff.get("sentiment", 0))

            # Aggregate (range [-100, 100])
            total_raw = tech_score + fund_score + sent_score
            total_score = float(np.clip((total_raw + 100) / 2, 0, 100))

            results.append({
                "code": code,
                "tech_score": round(tech_score, 2),
                "fund_score": round(fund_score, 2),
                "sent_score": round(sent_score, 2),
                "total_score": round(total_score, 2),
            })

        if not results:
            return {"status": "empty", "date": str(trading_date), "stocks_computed": 0, "strategy": strategy_name}

        # 3. Sort by total score descending and assign ranks
        score_df = pd.DataFrame(results)
        score_df = score_df.sort_values("total_score", ascending=False).reset_index(drop=True)
        score_df["rank_position"] = range(1, len(score_df) + 1)

        # 4. Look up industry for each stock
        stmt = select(StockInfo.code, StockInfo.industry)
        info_result = await session.execute(stmt)
        industry_map = {row[0]: row[1] for row in info_result.all()}

        # Attach industry to score_df
        score_df["industry"] = score_df["code"].map(industry_map)

        # 5. Compute industry ranks (rank within each industry group)
        score_df["industry_rank"] = None
        for industry, group in score_df.groupby("industry", dropna=False):
            if pd.isna(industry):
                continue
            sorted_group = group.sort_values("total_score", ascending=False)
            for idx in sorted_group.index:
                score_df.at[idx, "industry_rank"] = int(sorted_group.index.get_loc(idx) + 1)

        # 6. Build ranking records
        rankings: list[dict] = []
        for _, row in score_df.iterrows():
            ind_rank = row.get("industry_rank")
            rankings.append({
                "code": row["code"],
                "rank_date": trading_date,
                "strategy": strategy_name,
                "rank_position": int(row["rank_position"]),
                "total_score": float(row["total_score"]),
                "industry": industry_map.get(row["code"]),
                "industry_rank": int(ind_rank) if ind_rank is not None and not pd.isna(ind_rank) else None,
                "tech_score": float(row["tech_score"]),
                "fund_score": float(row["fund_score"]),
                "sent_score": float(row["sent_score"]),
            })

        # Delete old rankings for this date + strategy
        await session.execute(
            sql_delete(StockRanking).where(
                (StockRanking.rank_date == trading_date) & (StockRanking.strategy == strategy_name)
            )
        )

        if rankings:
            await session.execute(StockRanking.__table__.insert(), rankings)
        await session.commit()

        logger.info(f"Computed rankings for {len(rankings)} stocks on {trading_date} (strategy={strategy_name})")
        return {"status": "success", "date": str(trading_date), "stocks_computed": len(rankings), "strategy": strategy_name}
    finally:
        # Restore original active strategy
        strategy_loader.set_active(orig_active)


async def compute_all_rankings(session: AsyncSession, trading_date: date) -> dict:
    """Compute rankings for ALL available strategies at once.

    Returns a summary dict with per-strategy results.
    """
    strategies = strategy_loader.list_strategies()
    results = {}
    total_stocks = 0

    for s in strategies:
        slug = s["slug"]
        result = await compute_rankings(session, trading_date, strategy_name=slug)
        results[slug] = result
        total_stocks = max(total_stocks, result.get("stocks_computed", 0))

    logger.info(f"Computed rankings for all {len(strategies)} strategies on {trading_date}")
    return {
        "status": "success",
        "date": str(trading_date),
        "stocks_computed": total_stocks,
        "strategies": results,
    }


async def get_ranking_list(
    session: AsyncSession,
    trading_date: date,
    page: int = 1,
    page_size: int = 50,
    strategy: str | None = None,
) -> tuple[list[dict], int]:
    """Get paginated ranking list.

    Returns
    -------
    tuple
        (list[dict], int) of ranking records and total count.
    """
    if strategy is None:
        strategy = strategy_loader.active_name

    base_filter = (StockRanking.rank_date == trading_date) & (StockRanking.strategy == strategy)

    count_stmt = select(func.count(StockRanking.id)).where(base_filter)
    count_result = await session.execute(count_stmt)
    total = count_result.scalar_one_or_none() or 0

    stmt = (
        select(StockRanking)
        .where(base_filter)
        .order_by(StockRanking.rank_position)
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    result = await session.execute(stmt)
    rows = result.scalars().all()

    # Batch-load stock names
    codes = [r.code for r in rows]
    name_stmt = select(StockInfo.code, StockInfo.name).where(StockInfo.code.in_(codes))
    name_result = await session.execute(name_stmt)
    name_map = {row[0]: row[1] for row in name_result.all()}

    records = []
    for r in rows:
        records.append({
            "id": r.id,
            "code": r.code,
            "name": name_map.get(r.code, ""),
            "industry": r.industry,
            "rank": int(r.rank_position),
            "score": r.total_score,
            "tech_score": float(r.tech_score) if hasattr(r, "tech_score") else None,
            "fund_score": float(r.fund_score) if hasattr(r, "fund_score") else None,
            "sent_score": float(r.sent_score) if hasattr(r, "sent_score") else None,
        })

    return records, total


async def get_stock_rank(
    session: AsyncSession,
    code: str,
    trading_date: date,
    strategy: str | None = None,
) -> dict | None:
    """Get ranking for a specific stock.

    Returns
    -------
    dict | None
        Ranking record with name look-up, or None.
    """
    if strategy is None:
        strategy = strategy_loader.active_name

    stmt = select(StockRanking).where(
        and_(
            StockRanking.code == code,
            StockRanking.rank_date == trading_date,
            StockRanking.strategy == strategy,
        )
    )
    result = await session.execute(stmt)
    row = result.scalar_one_or_none()

    if row is None:
        return None

    # Look up stock name
    name_stmt = select(StockInfo.name).where(StockInfo.code == code)
    name_result = await session.execute(name_stmt)
    name = name_result.scalar_one_or_none()

    return {
        "id": row.id,
        "code": code,
        "name": name or "",
        "rank_date": str(row.rank_date),
        "rank": int(row.rank_position),
        "total_score": row.total_score,
        "industry": row.industry,
        "industry_rank": row.industry_rank,
        "tech_score": float(row.tech_score) if hasattr(row, "tech_score") else None,
        "fund_score": float(row.fund_score) if hasattr(row, "fund_score") else None,
        "sent_score": float(row.sent_score) if hasattr(row, "sent_score") else None,
    }


# ======================================================================
# Sector (industry) ranking
# ======================================================================


async def get_sector_rankings(
    session: AsyncSession,
    trading_date: date,
    strategy: str | None = None,
) -> list[dict]:
    """Get sectors ranked by aggregate factor scores.

    Returns a list of sector dicts sorted by avg total_score descending.
    Each dict includes: industry, stock_count, avg scores, top stocks.
    """
    if strategy is None:
        strategy = strategy_loader.active_name

    stmt = select(StockRanking).where(
        (StockRanking.rank_date == trading_date)
        & (StockRanking.strategy == strategy)
        & (StockRanking.industry.isnot(None))
    )
    result = await session.execute(stmt)
    rows = result.scalars().all()

    if not rows:
        return []

    # Group by industry
    sectors: dict[str, list] = {}
    for r in rows:
        sectors.setdefault(r.industry, []).append(r)

    # Batch-load stock names
    all_codes = [r.code for r in rows]
    name_stmt = select(StockInfo.code, StockInfo.name).where(StockInfo.code.in_(all_codes))
    name_result = await session.execute(name_stmt)
    name_map = {row[0]: row[1] for row in name_result.all()}

    result_list = []
    for industry, stocks in sectors.items():
        count = len(stocks)
        avg_total = sum(s.total_score for s in stocks) / count
        avg_tech = sum(float(s.tech_score) for s in stocks) / count
        avg_fund = sum(float(s.fund_score) for s in stocks) / count
        avg_sent = sum(float(s.sent_score) for s in stocks) / count

        # Top 3 stocks in this sector
        sorted_stocks = sorted(stocks, key=lambda s: s.total_score, reverse=True)
        top_stocks = [
            {"code": s.code, "name": name_map.get(s.code, ""), "score": round(s.total_score, 2)}
            for s in sorted_stocks[:3]
        ]

        result_list.append({
            "industry": industry,
            "stock_count": count,
            "avg_score": round(avg_total, 2),
            "tech_score": round(avg_tech, 2),
            "fund_score": round(avg_fund, 2),
            "sent_score": round(avg_sent, 2),
            "top_stocks": top_stocks,
        })

    result_list.sort(key=lambda x: x["avg_score"], reverse=True)

    # Assign ranks
    for i, item in enumerate(result_list):
        item["rank"] = i + 1

    return result_list


async def get_sector_stocks(
    session: AsyncSession,
    industry: str,
    trading_date: date,
    page: int = 1,
    page_size: int = 20,
    strategy: str | None = None,
) -> tuple[list[dict], int]:
    """Get stocks within a specific sector, ranked by score.

    Returns (records, total).
    """
    if strategy is None:
        strategy = strategy_loader.active_name

    base_filter = (
        (StockRanking.rank_date == trading_date)
        & (StockRanking.strategy == strategy)
        & (StockRanking.industry == industry)
    )

    count_stmt = select(func.count(StockRanking.id)).where(base_filter)
    count_result = await session.execute(count_stmt)
    total = count_result.scalar_one_or_none() or 0

    stmt = (
        select(StockRanking)
        .where(base_filter)
        .order_by(StockRanking.total_score.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    result = await session.execute(stmt)
    stocks = result.scalars().all()

    # Batch-load names
    codes = [s.code for s in stocks]
    name_stmt = select(StockInfo.code, StockInfo.name).where(StockInfo.code.in_(codes))
    name_result = await session.execute(name_stmt)
    name_map = {row[0]: row[1] for row in name_result.all()}

    records = []
    for s in stocks:
        records.append({
            "code": s.code,
            "name": name_map.get(s.code, ""),
            "rank": int(s.rank_position),
            "industry_rank": int(s.industry_rank) if s.industry_rank else None,
            "score": round(s.total_score, 2),
            "tech_score": round(float(s.tech_score), 2),
            "fund_score": round(float(s.fund_score), 2),
            "sent_score": round(float(s.sent_score), 2),
        })

    return records, total