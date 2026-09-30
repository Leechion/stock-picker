"""Capital flow and chip distribution data from Eastmoney.

Fetches real money flow data (main force / large / medium / small orders)
and chip concentration metrics for use as sentiment factors.

Network notes
-------------
``push2.eastmoney.com`` (money flow) and ``datacenter-web.eastmoney.com``
(chip distribution) are *different hosts* with independent reachability. On
some networks ``push2`` is blocked while ``datacenter`` works fine, so each is
probed separately — a failure of one must not disable the other.

These probes must not use bare ``httpx.get``: see ``app/core/http.py`` for the
macOS ``NO_PROXY`` bug that makes every httpx call fail in the constructor.
"""

from __future__ import annotations

import time

from loguru import logger

from app.core.http import http_get

# Eastmoney money flow API
MONEYFLOW_URL = "https://push2.eastmoney.com/api/qt/stock/get"

# Eastmoney chip distribution API.
#
# ⚠️ As of 2026-09 the report ``RPT_COST_CONC`` returns
# ``报表配置不存在`` (code 9501) — Eastmoney removed it. The host is reachable,
# the report is simply gone. ``fetch_chip_distribution`` therefore logs at
# WARNING once and returns all-None rather than pretending otherwise.
# Re-enable by pointing CHIP_REPORT at a current report name if one appears.
CHIP_URL = "https://datacenter-web.eastmoney.com/api/data/v1/get"
CHIP_REPORT = "RPT_COST_CONC"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36"
    ),
    "Referer": "https://quote.eastmoney.com/",
}

# Per-host reachability, probed independently and re-checked periodically.
# A permanent "unreachable" verdict is wrong: a transient outage or a VPN
# toggle would disable flow data for the whole process lifetime.
_reachable: dict[str, bool] = {}
_last_probe: dict[str, float] = {}
_PROBE_TTL = 300.0  # re-probe every 5 minutes


def _probe(host_key: str, url: str) -> bool:
    """Is `url`'s host reachable? Cached for _PROBE_TTL seconds."""
    now = time.monotonic()
    if host_key in _reachable and now - _last_probe.get(host_key, 0) < _PROBE_TTL:
        return _reachable[host_key]

    ok = False
    try:
        resp = http_get(
            url,
            params={"secid": "1.600519", "fields": "f62", "ut": "test", "invt": "2", "fltt": "2"},
            timeout=5.0,
            headers=HEADERS,
        )
        # Any HTTP response — even an error status — proves the host is up.
        ok = resp.status_code < 500
    except Exception as exc:
        logger.debug(f"[capital_flow] {host_key} probe failed: {exc}")

    if _reachable.get(host_key) is not ok:
        logger.info(
            f"[capital_flow] {host_key} is now {'reachable' if ok else 'unreachable'}"
        )
    _reachable[host_key] = ok
    _last_probe[host_key] = now
    return ok


def _check_eastmoney() -> bool:
    """Money-flow host reachability (kept for backwards compatibility)."""
    return _probe("push2.eastmoney.com", MONEYFLOW_URL)


def _check_chip_host() -> bool:
    """Chip-distribution host reachability — separate host, separate verdict."""
    return _probe("datacenter-web.eastmoney.com", CHIP_URL)


def both_sources_unavailable() -> bool:
    """True when neither money flow nor chip data can be obtained.

    Callers use this to skip the per-stock fetch entirely. Measured cost of
    calling ``fetch_flow_and_chip`` 3000 times with both sources down:
    ~0.18-0.6 s each, i.e. 9-30 minutes of pure waste per factor run — the
    function still probes and parses only to discover it has nothing.
    """
    return not _check_eastmoney() and not _chip_report_usable()


def _chip_report_usable() -> bool:
    """Is the chip report still served upstream?

    Probes the report directly rather than relying on ``_chip_retired_warned``:
    that flag is only set *after* a fetch has failed, so a caller asking before
    the first fetch would be told "usable" and then pay for a doomed request on
    every stock.
    """
    if _chip_retired_warned:
        return False
    if not _check_chip_host():
        return False

    try:
        resp = http_get(
            CHIP_URL,
            params={"reportName": CHIP_REPORT, "columns": "ALL", "pageSize": 1,
                    "source": "WEB", "client": "WEB"},
            timeout=5.0,
            headers=HEADERS,
        )
        data = resp.json()
    except Exception:
        return False

    if not data.get("success", True):
        _warn_chip_retired(data.get("message"))
        return False
    return True


# Announced once, not per stock: this runs for ~3000 stocks a night.
_chip_retired_warned = False


def _warn_chip_retired(message: str | None) -> None:
    global _chip_retired_warned
    if not _chip_retired_warned:
        _chip_retired_warned = True
        logger.warning(
            f"[capital_flow] chip report {CHIP_REPORT!r} rejected upstream "
            f"({message!r}). Chip factors will be None until a valid report "
            f"name is configured."
        )


def _market_code(code: str) -> int:
    return 1 if code.startswith(("5", "6", "9")) else 0


def _safe_float(val) -> float | None:
    try:
        v = float(val)
        return v if v == v else None  # NaN check
    except (TypeError, ValueError):
        return None


def fetch_money_flow(code: str) -> dict[str, float | None]:
    """Fetch money flow data from Eastmoney."""
    result: dict[str, float | None] = {
        "main_net_inflow": None,
        "super_large_net": None,
        "large_net": None,
        "medium_net": None,
        "small_net": None,
        "main_net_ratio": None,
    }
    if not _check_eastmoney():
        return result

    try:
        secid = f"{_market_code(code)}.{code}"
        resp = http_get(
            MONEYFLOW_URL,
            params={
                "secid": secid,
                "ut": "7eea3edcaed734bea9cbfc24409ed989",
                "fields": "f62,f66,f69,f72,f75,f78,f184,f64,f65,f70,f71,f76,f77",
                "invt": "2",
                "fltt": "2",
            },
            timeout=10.0,
            headers=HEADERS,
        )
        resp.raise_for_status()
        data = resp.json()
        d = data.get("data", {})

        if d:
            # f62=主力净流入, f66=超大单净流入, f69=大单净流入
            # f72=中单净流入, f75=小单净流入, f184=主力净流入占比
            result["main_net_inflow"] = _safe_float(d.get("f62"))
            result["super_large_net"] = _safe_float(d.get("f66"))
            result["large_net"] = _safe_float(d.get("f69"))
            result["medium_net"] = _safe_float(d.get("f72"))
            result["small_net"] = _safe_float(d.get("f75"))
            result["main_net_ratio"] = _safe_float(d.get("f184"))

    except Exception as exc:
        logger.debug(f"Money flow fetch failed for {code}: {exc}")

    return result


def fetch_chip_distribution(code: str) -> dict[str, float | None]:
    """Fetch chip concentration data from Eastmoney."""
    result: dict[str, float | None] = {
        "chip_concentration": None,
        "profit_ratio": None,
        "avg_cost": None,
    }
    # Separate host from money flow: probe it independently, otherwise a
    # push2 outage silently suppresses chip data that is in fact available.
    if not _check_chip_host():
        return result

    try:
        resp = http_get(
            CHIP_URL,
            params={
                "reportName": CHIP_REPORT,
                "columns": "SECURITY_CODE,CHIP_CONCENTRATION,PROFIT_COST_RATIO,AVG_COST",
                "filter": f'(SECURITY_CODE="{code}")',
                "pageSize": 1,
                "sortColumns": "REPORT_DATE",
                "sortTypes": -1,
                "source": "WEB",
                "client": "WEB",
            },
            timeout=10.0,
            headers=HEADERS,
        )
        resp.raise_for_status()
        data = resp.json()

        # The API answers 200 even when it refuses the request; without this
        # check a retired report looks identical to "no data for this stock".
        if not data.get("success", True):
            _warn_chip_retired(data.get("message"))
            return result

        rows = (data.get("result") or {}).get("data") or []

        if rows:
            row = rows[0]
            result["chip_concentration"] = _safe_float(row.get("CHIP_CONCENTRATION"))
            result["profit_ratio"] = _safe_float(row.get("PROFIT_COST_RATIO"))
            result["avg_cost"] = _safe_float(row.get("AVG_COST"))

    except Exception as exc:
        logger.debug(f"Chip distribution fetch failed for {code}: {exc}")

    return result


def fetch_flow_and_chip(code: str) -> dict[str, float | None]:
    """Fetch both money flow and chip data in one call."""
    flow = fetch_money_flow(code)
    chip = fetch_chip_distribution(code)
    return {**flow, **chip}
