import asyncio
from datetime import date, timedelta

import httpx
import pandas as pd
from loguru import logger
from sqlalchemy import delete, insert, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.stock import StockDaily, StockInfo
from app.services.data_providers import provider_manager

MAIN_BOARD_PREFIXES = ("00", "60")  # 深市主板 + 沪市主板
MAX_CONCURRENCY = 20  # 最大并发请求数

EASTMONEY_STOCK_LIST_URL = "https://82.push2.eastmoney.com/api/qt/clist/get"
EASTMONEY_KLINE_HOSTS = [
    "push2his.eastmoney.com",
    "1.push2his.eastmoney.com",
    "2.push2his.eastmoney.com",
    "7.push2his.eastmoney.com",
    "33.push2his.eastmoney.com",
    "63.push2his.eastmoney.com",
    "72.push2his.eastmoney.com",
]
EASTMONEY_USER_TOKEN = "7eea3edcaed734bea9cbfc24409ed989"
EASTMONEY_LIST_TOKEN = "bd1d9ddb04089700cf9c27f6f7426281"
EASTMONEY_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36"
    ),
    "Referer": "https://quote.eastmoney.com/",
}


def _eastmoney_market_code(code: str) -> int:
    return 1 if code.startswith(("5", "6", "9")) else 0


def _fetch_stock_list_from_eastmoney() -> pd.DataFrame:
    params = {
        "pn": "1",
        "pz": "10000",
        "po": "1",
        "np": "1",
        "ut": EASTMONEY_LIST_TOKEN,
        "fltt": "2",
        "invt": "2",
        "fid": "f12",
        "fs": "m:0 t:6,m:0 t:80,m:1 t:2,m:1 t:23,m:0 t:81 s:2048",
        "fields": "f12,f14,f100",
    }
    response = httpx.get(EASTMONEY_STOCK_LIST_URL, params=params, timeout=20.0, headers=EASTMONEY_HEADERS)
    response.raise_for_status()
    payload = response.json()
    items = payload.get("data", {}).get("diff") or []
    records = [
        {"code": item.get("f12"), "name": item.get("f14"), "industry": item.get("f100")}
        for item in items
        if item.get("f12") and item.get("f14")
    ]
    return pd.DataFrame(records)


def _fetch_daily_data_from_eastmoney(code: str, start_date: str, end_date: str) -> pd.DataFrame:
    params = {
        "fields1": "f1,f2,f3,f4,f5,f6",
        "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61,f116",
        "ut": EASTMONEY_USER_TOKEN,
        "klt": "101",
        "fqt": "1",
        "secid": f"{_eastmoney_market_code(code)}.{code}",
        "beg": start_date,
        "end": end_date,
    }
    last_error: Exception | None = None
    for host in EASTMONEY_KLINE_HOSTS:
        try:
            response = httpx.get(
                f"https://{host}/api/qt/stock/kline/get",
                params=params,
                timeout=20.0,
                headers=EASTMONEY_HEADERS,
            )
            response.raise_for_status()
            break
        except Exception as exc:
            last_error = exc
    else:
        raise RuntimeError(f"all Eastmoney kline hosts failed: {last_error}") from last_error

    payload = response.json()
    klines = payload.get("data", {}).get("klines") or []
    if not klines:
        return pd.DataFrame()

    rows = [line.split(",") for line in klines]
    df = pd.DataFrame(
        rows,
        columns=[
            "trade_date",
            "open",
            "close",
            "high",
            "low",
            "volume",
            "amount",
            "amplitude",
            "change_pct",
            "change_amount",
            "turnover",
        ],
    )
    df["trade_date"] = pd.to_datetime(df["trade_date"], errors="coerce").dt.date
    for column in ["open", "close", "high", "low", "volume", "amount", "change_pct"]:
        df[column] = pd.to_numeric(df[column], errors="coerce")
    return df

async def get_stock_list() -> pd.DataFrame:
    """Fetch stock list using provider manager (AKShare → Eastmoney fallback)."""
    return provider_manager.fetch_stock_list()


async def fetch_daily_data(
    code: str,
    start_date: str,
    end_date: str,
) -> pd.DataFrame:
    """Fetch daily data using provider manager (AKShare → Eastmoney fallback)."""
    return provider_manager.fetch_daily_data(code, start_date, end_date)


async def _fetch_one_stock(
    code: str,
    name: str,
    industry,
    start_str: str,
    end_str: str,
    existing_pairs: set,
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
        td_val = td.date() if isinstance(td, pd.Timestamp) else td
        pair = (code, td_val)
        if pair in existing_pairs:
            continue
        daily_records.append(
            {
                "code": code,
                "trade_date": td,
                "open": data_row.get("open", 0.0),
                "close": data_row.get("close", 0.0),
                "high": data_row.get("high", 0.0),
                "low": data_row.get("low", 0.0),
                "volume": data_row.get("volume", 0.0),
                "amount": data_row.get("amount", 0.0),
                "change_pct": data_row.get("change_pct"),
            }
        )
        existing_pairs.add(pair)

    return {
        "code": code,
        "name": name,
        "industry": str(industry) if pd.notna(industry) else None,
        "daily_records": daily_records,
    }


async def sync_all_stocks(session: AsyncSession, days_back: int = 365, include_history: bool = True) -> int:
    stock_list_df = await get_stock_list()
    if stock_list_df.empty:
        logger.error("Empty stock list, aborting sync")
        return 0

    # Filter: only main board (00xxxx + 60xxxx), drop 30/688/83/43 etc.
    def _is_main_board(code: str) -> bool:
        return code.startswith(MAIN_BOARD_PREFIXES)

    end_date = date.today()
    start_date = end_date - timedelta(days=days_back)
    start_str = start_date.strftime("%Y%m%d")
    end_str = end_date.strftime("%Y%m%d")

    inserted_codes: set[str] = set()
    existing_stmt = select(StockDaily.code, StockDaily.trade_date)
    existing_result = await session.execute(existing_stmt)
    existing_pairs = {(row[0], row[1]) for row in existing_result.all()}

    # Build candidate list first
    candidates = []
    for _, row in stock_list_df.iterrows():
        code = str(row.get("代码", row.get("code", ""))).strip()
        name = str(row.get("名称", row.get("name", ""))).strip()
        industry = row.get("industry")
        if not code or not name:
            continue
        if not _is_main_board(code):
            continue
        candidates.append((code, name, industry))

    logger.info(f"Filtered to {len(candidates)} main-board stocks (prefixes: {MAIN_BOARD_PREFIXES})")

    # Remove non-mainboard stocks from DB
    all_existing_codes = (await session.execute(select(StockInfo.code))).scalars().all()
    to_remove = [c for c in all_existing_codes if not _is_main_board(c)]
    if to_remove:
        await session.execute(delete(StockDaily).where(StockDaily.code.in_(to_remove)))
        await session.execute(delete(StockInfo).where(StockInfo.code.in_(to_remove)))
        await session.commit()
        logger.info(f"Removed {len(to_remove)} non-mainboard stocks from DB")

    if not include_history:
        # Fast path: only sync stock info, no daily data
        for code, name, industry in candidates:
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

    # Concurrent fetch daily data
    semaphore = asyncio.Semaphore(MAX_CONCURRENCY)
    tasks = [
        _fetch_one_stock(code, name, industry, start_str, end_str, existing_pairs, semaphore)
        for code, name, industry in candidates
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    # Process results: insert stock info + daily records
    synced_records: list[dict] = []
    for i, result in enumerate(results):
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

    # Batch insert daily records
    for i in range(0, len(synced_records), 500):
        await session.execute(insert(StockDaily), synced_records[i : i + 500])

    await session.commit()
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
# Fundamental data fetching (real financial data from AKShare)
# ======================================================================

FUNDAMENTAL_CACHE_DAYS = 7  # refresh fundamental data weekly

EASTMONEY_DATACENTER_URL = "https://datacenter.eastmoney.com/securities/api/data/v1/get"


def _fetch_fundamental_sync(code: str) -> dict[str, float | None] | None:
    """Fetch fundamental data directly from Eastmoney datacenter API.

    Replaces broken AKShare functions with direct HTTP calls.
    """
    result: dict[str, float | None] = {
        "pe_ttm": None,
        "pb": None,
        "roe": None,
        "revenue_growth": None,
        "profit_growth": None,
        "debt_ratio": None,
    }

    # --- PE / PB ---
    try:
        resp = httpx.get(
            EASTMONEY_DATACENTER_URL,
            params={
                "reportName": "RPT_VALUEANALYSIS_DET",
                "columns": "SECURITY_CODE,PE_TTM,PB_MRQ",
                "filter": f'(SECURITY_CODE="{code}")',
                "pageSize": 1,
                "source": "WEB",
                "client": "WEB",
            },
            timeout=10.0,
            headers=EASTMONEY_HEADERS,
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
        resp = httpx.get(
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
            timeout=10.0,
            headers=EASTMONEY_HEADERS,
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


async def _fetch_one_fundamental(
    code: str,
    executor,
    progress: dict,
) -> tuple[str, dict[str, float | None] | None]:
    """Fetch fundamental data for one stock using a shared thread pool."""
    loop = asyncio.get_running_loop()
    try:
        data = await loop.run_in_executor(executor, lambda: _fetch_fundamental_sync(code))
        progress["done"] += 1
        if progress["done"] % 50 == 0:
            logger.info(f"Fundamental sync progress: {progress['done']}/{progress['total']}")
        if data is None or all(v is None for v in data.values()):
            return code, None
        return code, data
    except Exception as exc:
        progress["done"] += 1
        logger.debug(f"Fundamental fetch failed for {code}: {exc}")
        return code, None

    return result


async def sync_fundamentals(session: AsyncSession, code_prefix: str = "") -> int:
    """Fetch and cache fundamental data for all main-board stocks.

    Uses a ThreadPoolExecutor for true parallel HTTP requests.
    Only refreshes stocks whose cached data is older than FUNDAMENTAL_CACHE_DAYS.
    Returns the number of stocks synced.
    """
    from concurrent.futures import ThreadPoolExecutor
    from datetime import datetime, timedelta
    from app.models.stock import StockFundamental

    # Build query — filter by prefix if given, otherwise all main board stocks
    if code_prefix:
        stmt = select(StockInfo.code).where(StockInfo.code.startswith(code_prefix))
    else:
        stmt = select(StockInfo.code).where(
            StockInfo.code.startswith("00") | StockInfo.code.startswith("60")
        )
    result = await session.execute(stmt)
    all_codes = list(result.scalars().all())

    # Pre-load existing cached records
    cutoff = datetime.now() - timedelta(days=FUNDAMENTAL_CACHE_DAYS)
    existing_stmt = select(StockFundamental)
    existing_result = await session.execute(existing_stmt)
    existing_map: dict[str, object] = {}
    for row in existing_result.scalars().all():
        existing_map[row.code] = row

    # Filter out recently cached stocks
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

    # Concurrent fetch with explicit thread pool
    progress = {"done": 0, "total": len(codes_to_fetch)}
    executor = ThreadPoolExecutor(max_workers=MAX_CONCURRENCY)
    try:
        tasks = [_fetch_one_fundamental(code, executor, progress) for code in codes_to_fetch]
        results = await asyncio.gather(*tasks)
    finally:
        executor.shutdown(wait=False)

    # Persist results
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


def _find_column(df: "pd.DataFrame", candidates: list[str]) -> str | None:
    """Return the first column name in *df* that matches one of *candidates*."""
    for col in df.columns:
        if col in candidates or any(c in str(col) for c in candidates):
            return col
    return None


def _lookup(series, candidates: list[str]) -> float | None:
    """Return the first value whose index contains any of *candidates*."""
    for idx in series.index:
        for c in candidates:
            if c in str(idx):
                return series[idx]
    return None


def _safe_float(val) -> float | None:
    """Convert to float, returning None on failure or NaN."""
    try:
        v = float(val)
        return v if not pd.isna(v) else None
    except (ValueError, TypeError):
        return None


async def sync_industry(session: AsyncSession) -> int:
    """Fetch industry/sector info from Eastmoney datacenter API and update StockInfo records.

    Returns the number of stocks updated.
    """
    # Fetch all latest industry data from Eastmoney datacenter (paginated)
    industry_map: dict[str, str] = {}
    page = 1
    page_size = 500  # API max per page

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

    # Update StockInfo
    all_stocks = (await session.execute(select(StockInfo))).scalars().all()
    updated = 0
    for stock in all_stocks:
        ind = industry_map.get(stock.code)
        if ind and stock.industry != ind:
            stock.industry = ind
            updated += 1

    await session.commit()

    # Also update industry in latest rankings
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
