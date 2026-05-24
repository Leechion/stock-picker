"""Capital flow and chip distribution data from Eastmoney.

Fetches real money flow data (main force / large / medium / small orders)
and chip concentration metrics for use as sentiment factors.
"""

from __future__ import annotations

import httpx
from loguru import logger

# Eastmoney money flow API
MONEYFLOW_URL = "https://push2.eastmoney.com/api/qt/stock/get"

# Eastmoney chip distribution API
CHIP_URL = "https://datacenter-web.eastmoney.com/api/data/v1/get"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36"
    ),
    "Referer": "https://quote.eastmoney.com/",
}


def _market_code(code: str) -> int:
    return 1 if code.startswith(("5", "6", "9")) else 0


def _safe_float(val) -> float | None:
    try:
        v = float(val)
        return v if v == v else None  # NaN check
    except (TypeError, ValueError):
        return None


def fetch_money_flow(code: str) -> dict[str, float | None]:
    """Fetch money flow data from Eastmoney.

    Returns dict with:
    - main_net_inflow: 主力净流入 (万元)
    - super_large_net: 超大单净流入 (万元)
    - large_net: 大单净流入 (万元)
    - medium_net: 中单净流入 (万元)
    - small_net: 小单净流入 (万元)
    - main_net_ratio: 主力净流入占比 (%)
    """
    result: dict[str, float | None] = {
        "main_net_inflow": None,
        "super_large_net": None,
        "large_net": None,
        "medium_net": None,
        "small_net": None,
        "main_net_ratio": None,
    }

    try:
        secid = f"{_market_code(code)}.{code}"
        resp = httpx.get(
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
    """Fetch chip concentration data from Eastmoney.

    Returns dict with:
    - chip_concentration: 筹码集中度 (90%成本集中度)
    - profit_ratio: 获利比例 (%)
    - avg_cost: 平均成本 (元)
    """
    result: dict[str, float | None] = {
        "chip_concentration": None,
        "profit_ratio": None,
        "avg_cost": None,
    }

    try:
        resp = httpx.get(
            CHIP_URL,
            params={
                "reportName": "RPT_COST_CONC",
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
