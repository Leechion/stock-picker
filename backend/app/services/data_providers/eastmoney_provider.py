"""Eastmoney data provider - free, no token required."""

from __future__ import annotations

import pandas as pd
import httpx
from loguru import logger

from app.services.data_providers.base import DataProvider

STOCK_LIST_URL = "https://82.push2.eastmoney.com/api/qt/clist/get"
KLINE_HOSTS = [
    "push2his.eastmoney.com",
    "1.push2his.eastmoney.com",
    "2.push2his.eastmoney.com",
    "7.push2his.eastmoney.com",
    "33.push2his.eastmoney.com",
    "63.push2his.eastmoney.com",
    "72.push2his.eastmoney.com",
]
USER_TOKEN = "7eea3edcaed734bea9cbfc24409ed989"
LIST_TOKEN = "bd1d9ddb04089700cf9c27f6f7426281"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36"
    ),
    "Referer": "https://quote.eastmoney.com/",
}


def _market_code(code: str) -> int:
    return 1 if code.startswith(("5", "6", "9")) else 0


class EastmoneyProvider(DataProvider):
    name = "eastmoney"

    def __init__(self) -> None:
        self._reachable: bool | None = None  # None = unknown, True/False = cached

    def _check_reachable(self) -> bool:
        """Quick probe to check if Eastmoney is accessible."""
        if self._reachable is not None:
            return self._reachable
        try:
            httpx.get(
                f"https://{KLINE_HOSTS[0]}/api/qt/stock/kline/get",
                params={"secid": "1.000001", "beg": "20250101", "end": "20250102",
                        "fields1": "f1,f2,f3", "fields2": "f51,f52", "klt": "101", "fqt": "1",
                        "ut": USER_TOKEN},
                timeout=5.0,
                headers=HEADERS,
            )
            self._reachable = True
        except Exception:
            self._reachable = False
            logger.warning("[eastmoney] Unreachable, skipping for this session")
        return self._reachable

    def fetch_stock_list(self) -> pd.DataFrame:
        params = {
            "pn": "1",
            "pz": "10000",
            "po": "1",
            "np": "1",
            "ut": LIST_TOKEN,
            "fltt": "2",
            "invt": "2",
            "fid": "f12",
            "fs": "m:0 t:6,m:0 t:80,m:1 t:2,m:1 t:23,m:0 t:81 s:2048",
            "fields": "f12,f14,f100",
        }
        resp = httpx.get(STOCK_LIST_URL, params=params, timeout=20.0, headers=HEADERS)
        resp.raise_for_status()
        payload = resp.json()
        items = payload.get("data", {}).get("diff") or []
        records = [
            {"code": item.get("f12"), "name": item.get("f14"), "industry": item.get("f100")}
            for item in items
            if item.get("f12") and item.get("f14")
        ]
        df = pd.DataFrame(records)
        logger.info(f"[{self.name}] Fetched {len(df)} stock codes")
        return df

    def fetch_daily_data(self, code: str, start_date: str, end_date: str) -> pd.DataFrame:
        params = {
            "fields1": "f1,f2,f3,f4,f5,f6",
            "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61,f116",
            "ut": USER_TOKEN,
            "klt": "101",
            "fqt": "1",
            "secid": f"{_market_code(code)}.{code}",
            "beg": start_date,
            "end": end_date,
        }
        last_error: Exception | None = None
        for host in KLINE_HOSTS:
            try:
                resp = httpx.get(
                    f"https://{host}/api/qt/stock/kline/get",
                    params=params,
                    timeout=20.0,
                    headers=HEADERS,
                )
                resp.raise_for_status()
                break
            except Exception as exc:
                last_error = exc
        else:
            logger.error(f"[{self.name}] All kline hosts failed for {code}: {last_error}")
            return pd.DataFrame()

        payload = resp.json()
        klines = payload.get("data", {}).get("klines") or []
        if not klines:
            return pd.DataFrame()

        rows = [line.split(",") for line in klines]
        df = pd.DataFrame(
            rows,
            columns=[
                "trade_date", "open", "close", "high", "low",
                "volume", "amount", "amplitude", "change_pct",
                "change_amount", "turnover",
            ],
        )
        df["trade_date"] = pd.to_datetime(df["trade_date"], errors="coerce").dt.date
        for col in ["open", "close", "high", "low", "volume", "amount", "change_pct"]:
            df[col] = pd.to_numeric(df[col], errors="coerce")
        logger.debug(f"[{self.name}] Fetched {len(df)} records for {code}")
        return df

    async def async_fetch_stock_list(self) -> pd.DataFrame:
        async with httpx.AsyncClient(timeout=20.0, headers=HEADERS) as client:
            params = {
                "pn": "1", "pz": "10000", "po": "1", "np": "1",
                "ut": LIST_TOKEN, "fltt": "2", "invt": "2", "fid": "f12",
                "fs": "m:0 t:6,m:0 t:80,m:1 t:2,m:1 t:23,m:0 t:81 s:2048",
                "fields": "f12,f14,f100",
            }
            resp = await client.get(STOCK_LIST_URL, params=params)
            resp.raise_for_status()
            payload = resp.json()
            items = payload.get("data", {}).get("diff") or []
            records = [
                {"code": item.get("f12"), "name": item.get("f14"), "industry": item.get("f100")}
                for item in items if item.get("f12") and item.get("f14")
            ]
            df = pd.DataFrame(records)
            logger.info(f"[{self.name}] Fetched {len(df)} stock codes")
            return df

    async def async_fetch_daily_data(self, code: str, start_date: str, end_date: str) -> pd.DataFrame:
        params = {
            "fields1": "f1,f2,f3,f4,f5,f6",
            "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61,f116",
            "ut": USER_TOKEN, "klt": "101", "fqt": "1",
            "secid": f"{_market_code(code)}.{code}",
            "beg": start_date, "end": end_date,
        }
        async with httpx.AsyncClient(timeout=20.0, headers=HEADERS) as client:
            last_error: Exception | None = None
            for host in KLINE_HOSTS:
                try:
                    resp = await client.get(f"https://{host}/api/qt/stock/kline/get", params=params)
                    resp.raise_for_status()
                    break
                except Exception as exc:
                    last_error = exc
            else:
                logger.error(f"[{self.name}] All kline hosts failed for {code}: {last_error}")
                return pd.DataFrame()

            payload = resp.json()
            klines = payload.get("data", {}).get("klines") or []
            if not klines:
                return pd.DataFrame()

            rows = [line.split(",") for line in klines]
            df = pd.DataFrame(
                rows,
                columns=[
                    "trade_date", "open", "close", "high", "low",
                    "volume", "amount", "amplitude", "change_pct",
                    "change_amount", "turnover",
                ],
            )
            df["trade_date"] = pd.to_datetime(df["trade_date"], errors="coerce").dt.date
            for col in ["open", "close", "high", "low", "volume", "amount", "change_pct"]:
                df[col] = pd.to_numeric(df[col], errors="coerce")
            logger.debug(f"[{self.name}] Fetched {len(df)} records for {code}")
            return df
