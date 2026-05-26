"""Unit tests for factor computation engine."""

import numpy as np
import pandas as pd

from app.services.factor_engine import (
    compute_factors_for_stock,
    compute_category_score,
    compute_total_score,
    standardize_factors_cross_sectional,
)


def make_test_df(length: int = 100) -> pd.DataFrame:
    """Create synthetic daily OHLCV data."""
    np.random.seed(42)
    close = pd.Series(10 + np.cumsum(np.random.randn(length) * 0.1), name="close")
    high = close + np.abs(np.random.randn(length) * 0.2)
    low = close - np.abs(np.random.randn(length) * 0.2)
    volume = pd.Series(np.random.uniform(1e6, 1e7, size=length), name="volume")
    return pd.DataFrame({"close": close, "high": high, "low": low, "volume": volume})


CODE = "600519"


def test_compute_factors_returns_all_factors():
    df = make_test_df(120)
    factors = compute_factors_for_stock(df, CODE)
    assert len(factors) == 19
    types = [f["factor_type"].value for f in factors]
    assert types.count("technical") == 6
    assert types.count("fundamental") == 6
    assert types.count("sentiment") == 7


def test_compute_factors_empty_df():
    df = pd.DataFrame()
    factors = compute_factors_for_stock(df, "000001")
    assert factors == []


def test_compute_factors_values_in_range():
    df = make_test_df(250)
    factors = compute_factors_for_stock(df, CODE)
    for f in factors:
        v = f["value"]
        assert not np.isnan(v), f"Factor {f['factor_name']} value is NaN"
        assert -1.5 <= v <= 1.5, f"Factor {f['factor_name']} value {v} out of range"


def test_compute_category_score():
    TEnum = type("TEnum", (), {"value": "technical"})
    factors = [
        {"factor_name": "ma_crossover", "factor_type": TEnum(), "value": 0.8},
        {"factor_name": "macd", "factor_type": TEnum(), "value": 0.6},
    ]
    score = compute_category_score(factors, "technical", 0.4)
    assert -50 <= score <= 50


def test_compute_total_score():
    df = make_test_df(250)
    factors = compute_factors_for_stock(df, CODE)
    total = compute_total_score(factors)
    assert not np.isnan(total), "total score is NaN"
    assert 0 <= total <= 100


def test_fundamentals_override_simulation():
    """Real fundamental data should produce different scores than missing data."""
    df = make_test_df(250)
    # With real fundamental data
    fd = {"pe_ttm": 25.0, "pb": 3.0, "roe": 15.0, "revenue_growth": 10.0, "profit_growth": 20.0, "debt_ratio": 45.0}
    factors_real = compute_factors_for_stock(df, CODE, fd)
    # Without fundamental data (all None)
    factors_none = compute_factors_for_stock(df, CODE, None)

    # pe_score should differ between real and none
    pe_real = next(f["value"] for f in factors_real if f["factor_name"] == "pe_score")
    pe_none = next(f["value"] for f in factors_none if f["factor_name"] == "pe_score")
    assert pe_real != pe_none, "Real PE data should produce different score than None"


def test_fundamentals_none_returns_zero():
    """Missing fundamentals should return 0.0 for all fundamental factors."""
    df = make_test_df(250)
    factors = compute_factors_for_stock(df, CODE, None)
    fund_scores = [f["value"] for f in factors if f["factor_type"].value == "fundamental"]
    assert all(v == 0.0 for v in fund_scores), f"Expected all 0.0, got {fund_scores}"


def test_standardize_cross_sectional():
    stock_factors = {
        "A": [
            {"factor_name": "rsi", "factor_type": "technical", "value": 1.0},
            {"factor_name": "macd", "factor_type": "technical", "value": 0.5},
        ],
        "B": [
            {"factor_name": "rsi", "factor_type": "technical", "value": -1.0},
            {"factor_name": "macd", "factor_type": "technical", "value": -0.5},
        ],
    }
    result = standardize_factors_cross_sectional(stock_factors)
    assert len(result) == 2
    assert abs(result["A"][0]["value"] - 1.0) < 0.01
    assert abs(result["B"][0]["value"] - (-1.0)) < 0.01


def test_standardize_cross_sectional_empty():
    result = standardize_factors_cross_sectional({})
    assert result == {}


def test_standardize_cross_sectional_zero_std():
    stock_factors = {
        "A": [{"factor_name": "rsi", "factor_type": "technical", "value": 0.5}],
        "B": [{"factor_name": "rsi", "factor_type": "technical", "value": 0.5}],
    }
    result = standardize_factors_cross_sectional(stock_factors)
    assert result["A"][0]["value"] == 0.5
    assert result["B"][0]["value"] == 0.5
