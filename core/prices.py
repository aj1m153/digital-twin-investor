"""
yfinance wrapper for the digital-twin investor.

Works for both stocks ("AAPL") and crypto ("BTC-USD", "ETH-USD"). All prices
are returned in USD.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from functools import lru_cache

import pandas as pd
import yfinance as yf


def validate_ticker(ticker: str) -> bool:
    """Return True if yfinance recognises the ticker and returns recent data."""
    try:
        df = yf.Ticker(ticker).history(period="5d", auto_adjust=True)
        return not df.empty
    except Exception:
        return False


def fetch_history(
    ticker: str, period: str = "1y", interval: str = "1d"
) -> pd.DataFrame:
    """Historical OHLCV for a single ticker. Returns empty DataFrame on failure."""
    try:
        df = yf.Ticker(ticker).history(
            period=period, interval=interval, auto_adjust=True
        )
        if df.empty:
            return df
        df.index = pd.to_datetime(df.index)
        # Strip timezone for easier downstream comparisons
        if df.index.tz is not None:
            df.index = df.index.tz_localize(None)
        return df
    except Exception:
        return pd.DataFrame()


def fetch_latest_prices(tickers: list[str]) -> dict[str, float]:
    """
    Current (or most recent close) price for each ticker.
    Uses the last available row from a 5-day window — robust to weekends
    and missing data.
    """
    prices: dict[str, float] = {}
    for t in tickers:
        df = fetch_history(t, period="5d")
        if not df.empty:
            prices[t.upper()] = float(df["Close"].iloc[-1])
    return prices


def fetch_today_open(tickers: list[str]) -> dict[str, float]:
    """
    Today's opening price per ticker. For stocks, this requires the call to be
    made after 9:30 AM ET. For crypto (24/7), returns the daily bar's open.
    Falls back to latest close if today's open is unavailable.
    """
    out: dict[str, float] = {}
    today = datetime.utcnow().date()
    for t in tickers:
        df = fetch_history(t, period="5d")
        if df.empty:
            continue
        # Find a row whose date matches today (UTC); else use the last row
        matching = df[df.index.date == today]
        if not matching.empty and not pd.isna(matching["Open"].iloc[0]):
            out[t.upper()] = float(matching["Open"].iloc[0])
        else:
            out[t.upper()] = float(df["Close"].iloc[-1])
    return out
