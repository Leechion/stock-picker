"""Provider manager - tries providers in priority order with fallback."""

from __future__ import annotations

import pandas as pd
from loguru import logger

from app.services.data_providers.base import DataProvider
from app.services.data_providers.akshare_provider import AKShareProvider
from app.services.data_providers.eastmoney_provider import EastmoneyProvider
from app.services.data_providers.sina_provider import SinaProvider
from app.services.data_providers.ths_provider import THSProvider


class ProviderManager:
    """Manages multiple data providers with automatic fallback."""

    def __init__(self) -> None:
        self._providers: list[DataProvider] = [
            THSProvider(),
            SinaProvider(),
            EastmoneyProvider(),
            AKShareProvider(),
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
        """Try HTTP providers first (thread-safe), then AKShare (single-threaded V8)."""
        # Try Sina and Eastmoney (both pure HTTP, concurrent-safe)
        for provider in self._providers:
            if provider.name == "akshare":
                continue
            if provider.name == "eastmoney" and not provider._check_reachable():
                continue
            try:
                df = provider.fetch_daily_data(code, start_date, end_date)
                if df is not None and not df.empty:
                    return df
            except Exception as exc:
                logger.debug(f"[{provider.name}] daily data failed for {code}: {exc}")

        # Fallback to AKShare (not thread-safe, single-threaded only)
        for provider in self._providers:
            if provider.name != "akshare":
                continue
            try:
                df = provider.fetch_daily_data(code, start_date, end_date)
                if df is not None and not df.empty:
                    return df
            except Exception as exc:
                logger.debug(f"[{provider.name}] daily data failed for {code}: {exc}")

        return pd.DataFrame()

    async def async_fetch_stock_list(self) -> pd.DataFrame:
        """Async: try each provider with cancellable HTTP calls."""
        for provider in self._providers:
            try:
                df = await provider.async_fetch_stock_list()
                if df is not None and not df.empty:
                    break
                logger.warning(f"[{provider.name}] async stock list returned empty, trying next")
                df = None
            except Exception as exc:
                logger.warning(f"[{provider.name}] async stock list failed: {exc}, trying next")
                df = None

        if df is None or df.empty:
            logger.error("All providers failed for async stock list")
            return pd.DataFrame()

        if "industry" not in df.columns or df["industry"].isna().all():
            try:
                from app.services.data_providers.eastmoney_provider import EastmoneyProvider
                em_df = await EastmoneyProvider().async_fetch_stock_list()
                if not em_df.empty and "industry" in em_df.columns:
                    industry_map = em_df.set_index("code")["industry"]
                    df["industry"] = df["code"].map(industry_map)
                    logger.info(f"Merged industry from Eastmoney for {df['industry'].notna().sum()} stocks")
            except Exception as exc:
                logger.warning(f"Failed to merge industry: {exc}")

        return df

    async def async_fetch_daily_data(self, code: str, start_date: str, end_date: str) -> pd.DataFrame:
        """Async: try HTTP providers first (cancellable), then AKShare fallback."""
        for provider in self._providers:
            if provider.name == "akshare":
                continue
            if provider.name == "eastmoney" and not provider._check_reachable():
                continue
            try:
                df = await provider.async_fetch_daily_data(code, start_date, end_date)
                if df is not None and not df.empty:
                    return df
            except Exception as exc:
                logger.debug(f"[{provider.name}] async daily data failed for {code}: {exc}")

        for provider in self._providers:
            if provider.name != "akshare":
                continue
            try:
                import asyncio
                df = await asyncio.to_thread(provider.fetch_daily_data, code, start_date, end_date)
                if df is not None and not df.empty:
                    return df
            except Exception as exc:
                logger.debug(f"[{provider.name}] daily data failed for {code}: {exc}")

        return pd.DataFrame()


# Singleton
provider_manager = ProviderManager()
