"""Tests for the ranking search filter.

Covers the regression behind the `A | B` -> `or_(A, B)` change in
`app.services.ranking_service.get_ranking_list`:

* the generated SQL must keep the OR inside its own parenthesised group, so it
  can never swallow the surrounding date/strategy filter;
* blank / whitespace-only search terms must behave exactly like "no search";
* a real search term must still filter correctly end-to-end.
"""

from datetime import date

import pytest
from sqlalchemy import select

from app.models.stock import StockInfo, StockRanking
from app.services.ranking_service import get_ranking_list


# --------------------------------------------------------------------------
# (a) SQL shape: the OR must be explicitly grouped
# --------------------------------------------------------------------------


def test_search_sql_keeps_or_grouped() -> None:
    """`or_(...)` must render as a single parenthesised group.

    This is the guard against the Python-operator trap: `&` binds tighter than
    `|`, so `base & a | b` degrades to `(base & a) | b` and the OR branch
    escapes the date/strategy filter. Using `or_()` (or wrapping the whole
    expression in parentheses) is the only safe spelling.
    """
    from sqlalchemy import or_

    base = (StockRanking.rank_date == date(2025, 1, 2)) & (StockRanking.strategy == "momentum")
    stmt = select(StockInfo.code).where(
        or_(StockInfo.code.contains("60"), StockInfo.name.contains("60"))
    )
    sql = str(stmt)

    # One explicit, balanced parenthesis pair around the OR.
    assert "(stocks.code LIKE" in sql
    assert sql.count("(") == sql.count(")"), sql

    # The grouped OR combined with AND keeps the filter scoped.
    combined = str(select(StockRanking).where(base & or_(
        StockInfo.code.contains("60"), StockInfo.name.contains("60")
    )))
    grouped = combined.split("WHERE", 1)[1]
    assert "AND ((stocks.code LIKE" in grouped, grouped

    # Regression guard: the un-parenthesised spelling really does leak.
    leaky = str(select(StockRanking).where(base & StockInfo.code.contains("60")
                                          | StockInfo.name.contains("60")))
    leaky_where = leaky.split("WHERE", 1)[1]
    assert "AND ((stocks.code LIKE" not in leaky_where, "expected the naive form to be ungrouped"

    # And the production form must NOT look like the leaky form.
    assert grouped != leaky_where


def test_ranking_service_uses_or_not_bitwise_pipe() -> None:
    """Source-level guard: no `contains(...) | ...contains(...)` in the service."""
    import inspect

    from app.services import ranking_service

    src = inspect.getsource(ranking_service.get_ranking_list)
    assert "or_(" in src
    assert "contains(search) |" not in src


# --------------------------------------------------------------------------
# fixtures / helpers
# --------------------------------------------------------------------------

TRADE_DATE = date(2025, 1, 2)


async def _seed(session):
    session.add_all([
        StockInfo(code="600519", name="贵州茅台"),
        StockInfo(code="000001", name="平安银行"),
        StockInfo(code="300750", name="宁德时代"),
    ])
    session.add_all([
        StockRanking(code="600519", rank_date=TRADE_DATE, strategy="momentum",
                     rank_position=1, total_score=95.0, industry="白酒"),
        StockRanking(code="000001", rank_date=TRADE_DATE, strategy="momentum",
                     rank_position=2, total_score=80.0, industry="银行"),
        StockRanking(code="300750", rank_date=TRADE_DATE, strategy="momentum",
                     rank_position=3, total_score=70.0, industry="电池"),
    ])
    await session.commit()


# --------------------------------------------------------------------------
# (b) blank / whitespace search behaves like no search
# --------------------------------------------------------------------------


@pytest.mark.parametrize("blank", ["", "   ", "\t", "\n", "  \t \n "])
async def test_blank_search_is_ignored(session, blank) -> None:
    """Blank search must return the full list, not an empty/like-%% scan."""
    await _seed(session)

    records, total = await get_ranking_list(
        session, TRADE_DATE, page=1, page_size=50, strategy="momentum", search=blank
    )

    assert total == 3
    assert [r["code"] for r in records] == ["600519", "000001", "300750"]


async def test_blank_search_does_not_query_candidates(session) -> None:
    """Whitespace-only search must not issue the candidate StockInfo query.

    We assert on the SQL actually emitted: a blank term should produce no
    `stocks.code LIKE` lookup at all (that would be a full-table scan).
    """
    await _seed(session)

    seen: list[str] = []
    real_execute = session.execute

    async def spy(stmt, *args, **kwargs):
        seen.append(str(stmt))
        return await real_execute(stmt, *args, **kwargs)

    session.execute = spy  # type: ignore[method-assign]
    try:
        records, total = await get_ranking_list(
            session, TRADE_DATE, page=1, page_size=50, strategy="momentum", search="   "
        )
    finally:
        session.execute = real_execute  # type: ignore[method-assign]

    assert total == 3 and len(records) == 3
    assert not any("LIKE" in s for s in seen), seen


async def test_none_search_returns_everything(session) -> None:
    await _seed(session)

    records, total = await get_ranking_list(
        session, TRADE_DATE, page=1, page_size=50, strategy="momentum", search=None
    )
    assert total == 3
    assert len(records) == 3


# --------------------------------------------------------------------------
# (c) a real search term still filters correctly
# --------------------------------------------------------------------------


async def test_search_by_code_prefix(session) -> None:
    await _seed(session)

    records, total = await get_ranking_list(
        session, TRADE_DATE, page=1, page_size=50, strategy="momentum", search="000001"
    )
    assert total == 1
    assert records[0]["code"] == "000001"
    assert records[0]["name"] == "平安银行"


async def test_search_by_name_substring(session) -> None:
    await _seed(session)

    records, total = await get_ranking_list(
        session, TRADE_DATE, page=1, page_size=50, strategy="momentum", search="银行"
    )
    assert total == 1
    assert records[0]["code"] == "000001"


async def test_search_matching_nothing_returns_empty(session) -> None:
    await _seed(session)

    records, total = await get_ranking_list(
        session, TRADE_DATE, page=1, page_size=50, strategy="momentum", search="ZZZZZZ"
    )
    assert records == []
    assert total == 0


async def test_search_respects_strategy_filter(session) -> None:
    """The critical correctness property: search must not bypass strategy/date.

    The same code exists under a second strategy; searching for it under
    `momentum` must not leak the `value` row (this is what an ungrouped OR
    would do).
    """
    await _seed(session)
    session.add(
        StockRanking(code="600519", rank_date=TRADE_DATE, strategy="value",
                     rank_position=1, total_score=60.0, industry="白酒")
    )
    await session.commit()

    records, total = await get_ranking_list(
        session, TRADE_DATE, page=1, page_size=50, strategy="momentum", search="600519"
    )
    assert total == 1
    assert "600519" in [r["code"] for r in records]

    # And the other strategy still resolves independently.
    other, other_total = await get_ranking_list(
        session, TRADE_DATE, page=1, page_size=50, strategy="value", search="600519"
    )
    assert other_total == 1

    # Date filter must hold too: a different date yields nothing.
    none_records, none_total = await get_ranking_list(
        session, date(2025, 1, 3), page=1, page_size=50, strategy="momentum", search="600519"
    )
    assert none_records == [] and none_total == 0


async def test_search_whitespace_is_stripped_before_matching(session) -> None:
    """A padded term must match the same rows as the trimmed term."""
    await _seed(session)

    padded, padded_total = await get_ranking_list(
        session, TRADE_DATE, page=1, page_size=50, strategy="momentum", search="  600519  "
    )
    assert padded_total == 1
    assert padded[0]["code"] == "600519"


async def test_candidate_codes_are_capped(session, monkeypatch) -> None:
    """An over-broad term must truncate rather than emit an oversized IN clause."""
    from app.services import ranking_service

    monkeypatch.setattr(ranking_service, "MAX_SEARCH_CANDIDATES", 2)
    await _seed(session)

    records, total = await get_ranking_list(
        session, TRADE_DATE, page=1, page_size=50, strategy="momentum", search="0"
    )
    # All three seeded codes contain "0"; the cap keeps only 2 -> at most 2 rows.
    assert total <= 2
    assert len(records) <= 2
