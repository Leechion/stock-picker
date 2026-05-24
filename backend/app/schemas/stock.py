from datetime import date, datetime
from typing import Any

from pydantic import BaseModel


class HealthResponse(BaseModel):
    status: str
    version: str
    database: str


class SyncResponse(BaseModel):
    status: str
    message: str
    synced_count: int = 0


class HistoryResponse(BaseModel):
    code: str
    data: list[dict[str, Any]]


class RankingComputeResponse(BaseModel):
    status: str
    date: date
    stocks_computed: int


class StockListRead(BaseModel):
    code: str
    name: str
    industry: str | None = None
    model_config = {"from_attributes": True}


class FactorRead(BaseModel):
    id: int
    code: str
    factor_name: str
    factor_type: str
    value: float
    computed_at: datetime | None = None


class FactorGroupRead(BaseModel):
    technical_factors: list[FactorRead]
    fundamental_factors: list[FactorRead]
    sentiment_factors: list[FactorRead]


class StockRankingRead(BaseModel):
    id: int
    code: str
    rank_date: date
    rank_position: int
    total_score: float
    industry: str | None = None
    industry_rank: int | None = None
    model_config = {"from_attributes": True}
