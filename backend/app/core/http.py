"""HTTP client helpers with a project-wide workaround for a macOS proxy bug.

The bug
-------
On macOS, ``urllib.request.getproxies()`` reads System Configuration and can
return a ``no`` value containing bracketed IPv6 literals::

    {'no': 'localhost,127.0.0.1,::1,[::1]', 'http': 'http://127.0.0.1:7897', ...}

httpx 0.28.1 feeds each ``NO_PROXY`` entry through ``URLPattern``, which parses
``[::1]`` as a URL and raises::

    httpx.InvalidURL: Invalid port: ':1]'

Critically, this happens in the **``httpx.Client`` / ``httpx.AsyncClient``
constructor** — before any request is made — so *every* httpx call in the
process fails, sync or async, regardless of the URL being requested. Observed
symptoms were misleading: ``Eastmoney unreachable``, ``Server disconnected
without sending a response``, and silently empty market data.

The fix
-------
Strip brackets from IPv6 entries in ``NO_PROXY`` / ``no_proxy`` before httpx
reads them. This preserves the intent (bypass the proxy for loopback) while
keeping the value parseable.

Call :func:`install_proxy_env_fix` once at import of ``app.core``. All new code
should build clients via :func:`async_client` / :func:`new_sync_client` so the
workaround can never be forgotten.
"""

from __future__ import annotations

import os
import re
from typing import Any

import httpx
from loguru import logger

#: Matches a bracketed IPv6 literal, e.g. "[::1]".
_BRACKETED_IPV6 = re.compile(r"\[([0-9A-Fa-f:]+)\]")

_installed = False


def _sanitize_no_proxy(value: str) -> str:
    """Remove square brackets from IPv6 entries so httpx can parse them."""
    return _BRACKETED_IPV6.sub(r"\1", value)


def install_proxy_env_fix() -> bool:
    """Normalise ``NO_PROXY``/``no_proxy`` so httpx can construct a client.

    Idempotent. Returns True if anything was changed.

    Note: this only patches the *environment*. It does not disable proxies, so
    users behind a corporate proxy keep working — only the unparseable
    bracketed form is rewritten.
    """
    global _installed
    if _installed:
        return False

    changed = False
    for key in ("NO_PROXY", "no_proxy"):
        raw = os.environ.get(key)
        if not raw or "[" not in raw:
            continue
        cleaned = _sanitize_no_proxy(raw)
        if cleaned != raw:
            os.environ[key] = cleaned
            logger.debug(f"Normalised {key} for httpx compatibility: {raw!r} -> {cleaned!r}")
            changed = True

    _installed = True
    return changed


def _client_kwargs(**kwargs: Any) -> dict[str, Any]:
    """Ensure a client can always be built, even on a hostile environment.

    ``install_proxy_env_fix`` handles the common macOS case. If a client still
    cannot be constructed (some other unparseable proxy value), fall back to
    ``trust_env=False`` so the request proceeds without proxy configuration —
    better a direct connection than a hard crash on import.
    """
    try:
        httpx.Client(**{k: v for k, v in kwargs.items() if k != "timeout"})  # probe
        return kwargs
    except Exception as exc:
        logger.warning(
            f"httpx client construction failed ({exc}); retrying with trust_env=False"
        )
        return {**kwargs, "trust_env": False}


def async_client(**kwargs: Any) -> httpx.AsyncClient:
    """Build an ``httpx.AsyncClient`` that tolerates proxy env quirks."""
    install_proxy_env_fix()
    try:
        return httpx.AsyncClient(**kwargs)
    except Exception as exc:
        logger.warning(
            f"httpx.AsyncClient construction failed ({exc}); retrying with trust_env=False"
        )
        return httpx.AsyncClient(**{**kwargs, "trust_env": False})


def sync_client(**kwargs: Any) -> httpx.Client:
    """Build an ``httpx.Client`` that tolerates proxy env quirks."""
    install_proxy_env_fix()
    try:
        return httpx.Client(**kwargs)
    except Exception:
        return httpx.Client(**{**kwargs, "trust_env": False})


def http_get(url: str, **kwargs: Any) -> httpx.Response:
    """Sync GET that survives the proxy env bug. Use for one-shot requests."""
    install_proxy_env_fix()
    try:
        return httpx.get(url, **kwargs)
    except httpx.InvalidURL:
        with httpx.Client(trust_env=False) as client:
            return client.get(url, **kwargs)
