from __future__ import annotations

from datetime import date, datetime
from enum import Enum

from sqlalchemy import Date, DateTime, Float, ForeignKey, Integer, String
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class StockInfo(Base):
    __tablename__ = "stocks"

    code: Mapped[str] = mapped_column(String(10), primary_key=True)
    name: Mapped[str] = mapped_column(String(50))
    industry: Mapped[str | None] = mapped_column(String(50))
    market: Mapped[str] = mapped_column(String(10), default="main")
    list_date: Mapped[date | None] = mapped_column(Date)

    daily_data: Mapped[list[StockDaily]] = relationship(back_populates="stock", lazy="selectin")


class StockDaily(Base):
    __tablename__ = "stock_daily"
    __table_args__ = {"sqlite_autoincrement": True}

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(10), ForeignKey("stocks.code"), index=True)
    trade_date: Mapped[date] = mapped_column(Date)

    open: Mapped[float] = mapped_column(Float)
    close: Mapped[float] = mapped_column(Float)
    high: Mapped[float] = mapped_column(Float)
    low: Mapped[float] = mapped_column(Float)
    volume: Mapped[float] = mapped_column(Float)
    amount: Mapped[float] = mapped_column(Float)
    change_pct: Mapped[float | None] = mapped_column(Float)

    stock: Mapped[StockInfo] = relationship(back_populates="daily_data")


class FactorType(str, Enum):
    TECHNICAL = "technical"
    FUNDAMENTAL = "fundamental"
    SENTIMENT = "sentiment"


class FactorValue(Base):
    __tablename__ = "factor_values"
    __table_args__ = {"sqlite_autoincrement": True}

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(10), index=True)
    factor_name: Mapped[str] = mapped_column(String(50), index=True)
    factor_type: Mapped[FactorType] = mapped_column(SAEnum(FactorType))
    value: Mapped[float] = mapped_column(Float)
    computed_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


class StockFundamental(Base):
    """Cached fundamental data per stock (refreshed weekly)."""

    __tablename__ = "stock_fundamentals"

    code: Mapped[str] = mapped_column(String(10), ForeignKey("stocks.code"), primary_key=True)
    pe_ttm: Mapped[float | None] = mapped_column(Float, nullable=True)
    pb: Mapped[float | None] = mapped_column(Float, nullable=True)
    roe: Mapped[float | None] = mapped_column(Float, nullable=True)
    revenue_growth: Mapped[float | None] = mapped_column(Float, nullable=True)
    profit_growth: Mapped[float | None] = mapped_column(Float, nullable=True)
    debt_ratio: Mapped[float | None] = mapped_column(Float, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


class StockRanking(Base):
    __tablename__ = "stock_rankings"
    __table_args__ = {"sqlite_autoincrement": True}

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(10), index=True)
    rank_date: Mapped[date] = mapped_column(Date, index=True)
    strategy: Mapped[str] = mapped_column(String(50), index=True, default="default")
    rank_position: Mapped[int] = mapped_column(Integer)
    total_score: Mapped[float] = mapped_column(Float)
    industry: Mapped[str | None] = mapped_column(String(50))
    industry_rank: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tech_score: Mapped[float] = mapped_column(Float, default=0.0)
    fund_score: Mapped[float] = mapped_column(Float, default=0.0)
    sent_score: Mapped[float] = mapped_column(Float, default=0.0)
    computed_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
