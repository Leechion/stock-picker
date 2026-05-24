"""Factor computation configuration constants.

Defines all factor categories, individual factor weights, category weights,
and simulation parameters for fundamental data (since real fundamental data
requires a paid API in the MVP).
"""

from __future__ import annotations

from typing import Final

# Category group weights (sum must equal 1.0)
CATEGORY_WEIGHTS: Final[dict[str, float]] = {
    "technical": 0.4,
    "fundamental": 0.4,
    "sentiment": 0.2,
}

FACTOR_CONFIG: Final[dict[str, dict]] = {
    "technical": {
        "ma_crossover": {"weight": 0.25},
        "macd": {"weight": 0.25},
        "rsi": {"weight": 0.20},
        "kdj": {"weight": 0.15},
        "bollinger": {"weight": 0.10},
        "volume_ratio": {"weight": 0.05},
        "category_weight": 0.4,
    },
    "fundamental": {
        "pe_score": {"weight": 0.20},
        "pb_score": {"weight": 0.15},
        "roe_score": {"weight": 0.25},
        "revenue_growth_score": {"weight": 0.20},
        "profit_growth_score": {"weight": 0.15},
        "debt_ratio_score": {"weight": 0.05},
        "category_weight": 0.4,
    },
    "sentiment": {
        "turnover_score": {"weight": 0.12},
        "capital_flow_score": {"weight": 0.12},
        "real_capital_flow_score": {"weight": 0.22},
        "chip_concentration_score": {"weight": 0.12},
        "sector_heat_score": {"weight": 0.17},
        "momentum_5d_score": {"weight": 0.12},
        "momentum_20d_score": {"weight": 0.13},
        "category_weight": 0.2,
    },
}

# ============================================================
# Technical indicator hyper-parameters
# ============================================================

#: Moving average windows (short, medium, long)
MA_WINDOWS: Final[tuple[int, int, int]] = (5, 20, 60)

#: MACD parameters (fast, slow, signal)
MACD_PARAMS: Final[tuple[int, int, int]] = (12, 26, 9)

#: RSI period
RSI_PERIOD: Final[int] = 14

#: KDJ parameters (N, M1, M2)
KDJ_PARAMS: Final[tuple[int, int, int]] = (9, 3, 3)

#: Bollinger Band parameters (window, standard deviations)
BOLLINGER_PARAMS: Final[tuple[int, float]] = (20, 2.0)

#: Volume MA windows for ratio computation
VOLUME_MA_SHORT: Final[int] = 5
VOLUME_MA_LONG: Final[int] = 20

#: KDJ oversold / overbought thresholds
KDJ_OVERSOLD: Final[float] = 20.0
KDJ_OVERBOUGHT: Final[float] = 80.0

# ============================================================
# Fundamental / sentiment simulation parameters (MVP)
# ============================================================

#: Simulated PE ratio range across industries (for percentile scoring)
SIM_PE_RANGE: Final[tuple[float, float]] = (5.0, 100.0)

#: Simulated PB ratio range across industries
SIM_PB_RANGE: Final[tuple[float, float]] = (0.2, 15.0)

#: Simulated ROE range (12-month, percentage)
SIM_ROE_RANGE: Final[tuple[float, float]] = (-20.0, 60.0)

#: Simulated asset-liability ratio range
SIM_DEBT_RATIO_RANGE: Final[tuple[float, float]] = (10.0, 90.0)

#: Float-share multiplier for turnover estimation (MVP placeholder)
FLOAT_SHARES_MULTIPLIER: Final[float] = 1e8

#: Capital flow estimation window (days)
CAPITAL_FLOW_WINDOW: Final[int] = 5
