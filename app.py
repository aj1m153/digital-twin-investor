"""
Digital Twin Investor — Streamlit UI.

Run locally:  streamlit run app.py
"""
from __future__ import annotations

import json
import os
import secrets
from datetime import datetime

import bcrypt
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from dotenv import load_dotenv

from core import db, prices as prices_mod, executor
from strategies import (
    STRATEGY_DISPLAY_NAMES,
    STRATEGY_DESCRIPTIONS,
    STRATEGY_REGISTRY,
)

load_dotenv()
db.init_db()

st.set_page_config(
    page_title="Digital Twin Investor",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ────────────────────────────────────────────────
# Styling
# ────────────────────────────────────────────────
st.markdown("""
<style>
:root {
    --accent: #16a34a;
    --danger: #dc2626;
}
.stApp { background: #0f172a; }
section[data-testid="stSidebar"] { background: #1e293b; }
h1, h2, h3, h4 { color: #f1f5f9; }
.metric-card {
    background: #1e293b;
    border: 1px solid #334155;
    border-radius: 12px;
    padding: 16px 20px;
}
.pos { color: #16a34a; }
.neg { color: #dc2626; }
.small-muted { font-size: 12px; color: #94a3b8; text-transform: uppercase; letter-spacing: 1.5px; }
</style>
""", unsafe_allow_html=True)

# ────────────────────────────────────────────────
# Auth helpers
# ────────────────────────────────────────────────
def hash_password(pw: str) -> str:
    return bcrypt.hashpw(pw.encode(), bcrypt.gensalt()).decode()


def verify_password(pw: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(pw.encode(), hashed.encode())
    except Exception:
        return False


def current_user() -> dict | None:
    return st.session_state.get("user")


def require_login() -> dict | None:
    user = current_user()
    if not user:
        render_auth()
        return None
    return user


# ────────────────────────────────────────────────
# Auth screen
# ────────────────────────────────────────────────
def render_auth() -> None:
    st.title("📈 Digital Twin Investor")
    st.caption("Paper-trade real strategies on real markets. Invite-only.")

    tab_login, tab_signup = st.tabs(["Sign in", "Create account"])

    with tab_login:
        with st.form("login_form"):
            email = st.text_input("Email", key="login_email")
            password = st.text_input("Password", type="password", key="login_pw")
            submit = st.form_submit_button("Sign in", use_container_width=True)
            if submit:
                user = db.get_user_by_email(email.strip())
                if user and verify_password(password, user["password_hash"]):
                    st.session_state["user"] = user
                    st.rerun()
                else:
                    st.error("Invalid email or password.")

    with tab_signup:
        with st.form("signup_form"):
            email = st.text_input("Email", key="signup_email")
            password = st.text_input("Password (8+ characters)", type="password",
                                     key="signup_pw")
            invite = st.text_input("Invite code", key="signup_invite")
            submit = st.form_submit_button("Create account", use_container_width=True)
            if submit:
                if not email or "@" not in email:
                    st.error("Valid email required.")
                elif len(password) < 8:
                    st.error("Password must be at least 8 characters.")
                elif not invite:
                    st.error("Invite code required.")
                elif db.get_user_by_email(email):
                    st.error("An account with this email already exists.")
                else:
                    user_id = db.create_user(email.strip(), hash_password(password))
                    ok = db.consume_invite_code(invite.strip(), user_id)
                    if not ok:
                        st.error("Invite code is invalid or already used.")
                    else:
                        st.success("Account created — sign in on the other tab.")


# ────────────────────────────────────────────────
# Portfolio creation
# ────────────────────────────────────────────────
def render_create_portfolio(user: dict) -> None:
    st.subheader("➕ New portfolio")

    with st.form("new_portfolio"):
        name = st.text_input("Portfolio name", value="My Strategy Test")
        starting_capital = st.number_input(
            "Starting capital ($)", min_value=100.0, max_value=1_000_000.0,
            value=10_000.0, step=500.0
        )

        strategy_key = st.selectbox(
            "Strategy",
            options=list(STRATEGY_REGISTRY.keys()),
            format_func=lambda k: STRATEGY_DISPLAY_NAMES[k],
        )
        st.caption(STRATEGY_DESCRIPTIONS[strategy_key])

        tickers_input = st.text_input(
            "Tickers (comma-separated) — stocks or crypto",
            value="AAPL, MSFT, NVDA, BTC-USD, ETH-USD",
            help="Any Yahoo Finance ticker. Crypto uses -USD suffix (BTC-USD, ETH-USD).",
        )

        # Strategy-specific parameter overrides
        params: dict = {}
        with st.expander("Advanced strategy parameters"):
            if strategy_key == "sma_crossover":
                params["fast"] = st.number_input("Fast SMA period", 5, 100, 50)
                params["slow"] = st.number_input("Slow SMA period", 50, 400, 200)
            elif strategy_key == "rsi_mean_reversion":
                params["period"] = st.number_input("RSI period", 5, 50, 14)
                params["oversold"] = st.number_input("Oversold threshold", 10, 40, 30)
                params["overbought"] = st.number_input("Overbought threshold", 60, 90, 70)
            elif strategy_key == "macd_momentum":
                params["fast"] = st.number_input("MACD fast", 5, 30, 12)
                params["slow"] = st.number_input("MACD slow", 15, 50, 26)
                params["signal"] = st.number_input("MACD signal", 5, 20, 9)
            elif strategy_key == "bollinger_mean_reversion":
                params["window"] = st.number_input("Bollinger window", 10, 50, 20)
                params["num_std"] = st.number_input(
                    "Num std devs", 1.0, 4.0, 2.0, step=0.1
                )
            elif strategy_key == "dca":
                params["daily_fraction"] = st.number_input(
                    "Daily fraction of starting capital",
                    0.001, 0.1, 0.01, step=0.005, format="%.3f",
                    help="Default 0.01 = 1%/day = fully invested in ~100 days",
                )
            elif strategy_key == "momentum_rotation":
                params["lookback"] = st.number_input("Lookback days", 5, 180, 30)
                params["top_k"] = st.number_input("Hold top K", 1, 10, 3)

        submit = st.form_submit_button("Create portfolio", use_container_width=True,
                                       type="primary")
        if submit:
            raw_tickers = [t.strip().upper() for t in tickers_input.split(",") if t.strip()]
            if not raw_tickers:
                st.error("At least one ticker required.")
                return
            # Validate tickers
            bad = []
            with st.spinner(f"Validating {len(raw_tickers)} ticker(s)…"):
                for t in raw_tickers:
                    if not prices_mod.validate_ticker(t):
                        bad.append(t)
            if bad:
                st.error(f"Unknown tickers: {', '.join(bad)}")
                return
            pid = db.create_portfolio(
                user_id=user["id"],
                name=name,
                starting_capital=starting_capital,
                strategy=strategy_key,
                strategy_params=params,
                tickers=raw_tickers,
            )
            st.success(f"Portfolio '{name}' created. The strategy will start executing on the next worker run.")
            st.rerun()


# ────────────────────────────────────────────────
# Dashboard
# ────────────────────────────────────────────────
def render_dashboard(user: dict) -> None:
    portfolios = db.get_portfolios_for_user(user["id"])
    if not portfolios:
        st.info("You don't have any portfolios yet. Create one below to get started.")
        render_create_portfolio(user)
        return

    labels = [f"{p['name']} · {STRATEGY_DISPLAY_NAMES[p['strategy']]}" for p in portfolios]
    idx = st.sidebar.selectbox(
        "Portfolio",
        options=list(range(len(portfolios))),
        format_func=lambda i: labels[i],
    )
    portfolio = portfolios[idx]

    st.title(f"📊 {portfolio['name']}")
    st.caption(
        f"Strategy: **{STRATEGY_DISPLAY_NAMES[portfolio['strategy']]}** · "
        f"Tickers: {', '.join(portfolio['tickers'])} · "
        f"Started {portfolio['created_at'][:10]}"
    )

    # Live snapshot
    with st.spinner("Fetching live prices…"):
        snap = executor.compute_current_value(portfolio)

    total = snap["total_value"]
    starting = float(portfolio["starting_capital"])
    total_return_pct = (total / starting - 1) * 100

    snapshots_rows = db.get_snapshots(portfolio["id"])
    prior_total = (
        float(snapshots_rows[-2]["total_value"])
        if len(snapshots_rows) >= 2 else starting
    )
    day_pnl = total - prior_total
    day_pnl_pct = (day_pnl / prior_total * 100) if prior_total else 0.0

    # KPI cards
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Portfolio Value", f"${total:,.2f}",
              f"{total_return_pct:+.2f}% vs start")
    k2.metric("Cash", f"${snap['cash']:,.2f}")
    k3.metric("Holdings", f"${snap['holdings_value']:,.2f}")
    k4.metric("Today", f"{day_pnl_pct:+.2f}%", f"${day_pnl:+,.2f}")

    # Equity curve
    st.subheader("Equity curve")
    if snapshots_rows:
        eq_df = pd.DataFrame(snapshots_rows)
        eq_df["date"] = pd.to_datetime(eq_df["date"])
        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=eq_df["date"], y=eq_df["total_value"],
            mode="lines+markers",
            line=dict(color="#16a34a", width=2),
            fill="tozeroy",
            fillcolor="rgba(22,163,74,0.1)",
            name="Total value",
        ))
        fig.add_hline(y=starting, line_dash="dash", line_color="#64748b",
                      annotation_text="Starting capital")
        fig.update_layout(
            paper_bgcolor="#0f172a", plot_bgcolor="#0f172a",
            font=dict(color="#e2e8f0"),
            xaxis=dict(gridcolor="#1e293b"), yaxis=dict(gridcolor="#1e293b",
                                                       tickprefix="$"),
            height=340, margin=dict(l=40, r=20, t=30, b=40), showlegend=False,
        )
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("No performance data yet — run the daily worker once to seed the first snapshot.")

    # Holdings table
    st.subheader("Holdings")
    if snap["positions"]:
        hold_df = pd.DataFrame(snap["positions"])
        hold_df = hold_df.rename(columns={
            "ticker": "Ticker", "shares": "Shares", "avg_cost": "Avg Cost",
            "current_price": "Price", "market_value": "Value",
            "unrealized_pnl": "P&L $", "unrealized_pnl_pct": "P&L %",
        })
        st.dataframe(
            hold_df.style.format({
                "Shares": "{:.4f}", "Avg Cost": "${:.2f}",
                "Price": "${:.2f}", "Value": "${:,.2f}",
                "P&L $": "${:+,.2f}", "P&L %": "{:+.2f}%",
            }),
            use_container_width=True, hide_index=True,
        )
    else:
        st.info("No open positions — all in cash.")

    # Recent trades
    st.subheader("Recent trades")
    trades = db.get_trades(portfolio["id"], limit=50)
    if trades:
        t_df = pd.DataFrame(trades)
        t_df["executed_at"] = pd.to_datetime(t_df["executed_at"]).dt.strftime(
            "%Y-%m-%d %H:%M"
        )
        t_df = t_df[["executed_at", "ticker", "side", "shares",
                     "price", "fee", "reason"]]
        t_df.columns = ["Time", "Ticker", "Side", "Shares", "Price", "Fee", "Reason"]
        st.dataframe(
            t_df.style.format({
                "Shares": "{:.4f}", "Price": "${:.2f}", "Fee": "${:.2f}"
            }),
            use_container_width=True, hide_index=True,
        )
    else:
        st.info("No trades yet.")

    # Portfolio actions
    st.subheader("Manage")
    c1, c2, c3 = st.columns(3)
    if c1.button("🔄 Reset portfolio", help="Wipes all positions, trades, snapshots and restores starting capital."):
        db.reset_portfolio(portfolio["id"])
        st.success("Portfolio reset.")
        st.rerun()
    active = bool(portfolio["active"])
    if c2.button(("⏸ Pause" if active else "▶ Resume") + " strategy"):
        db.set_portfolio_active(portfolio["id"], not active)
        st.rerun()
    if c3.button("➕ New portfolio"):
        st.session_state["show_new"] = True
        st.rerun()

    if st.session_state.get("show_new"):
        st.markdown("---")
        render_create_portfolio(user)


# ────────────────────────────────────────────────
# Admin (invite codes)
# ────────────────────────────────────────────────
ADMIN_EMAILS = [
    e.strip().lower() for e in os.environ.get("ADMIN_EMAILS", "").split(",") if e.strip()
]


def render_admin(user: dict) -> None:
    if user["email"].lower() not in ADMIN_EMAILS:
        st.error("Admin access only. Add your email to ADMIN_EMAILS in .env.")
        return
    st.title("🛡 Admin · Invite codes")

    c1, c2 = st.columns([1, 1])
    with c1:
        if st.button("Generate new invite code", type="primary"):
            code = secrets.token_urlsafe(12)
            db.create_invite_code(code)
            st.success(f"New code: `{code}`")

    codes = db.list_invite_codes()
    if codes:
        df = pd.DataFrame(codes)
        st.dataframe(df, use_container_width=True, hide_index=True)


# ────────────────────────────────────────────────
# Main
# ────────────────────────────────────────────────
def main() -> None:
    user = current_user()
    if not user:
        render_auth()
        return

    st.sidebar.markdown(f"**Signed in as**")
    st.sidebar.markdown(f"`{user['email']}`")
    st.sidebar.markdown("---")

    page = st.sidebar.radio(
        "Navigate",
        ["Dashboard", "New portfolio", "Admin"],
    )
    st.sidebar.markdown("---")
    if st.sidebar.button("Sign out", use_container_width=True):
        st.session_state.pop("user", None)
        st.rerun()

    if page == "Dashboard":
        render_dashboard(user)
    elif page == "New portfolio":
        render_create_portfolio(user)
    elif page == "Admin":
        render_admin(user)


if __name__ == "__main__":
    main()
