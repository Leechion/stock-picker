"""Sector heat tracking - identifies hot industry/concept sectors.

Uses Eastmoney API to fetch sector performance, money flow, and
limit-up counts to compute a heat score per sector.
"""

from __future__ import annotations

import httpx
from loguru import logger

SECTOR_URL = "https://push2.eastmoney.com/api/qt/clist/get"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36"
    ),
    "Referer": "https://quote.eastmoney.com/",
}


def fetch_sector_performance() -> list[dict]:
    """Fetch industry sector performance from Eastmoney.

    Returns list of dicts with: name, change_pct, net_inflow, limit_up_count.
    Falls back to empty list if API is unavailable (e.g. proxy issues).
    """
    try:
        resp = httpx.get(
            SECTOR_URL,
            params={
                "pn": "1",
                "pz": "100",
                "po": "1",
                "np": "1",
                "ut": "bd1d9ddb04089700cf9c27f6f7426281",
                "fltt": "2",
                "invt": "2",
                "fid": "f3",
                "fs": "m:90+t:2+f:!50",
                "fields": "f2,f3,f4,f62,f104,f105,f128,f140",
            },
            timeout=10.0,
            headers=HEADERS,
        )
        resp.raise_for_status()
        data = resp.json()
        items = (data.get("data") or {}).get("diff") or []

        sectors = []
        for item in items:
            sectors.append({
                "name": item.get("f140", ""),
                "change_pct": item.get("f3"),
                "net_inflow": item.get("f62"),
                "limit_up_count": item.get("f104", 0),
                "fall_count": item.get("f105", 0),
            })
        logger.info(f"Fetched {len(sectors)} sector performance records")
        return sectors

    except Exception as exc:
        logger.warning(f"Sector API unavailable (proxy/network issue), sector heat disabled: {exc}")
        return []


def compute_sector_heat(sectors: list[dict]) -> dict[str, float]:
    """Compute a heat score (0-100) for each sector.

    Score = 0.4 * change_rank + 0.4 * inflow_rank + 0.2 * limit_up_rank
    Normalized to 0-100 where 100 = hottest sector.
    """
    if not sectors:
        return {}

    # Filter out sectors with None values
    valid = [s for s in sectors if s.get("change_pct") is not None]
    if not valid:
        return {}

    # Sort for ranking
    by_change = sorted(valid, key=lambda s: float(s.get("change_pct") or 0), reverse=True)
    by_inflow = sorted(valid, key=lambda s: float(s.get("net_inflow") or 0), reverse=True)
    by_limit = sorted(valid, key=lambda s: int(s.get("limit_up_count") or 0), reverse=True)

    n = len(valid)
    change_rank = {s["name"]: 1 - i / n for i, s in enumerate(by_change)}
    inflow_rank = {s["name"]: 1 - i / n for i, s in enumerate(by_inflow)}
    limit_rank = {s["name"]: 1 - i / n for i, s in enumerate(by_limit)}

    heat: dict[str, float] = {}
    for s in valid:
        name = s["name"]
        score = (
            0.4 * change_rank.get(name, 0)
            + 0.4 * inflow_rank.get(name, 0)
            + 0.2 * limit_rank.get(name, 0)
        )
        heat[name] = round(score * 100, 2)

    return heat
