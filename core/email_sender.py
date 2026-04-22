"""
Robust SMTP email sender (UTF-8 safe + NBSP-proof)

Fixes:
- Removes hidden non-breaking spaces (\xa0) from credentials
- Forces UTF-8 email encoding (prevents ASCII crashes)
- Adds debug + validation for SMTP issues
"""

from __future__ import annotations

import os
import smtplib
from datetime import datetime
from email.message import EmailMessage
from email import policy


print("USER:", repr(user))
print("PASS:", repr(password))
print("TO:", repr(to_email))
print("SUBJECT:", repr(subject))

# ---------- CLEANING ----------

def clean_smtp(value: str | None) -> str | None:
    """Strict clean for SMTP credentials (removes NBSP + ALL whitespace)."""
    if value is None:
        return None

    # Remove NBSP explicitly
    value = value.replace("\xa0", "")

    # Remove ALL whitespace (spaces, tabs, newlines)
    value = "".join(value.split())

    return value


def clean_text(value: str | None) -> str:
    """Clean display text (keeps readable spaces)."""
    if value is None:
        return ""
    return value.replace("\xa0", " ").strip()


# ---------- EMAIL SENDER ----------

def send_email(to_email: str, subject: str, html_body: str, text_body: str = "") -> None:
    host = clean_smtp(os.environ.get("SMTP_HOST", "smtp.gmail.com"))
    port = int(clean_smtp(os.environ.get("SMTP_PORT", "587")) or 587)

    user = clean_smtp(os.environ.get("SMTP_USER"))
    password = clean_smtp(os.environ.get("SMTP_PASSWORD"))
    from_addr = clean_smtp(os.environ.get("SMTP_FROM")) or user
    to_email = clean_smtp(to_email)

    # ---- DEBUG (remove after fixing) ----
    print("DEBUG SMTP_USER:", repr(user))
    print("DEBUG SMTP_PASS:", repr(password))
    # ------------------------------------

    if not user or not password:
        print("[email_sender] SMTP not configured. Skipping.")
        return

    if "\xa0" in user or "\xa0" in password:
        raise ValueError("NBSP detected in SMTP credentials.")

    # ✅ UTF-8 SAFE EMAIL OBJECT
    msg = EmailMessage(policy=policy.SMTP)

    msg["Subject"] = clean_text(subject)
    msg["From"] = from_addr
    msg["To"] = to_email

    msg.set_content(clean_text(text_body or "View in HTML client"))
    msg.add_alternative(html_body, subtype="html")

    try:
        with smtplib.SMTP(host, port) as server:
            server.ehlo()
            server.starttls()
            server.ehlo()

            server.login(user, password)   # <-- where error usually happens
            server.send_message(msg)

            print("[email_sender] Email sent successfully")

    except Exception as e:
        print(f"[email_sender] Failed to send email: {e}")


# ---------- EMAIL RENDER ----------

def render_daily_email(
    portfolio: dict,
    total_value: float,
    day_pnl: float,
    day_pnl_pct: float,
    total_return_pct: float,
    trades_today: list[dict],
    positions: list[dict],
    strategy_display: str,
) -> tuple[str, str]:

    today = datetime.utcnow().strftime("%A, %B %d, %Y")

    pnl_sign = "+" if day_pnl >= 0 else ""
    portfolio_name = clean_text(portfolio.get("name", "Portfolio"))

    # ---- Trades ----
    if trades_today:
        trades_rows = ""
        for t in trades_today:
            trades_rows += f"""
            <tr>
              <td>{clean_text(str(t.get('ticker', '')))}</td>
              <td>{clean_text(str(t.get('side', '')))}</td>
              <td>{t.get('shares', 0):.4f}</td>
              <td>${t.get('price', 0):.2f}</td>
              <td>{clean_text(str(t.get('reason', '')))}</td>
            </tr>
            """
    else:
        trades_rows = "<tr><td colspan='5'>No trades today</td></tr>"

    # ---- Holdings ----
    if positions:
        holdings_rows = ""
        for p in positions:
            holdings_rows += f"""
            <tr>
              <td>{clean_text(str(p.get('ticker', '')))}</td>
              <td>{p.get('shares', 0):.4f}</td>
              <td>${p.get('current_price', 0):.2f}</td>
              <td>${p.get('market_value', 0):,.2f}</td>
              <td>{p.get('unrealized_pnl_pct', 0):+.2f}%</td>
            </tr>
            """
    else:
        holdings_rows = "<tr><td colspan='5'>All in cash</td></tr>"

    subject = clean_text(
        f"{portfolio_name}: ${total_value:,.2f} ({pnl_sign}{day_pnl_pct:.2f}% today)"
    )

    html = f"""
    <html>
    <body>
        <h2>{portfolio_name}</h2>
        <p>{today}</p>

        <h3>Trades</h3>
        <table border="1">{trades_rows}</table>

        <h3>Holdings</h3>
        <table border="1">{holdings_rows}</table>

        <p style="font-size:12px;">Paper trading only</p>
    </body>
    </html>
    """

    return subject, html
