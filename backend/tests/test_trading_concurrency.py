"""Concurrency / auth regression tests for the trading engine and monitor WS.

Covers:
  (a) execute_buy never drives account.cash negative when cash is insufficient
  (b) concurrent buys cannot oversell the account (asyncio.Lock + cash check)
  (c) WebSocket auth stays a no-op when the feature flag is off

Everything here is fully offline: in-memory SQLite only, no network, no Redis.
"""

from __future__ import annotations

import asyncio
import os

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")

from app.core.config import settings  # noqa: E402
from app.core.database import Base  # noqa: E402
from app.models.trading import Position, TradeLog, TradingAccount  # noqa: E402
from app.services import trading_service  # noqa: E402
from app.services.trading_service import (  # noqa: E402
    execute_buy,
    execute_sell,
    pyramid_weight,
)


@pytest_asyncio.fixture
async def memory_engine():
    """Fresh in-memory SQLite DB per test (StaticPool keeps one connection)."""
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest_asyncio.fixture
async def factory(memory_engine):
    return async_sessionmaker(memory_engine, expire_on_commit=False)


def _make_account(cash: float, initial_capital: float = 500000.0) -> TradingAccount:
    return TradingAccount(
        initial_capital=initial_capital,
        cash=cash,
        total_value=cash,
        prev_close_value=cash,
    )


# ======================================================================
# (a) Insufficient-balance buy must not produce negative cash
# ======================================================================

@pytest.mark.parametrize(
    "cash,price,initial_capital",
    [
        (1000.0, 50.0, 500000.0),      # pyramid target (12%) far exceeds cash
        (500.0, 100.0, 500000.0),      # exactly 5 lots affordable by amount, not by pyramid
        (300.0, 100.0, 500000.0),      # can afford 3 lots on cash basis
        (50.0, 100.0, 500000.0),       # cannot afford even one 100-share lot
        (0.0, 10.0, 500000.0),         # zero cash
    ],
)
async def test_buy_insufficient_balance_never_negative(
    memory_engine, factory, cash, price, initial_capital
) -> None:
    async with factory() as session:
        account = _make_account(cash, initial_capital)
        session.add(account)
        await session.commit()
        await session.refresh(account)

        start_cash = account.cash
        log = await execute_buy(session, account, "600000", "测试股", rank=1, price=price, atr=1.0)
        await session.commit()

        assert account.cash >= 0, f"cash went negative: {account.cash}"
        assert account.cash <= start_cash + 1e-9

        if log is not None:
            # Whatever was actually bought must be fully covered by the cash we had.
            assert log.amount <= start_cash + 1e-9
            assert log.shares >= 100
            assert log.shares * price <= start_cash + 1e-9
            assert abs((start_cash - log.amount) - account.cash) < 1e-6
        else:
            # Rejected outright: no cash movement, no position row.
            assert account.cash == pytest.approx(start_cash)
            positions = (await session.execute(select(Position))).scalars().all()
            assert positions == []


async def test_buy_exact_cash_does_not_overdraw(memory_engine, factory) -> None:
    """When pyramid sizing exceeds cash, size must be clipped to affordable lots."""
    price = 30.0
    cash = price * 700  # exactly 7 lots
    async with factory() as session:
        account = _make_account(cash, initial_capital=10_000_000.0)
        session.add(account)
        await session.commit()
        await session.refresh(account)

        # pyramid_weight(1) = 0.12 -> 1.2M target, far above 21k cash.
        log = await execute_buy(session, account, "600519", "贵州茅台", rank=1, price=price, atr=2.0)
        await session.commit()

        assert log is not None
        assert log.shares * price <= cash + 1e-9
        assert account.cash >= 0
        assert account.cash == pytest.approx(cash - log.amount)


async def test_buy_rejected_when_cannot_afford_one_lot(memory_engine, factory) -> None:
    async with factory() as session:
        account = _make_account(99.0, initial_capital=500000.0)
        session.add(account)
        await session.commit()
        await session.refresh(account)

        log = await execute_buy(session, account, "000001", "平安银行", rank=5, price=100.0, atr=1.0)
        await session.commit()

        assert log is None
        assert account.cash == pytest.approx(99.0)
        assert (await session.execute(select(Position))).scalars().all() == []
        assert (await session.execute(select(TradeLog))).scalars().all() == []


async def test_buy_zero_or_negative_price_is_rejected(memory_engine, factory) -> None:
    async with factory() as session:
        account = _make_account(100000.0)
        session.add(account)
        await session.commit()
        await session.refresh(account)

        assert await execute_buy(session, account, "600000", "X", 1, price=0.0, atr=1.0) is None
        assert await execute_buy(session, account, "600000", "X", 1, price=-5.0, atr=1.0) is None
        await session.commit()
        assert account.cash == pytest.approx(100000.0)


async def test_buy_sweep_never_overdraws(memory_engine, factory) -> None:
    """Exhaustive-ish sweep over cash/price/capital: cash must never go negative.

    This is the property the fix guarantees regardless of which internal branch
    (pyramid cap vs. explicit overdraft guard) ends up doing the clamping.
    """
    prices = [0.01, 0.1, 1.0, 3.33, 7.77, 33.3, 99.99, 100.0, 333.33, 1000.0]
    cashes = [0.01, 1.0, 7.0, 99.0, 100.0, 101.0, 150.0, 999.0, 1000.0, 1234.56, 10000.0]
    for price in prices:
        for cash in cashes:
            async with factory() as session:
                account = _make_account(cash, initial_capital=500000.0)
                session.add(account)
                await session.commit()
                await session.refresh(account)

                log = await execute_buy(session, account, "600000", "X", rank=1, price=price, atr=1.0)
                await session.commit()

                assert account.cash >= -1e-9, f"cash negative: {account.cash} (price={price} cash={cash})"
                if log is not None:
                    assert log.shares * price <= cash + 1e-6
                    assert account.cash == pytest.approx(cash - log.amount)
                else:
                    assert account.cash == pytest.approx(cash)


# ======================================================================
# (b) Concurrent buys must not oversell / overdraw
# ======================================================================

async def test_concurrent_buys_do_not_oversell(memory_engine, factory) -> None:
    """20 concurrent buys against cash that only covers a handful of lots."""
    price = 100.0
    initial_capital = 500000.0
    cash = price * 100 * 5  # exactly 5 lots affordable

    async with factory() as session:
        account = _make_account(cash, initial_capital)
        session.add(account)
        await session.commit()
        await session.refresh(account)

        # Re-load the account through the same identity-mapped session; every
        # coroutine shares this ORM object, exactly like the API dependency would.
        codes = [f"60000{i}" for i in range(20)]
        results = await asyncio.gather(
            *(
                execute_buy(session, account, code, f"股票{i}", rank=3, price=price, atr=1.0)
                for i, code in enumerate(codes)
            ),
            return_exceptions=True,
        )

        errors = [r for r in results if isinstance(r, BaseException)]
        assert not errors, f"concurrent buys raised: {errors}"

        await session.commit()

    # Verify against a *fresh* session so we read what was really persisted.
    async with factory() as verify:
        account = (await verify.execute(select(TradingAccount))).scalar_one()
        positions = (await verify.execute(select(Position))).scalars().all()
        logs = (await verify.execute(select(TradeLog))).scalars().all()

        assert account.cash >= 0, f"cash went negative: {account.cash}"

        spent = sum(p.shares * p.avg_cost for p in positions)
        assert spent <= cash + 1e-6, f"overbought: spent={spent} cash was {cash}"
        assert abs(account.cash + spent - cash) < 1e-6, (
            f"cash accounting broken: cash={account.cash} spent={spent} start={cash}"
        )

        accepted = [r for r in results if r is not None]
        assert len(positions) == len(accepted)
        assert sum(l.shares for l in logs) == sum(p.shares for p in positions)
        # With only 5 lots of headroom, most orders must have been refused.
        assert len(accepted) < len(codes)


async def test_concurrent_buys_separate_sessions_do_not_oversell(memory_engine, factory) -> None:
    """Worst case and the real API path: one session per request.

    Each request loads its own ORM copy of the account, so locking around a
    stale in-memory `cash` is not enough -- the balance must be re-read inside
    the critical section and flushed before the lock is released.
    """
    price = 100.0
    cash = price * 100 * 5  # 5 lots affordable
    async with factory() as setup:
        account = _make_account(cash, initial_capital=500000.0)
        setup.add(account)
        await setup.commit()
        await setup.refresh(account)
        account_id = account.id

    async def one_request(i: int):
        async with factory() as s:
            acc = (
                await s.execute(select(TradingAccount).where(TradingAccount.id == account_id))
            ).scalar_one()
            log = await execute_buy(s, acc, f"60{i:04d}", f"N{i}", rank=3, price=price, atr=1.0)
            await s.commit()
            return log

    results = await asyncio.gather(*(one_request(i) for i in range(30)), return_exceptions=True)
    errors = [r for r in results if isinstance(r, BaseException)]
    assert not errors, f"concurrent requests raised: {errors}"

    accepted = [r for r in results if r is not None]
    async with factory() as verify:
        account = (await verify.execute(select(TradingAccount))).scalar_one()
        positions = (await verify.execute(select(Position))).scalars().all()
        spent = sum(p.shares * p.avg_cost for p in positions)

        assert account.cash >= 0, f"cash went negative: {account.cash}"
        assert spent <= cash + 1e-6, f"OVERSOLD: spent={spent} but only {cash} was available"
        assert abs(account.cash + spent - cash) < 1e-6, (
            f"lost cash update: cash={account.cash} spent={spent} started={cash}"
        )
        assert len(positions) == len(accepted)
        assert len(accepted) <= 5, f"expected at most 5 affordable lots, got {len(accepted)}"


async def test_concurrent_buys_respect_lock_serialization(memory_engine, factory) -> None:
    """Each accepted buy must be individually affordable given prior accepted buys."""
    price = 1000.0
    cash = price * 100 * 3  # 3 lots
    async with factory() as session:
        account = _make_account(cash, initial_capital=500000.0)
        session.add(account)
        await session.commit()
        await session.refresh(account)

        results = await asyncio.gather(
            *(
                execute_buy(session, account, f"6001{i:02d}", f"N{i}", rank=2, price=price, atr=5.0)
                for i in range(10)
            ),
            return_exceptions=True,
        )
        await session.commit()

    assert not [r for r in results if isinstance(r, BaseException)]
    async with factory() as verify:
        account = (await verify.execute(select(TradingAccount))).scalar_one()
        positions = (await verify.execute(select(Position))).scalars().all()
        assert account.cash >= 0
        assert len(positions) <= 3, f"expected at most 3 affordable lots, got {len(positions)}"
        assert account.cash + sum(p.shares * p.avg_cost for p in positions) == pytest.approx(cash)


async def test_concurrent_buy_and_sell_keep_cash_consistent(memory_engine, factory) -> None:
    """Buys and sells interleaved concurrently must not lose cash updates."""
    async with factory() as session:
        account = _make_account(100000.0)
        session.add(account)
        await session.commit()
        await session.refresh(account)

        held = _detached_position(account.id, 100.0, 200)
        session.add(held)
        await session.commit()
        await session.refresh(held)

        buy = execute_buy(session, account, "600000", "买入股", rank=7, price=100.0, atr=2.0)
        sell = execute_sell(session, account, held, 100.0, "测试卖出")
        results = await asyncio.gather(buy, sell, return_exceptions=True)
        assert not [r for r in results if isinstance(r, BaseException)]
        buy_log, sell_log = results
        await session.commit()

    async with factory() as verify:
        account = (await verify.execute(select(TradingAccount))).scalar_one()
        assert account.cash >= 0
        # Exact accounting: no update may be lost to the interleaving.
        # 100000 - buy.amount + sell.amount
        assert buy_log is not None and sell_log is not None
        expected = 100000.0 - buy_log.amount + sell_log.amount
        assert account.cash == pytest.approx(expected)
        assert sell_log.amount == pytest.approx(200 * 100.0)


def _detached_position(account_id: int, avg_cost: float, shares: int) -> Position:
    """A Position not yet added to the session (sell deletes/updates it)."""
    return Position(
        account_id=account_id,
        code="000002",
        name="卖出股",
        shares=shares,
        avg_cost=avg_cost,
        open_price=avg_cost,
        high_since_open=avg_cost,
        atr_at_buy=1.0,
        stop_loss_price=avg_cost * 0.9,
        tier=1,
    )


async def test_pyramid_add_never_overdraws(memory_engine, factory) -> None:
    """check_and_execute_pyramid_add shares the cash lock and cannot overdraw."""
    from app.services.trading_service import check_and_execute_pyramid_add

    async with factory() as session:
        account = _make_account(1000.0)
        session.add(account)
        await session.commit()
        await session.refresh(account)

        pos = _detached_position(account.id, 100.0, 100)
        pos.open_price = 100.0
        session.add(pos)
        await session.commit()
        await session.refresh(pos)

        # +20% triggers tier-2 add; add_value = 100*100*0.5 = 5000 >> cash 1000.
        log = await check_and_execute_pyramid_add(session, account, pos, current_price=120.0)
        await session.commit()

        assert log is None
        assert account.cash == pytest.approx(1000.0)
        assert pos.tier == 1


# ======================================================================
# (c) WS auth flag off -> behaviour unchanged
# ======================================================================

class _FakeWS:
    """Minimal WebSocket stand-in exposing only what authorize_ws reads."""

    def __init__(self, query: str = "", headers: dict | None = None):
        self.url = type("URL", (), {"query": query})()
        self.headers = headers or {}


def test_ws_auth_disabled_allows_everything(monkeypatch) -> None:
    from app.core.websocket import authorize_ws

    monkeypatch.setattr(settings, "ws_auth_enabled", False)
    monkeypatch.setattr(settings, "ws_auth_token", "")

    # No token, no origin -> still allowed (legacy behaviour preserved).
    ok, reason = authorize_ws(_FakeWS())
    assert ok is True, reason

    # Even with a configured token, the flag being off means no enforcement.
    monkeypatch.setattr(settings, "ws_auth_token", "secret")
    ok, _ = authorize_ws(_FakeWS())
    assert ok is True

    # And a hostile origin is not rejected while the flag is off.
    monkeypatch.setattr(settings, "ws_allowed_origins", ["https://app.example.com"])
    ok, _ = authorize_ws(_FakeWS(headers={"origin": "https://evil.example.com"}))
    assert ok is True


def test_ws_auth_enabled_enforces_token(monkeypatch) -> None:
    from app.core.websocket import authorize_ws

    monkeypatch.setattr(settings, "ws_auth_enabled", True)
    monkeypatch.setattr(settings, "ws_auth_token", "s3cret")
    monkeypatch.setattr(settings, "ws_allowed_origins", [])

    assert authorize_ws(_FakeWS()) == (False, "missing token")
    assert authorize_ws(_FakeWS(query="token=wrong"))[0] is False
    assert authorize_ws(_FakeWS(query="token=s3cret"))[0] is True
    assert authorize_ws(_FakeWS(headers={"authorization": "Bearer s3cret"}))[0] is True
    assert authorize_ws(_FakeWS(headers={"x-ws-token": "s3cret"}))[0] is True


def test_ws_auth_enabled_enforces_origin(monkeypatch) -> None:
    from app.core.websocket import authorize_ws

    monkeypatch.setattr(settings, "ws_auth_enabled", True)
    monkeypatch.setattr(settings, "ws_auth_token", "s3cret")
    monkeypatch.setattr(settings, "ws_allowed_origins", ["https://app.example.com"])

    assert authorize_ws(_FakeWS(query="token=s3cret", headers={"origin": "https://evil.example.com"}))[0] is False
    assert authorize_ws(_FakeWS(query="token=s3cret", headers={"origin": "https://app.example.com"}))[0] is True


async def test_ws_handle_ws_accepts_client_when_auth_disabled(monkeypatch) -> None:
    """End-to-end through MonitorHub.handle_ws over the real ASGI app."""
    from httpx import ASGITransport, AsyncClient

    from app.main import create_app

    monkeypatch.setattr(settings, "ws_auth_enabled", False)

    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.get("/api/health")
        assert resp.status_code == 200

    # handle_ws must at least reach accept() when auth is disabled.
    from app.core.websocket import monitor_hub

    accepted = {"v": False}

    class _Ws:
        url = type("URL", (), {"query": ""})()
        headers: dict = {}

        async def accept(self):
            accepted["v"] = True

        async def receive_text(self):
            from fastapi import WebSocketDisconnect

            raise WebSocketDisconnect()

    await monitor_hub.handle_ws(_Ws())
    assert accepted["v"] is True


async def test_ws_handle_ws_rejects_when_auth_enabled(monkeypatch) -> None:
    from app.core.websocket import monitor_hub

    monkeypatch.setattr(settings, "ws_auth_enabled", True)
    monkeypatch.setattr(settings, "ws_auth_token", "s3cret")
    monkeypatch.setattr(settings, "ws_allowed_origins", [])

    closed = {"code": None}
    accepted = {"v": False}

    class _Ws:
        url = type("URL", (), {"query": ""})()
        headers: dict = {}
        client = ("1.2.3.4", 1234)

        async def accept(self):
            accepted["v"] = True

        async def close(self, code=1000, reason=""):
            closed["code"] = code

    await monitor_hub.handle_ws(_Ws())
    assert accepted["v"] is False, "unauthenticated client must not be accepted"
    assert closed["code"] == 1008


# ======================================================================
# Scheduler: each coroutine gets its own session
# ======================================================================

async def test_factor_pipeline_uses_own_sessions() -> None:
    """Guard against regressing #4 / the old /rankings/compute crash.

    The concurrent worker must open its OWN session. Previously the API endpoint
    gathered 10 coroutines over one shared ``AsyncSession`` and died with
    ``IllegalStateChangeError``. The scheduler and the endpoint also each had a
    private copy of this loop; both now delegate to the pipeline below.
    """
    import inspect

    from app.pipelines import factor_pipeline

    src = inspect.getsource(factor_pipeline._compute_one)
    # The worker must OPEN its own session rather than accept an injected one.
    assert "AsyncSessionLocal()" in src, "worker must open its own session"
    assert "session: AsyncSession" not in src, "must not accept a shared session param"
    # And no module-level session may be closed over.
    mod_src = inspect.getsource(factor_pipeline)
    assert "get_history(ctx.session" not in mod_src


async def test_scheduler_delegates_to_shared_pipeline() -> None:
    """The scheduler must not carry its own copy of the factor pipeline.

    Two divergent copies is exactly how the shared-session bug survived in one
    of them; the fix is delegation, so assert that rather than the old body.
    """
    import inspect

    from app.core import scheduler as scheduler_mod

    src = inspect.getsource(scheduler_mod.run_daily_ranking)
    assert "run_full_ranking_pipeline" in src, "scheduler must delegate to the pipeline"
    assert "compute_factors_for_stock" not in src, "must not re-implement factor compute"
    assert "asyncio.gather" not in src, "concurrency belongs to the pipeline"


def test_pyramid_weight_unchanged() -> None:
    assert pyramid_weight(1) == 0.12
    assert pyramid_weight(5) == 0.10
    assert pyramid_weight(20) == 0.08


def test_trading_lock_is_per_event_loop() -> None:
    """The lock is created lazily per running loop (asyncio primitives bind to a loop)."""
    seen: list = []

    async def grab():
        lock = trading_service.get_trading_lock()
        seen.append(lock)
        # Same loop -> same lock instance, so it actually serializes.
        assert trading_service.get_trading_lock() is lock
        async with lock:
            pass
        return lock

    a = asyncio.run(grab())
    b = asyncio.run(grab())
    assert a is not b, "each event loop must get its own lock"
    assert len(seen) == 2


def test_trading_lock_survives_multiple_event_loops() -> None:
    """Regression: a module-level lock reused across loops raises RuntimeError."""
    async def cycle(n: int):
        async with trading_service.get_trading_lock():
            await asyncio.sleep(0)  # yielding inside the lock binds it to the loop
        return n

    for i in range(3):
        assert asyncio.run(cycle(i)) == i
