"""AI pick model — stores daily AI stock recommendations for tomorrow."""
from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Date, DateTime, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class AIPick(Base):
    __tablename__ = "ai_picks"
    __table_args__ = {"sqlite_autoincrement": True}

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    pick_date: Mapped[date] = mapped_column(Date, index=True)
    code: Mapped[str] = mapped_column(String(10))
    name: Mapped[str] = mapped_column(String(50))
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence: Mapped[str | None] = mapped_column(String(20), nullable=True)
    price_at_pick: Mapped[float | None] = mapped_column(Float, nullable=True)
    next_day_open: Mapped[float | None] = mapped_column(Float, nullable=True)
    next_day_close: Mapped[float | None] = mapped_column(Float, nullable=True)
    next_day_change_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    backtest_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
