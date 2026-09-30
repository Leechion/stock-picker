"""A-share market calendar helpers.

A-share trading sessions (Asia/Shanghai):
  * 09:30–11:30  morning
  * 13:00–15:00  afternoon

There is no holiday calendar wired in, so this answers "is it plausible market
hours" (weekday + session window). That is the right granularity for deciding
whether to *poll* a free quote API: polling on a holiday wastes a few requests,
but never produces wrong data — the upstream simply returns the last close.
"""

from __future__ import annotations

from datetime import datetime, time
from zoneinfo import ZoneInfo

CN_TZ = ZoneInfo("Asia/Shanghai")

MORNING_OPEN = time(9, 30)
MORNING_CLOSE = time(11, 30)
AFTERNOON_OPEN = time(13, 0)
AFTERNOON_CLOSE = time(15, 0)

#: Broad window used by the quote poller — starts slightly before the open so
#: the first tick is already warm when trading begins.
POLL_START = time(9, 15)
POLL_END = time(15, 5)


def now_cn() -> datetime:
    """Current time in the exchange timezone."""
    return datetime.now(CN_TZ)


def is_weekday(dt: datetime) -> bool:
    return dt.weekday() < 5


def is_trading_session(dt: datetime | None = None) -> bool:
    """True during the morning or afternoon continuous session."""
    dt = dt or now_cn()
    if not is_weekday(dt):
        return False
    t = dt.time()
    return (MORNING_OPEN <= t <= MORNING_CLOSE) or (AFTERNOON_OPEN <= t <= AFTERNOON_CLOSE)


def should_poll_quotes(dt: datetime | None = None) -> bool:
    """True when the realtime poller should be active (slightly wider window)."""
    dt = dt or now_cn()
    if not is_weekday(dt):
        return False
    return POLL_START <= dt.time() <= POLL_END


def session_label(dt: datetime | None = None) -> str:
    """Human-readable session state, handy for API responses and the UI."""
    dt = dt or now_cn()
    if not is_weekday(dt):
        return "休市"
    t = dt.time()
    if t < MORNING_OPEN:
        return "盘前"
    if t <= MORNING_CLOSE:
        return "上午盘"
    if t < AFTERNOON_OPEN:
        return "午间休市"
    if t <= AFTERNOON_CLOSE:
        return "下午盘"
    return "已收盘"
