"""AKShare data provider."""

from __future__ import annotations

import threading

import pandas as pd
from loguru import logger

from app.services.data_providers.base import DataProvider

# AKShare uses mini_racer (V8) internally which is not thread-safe.
# Serialize all AKShare calls with a global lock.
_akshare_lock = threading.Lock()


class AKShareProvider(DataProvider):
    name = "akshare"

    def _market_symbol(self, code: str) -> str:
        return f"sh{code}" if code.startswith(("5", "6", "9")) else f"sz{code}"

    def fetch_stock_list(self) -> pd.DataFrame:
        import akshare as ak

        with _akshare_lock:
            if hasattr(ak, "stock_info_a_code_name_df"):
                result = ak.stock_info_a_code_name_df()
            else:
                result = ak.stock_info_a_code_name()
        logger.info(f"[{self.name}] Fetched {len(result)} stock codes")
        return result

    def fetch_daily_data(self, code: str, start_date: str, end_date: str) -> pd.DataFrame:
        import akshare as ak

        with _akshare_lock:
            df = ak.stock_zh_a_daily(
                symbol=self._market_symbol(code),
                start_date=start_date,
                end_date=end_date,
                adjust="qfq",
            )
        if df is not None and not df.empty:
            # Normalize column names
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

            for col in ["open", "close", "high", "low", "volume", "amount", "change_pct"]:
                if col in df.columns:
                    df[col] = pd.to_numeric(df[col], errors="coerce")

            if "change_pct" not in df.columns or df["change_pct"].isna().all():
                if "close" in df.columns and len(df) > 1:
                    df["change_pct"] = df["close"].pct_change() * 100

            logger.debug(f"[{self.name}] Fetched {len(df)} records for {code}")
            return df

        logger.warning(f"[{self.name}] No data for {code}")
        return pd.DataFrame()
