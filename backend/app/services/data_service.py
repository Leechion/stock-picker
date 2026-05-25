import asyncio
from datetime import date, timedelta

import httpx
import pandas as pd
from loguru import logger
from sqlalchemy import delete, insert, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.stock import StockDaily, StockInfo
from app.services.data_providers import provider_manager

MAIN_BOARD_PREFIXES = ("00", "60")
MAX_CONCURRENCY = 20

# Set when the server is shutting down — checked in long-running sync loops
shutdown_event = asyncio.Event()

EASTMONEY_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36"
    ),
    "Referer": "https://quote.eastmoney.com/",
}


async def get_stock_list() -> pd.DataFrame:
    """Fetch stock list using async provider (cancellable HTTP)."""
    return await provider_manager.async_fetch_stock_list()


async def fetch_daily_data(
    code: str,
    start_date: str,
    end_date: str,
) -> pd.DataFrame:
    """Fetch daily data using async provider (cancellable HTTP)."""
    return await provider_manager.async_fetch_daily_data(code, start_date, end_date)


async def _fetch_one_stock(
    code: str,
    name: str,
    industry,
    start_str: str,
    end_str: str,
    semaphore: asyncio.Semaphore,
) -> dict | None:
    """Fetch daily data for a single stock with concurrency control.

    Returns a dict with stock info + daily records, or None if filtered/skipped.
    """
    async with semaphore:
        df = await fetch_daily_data(code, start_str, end_str)
    if df.empty:
        return None

    # Filter: skip stocks with latest close price > 70
    close_col = "close" if "close" in df.columns else None
    if close_col:
        latest_close = pd.to_numeric(df[close_col], errors="coerce").dropna()
        if not latest_close.empty and latest_close.iloc[-1] > 70:
            return None

    col_map = {
        "日期": "trade_date",
        "date": "trade_date",
        "开盘": "open",
        "收盘": "close",
        "最高": "high",
        "最低": "low",
        "成交量": "volume",
        "成交额": "amount",
        "涨跌幅": "change_pct",
    }
    for cn, en in col_map.items():
        if cn in df.columns:
            df.rename(columns={cn: en}, inplace=True)

    if "trade_date" in df.columns:
        df["trade_date"] = pd.to_datetime(df["trade_date"]).dt.date

    if ("change_pct" not in df.columns or df["change_pct"].isna().all()) and "close" in df.columns and len(df) > 1:
        df["change_pct"] = df["close"].pct_change() * 100

    daily_records = []
    for _, data_row in df.iterrows():
        td = data_row.get("trade_date")
        if td is None:
            continue

        def _val(key: str, default=None):
            v = data_row.get(key)
            return default if v is None or (isinstance(v, float) and pd.isna(v)) else v

        daily_records.append(
            {
                "code": code,
                "trade_date": td,
                "open": _val("open", 0.0),
                "close": _val("close", 0.0),
                "high": _val("high", 0.0),
                "low": _val("low", 0.0),
                "volume": _val("volume", 0.0),
                "amount": _val("amount", 0.0),
                "change_pct": _val("change_pct", None),
            }
        )

    return {
        "code": code,
        "name": name,
        "industry": str(industry) if pd.notna(industry) else None,
        "daily_records": daily_records,
    }


async def _load_sync_state(session: AsyncSession) -> dict[str, date]:
    """Load the latest trade_date per stock code from DB."""
    from sqlalchemy import func
    stmt = select(StockDaily.code, func.max(StockDaily.trade_date)).group_by(StockDaily.code)
    result = await session.execute(stmt)
    return {code: latest for code, latest in result.all()}


async def sync_all_stocks(session: AsyncSession, days_back: int = 80, include_history: bool = True) -> int:
    stock_list_df = await get_stock_list()
    if stock_list_df.empty:
        logger.error("Empty stock list, aborting sync")
        return 0

    def _is_main_board(code: str) -> bool:
        return code.startswith(MAIN_BOARD_PREFIXES)

    today = date.today()
    end_str = today.strftime("%Y%m%d")

    latest_dates = await _load_sync_state(session)
    logger.info(f"Loaded sync state for {len(latest_dates)} stocks from DB")

    candidates = []
    skipped = 0
    for _, row in stock_list_df.iterrows():
        code = str(row.get("代码", row.get("code", ""))).strip()
        name = str(row.get("名称", row.get("name", ""))).strip()
        industry = row.get("industry")
        if not code or not name:
            continue
        if not _is_main_board(code):
            continue
        if latest_dates.get(code) == today:
            skipped += 1
            continue
        candidates.append((code, name, industry, latest_dates.get(code)))

    logger.info(f"Filtered to {len(candidates)} stocks to sync ({skipped} already up to date)")

    inserted_codes: set[str] = set()

    # Remove non-mainboard stocks from DB
    all_existing_codes = (await session.execute(select(StockInfo.code))).scalars().all()
    to_remove = [c for c in all_existing_codes if not _is_main_board(c)]
    if to_remove:
        await session.execute(delete(StockDaily).where(StockDaily.code.in_(to_remove)))
        await session.execute(delete(StockInfo).where(StockInfo.code.in_(to_remove)))
        await session.commit()
        logger.info(f"Removed {len(to_remove)} non-mainboard stocks from DB")

    if not include_history:
        for code, name, industry, _ in candidates:
            existing_stock = await session.get(StockInfo, code)
            if existing_stock:
                existing_stock.name = name
                if pd.notna(industry):
                    existing_stock.industry = str(industry)
            else:
                session.add(StockInfo(code=code, name=name, industry=str(industry) if pd.notna(industry) else None))
            inserted_codes.add(code)
        await session.commit()
        logger.info(f"Info-only sync complete: {len(inserted_codes)} stocks")
        return len(inserted_codes)

    # Concurrent fetch daily data (cancellable — all HTTP calls are async)
    semaphore = asyncio.Semaphore(MAX_CONCURRENCY)

    async def _fetch_with_state(code, name, industry, latest):
        if shutdown_event.is_set():
            return None
        if latest:
            fetch_start = (latest + timedelta(days=1)).strftime("%Y%m%d")
        else:
            fetch_start = (today - timedelta(days=days_back)).strftime("%Y%m%d")
        if fetch_start > end_str:
            return None
        return await _fetch_one_stock(code, name, industry, fetch_start, end_str, semaphore)

    tasks = [_fetch_with_state(code, name, ind, lat) for code, name, ind, lat in candidates]
    try:
        results = await asyncio.gather(*tasks, return_exceptions=True)
    except asyncio.CancelledError:
        logger.warning("Stock sync cancelled, cleaning up...")
        # Cancel all pending tasks
        for t in tasks:
            if not t.done():
                t.cancel()
        raise

    synced_records: list[dict] = []
    for i, result in enumerate(results):
        if shutdown_event.is_set():
            logger.warning("Shutdown requested, stopping sync early")
            break
        if isinstance(result, Exception):
            code = candidates[i][0]
            logger.debug(f"Fetch failed for {code}: {result}")
            continue
        if result is None:
            continue

        code = result["code"]
        name = result["name"]
        industry = result["industry"]

        existing_stock = await session.get(StockInfo, code)
        if existing_stock:
            existing_stock.name = name
            if industry:
                existing_stock.industry = industry
        else:
            session.add(StockInfo(code=code, name=name, industry=industry))
        inserted_codes.add(code)

        synced_records.extend(result["daily_records"])

    for i in range(0, len(synced_records), 500):
        await session.execute(insert(StockDaily), synced_records[i : i + 500])

    await session.commit()

    # Update Redis with synced stock codes for today
    try:
        from app.core.redis import get_redis
        redis = await get_redis()
        if inserted_codes:
            await redis.sadd(f"synced:{today}", *inserted_codes)
            await redis.expire(f"synced:{today}", 86400 * 2)
    except Exception:
        pass

    logger.info(
        f"Sync complete: {len(inserted_codes)} stocks, {len(synced_records)} daily records, "
        f"concurrency={MAX_CONCURRENCY}"
    )
    return len(inserted_codes)


async def get_history(
    session: AsyncSession,
    code: str,
    days: int = 250,
) -> pd.DataFrame:
    stmt = select(StockDaily).where(StockDaily.code == code).order_by(StockDaily.trade_date.desc()).limit(days)
    result = await session.execute(stmt)
    rows = result.scalars().all()

    records = [
        {
            "trade_date": r.trade_date,
            "open": r.open,
            "close": r.close,
            "high": r.high,
            "low": r.low,
            "volume": r.volume,
            "amount": r.amount,
            "change_pct": r.change_pct,
        }
        for r in rows
    ]
    df = pd.DataFrame(records)
    if not df.empty:
        df.sort_values("trade_date", inplace=True)
        df.reset_index(drop=True, inplace=True)
    return df


# ======================================================================
# Fundamental data fetching
# ======================================================================

FUNDAMENTAL_CACHE_DAYS = 7

EASTMONEY_DATACENTER_URL = "https://datacenter.eastmoney.com/securities/api/data/v1/get"


async def _fetch_fundamental_async(code: str, client: httpx.AsyncClient) -> dict[str, float | None] | None:
    """Fetch fundamental data directly from Eastmoney datacenter API (async)."""
    result: dict[str, float | None] = {
        "pe_ttm": None, "pb": None, "roe": None,
        "revenue_growth": None, "profit_growth": None, "debt_ratio": None,
    }

    # --- PE / PB ---
    try:
        resp = await client.get(
            EASTMONEY_DATACENTER_URL,
            params={
                "reportName": "RPT_VALUEANALYSIS_DET",
                "columns": "SECURITY_CODE,PE_TTM,PB_MRQ",
                "filter": f'(SECURITY_CODE="{code}")',
                "pageSize": 1,
                "source": "WEB",
                "client": "WEB",
            },
        )
        resp.raise_for_status()
        data = resp.json()
        rows = (data.get("result") or {}).get("data") or []
        if rows:
            result["pe_ttm"] = _safe_float(rows[0].get("PE_TTM"))
            result["pb"] = _safe_float(rows[0].get("PB_MRQ"))
    except Exception:
        pass

    # --- ROE / growth / debt ---
    try:
        resp = await client.get(
            EASTMONEY_DATACENTER_URL,
            params={
                "reportName": "RPT_F10_FINANCE_MAINFINADATA",
                "columns": "SECURITY_CODE,ROEJQ,TOTALOPERATEREVETZ,PARENTNETPROFITTZ,ZCFZL",
                "filter": f'(SECURITY_CODE="{code}")',
                "pageSize": 1,
                "sortColumns": "REPORT_DATE",
                "sortTypes": -1,
                "source": "WEB",
                "client": "WEB",
            },
        )
        resp.raise_for_status()
        data = resp.json()
        rows = (data.get("result") or {}).get("data") or []
        if rows:
            result["roe"] = _safe_float(rows[0].get("ROEJQ"))
            result["revenue_growth"] = _safe_float(rows[0].get("TOTALOPERATEREVETZ"))
            result["profit_growth"] = _safe_float(rows[0].get("PARENTNETPROFITTZ"))
            result["debt_ratio"] = _safe_float(rows[0].get("ZCFZL"))
    except Exception:
        pass

    return result


async def sync_fundamentals(session: AsyncSession, code_prefix: str = "") -> int:
    """Fetch and cache fundamental data for all main-board stocks.

    Uses async HTTP via httpx.AsyncClient for cancellable I/O.
    """
    from datetime import datetime, timedelta
    from app.models.stock import StockFundamental

    if code_prefix:
        stmt = select(StockInfo.code).where(StockInfo.code.startswith(code_prefix))
    else:
        stmt = select(StockInfo.code).where(
            StockInfo.code.startswith("00") | StockInfo.code.startswith("60")
        )
    result = await session.execute(stmt)
    all_codes = list(result.scalars().all())

    cutoff = datetime.now() - timedelta(days=FUNDAMENTAL_CACHE_DAYS)
    existing_stmt = select(StockFundamental)
    existing_result = await session.execute(existing_stmt)
    existing_map: dict[str, object] = {}
    for row in existing_result.scalars().all():
        existing_map[row.code] = row

    codes_to_fetch = []
    for code in all_codes:
        existing = existing_map.get(code)
        if existing and existing.updated_at and existing.updated_at > cutoff:
            if existing.pe_ttm is not None and existing.roe is not None:
                continue
        codes_to_fetch.append(code)

    logger.info(f"Fundamental sync: {len(codes_to_fetch)} stocks to fetch (concurrency={MAX_CONCURRENCY})")

    if not codes_to_fetch:
        return 0

    sem = asyncio.Semaphore(MAX_CONCURRENCY)
    done = 0
    total = len(codes_to_fetch)

    async def _fetch_one(code: str, client: httpx.AsyncClient) -> tuple[str, dict[str, float | None] | None]:
        nonlocal done
        if shutdown_event.is_set():
            return code, None
        async with sem:
            try:
                data = await _fetch_fundamental_async(code, client)
            except Exception as exc:
                logger.debug(f"Fundamental fetch failed for {code}: {exc}")
                return code, None
        done += 1
        if done % 50 == 0:
            logger.info(f"Fundamental sync progress: {done}/{total}")
        if data is None or all(v is None for v in data.values()):
            return code, None
        return code, data

    async with httpx.AsyncClient(timeout=10.0, headers=EASTMONEY_HEADERS) as client:
        tasks = [_fetch_one(code, client) for code in codes_to_fetch]
        try:
            results = await asyncio.gather(*tasks)
        except asyncio.CancelledError:
            logger.warning("Fundamental sync cancelled, cleaning up...")
            for t in tasks:
                if not t.done():
                    t.cancel()
            raise

    synced = 0
    now = datetime.now()
    for code, data in results:
        if data is None:
            continue

        existing = existing_map.get(code)
        if existing:
            for k, v in data.items():
                if v is not None:
                    setattr(existing, k, v)
            existing.updated_at = now
        else:
            session.add(StockFundamental(code=code, **{k: v for k, v in data.items() if v is not None}))
        synced += 1

    await session.commit()
    logger.info(f"Fundamental sync complete: {synced}/{len(codes_to_fetch)} stocks")
    return synced


def _safe_float(val) -> float | None:
    """Convert to float, returning None on failure or NaN."""
    try:
        v = float(val)
        return v if not pd.isna(v) else None
    except (ValueError, TypeError):
        return None


async def sync_industry(session: AsyncSession) -> int:
    """Fetch industry/sector info from Eastmoney datacenter API and update StockInfo records."""
    industry_map: dict[str, str] = {}
    page = 1
    page_size = 500

    while True:
        try:
            resp = httpx.get(
                EASTMONEY_DATACENTER_URL,
                params={
                    "reportName": "RPT_LICO_FN_CPD",
                    "columns": "SECURITY_CODE,BOARD_NAME",
                    "filter": '(ISNEW="1")',
                    "pageSize": page_size,
                    "pageNumber": page,
                    "sortColumns": "SECURITY_CODE",
                    "sortTypes": 1,
                    "source": "WEB",
                    "client": "WEB",
                },
                timeout=30.0,
                headers=EASTMONEY_HEADERS,
            )
            resp.raise_for_status()
            data = resp.json()
            result = data.get("result") or {}
            rows = result.get("data") or []
            for row in rows:
                code = row.get("SECURITY_CODE")
                board = row.get("BOARD_NAME")
                if code and board:
                    industry_map[code] = board

            if len(rows) < page_size:
                break
            page += 1
        except Exception as exc:
            logger.error(f"Failed to fetch industry data (page {page}): {exc}")
            break

    if not industry_map:
        logger.error("No industry data fetched from Eastmoney")
        return 0

    logger.info(f"Fetched industry for {len(industry_map)} stocks from Eastmoney")

    all_stocks = (await session.execute(select(StockInfo))).scalars().all()
    updated = 0
    for stock in all_stocks:
        ind = industry_map.get(stock.code)
        if ind and stock.industry != ind:
            stock.industry = ind
            updated += 1

    await session.commit()

    from app.models.stock import StockRanking
    from sqlalchemy import update as sql_update

    for stock in all_stocks:
        if stock.industry:
            await session.execute(
                sql_update(StockRanking)
                .where(StockRanking.code == stock.code)
                .values(industry=stock.industry)
            )
    await session.commit()

    logger.info(f"Industry sync complete: {updated} stocks updated")
    return updated
