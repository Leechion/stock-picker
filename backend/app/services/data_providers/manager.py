"""Provider manager - tries providers in priority order with fallback."""

from __future__ import annotations

import pandas as pd
from loguru import logger

from app.services.data_providers.base import DataProvider
from app.services.data_providers.akshare_provider import AKShareProvider
from app.services.data_providers.eastmoney_provider import EastmoneyProvider


class ProviderManager:
    """Manages multiple data providers with automatic fallback."""

    def __init__(self) -> None:
        self._providers: list[DataProvider] = [
            AKShareProvider(),
            EastmoneyProvider(),
        ]

    @property
    def provider_names(self) -> list[str]:
        return [p.name for p in self._providers]

    def fetch_stock_list(self) -> pd.DataFrame:
        """Try each provider in order until one succeeds."""
        df = None
        for provider in self._providers:
            try:
                df = provider.fetch_stock_list()
                if df is not None and not df.empty:
                    break
                logger.warning(f"[{provider.name}] returned empty stock list, trying next")
                df = None
            except Exception as exc:
                logger.warning(f"[{provider.name}] stock list failed: {exc}, trying next")
                df = None

        if df is None or df.empty:
            logger.error("All providers failed for stock list")
            return pd.DataFrame()

        # Ensure industry column is populated — Eastmoney provides it
        if "industry" not in df.columns or df["industry"].isna().all():
            try:
                eastmoney_df = EastmoneyProvider().fetch_stock_list()
                if not eastmoney_df.empty and "industry" in eastmoney_df.columns:
                    industry_map = eastmoney_df.set_index("code")["industry"]
                    df["industry"] = df["code"].map(industry_map)
                    logger.info(f"Merged industry data for {df['industry'].notna().sum()} stocks from Eastmoney")
            except Exception as exc:
                logger.warning(f"Failed to merge industry from Eastmoney: {exc}")

        return df

    def fetch_daily_data(self, code: str, start_date: str, end_date: str) -> pd.DataFrame:
        """Try each provider in order until one succeeds."""
        for provider in self._providers:
            try:
                df = provider.fetch_daily_data(code, start_date, end_date)
                if df is not None and not df.empty:
                    return df
            except Exception as exc:
                logger.debug(f"[{provider.name}] daily data failed for {code}: {exc}")
        return pd.DataFrame()


# Singleton
provider_manager = ProviderManager()
