"""
Portfolio executor.

Given a portfolio and a list of signals, compute and persist the actual trades
using current prices. Applies a slippage/fee to every trade.
"""
from __future__ import annotations

from datetime import datetime

from . import db
from . import prices as prices_mod


DEFAULT_FEE_RATE = 0.001  # 10 bps combined slippage + fee


def _portfolio_value(
    cash: float, positions: dict[str, float], price_map: dict[str, float]
) -> float:
    holdings = sum(
        shares * price_map.get(ticker, 0.0) for ticker, shares in positions.items()
    )
    return cash + holdings


def _buy(
    portfolio_id: int,
    ticker: str,
    dollars: float,
    price: float,
    fee_rate: float,
    reason: str,
    current_positions: dict[str, dict],
    cash: float,
) -> tuple[float, dict[str, dict]]:
    """Execute a buy. Returns (new_cash, updated_positions_map)."""
    if price <= 0 or dollars <= 0 or cash <= 0:
        return cash, current_positions
    dollars = min(dollars, cash)
    fee = dollars * fee_rate
    invested = dollars - fee
    shares = invested / price
    if shares <= 1e-9:
        return cash, current_positions
    db.record_trade(portfolio_id, ticker, "buy", shares, price, fee, reason)
    pos = current_positions.get(ticker.upper())
    if pos:
        new_shares = pos["shares"] + shares
        new_avg = (pos["shares"] * pos["avg_cost"] + shares * price) / new_shares
    else:
        new_shares, new_avg = shares, price
    db.upsert_position(portfolio_id, ticker, new_shares, new_avg)
    current_positions[ticker.upper()] = {
        "ticker": ticker.upper(), "shares": new_shares, "avg_cost": new_avg
    }
    return cash - dollars, current_positions


def _sell(
    portfolio_id: int,
    ticker: str,
    shares_to_sell: float,
    price: float,
    fee_rate: float,
    reason: str,
    current_positions: dict[str, dict],
    cash: float,
) -> tuple[float, dict[str, dict]]:
    """Execute a sell. Returns (new_cash, updated_positions_map)."""
    pos = current_positions.get(ticker.upper())
    if not pos or pos["shares"] < 1e-9 or price <= 0:
        return cash, current_positions
    shares_to_sell = min(shares_to_sell, pos["shares"])
    gross = shares_to_sell * price
    fee = gross * fee_rate
    net = gross - fee
    db.record_trade(portfolio_id, ticker, "sell", shares_to_sell, price, fee, reason)
    remaining = pos["shares"] - shares_to_sell
    db.upsert_position(portfolio_id, ticker, remaining, pos["avg_cost"])
    if remaining <= 1e-9:
        current_positions.pop(ticker.upper(), None)
    else:
        current_positions[ticker.upper()]["shares"] = remaining
    return cash + net, current_positions


def execute_signals(
    portfolio: dict,
    signals: list[dict],
    price_map: dict[str, float],
    fee_rate: float = DEFAULT_FEE_RATE,
) -> tuple[float, float]:
    """
    Apply the given signals to the portfolio. Returns (new_cash, new_total_value).

    `portfolio` is the dict returned by db.get_portfolio.
    `price_map` is ticker -> execution price (e.g., today's open).
    """
    portfolio_id = portfolio["id"]
    cash = float(portfolio["cash_balance"])
    tickers = portfolio["tickers"]

    # Load current positions as a ticker -> dict map
    pos_rows = db.get_positions(portfolio_id)
    positions: dict[str, dict] = {r["ticker"]: dict(r) for r in pos_rows}

    # Compute "allocation" unit: 1/N of total portfolio value
    total_value_for_alloc = _portfolio_value(
        cash, {k: v["shares"] for k, v in positions.items()}, price_map
    )
    allocation_per_ticker = (
        total_value_for_alloc / len(tickers) if tickers else 0.0
    )

    # Process sells first so their proceeds can fund buys
    sorted_signals = sorted(
        signals, key=lambda s: 0 if s["action"] == "sell" else 1
    )

    for sig in sorted_signals:
        ticker = sig["ticker"].upper()
        price = price_map.get(ticker, 0.0)
        if price <= 0:
            continue

        if sig["action"] == "buy":
            size = sig["size"]
            if size == "allocation":
                dollars = allocation_per_ticker
            elif isinstance(size, dict) and "dollars" in size:
                dollars = float(size["dollars"])
            elif isinstance(size, dict) and "allocation_of" in size:
                # Equal split of total value among a subset (momentum)
                group = size["allocation_of"]
                dollars = total_value_for_alloc / max(len(group), 1)
            else:
                dollars = allocation_per_ticker
            cash, positions = _buy(
                portfolio_id, ticker, dollars, price, fee_rate,
                sig.get("reason", ""), positions, cash
            )
        elif sig["action"] == "sell":
            size = sig["size"]
            if size == "full_position":
                shares_to_sell = positions.get(ticker, {}).get("shares", 0)
            elif isinstance(size, dict) and "shares" in size:
                shares_to_sell = float(size["shares"])
            else:
                shares_to_sell = positions.get(ticker, {}).get("shares", 0)
            if shares_to_sell > 0:
                cash, positions = _sell(
                    portfolio_id, ticker, shares_to_sell, price, fee_rate,
                    sig.get("reason", ""), positions, cash
                )

    db.update_portfolio_cash(portfolio_id, cash)
    new_total = _portfolio_value(
        cash, {k: v["shares"] for k, v in positions.items()}, price_map
    )
    holdings = new_total - cash
    db.record_snapshot(
        portfolio_id,
        date=datetime.utcnow().strftime("%Y-%m-%d"),
        total_value=new_total,
        cash=cash,
        holdings_value=holdings,
    )
    return cash, new_total


def compute_current_value(portfolio: dict) -> dict:
    """
    Compute on-the-fly portfolio value using latest prices.
    Returns {cash, holdings_value, total_value, positions: [...]}.
    """
    cash = float(portfolio["cash_balance"])
    pos_rows = db.get_positions(portfolio["id"])
    if not pos_rows:
        return {
            "cash": cash, "holdings_value": 0, "total_value": cash, "positions": []
        }
    tickers = [r["ticker"] for r in pos_rows]
    price_map = prices_mod.fetch_latest_prices(tickers)
    enriched = []
    holdings_value = 0.0
    for r in pos_rows:
        t = r["ticker"]
        px = price_map.get(t, 0.0)
        market_value = r["shares"] * px
        holdings_value += market_value
        enriched.append({
            "ticker": t,
            "shares": r["shares"],
            "avg_cost": r["avg_cost"],
            "current_price": px,
            "market_value": market_value,
            "unrealized_pnl": market_value - r["shares"] * r["avg_cost"],
            "unrealized_pnl_pct": (
                (px / r["avg_cost"] - 1) * 100 if r["avg_cost"] > 0 else 0
            ),
        })
    return {
        "cash": cash,
        "holdings_value": holdings_value,
        "total_value": cash + holdings_value,
        "positions": enriched,
    }
