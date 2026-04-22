"""
SQLite database layer for the digital-twin investor.

Schema covers users, invite codes, portfolios, positions, trades, and daily
snapshots. The DB file lives at the path given by DATABASE_PATH (env var) or
./data/app.db by default.

For GitHub Actions deployment, commit the SQLite file back after each run
(see .github/workflows/daily.yml). For a more robust setup, point DATABASE_PATH
at a hosted SQLite (Turso) or swap this module for Postgres.
"""
from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator

DB_PATH = Path(os.environ.get("DATABASE_PATH", "data/app.db"))


def _ensure_dir() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)


@contextmanager
def get_conn() -> Iterator[sqlite3.Connection]:
    _ensure_dir()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


SCHEMA = """
CREATE TABLE IF NOT EXISTS invite_codes (
    code TEXT PRIMARY KEY,
    used_by_user_id INTEGER,
    created_at TEXT NOT NULL,
    used_at TEXT
);

CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS portfolios (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    starting_capital REAL NOT NULL,
    cash_balance REAL NOT NULL,
    strategy TEXT NOT NULL,
    strategy_params TEXT NOT NULL DEFAULT '{}',
    tickers TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS positions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    portfolio_id INTEGER NOT NULL,
    ticker TEXT NOT NULL,
    shares REAL NOT NULL,
    avg_cost REAL NOT NULL,
    UNIQUE(portfolio_id, ticker),
    FOREIGN KEY(portfolio_id) REFERENCES portfolios(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    portfolio_id INTEGER NOT NULL,
    ticker TEXT NOT NULL,
    side TEXT NOT NULL,
    shares REAL NOT NULL,
    price REAL NOT NULL,
    fee REAL NOT NULL DEFAULT 0,
    executed_at TEXT NOT NULL,
    reason TEXT,
    FOREIGN KEY(portfolio_id) REFERENCES portfolios(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS portfolio_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    portfolio_id INTEGER NOT NULL,
    date TEXT NOT NULL,
    total_value REAL NOT NULL,
    cash REAL NOT NULL,
    holdings_value REAL NOT NULL,
    UNIQUE(portfolio_id, date),
    FOREIGN KEY(portfolio_id) REFERENCES portfolios(id) ON DELETE CASCADE
);
"""


def init_db() -> None:
    """Create tables if they do not exist."""
    with get_conn() as conn:
        conn.executescript(SCHEMA)


# ────────────────────────────────────────────────
# Invite codes
# ────────────────────────────────────────────────
def create_invite_code(code: str) -> None:
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO invite_codes (code, created_at) VALUES (?, ?)",
            (code, datetime.utcnow().isoformat()),
        )


def consume_invite_code(code: str, user_id: int) -> bool:
    """Mark an invite code as used. Returns True if successful."""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT used_by_user_id FROM invite_codes WHERE code = ?", (code,)
        ).fetchone()
        if not row or row["used_by_user_id"] is not None:
            return False
        conn.execute(
            "UPDATE invite_codes SET used_by_user_id = ?, used_at = ? WHERE code = ?",
            (user_id, datetime.utcnow().isoformat(), code),
        )
        return True


def list_invite_codes() -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM invite_codes ORDER BY created_at DESC"
        ).fetchall()
        return [dict(r) for r in rows]


# ────────────────────────────────────────────────
# Users
# ────────────────────────────────────────────────
def create_user(email: str, password_hash: str) -> int:
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO users (email, password_hash, created_at) VALUES (?, ?, ?)",
            (email.lower(), password_hash, datetime.utcnow().isoformat()),
        )
        return cur.lastrowid


def get_user_by_email(email: str) -> dict | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM users WHERE email = ?", (email.lower(),)
        ).fetchone()
        return dict(row) if row else None


def get_all_users() -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM users").fetchall()
        return [dict(r) for r in rows]


# ────────────────────────────────────────────────
# Portfolios
# ────────────────────────────────────────────────
def create_portfolio(
    user_id: int,
    name: str,
    starting_capital: float,
    strategy: str,
    strategy_params: dict,
    tickers: list[str],
) -> int:
    with get_conn() as conn:
        cur = conn.execute(
            """INSERT INTO portfolios
               (user_id, name, starting_capital, cash_balance, strategy,
                strategy_params, tickers, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                user_id,
                name,
                starting_capital,
                starting_capital,
                strategy,
                json.dumps(strategy_params),
                json.dumps([t.upper() for t in tickers]),
                datetime.utcnow().isoformat(),
            ),
        )
        return cur.lastrowid


def get_portfolio(portfolio_id: int) -> dict | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM portfolios WHERE id = ?", (portfolio_id,)
        ).fetchone()
        if not row:
            return None
        p = dict(row)
        p["strategy_params"] = json.loads(p["strategy_params"])
        p["tickers"] = json.loads(p["tickers"])
        return p


def get_portfolios_for_user(user_id: int) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM portfolios WHERE user_id = ? ORDER BY created_at DESC",
            (user_id,),
        ).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["strategy_params"] = json.loads(d["strategy_params"])
            d["tickers"] = json.loads(d["tickers"])
            out.append(d)
        return out


def get_all_active_portfolios() -> list[dict]:
    """Used by the daily worker to find everything to execute."""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM portfolios WHERE active = 1"
        ).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["strategy_params"] = json.loads(d["strategy_params"])
            d["tickers"] = json.loads(d["tickers"])
            out.append(d)
        return out


def update_portfolio_cash(portfolio_id: int, cash: float) -> None:
    with get_conn() as conn:
        conn.execute(
            "UPDATE portfolios SET cash_balance = ? WHERE id = ?",
            (cash, portfolio_id),
        )


def set_portfolio_active(portfolio_id: int, active: bool) -> None:
    with get_conn() as conn:
        conn.execute(
            "UPDATE portfolios SET active = ? WHERE id = ?",
            (1 if active else 0, portfolio_id),
        )


def reset_portfolio(portfolio_id: int) -> None:
    """Reset portfolio: wipe positions, trades, snapshots; restore cash."""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT starting_capital FROM portfolios WHERE id = ?",
            (portfolio_id,),
        ).fetchone()
        if not row:
            return
        conn.execute("DELETE FROM positions WHERE portfolio_id = ?", (portfolio_id,))
        conn.execute("DELETE FROM trades WHERE portfolio_id = ?", (portfolio_id,))
        conn.execute(
            "DELETE FROM portfolio_snapshots WHERE portfolio_id = ?",
            (portfolio_id,),
        )
        conn.execute(
            "UPDATE portfolios SET cash_balance = ? WHERE id = ?",
            (row["starting_capital"], portfolio_id),
        )


# ────────────────────────────────────────────────
# Positions
# ────────────────────────────────────────────────
def get_positions(portfolio_id: int) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM positions WHERE portfolio_id = ?", (portfolio_id,)
        ).fetchall()
        return [dict(r) for r in rows]


def upsert_position(
    portfolio_id: int, ticker: str, shares: float, avg_cost: float
) -> None:
    with get_conn() as conn:
        if shares <= 1e-9:
            conn.execute(
                "DELETE FROM positions WHERE portfolio_id = ? AND ticker = ?",
                (portfolio_id, ticker.upper()),
            )
            return
        conn.execute(
            """INSERT INTO positions (portfolio_id, ticker, shares, avg_cost)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(portfolio_id, ticker)
               DO UPDATE SET shares = excluded.shares, avg_cost = excluded.avg_cost""",
            (portfolio_id, ticker.upper(), shares, avg_cost),
        )


# ────────────────────────────────────────────────
# Trades
# ────────────────────────────────────────────────
def record_trade(
    portfolio_id: int,
    ticker: str,
    side: str,
    shares: float,
    price: float,
    fee: float,
    reason: str = "",
) -> None:
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO trades
               (portfolio_id, ticker, side, shares, price, fee, executed_at, reason)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                portfolio_id,
                ticker.upper(),
                side,
                shares,
                price,
                fee,
                datetime.utcnow().isoformat(),
                reason,
            ),
        )


def get_trades(portfolio_id: int, limit: int = 100) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT * FROM trades WHERE portfolio_id = ?
               ORDER BY executed_at DESC LIMIT ?""",
            (portfolio_id, limit),
        ).fetchall()
        return [dict(r) for r in rows]


def get_trades_on_date(portfolio_id: int, date_str: str) -> list[dict]:
    """Trades executed on a given YYYY-MM-DD (UTC)."""
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT * FROM trades
               WHERE portfolio_id = ? AND executed_at LIKE ?
               ORDER BY executed_at""",
            (portfolio_id, f"{date_str}%"),
        ).fetchall()
        return [dict(r) for r in rows]


# ────────────────────────────────────────────────
# Snapshots
# ────────────────────────────────────────────────
def record_snapshot(
    portfolio_id: int,
    date: str,
    total_value: float,
    cash: float,
    holdings_value: float,
) -> None:
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO portfolio_snapshots
               (portfolio_id, date, total_value, cash, holdings_value)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(portfolio_id, date)
               DO UPDATE SET total_value = excluded.total_value,
                             cash = excluded.cash,
                             holdings_value = excluded.holdings_value""",
            (portfolio_id, date, total_value, cash, holdings_value),
        )


def get_snapshots(portfolio_id: int) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT * FROM portfolio_snapshots
               WHERE portfolio_id = ? ORDER BY date""",
            (portfolio_id,),
        ).fetchall()
        return [dict(r) for r in rows]
