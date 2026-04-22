"""
Small admin CLI for offline tasks.

Usage:
    python admin.py invite              # generate a new invite code
    python admin.py invites             # list all codes
    python admin.py users               # list users
    python admin.py portfolios          # list all portfolios
    python admin.py run-once            # trigger daily_worker manually
"""
from __future__ import annotations

import secrets
import sys

from core import db


def gen_invite() -> None:
    code = secrets.token_urlsafe(12)
    db.create_invite_code(code)
    print(f"New invite code: {code}")


def list_invites() -> None:
    for c in db.list_invite_codes():
        used = f"used by user {c['used_by_user_id']}" if c["used_by_user_id"] else "unused"
        print(f"  {c['code']}  — {used}")


def list_users() -> None:
    for u in db.get_all_users():
        print(f"  #{u['id']}  {u['email']}  created {u['created_at'][:10]}")


def list_portfolios() -> None:
    for p in db.get_all_active_portfolios():
        print(
            f"  #{p['id']}  user={p['user_id']}  '{p['name']}'  "
            f"strategy={p['strategy']}  tickers={p['tickers']}  "
            f"cash=${p['cash_balance']:.2f}"
        )


def run_once() -> None:
    import daily_worker
    daily_worker.main()


def main() -> None:
    db.init_db()
    if len(sys.argv) < 2:
        print(__doc__)
        return
    cmd = sys.argv[1]
    if cmd == "invite":
        gen_invite()
    elif cmd == "invites":
        list_invites()
    elif cmd == "users":
        list_users()
    elif cmd == "portfolios":
        list_portfolios()
    elif cmd == "run-once":
        run_once()
    else:
        print(f"Unknown command: {cmd}")
        print(__doc__)


if __name__ == "__main__":
    main()
