"""
Daily worker.

Runs once per trading day (scheduled by GitHub Actions). For each active
portfolio:
  1. Pull recent price history for the portfolio's tickers
  2. Ask the strategy what to do today
  3. Execute the resulting buy/sell orders at today's open price
  4. Record the new snapshot
  5. Email the user their daily digest

Run manually for testing:
    python daily_worker.py
"""
from __future__ import annotations

import os
import sys
import traceback
from datetime import datetime

from dotenv import load_dotenv

from core import db, prices as prices_mod, executor, email_sender
from strategies import STRATEGY_REGISTRY, STRATEGY_DISPLAY_NAMES

load_dotenv()


def _previous_total_value(portfolio_id: int, today: str) -> float | None:
    snapshots = db.get_snapshots(portfolio_id)
    prior = [s for s in snapshots if s["date"] < today]
    if not prior:
        return None
    return float(prior[-1]["total_value"])


def run_portfolio(portfolio: dict, today: str) -> None:
    print(f"\n▶ Portfolio {portfolio['id']} ({portfolio['name']}) — {portfolio['strategy']}")

    strategy_fn = STRATEGY_REGISTRY.get(portfolio["strategy"])
    if strategy_fn is None:
        print(f"  ✗ Unknown strategy: {portfolio['strategy']}")
        return

    tickers = portfolio["tickers"]
    if not tickers:
        print("  ✗ No tickers configured")
        return

    # Fetch price history (1 year — enough for 200-day SMA etc.)
    history: dict[str, object] = {}
    for t in tickers:
        df = prices_mod.fetch_history(t, period="1y")
        if not df.empty:
            history[t.upper()] = df
        else:
            print(f"  ⚠ No data for {t}")

    # Execution prices: today's open for stocks, latest available for crypto
    price_map = prices_mod.fetch_today_open(tickers)
    if not price_map:
        print("  ✗ Could not fetch any execution prices — skipping")
        return

    # Build the portfolio state the strategy expects
    pos_rows = db.get_positions(portfolio["id"])
    positions_map = {r["ticker"]: r["shares"] for r in pos_rows}
    portfolio_state = {
        "cash": float(portfolio["cash_balance"]),
        "positions": positions_map,
        "tickers": tickers,
    }

    # Strategy params — inject starting_capital so DCA can use it
    params = dict(portfolio["strategy_params"])
    params.setdefault("starting_capital", portfolio["starting_capital"])

    signals = strategy_fn(portfolio_state, history, params)
    for s in signals:
        print(f"  • {s['ticker']} {s['action']:>4}  {s['reason']}")

    # Execute
    prior_total = _previous_total_value(portfolio["id"], today)
    new_cash, new_total = executor.execute_signals(portfolio, signals, price_map)

    # Email the user
    user = db.get_all_users()
    user_map = {u["id"]: u for u in user}
    user_row = user_map.get(portfolio["user_id"])
    if not user_row:
        print("  ✗ No user for this portfolio — email skipped")
        return

    snapshot = executor.compute_current_value(
        {**portfolio, "cash_balance": new_cash}
    )
    day_pnl = (new_total - prior_total) if prior_total is not None else 0.0
    day_pnl_pct = (day_pnl / prior_total * 100) if prior_total else 0.0
    total_return_pct = (
        (new_total / float(portfolio["starting_capital"]) - 1) * 100
    )
    trades_today = db.get_trades_on_date(portfolio["id"], today)

    subject, html = email_sender.render_daily_email(
        user_email=user_row["email"],
        portfolio=portfolio,
        total_value=new_total,
        day_pnl=day_pnl,
        day_pnl_pct=day_pnl_pct,
        total_return_pct=total_return_pct,
        trades_today=trades_today,
        positions=snapshot["positions"],
        strategy_display=STRATEGY_DISPLAY_NAMES.get(
            portfolio["strategy"], portfolio["strategy"]
        ),
    )

    try:
        email_sender.send_email(user_row["email"], subject, html)
        print(f"  ✉ Email sent to {user_row['email']}")
    except Exception as e:
        print(f"  ✗ Email failed: {e}")


def main() -> None:
    db.init_db()
    today = datetime.utcnow().strftime("%Y-%m-%d")
    portfolios = db.get_all_active_portfolios()
    if not portfolios:
        print("No active portfolios.")
        return
    print(f"Running {len(portfolios)} portfolio(s) for {today}")
    for p in portfolios:
        try:
            run_portfolio(p, today)
        except Exception:
            print(f"Error processing portfolio {p['id']}:")
            traceback.print_exc()


if __name__ == "__main__":
    main()
