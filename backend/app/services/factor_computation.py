"""Helper functions for computing technical indicators using vectorised
pandas / numpy operations.

All functions accept and return pandas Series, operate element-wise on a
single asset row, and propagate NaN naturally.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

import app.services.factor_config as cfg

# ===========================================================================
# Moving averages
# ===========================================================================


def compute_ma(df: pd.DataFrame, window: int) -> pd.Series:
    """Simple Moving Average.

    Parameters
    ----------
    df :
        DataFrame with at least a ``close`` column (MultiIndex: symbol x date).
    window :
        Look-back window.

    Returns
    -------
    pd.Series
        SMA values aligned to the original index.
    """
    closes = df["close"]
    if isinstance(closes.index, pd.MultiIndex):
        return closes.groupby(level=0).apply(lambda s: s.rolling(window=window, min_periods=window).mean()).droplevel(0)
    return closes.rolling(window=window, min_periods=window).mean()


def compute_ema(df: pd.DataFrame, window: int) -> pd.Series:
    """Exponential Moving Average.

    Parameters
    ----------
    df :
        DataFrame with at least a ``close`` column.
    window :
        Smoothing window.

    Returns
    -------
    pd.Series
        EMA values aligned to the original index.
    """
    closes = df["close"]
    if isinstance(closes.index, pd.MultiIndex):
        return closes.groupby(level=0).apply(lambda s: s.ewm(span=window, adjust=False).mean()).droplevel(0)
    return closes.ewm(span=window, adjust=False).mean()


# ===========================================================================
# RSI
# ===========================================================================


def compute_rsi(df: pd.DataFrame, period: int = cfg.RSI_PERIOD) -> pd.Series:
    """Relative Strength Index (Wilder's smoothing).

    Parameters
    ----------
    df :
        DataFrame with a ``close`` column.
    period :
        RSI look-back period.

    Returns
    -------
    pd.Series
        RSI values in [0, 100], NaN where insufficient data.
    """
    closes = df["close"]

    delta = closes.groupby(level=0).diff() if isinstance(closes.index, pd.MultiIndex) else closes.diff()

    gain = delta.clip(lower=0.0)
    loss = (-delta).clip(lower=0.0)

    avg_gain = gain.ewm(com=period - 1, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(com=period - 1, min_periods=period, adjust=False).mean()

    rs = avg_gain / avg_loss
    rsi = 100.0 - (100.0 / (1.0 + rs))
    return rsi


# ===========================================================================
# MACD
# ===========================================================================


def compute_macd(
    df: pd.DataFrame,
    fast: int = cfg.MACD_PARAMS[0],
    slow: int = cfg.MACD_PARAMS[1],
    signal: int = cfg.MACD_PARAMS[2],
) -> tuple[pd.Series, pd.Series, pd.Series]:
    """MACD line, Signal line, and Histogram.

    Parameters
    ----------
    df :
        DataFrame with a ``close`` column.
    fast, slow, signal :
        EMA window lengths.

    Returns
    -------
    dif : pd.Series
        MACD line (EMA_fast - EMA_slow).
    dea : pd.Series
        Signal line (EMA of DIF).
    histogram : pd.Series
        DIF - DEA.
    """
    if isinstance(df["close"].index, pd.MultiIndex):
        ema_fast = df.groupby(level=0)["close"].apply(lambda s: s.ewm(span=fast, adjust=False).mean()).droplevel(0)
        ema_slow = df.groupby(level=0)["close"].apply(lambda s: s.ewm(span=slow, adjust=False).mean()).droplevel(0)
    else:
        ema_fast = df["close"].ewm(span=fast, adjust=False).mean()
        ema_slow = df["close"].ewm(span=slow, adjust=False).mean()

    dif = ema_fast - ema_slow

    if isinstance(dif.index, pd.MultiIndex):
        dea = dif.groupby(level=0).apply(lambda s: s.ewm(span=signal, adjust=False).mean()).droplevel(0)
    else:
        dea = dif.ewm(span=signal, adjust=False).mean()

    histogram = dif - dea
    return dif, dea, histogram


# ===========================================================================
# KDJ
# ===========================================================================


def compute_kdj(
    df: pd.DataFrame,
    n: int = cfg.KDJ_PARAMS[0],
    m1: int = cfg.KDJ_PARAMS[1],
    m2: int = cfg.KDJ_PARAMS[2],
) -> tuple[pd.Series, pd.Series, pd.Series]:
    """KDJ stochastic oscillator.

    Parameters
    ----------
    df :
        DataFrame with ``high``, ``low``, ``close`` columns.
    n, m1, m2 :
        KDJ period and smoothing parameters.

    Returns
    -------
    k : pd.Series
        Slow K line.
    d : pd.Series
        Slow D line.
    j : pd.Series
        J line (3*K - 2*D).
    """
    low_n = df["low"].rolling(window=n, min_periods=n).min()
    high_n = df["high"].rolling(window=n, min_periods=n).max()
    close = df["close"]

    rsv = (close - low_n) / (high_n - low_n)
    rsv = rsv.fillna(50.0)

    # Iterative SMA for K and D (vectorised via ewm as a fast approx)
    # For correctness we use a small loop-equivalent via pandas rolling/ewm
    k = rsv.ewm(com=m1 - 1, adjust=False, min_periods=m1).mean()
    d = k.ewm(com=m2 - 1, adjust=False, min_periods=m2).mean()
    j = 3.0 * k - 2.0 * d

    return k, d, j


# ===========================================================================
# Bollinger Bands
# ===========================================================================


def compute_bollinger_bands(
    df: pd.DataFrame,
    window: int = cfg.BOLLINGER_PARAMS[0],
    num_std: float = cfg.BOLLINGER_PARAMS[1],
) -> tuple[pd.Series, pd.Series, pd.Series]:
    """Bollinger Bands (upper, middle=SMA, lower).

    Parameters
    ----------
    df :
        DataFrame with a ``close`` column.
    window :
        SMA window.
    num_std :
        Number of standard deviations for band width.

    Returns
    -------
    upper : pd.Series
        Upper Bollinger Band.
    middle : pd.Series
        Middle band (SMA).
    lower : pd.Series
        Lower Bollinger Band.
    """
    close = df["close"]
    if isinstance(close.index, pd.MultiIndex):
        sma = close.groupby(level=0).apply(lambda s: s.rolling(window=window, min_periods=window).mean()).droplevel(0)
        std = close.groupby(level=0).apply(lambda s: s.rolling(window=window, min_periods=window).std()).droplevel(0)
    else:
        sma = close.rolling(window=window, min_periods=window).mean()
        std = close.rolling(window=window, min_periods=window).std()

    upper = sma + num_std * std
    lower = sma - num_std * std
    return upper, sma, lower


# ===========================================================================
# Standardisation
# ===========================================================================


def standardize_cross_sectional(values: pd.Series) -> pd.Series:
    """Cross-sectional Z-score standardization.

    For MultiIndex DataFrames this is applied **across stocks** at each
    time-step (group by date level).

    Parameters
    ----------
    values :
        Factor values, index may be MultiIndex (symbol, date).

    Returns
    -------
    pd.Series
        Z-scores with the same index. NaN where the denominator is zero.
    """
    if isinstance(values.index, pd.MultiIndex):
        # levels are typically (symbol, date) – date is the cross-section axis
        date_level = values.index.names.index("date") if "date" in values.index.names else 1
        z = values.groupby(level=date_level).transform(lambda s: (s - s.mean()) / s.std())
    else:
        z = (values - values.mean()) / values.std()
    return z


def industry_neutralize(values: pd.Series, industries: pd.Series) -> pd.Series:
    """Industry-neutral Z-score: demean within each industry, then z-score.

    Parameters
    ----------
    values :
        Factor scores (z-scored internally).
    industries :
        Industry labels aligned to ``values``.

    Returns
    -------
    pd.Series
        Industry-neutral Z-scores with the same index as ``values``.
    """
    grouped = values.groupby(industries)
    demeaned = values - grouped.transform("mean")
    return standardize_series(demeaned)


def standardize_series(values: pd.Series) -> pd.Series:
    """Simple global Z-score standardization (no group structure).

    Parameters
    ----------
    values :
        Numeric series.

    Returns
    -------
    pd.Series
        Z-scored series. Returns NaN-filled series of same length if std is
        zero or indeterminate.
    """
    mean = values.mean()
    std = values.std()
    if std is None or std == 0 or np.isnan(std):
        return pd.Series(np.nan, index=values.index, dtype=float)
    return (values - mean) / std
