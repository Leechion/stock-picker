"""Sina Finance data provider - fast, free, pure HTTP."""

from __future__ import annotations

import pandas as pd
import httpx
from loguru import logger

from app.services.data_providers.base import DataProvider


def _sina_symbol(code: str) -> str:
    return f"sh{code}" if code.startswith(("5", "6", "9")) else f"sz{code}"


class SinaProvider(DataProvider):
    name = "sina"

    def fetch_stock_list(self) -> pd.DataFrame:
        # Sina doesn't have a clean stock list API, return empty to let other providers handle it
        return pd.DataFrame()

    def fetch_daily_data(self, code: str, start_date: str, end_date: str) -> pd.DataFrame:
        symbol = _sina_symbol(code)
        url = "http://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData"
        params = {
            "symbol": symbol,
            "scale": "240",
            "ma": "no",
            "datalen": "500",
        }
        resp = httpx.get(url, params=params, timeout=10.0)
        resp.raise_for_status()

        # Response is JSON array: [{"day":"2025-01-02","open":"10.5",...}, ...]
        data = resp.json()
        if not data:
            return pd.DataFrame()

        df = pd.DataFrame(data)
        df.rename(columns={"day": "trade_date"}, inplace=True)
        df["trade_date"] = pd.to_datetime(df["trade_date"], errors="coerce").dt.date
        for col in ["open", "high", "low", "close", "volume"]:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")

        # Sina doesn't provide amount/change_pct, compute them
        if "close" in df.columns and len(df) > 1:
            df["change_pct"] = df["close"].pct_change() * 100
        df["amount"] = 0.0

        # Filter by date range
        if start_date:
            start = pd.to_datetime(start_date).date()
            df = df[df["trade_date"] >= start]
        if end_date:
            end = pd.to_datetime(end_date).date()
            df = df[df["trade_date"] <= end]

        logger.debug(f"[{self.name}] Fetched {len(df)} records for {code}")
        return df

    async def async_fetch_daily_data(self, code: str, start_date: str, end_date: str) -> pd.DataFrame:
        symbol = _sina_symbol(code)
        url = "http://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData"
        params = {"symbol": symbol, "scale": "240", "ma": "no", "datalen": "500"}
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url, params=params)
            resp.raise_for_status()
            data = resp.json()
            if not data:
                return pd.DataFrame()

            df = pd.DataFrame(data)
            df.rename(columns={"day": "trade_date"}, inplace=True)
            df["trade_date"] = pd.to_datetime(df["trade_date"], errors="coerce").dt.date
            for col in ["open", "high", "low", "close", "volume"]:
                if col in df.columns:
                    df[col] = pd.to_numeric(df[col], errors="coerce")
            if "close" in df.columns and len(df) > 1:
                df["change_pct"] = df["close"].pct_change() * 100
            df["amount"] = 0.0
            if start_date:
                start = pd.to_datetime(start_date).date()
                df = df[df["trade_date"] >= start]
            if end_date:
                end = pd.to_datetime(end_date).date()
                df = df[df["trade_date"] <= end]
            logger.debug(f"[{self.name}] Fetched {len(df)} records for {code}")
            return df
