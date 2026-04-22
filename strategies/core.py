"""
Trading strategy implementations.

Each strategy is a callable taking:
    portfolio:  dict with keys {cash, positions: {ticker: shares}, tickers: list[str]}
    history:    dict[ticker] -> pd.DataFrame with OHLCV indexed by date
    params:     dict of strategy-specific parameters

and returning a list of Signal dicts:
    {"ticker": str, "action": "buy"|"sell"|"hold",
     "size": "allocation" | "full_position" | {"dollars": float},
     "reason": str}

The executor translates signals into actual trades using current prices.
"""
from __future__ import annotations

from typing import Callable, TypedDict

import numpy as np
import pandas as pd


class Signal(TypedDict):
    ticker: str
    action: str  # "buy" | "sell" | "hold"
    size: object  # "allocation" | "full_position" | {"dollars": float}
    reason: str


# ════════════════════════════════════════════════
# Technical indicators
# ════════════════════════════════════════════════
def sma(series: pd.Series, window: int) -> pd.Series:
    return series.rolling(window).mean()


def rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0).rolling(period).mean()
    loss = -delta.clip(upper=0).rolling(period).mean()
    rs = gain / loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def macd(
    series: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9
) -> tuple[pd.Series, pd.Series]:
    ema_fast = series.ewm(span=fast, adjust=False).mean()
    ema_slow = series.ewm(span=slow, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    return macd_line, signal_line


def bollinger(
    series: pd.Series, window: int = 20, num_std: float = 2.0
) -> tuple[pd.Series, pd.Series, pd.Series]:
    mid = series.rolling(window).mean()
    std = series.rolling(window).std()
    upper = mid + num_std * std
    lower = mid - num_std * std
    return lower, mid, upper


# ════════════════════════════════════════════════
# Strategy implementations
# ════════════════════════════════════════════════
def _held(portfolio: dict, ticker: str) -> bool:
    return portfolio["positions"].get(ticker.upper(), 0) > 1e-9


def buy_and_hold(portfolio: dict, history: dict, params: dict) -> list[Signal]:
    """On first run only, split cash equally across tickers and buy."""
    signals: list[Signal] = []
    # Only buy if we have cash and no positions yet
    if portfolio["cash"] < 1 or any(
        portfolio["positions"].get(t.upper(), 0) > 0 for t in portfolio["tickers"]
    ):
        return [{"ticker": t, "action": "hold", "size": "allocation",
                 "reason": "buy & hold: already deployed"} for t in portfolio["tickers"]]
    for t in portfolio["tickers"]:
        signals.append({
            "ticker": t,
            "action": "buy",
            "size": "allocation",
            "reason": "buy & hold: initial purchase",
        })
    return signals


def sma_crossover(portfolio: dict, history: dict, params: dict) -> list[Signal]:
    """
    Golden / death cross.
    Buy when fast SMA crosses above slow SMA. Sell when fast crosses below.
    """
    fast_p = int(params.get("fast", 50))
    slow_p = int(params.get("slow", 200))
    signals: list[Signal] = []
    for t in portfolio["tickers"]:
        df = history.get(t.upper())
        if df is None or len(df) < slow_p + 2:
            signals.append({"ticker": t, "action": "hold", "size": "allocation",
                           "reason": "insufficient history"})
            continue
        close = df["Close"]
        f = sma(close, fast_p)
        s = sma(close, slow_p)
        if pd.isna(f.iloc[-2]) or pd.isna(s.iloc[-2]):
            signals.append({"ticker": t, "action": "hold", "size": "allocation",
                           "reason": "SMA not yet valid"})
            continue
        cross_up = f.iloc[-2] <= s.iloc[-2] and f.iloc[-1] > s.iloc[-1]
        cross_down = f.iloc[-2] >= s.iloc[-2] and f.iloc[-1] < s.iloc[-1]
        if cross_up and not _held(portfolio, t):
            signals.append({
                "ticker": t, "action": "buy", "size": "allocation",
                "reason": f"SMA{fast_p} crossed above SMA{slow_p} (golden cross)",
            })
        elif cross_down and _held(portfolio, t):
            signals.append({
                "ticker": t, "action": "sell", "size": "full_position",
                "reason": f"SMA{fast_p} crossed below SMA{slow_p} (death cross)",
            })
        else:
            signals.append({
                "ticker": t, "action": "hold", "size": "allocation",
                "reason": f"no crossover (fast={f.iloc[-1]:.2f}, slow={s.iloc[-1]:.2f})",
            })
    return signals


def rsi_mean_reversion(portfolio: dict, history: dict, params: dict) -> list[Signal]:
    """Buy when RSI < oversold, sell when RSI > overbought."""
    period = int(params.get("period", 14))
    oversold = float(params.get("oversold", 30))
    overbought = float(params.get("overbought", 70))
    signals: list[Signal] = []
    for t in portfolio["tickers"]:
        df = history.get(t.upper())
        if df is None or len(df) < period + 2:
            signals.append({"ticker": t, "action": "hold", "size": "allocation",
                           "reason": "insufficient history"})
            continue
        r = rsi(df["Close"], period).iloc[-1]
        if pd.isna(r):
            signals.append({"ticker": t, "action": "hold", "size": "allocation",
                           "reason": "RSI undefined"})
        elif r < oversold and not _held(portfolio, t):
            signals.append({
                "ticker": t, "action": "buy", "size": "allocation",
                "reason": f"RSI={r:.1f} below {oversold} (oversold)",
            })
        elif r > overbought and _held(portfolio, t):
            signals.append({
                "ticker": t, "action": "sell", "size": "full_position",
                "reason": f"RSI={r:.1f} above {overbought} (overbought)",
            })
        else:
            signals.append({
                "ticker": t, "action": "hold", "size": "allocation",
                "reason": f"RSI={r:.1f} in neutral zone",
            })
    return signals


def macd_momentum(portfolio: dict, history: dict, params: dict) -> list[Signal]:
    """Buy on MACD-above-signal cross, sell on the opposite cross."""
    fast = int(params.get("fast", 12))
    slow = int(params.get("slow", 26))
    sig_p = int(params.get("signal", 9))
    signals: list[Signal] = []
    for t in portfolio["tickers"]:
        df = history.get(t.upper())
        if df is None or len(df) < slow + sig_p + 2:
            signals.append({"ticker": t, "action": "hold", "size": "allocation",
                           "reason": "insufficient history"})
            continue
        macd_line, signal_line = macd(df["Close"], fast, slow, sig_p)
        if pd.isna(macd_line.iloc[-2]) or pd.isna(signal_line.iloc[-2]):
            signals.append({"ticker": t, "action": "hold", "size": "allocation",
                           "reason": "MACD not yet valid"})
            continue
        cross_up = (macd_line.iloc[-2] <= signal_line.iloc[-2]
                    and macd_line.iloc[-1] > signal_line.iloc[-1])
        cross_down = (macd_line.iloc[-2] >= signal_line.iloc[-2]
                      and macd_line.iloc[-1] < signal_line.iloc[-1])
        if cross_up and not _held(portfolio, t):
            signals.append({
                "ticker": t, "action": "buy", "size": "allocation",
                "reason": f"MACD crossed above signal ({macd_line.iloc[-1]:.3f} > {signal_line.iloc[-1]:.3f})",
            })
        elif cross_down and _held(portfolio, t):
            signals.append({
                "ticker": t, "action": "sell", "size": "full_position",
                "reason": f"MACD crossed below signal ({macd_line.iloc[-1]:.3f} < {signal_line.iloc[-1]:.3f})",
            })
        else:
            signals.append({
                "ticker": t, "action": "hold", "size": "allocation",
                "reason": "no MACD cross",
            })
    return signals


def bollinger_mean_reversion(
    portfolio: dict, history: dict, params: dict
) -> list[Signal]:
    """Buy when close < lower band, sell when close > upper band."""
    window = int(params.get("window", 20))
    num_std = float(params.get("num_std", 2.0))
    signals: list[Signal] = []
    for t in portfolio["tickers"]:
        df = history.get(t.upper())
        if df is None or len(df) < window + 2:
            signals.append({"ticker": t, "action": "hold", "size": "allocation",
                           "reason": "insufficient history"})
            continue
        lower, mid, upper = bollinger(df["Close"], window, num_std)
        price = df["Close"].iloc[-1]
        if pd.isna(lower.iloc[-1]):
            signals.append({"ticker": t, "action": "hold", "size": "allocation",
                           "reason": "Bollinger not yet valid"})
        elif price < lower.iloc[-1] and not _held(portfolio, t):
            signals.append({
                "ticker": t, "action": "buy", "size": "allocation",
                "reason": f"price {price:.2f} below lower band {lower.iloc[-1]:.2f}",
            })
        elif price > upper.iloc[-1] and _held(portfolio, t):
            signals.append({
                "ticker": t, "action": "sell", "size": "full_position",
                "reason": f"price {price:.2f} above upper band {upper.iloc[-1]:.2f}",
            })
        else:
            signals.append({
                "ticker": t, "action": "hold", "size": "allocation",
                "reason": f"price {price:.2f} inside bands",
            })
    return signals


def dollar_cost_averaging(
    portfolio: dict, history: dict, params: dict
) -> list[Signal]:
    """
    Invest a fixed fraction of STARTING capital every run, split equally
    across tickers. Stops when cash is exhausted.
    """
    daily_fraction = float(params.get("daily_fraction", 0.01))  # 1% / day default
    # starting capital is in portfolio metadata; passed in via 'starting_capital'
    starting_capital = float(params.get("starting_capital", portfolio["cash"]))
    daily_budget = starting_capital * daily_fraction
    if portfolio["cash"] < 1:
        return [{"ticker": t, "action": "hold", "size": "allocation",
                 "reason": "DCA: cash exhausted"} for t in portfolio["tickers"]]
    per_ticker = min(daily_budget, portfolio["cash"]) / len(portfolio["tickers"])
    return [{
        "ticker": t, "action": "buy",
        "size": {"dollars": per_ticker},
        "reason": f"DCA: ${per_ticker:.2f} scheduled investment",
    } for t in portfolio["tickers"]]


def momentum_rotation(
    portfolio: dict, history: dict, params: dict
) -> list[Signal]:
    """
    Hold the top-K tickers by trailing N-day return. Sell anything no longer
    in the top K; buy anything newly in it.
    """
    lookback = int(params.get("lookback", 30))
    top_k = int(params.get("top_k", 3))
    signals: list[Signal] = []

    returns_by_ticker: dict[str, float] = {}
    for t in portfolio["tickers"]:
        df = history.get(t.upper())
        if df is None or len(df) < lookback + 1:
            continue
        ret = df["Close"].iloc[-1] / df["Close"].iloc[-lookback - 1] - 1
        returns_by_ticker[t.upper()] = float(ret)

    if not returns_by_ticker:
        return [{"ticker": t, "action": "hold", "size": "allocation",
                 "reason": "momentum: no data"} for t in portfolio["tickers"]]

    k = min(top_k, len(returns_by_ticker))
    ranked = sorted(returns_by_ticker.items(), key=lambda x: x[1], reverse=True)
    winners = {t for t, _ in ranked[:k]}

    for t in portfolio["tickers"]:
        tu = t.upper()
        ret = returns_by_ticker.get(tu)
        ret_str = f"{ret*100:+.1f}%" if ret is not None else "n/a"
        if tu in winners and not _held(portfolio, tu):
            signals.append({
                "ticker": tu, "action": "buy",
                "size": {"allocation_of": list(winners)},  # equal split among winners
                "reason": f"momentum: top {k} ({lookback}d return {ret_str})",
            })
        elif tu not in winners and _held(portfolio, tu):
            signals.append({
                "ticker": tu, "action": "sell", "size": "full_position",
                "reason": f"momentum: dropped out of top {k} ({lookback}d return {ret_str})",
            })
        else:
            signals.append({
                "ticker": tu, "action": "hold", "size": "allocation",
                "reason": f"momentum: rank holds ({lookback}d return {ret_str})",
            })
    return signals


# ════════════════════════════════════════════════
# Registry
# ════════════════════════════════════════════════
STRATEGY_REGISTRY: dict[str, Callable] = {
    "buy_and_hold": buy_and_hold,
    "sma_crossover": sma_crossover,
    "rsi_mean_reversion": rsi_mean_reversion,
    "macd_momentum": macd_momentum,
    "bollinger_mean_reversion": bollinger_mean_reversion,
    "dca": dollar_cost_averaging,
    "momentum_rotation": momentum_rotation,
}

STRATEGY_DISPLAY_NAMES = {
    "buy_and_hold": "Buy & Hold",
    "sma_crossover": "SMA Crossover (50/200)",
    "rsi_mean_reversion": "RSI Mean Reversion",
    "macd_momentum": "MACD Momentum",
    "bollinger_mean_reversion": "Bollinger Bands Mean Reversion",
    "dca": "Dollar-Cost Averaging",
    "momentum_rotation": "Momentum Rotation",
}

STRATEGY_DESCRIPTIONS = {
    "buy_and_hold": "Split cash equally across tickers on day 1, then never trade. The classic benchmark.",
    "sma_crossover": "Buy when the 50-day SMA crosses above the 200-day SMA (golden cross); sell on the death cross.",
    "rsi_mean_reversion": "Buy when 14-day RSI falls below 30 (oversold); sell when it rises above 70 (overbought).",
    "macd_momentum": "Buy when MACD crosses above its signal line; sell on the opposite cross.",
    "bollinger_mean_reversion": "Buy when price falls below the lower Bollinger band; sell when it rises above the upper band.",
    "dca": "Invest a fixed fraction of starting capital every day, split equally across tickers.",
    "momentum_rotation": "Hold only the top 3 tickers by trailing 30-day return. Rotate when rankings change.",
}
