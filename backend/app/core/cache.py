"""Simple in-memory cache with TTL support.

No external dependencies. Stores results in a Python dict with per-key expiry.
Cache is process-local, suitable for single-instance deployments.
"""

from __future__ import annotations

import time
from functools import wraps
from typing import Any

from fastapi.responses import JSONResponse


class TTLCache:
    def __init__(self):
        self._store: dict[str, tuple[float, Any]] = {}

    def get(self, key: str) -> Any | None:
        entry = self._store.get(key)
        if entry is None:
            return None
        expires, value = entry
        if time.monotonic() > expires:
            del self._store[key]
            return None
        return value

    def set(self, key: str, value: Any, ttl: float) -> None:
        self._store[key] = (time.monotonic() + ttl, value)

    def invalidate(self, prefix: str = "") -> None:
        """Remove all keys starting with prefix. Empty prefix = clear all."""
        if not prefix:
            self._store.clear()
            return
        keys_to_del = [k for k in self._store if k.startswith(prefix)]
        for k in keys_to_del:
            del self._store[k]

    @property
    def size(self) -> int:
        return len(self._store)


# Global cache instance
cache = TTLCache()


def cached(ttl: float = 300, prefix: str = ""):
    """Decorator that caches a FastAPI endpoint's JSON response.

    Args:
        ttl: Time-to-live in seconds.
        prefix: Cache key prefix (defaults to function name).
    """
    def decorator(fn):
        @wraps(fn)
        async def wrapper(*args, **kwargs):
            # Build cache key from function name + query params
            key_parts = [prefix or fn.__name__]
            for k, v in sorted(kwargs.items()):
                if k in ("session", "request"):
                    continue
                key_parts.append(f"{k}={v}")
            cache_key = "|".join(key_parts)

            # Check cache
            hit = cache.get(cache_key)
            if hit is not None:
                return hit

            # Call original
            result = await fn(*args, **kwargs)

            # Cache only JSONResponse
            if isinstance(result, JSONResponse):
                cache.set(cache_key, result, ttl)

            return result
        return wrapper
    return decorator
