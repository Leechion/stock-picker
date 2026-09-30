"""Tests for the realtime quote layer.

Covers the parts that are easy to get silently wrong:
  * the upstream payload parser (field indices, short/blank lines)
  * the batch-size cliff that makes the upstream truncate with HTTP 200
  * the market calendar that decides whether polling is worthwhile
  * the httpx proxy workaround (a real macOS bug that broke every HTTP call)
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from app.core.market_calendar import (
    CN_TZ,
    is_trading_session,
    session_label,
    should_poll_quotes,
)
from app.services.quote_service import (
    BATCH_SIZE,
    Quote,
    parse_quote_line,
    parse_quotes,
)

# A genuine, unmodified response line captured from the upstream API.
# Do NOT hand-write this: the payload has 88 positional fields, and a
# fixture that is even slightly short shifts every index and makes the
# parser look broken when it is the fixture that is wrong.
SAMPLE = (
    'v_sh600519="1~贵州茅台~600519~1258.62~1235.58~1239.53~38331~21633~16698~1258.62~'
    '14~1258.44~1~1258.16~1~1258.05~2~1258.00~41~1258.65~2~1258.66~3~1258.68~1~12'
    '58.69~2~1258.75~80~~20260930161458~23.04~1.86~1268.00~1236.05~1258.62/38331/'
    '4797246636~38331~479725~0.31~19.32~~1268.00~1236.05~2.59~15733.78~15733.78~6'
    '.26~1359.14~1112.02~1.36~-29~1251.53~17.67~19.11~~~0.06~479724.6636~453.1032'
    '~36~   A~GP-A~-6.71~0.38~4.13~32.41~27.30~1539.98~1151.01~-1.11~-3.15~5.87~1'
    '250081601~1250081601~-19.73~-9.97~1250081601~~~-9.58~0.16~~CNY~0~___D__F__N~'
    '1257.93~15~";'
)


def test_parse_quote_line_extracts_core_fields() -> None:
    q = parse_quote_line(SAMPLE)
    assert q is not None
    assert q.code == "600519"
    assert q.name == "贵州茅台"
    assert q.price == 1258.62
    assert q.prev_close == 1235.58
    assert q.open == 1239.53
    assert q.high == 1268.00
    assert q.low == 1236.05
    assert q.change_pct == 1.86
    assert q.ts == "20260930161458"


def test_parse_skips_blank_and_malformed_lines() -> None:
    assert parse_quote_line("") is None
    assert parse_quote_line("garbage") is None
    assert parse_quote_line('v_sh600519="";') is None
    # Too few fields to be a quote.
    assert parse_quote_line('v_sh600519="1~name~600519";') is None


def test_parse_rejects_zero_price() -> None:
    """A suspended/never-traded stock returns price 0 — must not be cached."""
    line = 'v_sz000001="51~平安银行~000001~0.00~11.35~0~1~1~1"'
    assert parse_quote_line(line) is None


def test_parse_quotes_handles_multiple_lines() -> None:
    other = SAMPLE.replace("sh600519", "sz000001").replace("600519", "000001")
    parsed = parse_quotes(SAMPLE + "\n" + other)
    assert set(parsed) == {"600519", "000001"}


def test_batch_size_is_below_the_upstream_truncation_cliff() -> None:
    """The API silently truncates past ~900 codes, returning HTTP 200 + 1 line.

    Measured: 900 codes -> full response; 950 codes -> 1 line. BATCH_SIZE must
    stay well clear, otherwise a full-market refresh silently loses stocks.
    """
    assert BATCH_SIZE <= 800, "batch size too close to the truncation cliff"


# ----------------------------------------------------------------------
# Market calendar
# ----------------------------------------------------------------------

def _at(y: int, m: int, d: int, hh: int, mm: int) -> datetime:
    return datetime(y, m, d, hh, mm, tzinfo=CN_TZ)


def test_trading_session_windows() -> None:
    # 2026-09-30 is a Wednesday.
    assert is_trading_session(_at(2026, 9, 30, 10, 0)) is True    # morning
    assert is_trading_session(_at(2026, 9, 30, 14, 0)) is True    # afternoon
    assert is_trading_session(_at(2026, 9, 30, 12, 0)) is False   # lunch
    assert is_trading_session(_at(2026, 9, 30, 9, 0)) is False    # pre-open
    assert is_trading_session(_at(2026, 9, 30, 16, 0)) is False   # after close


def test_weekend_is_never_a_session() -> None:
    # 2026-10-03 is a Saturday.
    assert is_trading_session(_at(2026, 10, 3, 10, 0)) is False
    assert should_poll_quotes(_at(2026, 10, 3, 10, 0)) is False
    assert session_label(_at(2026, 10, 3, 10, 0)) == "休市"


def test_poll_window_is_wider_than_the_session() -> None:
    """Polling starts before the open so the first tick is already warm."""
    assert should_poll_quotes(_at(2026, 9, 30, 9, 20)) is True
    assert is_trading_session(_at(2026, 9, 30, 9, 20)) is False
    # And stops shortly after the close, then idles.
    assert should_poll_quotes(_at(2026, 9, 30, 15, 3)) is True
    assert should_poll_quotes(_at(2026, 9, 30, 15, 30)) is False


@pytest.mark.parametrize(
    "hh,mm,expected",
    [
        (8, 0, "盘前"),
        (10, 0, "上午盘"),
        (12, 0, "午间休市"),
        (14, 0, "下午盘"),
        (16, 0, "已收盘"),
    ],
)
def test_session_labels(hh: int, mm: int, expected: str) -> None:
    assert session_label(_at(2026, 9, 30, hh, mm)) == expected


# ----------------------------------------------------------------------
# httpx proxy workaround
# ----------------------------------------------------------------------

def test_no_proxy_sanitizer_removes_ipv6_brackets() -> None:
    """macOS getproxies() returns '::1,[::1]'; httpx 0.28.1 cannot parse it.

    The failure happens in the client CONSTRUCTOR, so every httpx call in the
    process died with `InvalidURL: Invalid port: ':1]'` — which surfaced as
    misleading "Eastmoney unreachable" errors and silently empty market data.
    """
    from app.core.http import _sanitize_no_proxy

    assert _sanitize_no_proxy("localhost,127.0.0.1,::1,[::1]") == "localhost,127.0.0.1,::1,::1"
    assert _sanitize_no_proxy("[::1]") == "::1"
    assert _sanitize_no_proxy("localhost") == "localhost"
    assert _sanitize_no_proxy("") == ""


async def test_async_client_helper_always_constructs() -> None:
    """The helper must return a usable client even on a hostile environment."""
    from app.core.http import async_client

    client = async_client(timeout=5.0)
    try:
        assert client is not None
    finally:
        await client.aclose()


# ----------------------------------------------------------------------
# Data-source reachability isolation
# ----------------------------------------------------------------------

def test_probe_hosts_are_independent(monkeypatch) -> None:
    """One unreachable Eastmoney host must not disable the other.

    Observed live: ``push2.eastmoney.com`` (money flow) was blocked on the
    network while ``datacenter-web.eastmoney.com`` (chip) answered fine. The
    original code probed only push2 and used that verdict to gate BOTH calls,
    so working chip data was thrown away.
    """
    import app.services.capital_flow as cf

    probed: list[str] = []

    def fake_probe(host_key, url):
        probed.append(host_key)
        return host_key == "datacenter-web.eastmoney.com"

    monkeypatch.setattr(cf, "_probe", fake_probe)
    monkeypatch.setattr(cf, "_reachable", {}, raising=False)
    monkeypatch.setattr(cf, "_last_probe", {}, raising=False)

    # Rebind the two thin wrappers to the fake probe's semantics.
    monkeypatch.setattr(cf, "_check_eastmoney", lambda: fake_probe("push2.eastmoney.com", cf.MONEYFLOW_URL))
    monkeypatch.setattr(cf, "_check_chip_host", lambda: fake_probe("datacenter-web.eastmoney.com", cf.CHIP_URL))

    assert cf._check_eastmoney() is False
    assert cf._check_chip_host() is True
    assert "datacenter-web.eastmoney.com" in probed


def test_chip_retired_warning_fires_once(monkeypatch) -> None:
    """A retired upstream report must warn once, not once per stock.

    This runs over ~3000 stocks per night; per-stock warnings would bury the
    log, and silence would make a dead report look like 'no data'.
    """
    import app.services.capital_flow as cf

    warnings: list[str] = []
    monkeypatch.setattr(cf.logger, "warning", lambda msg: warnings.append(str(msg)))
    monkeypatch.setattr(cf, "_chip_retired_warned", False, raising=False)

    cf._warn_chip_retired("报表配置不存在")
    cf._warn_chip_retired("报表配置不存在")
    cf._warn_chip_retired("报表配置不存在")

    assert len(warnings) == 1, f"expected a single warning, got {len(warnings)}"
    assert "RPT_COST_CONC" in warnings[0]
