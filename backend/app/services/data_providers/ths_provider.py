"""THS (10jqka/Tonghuashun) data provider - fast, free, pure HTTP."""

from __future__ import annotations

import json
import re

import pandas as pd
import httpx
from loguru import logger

from app.services.data_providers.base import DataProvider


def _ths_symbol(code: str) -> str:
    return f"hs_{code}"


class THSProvider(DataProvider):
    name = "ths"

    def fetch_stock_list(self) -> pd.DataFrame:
        return pd.DataFrame()

    def fetch_daily_data(self, code: str, start_date: str, end_date: str) -> pd.DataFrame:
        symbol = _ths_symbol(code)
        url = f"http://d.10jqka.com.cn/v4/line/{symbol}/01/last500.js"
        resp = httpx.get(url, timeout=10.0, headers={
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
            "Referer": "http://q.10jqka.com.cn/",
        })
        resp.raise_for_status()

        # Parse JSONP: quotebridge_xxx({...})
        match = re.search(r"\((\{.*\})\)", resp.text)
        if not match:
            return pd.DataFrame()

        data = json.loads(match.group(1))
        raw = data.get("data", "")
        if not raw:
            return pd.DataFrame()

        # Format: date,open,high,low,close,volume,amount,turnover,...;date,...
        rows = []
        for record in raw.split(";"):
            fields = record.split(",")
            if len(fields) < 7:
                continue
            rows.append({
                "trade_date": fields[0],
                "open": fields[1],
                "high": fields[2],
                "low": fields[3],
                "close": fields[4],
                "volume": fields[5],
                "amount": fields[6],
            })

        if not rows:
            return pd.DataFrame()

        df = pd.DataFrame(rows)
        df["trade_date"] = pd.to_datetime(df["trade_date"], errors="coerce").dt.date
        for col in ["open", "high", "low", "close", "volume", "amount"]:
            df[col] = pd.to_numeric(df[col], errors="coerce")

        if "close" in df.columns and len(df) > 1:
            df["change_pct"] = df["close"].pct_change() * 100

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
        symbol = _ths_symbol(code)
        url = f"http://d.10jqka.com.cn/v4/line/{symbol}/01/last500.js"
        async with httpx.AsyncClient(timeout=10.0, headers={
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
            "Referer": "http://q.10jqka.com.cn/",
        }) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            match = re.search(r"\((\{.*\})\)", resp.text)
            if not match:
                return pd.DataFrame()
            data = json.loads(match.group(1))
            raw = data.get("data", "")
            if not raw:
                return pd.DataFrame()

            rows = []
            for record in raw.split(";"):
                fields = record.split(",")
                if len(fields) < 7:
                    continue
                rows.append({
                    "trade_date": fields[0], "open": fields[1], "high": fields[2],
                    "low": fields[3], "close": fields[4], "volume": fields[5], "amount": fields[6],
                })
            if not rows:
                return pd.DataFrame()

            df = pd.DataFrame(rows)
            df["trade_date"] = pd.to_datetime(df["trade_date"], errors="coerce").dt.date
            for col in ["open", "high", "low", "close", "volume", "amount"]:
                df[col] = pd.to_numeric(df[col], errors="coerce")
            if "close" in df.columns and len(df) > 1:
                df["change_pct"] = df["close"].pct_change() * 100
            if start_date:
                start = pd.to_datetime(start_date).date()
                df = df[df["trade_date"] >= start]
            if end_date:
                end = pd.to_datetime(end_date).date()
                df = df[df["trade_date"] <= end]
            logger.debug(f"[{self.name}] Fetched {len(df)} records for {code}")
            return df
