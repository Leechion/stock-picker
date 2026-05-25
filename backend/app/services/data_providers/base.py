"""Base data provider interface."""

from __future__ import annotations

from abc import ABC, abstractmethod

import pandas as pd


class DataProvider(ABC):
    """Abstract base for stock data providers."""

    name: str = "base"

    @abstractmethod
    def fetch_stock_list(self) -> pd.DataFrame:
        """Fetch list of all A-share stocks.

        Returns DataFrame with columns: code, name, industry (optional).
        """

    @abstractmethod
    def fetch_daily_data(self, code: str, start_date: str, end_date: str) -> pd.DataFrame:
        """Fetch daily OHLCV data for a stock.

        Returns DataFrame with columns:
        trade_date, open, close, high, low, volume, amount, change_pct.
        """

    async def async_fetch_stock_list(self) -> pd.DataFrame:
        """Async version — override in HTTP-based providers for cancellable I/O."""
        import asyncio
        return await asyncio.to_thread(self.fetch_stock_list)

    async def async_fetch_daily_data(self, code: str, start_date: str, end_date: str) -> pd.DataFrame:
        """Async version — override in HTTP-based providers for cancellable I/O."""
        import asyncio
        return await asyncio.to_thread(self.fetch_daily_data, code, start_date, end_date)
