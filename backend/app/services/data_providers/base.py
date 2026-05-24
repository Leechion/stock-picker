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
