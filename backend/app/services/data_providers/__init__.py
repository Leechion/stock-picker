"""Data provider abstraction layer.

Provides a unified interface for fetching stock data from multiple sources
with automatic fallback when a provider fails.
"""

from app.services.data_providers.base import DataProvider
from app.services.data_providers.manager import provider_manager

__all__ = ["DataProvider", "provider_manager"]
