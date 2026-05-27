"""Stock API routes.

Endpoints:
  GET /api/stocks/              - List all stocks (optionally filter by ?code= or ?name=)
  GET /api/stocks/info          - Stock detail info (requires ?code=)
  GET /api/stocks/history       - Historical data (requires ?code=)
  POST /api/stocks/sync         - Trigger data sync
"""

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.cache import cache, cached
from app.models.stock import StockInfo
from app.services.data_service import get_history, sync_all_stocks

router = APIRouter()


def _ok(data, message="ok"):
    return JSONResponse({"code": 0, "message": message, "data": data})


def _err(message, code=400):
    return JSONResponse({"code": code, "message": message, "data": None}, status_code=code)


@router.get("/stocks/")
@cached(ttl=3600, prefix="stock_list")
async def list_stocks(
    code: str | None = Query(None),
    name: str | None = Query(None),
    session: AsyncSession = Depends(get_db),
):
    stmt = select(StockInfo.code, StockInfo.name, StockInfo.industry)
    if code:
        stmt = stmt.where(StockInfo.code == code)
    if name:
        stmt = stmt.where(StockInfo.name.ilike(f"%{name}%"))
    stmt = stmt.order_by(StockInfo.code)
    result = await session.execute(stmt)
    rows = result.all()
    data = [{"code": r.code, "name": r.name, "industry": r.industry} for r in rows]
    return _ok(data)


@router.get("/stocks/info")
@cached(ttl=300, prefix="stock_info")
async def get_stock_info(
    code: str = Query(...),
    session: AsyncSession = Depends(get_db),
):
    stmt = select(StockInfo).where(StockInfo.code == code)
    result = await session.execute(stmt)
    stock = result.scalar_one_or_none()
    if stock is None:
        return _err(f"Stock {code} not found", 404)
    return _ok({"code": stock.code, "name": stock.name, "industry": stock.industry})


@router.get("/stocks/history")
@cached(ttl=300, prefix="stock_history")
async def get_stock_history(
    code: str = Query(...),
    days: int = Query(default=120, ge=1, le=1000),
    session: AsyncSession = Depends(get_db),
):
    df = await get_history(session, code, days)
    records = []
    if not df.empty:
        df = df.copy()
        if "trade_date" in df.columns:
            df["trade_date"] = df["trade_date"].astype(str)
        records = df.to_dict(orient="records")
    return _ok(records)


@router.post("/stocks/sync")
async def trigger_sync(
    days_back: int = Query(default=365, ge=1, le=3650),
    include_history: bool = Query(default=True),
    session: AsyncSession = Depends(get_db),
):
    from app.services.data_service import sync_cancel_event
    sync_cancel_event.clear()
    count = await sync_all_stocks(session, days_back, include_history)
    # Invalidate all stock-related caches
    cache.invalidate("stock_")
    return _ok({"status": "success", "message": f"Synced {count} stocks", "stock_count": count})


@router.post("/stocks/sync-cancel")
async def cancel_sync():
    """Cancel an in-progress stock sync."""
    from app.services.data_service import sync_cancel_event
    sync_cancel_event.set()
    return _ok({"status": "cancelled", "message": "Sync cancellation requested"})


@router.get("/stocks/fundamentals")
@cached(ttl=300, prefix="stock_fundamentals")
async def get_stock_fundamentals(
    code: str = Query(...),
    session: AsyncSession = Depends(get_db),
):
    from app.models.stock import StockFundamental

    stmt = select(StockFundamental).where(StockFundamental.code == code)
    result = await session.execute(stmt)
    row = result.scalar_one_or_none()
    if row is None:
        return _ok(None)
    return _ok({
        "code": row.code,
        "pe_ttm": row.pe_ttm,
        "pb": row.pb,
        "roe": row.roe,
        "revenue_growth": row.revenue_growth,
        "profit_growth": row.profit_growth,
        "debt_ratio": row.debt_ratio,
        "updated_at": str(row.updated_at) if row.updated_at else None,
    })


@router.post("/stocks/sync-industry")
async def trigger_industry_sync(session: AsyncSession = Depends(get_db)):
    from app.services.data_service import sync_industry

    count = await sync_industry(session)
    cache.invalidate("stock_")
    return _ok({"status": "success", "message": f"Updated industry for {count} stocks", "updated_count": count})


@router.get("/stocks/quote")
async def get_realtime_quote(code: str = Query(...)):
    """Get real-time quote via Sina Finance API."""
    import asyncio

    def _fetch_quote():
        import requests as req
        prefix = "sh" if code.startswith(("5", "6", "9")) else "sz"
        url = f"https://hq.sinajs.cn/list={prefix}{code}"
        try:
            r = req.get(url, headers={"Referer": "https://finance.sina.com.cn/"}, timeout=10)
            r.encoding = "gbk"
            text = r.text.strip()
            if not text or '"' not in text:
                return None
            data_str = text.split('"')[1]
            fields = data_str.split(",")
            if len(fields) < 10:
                return None
            # Fields: name, open, pre_close, current, high, low, buy, sell, volume(股), amount
            name = fields[0]
            open_price = float(fields[1]) if fields[1] else None
            pre_close = float(fields[2]) if fields[2] else None
            price = float(fields[3]) if fields[3] else None
            high = float(fields[4]) if fields[4] else None
            low = float(fields[5]) if fields[5] else None
            volume = int(fields[8]) if fields[8] else None
            amount = float(fields[9]) if fields[9] else None
            change_pct = round((price - pre_close) / pre_close * 100, 2) if price and pre_close else None
            return {
                "code": code,
                "name": name,
                "price": price,
                "open": open_price,
                "high": high,
                "low": low,
                "pre_close": pre_close,
                "volume": volume,
                "amount": amount,
                "change_pct": change_pct,
            }
        except Exception:
            return None

    loop = asyncio.get_running_loop()
    quote = await loop.run_in_executor(None, _fetch_quote)
    if quote is None:
        return _err("Failed to fetch real-time quote", 502)
    return _ok(quote)


@router.get("/stocks/intraday")
async def get_intraday_data(
    code: str = Query(...),
    period: int = Query(default=1, ge=1, le=60),
):
    """Get today's intraday minute-level data.

    period=1: Tencent 1-minute data (most granular)
    period>=5: Sina K-line data
    """
    import asyncio
    from datetime import date

    def _fetch_intraday():
        import requests as req
        prefix = "sh" if code.startswith(("5", "6", "9")) else "sz"

        if period == 1:
            # Tencent 1-minute data: "0930 10.70 6616 7079120.00"
            url = f"https://web.ifzq.gtimg.cn/appstock/app/minute/query?code={prefix}{code}"
            try:
                r = req.get(url, timeout=10)
                resp = r.json()
                items = resp.get("data", {}).get(f"{prefix}{code}", {}).get("data", {}).get("data", [])
                today = date.today().strftime("%Y-%m-%d")
                records = []
                for line in items:
                    parts = line.split(" ")
                    if len(parts) < 3:
                        continue
                    t = parts[0]  # "0930"
                    time_str = f"{today} {t[:2]}:{t[2:]}"
                    records.append({
                        "time": time_str,
                        "open": float(parts[1]),
                        "close": float(parts[1]),
                        "high": float(parts[1]),
                        "low": float(parts[1]),
                        "volume": float(parts[2]) if len(parts) > 2 else 0,
                    })
                return records
            except Exception:
                return []
        else:
            # Sina K-line for 5+ minute periods
            url = (
                f"https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/"
                f"CN_MarketData.getKLineData?symbol={prefix}{code}"
                f"&scale={period}&ma=no&datalen=240"
            )
            try:
                r = req.get(url, headers={"Referer": "https://finance.sina.com.cn/"}, timeout=10)
                data = r.json()
                if not data:
                    return []
                today = date.today().strftime("%Y-%m-%d")
                target_day = today
                today_records = [d for d in data if d.get("day", "").startswith(today)]
                if not today_records:
                    target_day = max(d.get("day", "")[:10] for d in data)
                records = []
                for item in data:
                    if not item.get("day", "").startswith(target_day):
                        continue
                    records.append({
                        "time": item["day"],
                        "open": float(item["open"]),
                        "close": float(item["close"]),
                        "high": float(item["high"]),
                        "low": float(item["low"]),
                        "volume": float(item["volume"]),
                    })
                return records
            except Exception:
                return []

    loop = asyncio.get_running_loop()
    records = await loop.run_in_executor(None, _fetch_intraday)
    return _ok(records)


@router.post("/stocks/sync-fundamentals")
async def trigger_fundamental_sync(
    code_prefix: str = Query(default=""),
    session: AsyncSession = Depends(get_db),
):
    from app.services.data_service import sync_fundamentals

    count = await sync_fundamentals(session, code_prefix)
    cache.invalidate("stock_")
    return _ok({"status": "success", "message": f"Synced fundamentals for {count} stocks", "stock_count": count})
