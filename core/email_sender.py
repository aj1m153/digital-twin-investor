"""
Strict ASCII-safe SMTP email sender.

- Removes ALL whitespace (including NBSP) from SMTP credentials
- Forces ASCII-only headers (prevents \xa0 + emoji issues)
- Sanitizes all dynamic text
"""

from __future__ import annotations

import os
import re
import smtplib
from datetime import datetime
from email.message import EmailMessage
from typing import Optional


# ---------- Cleaning Utilities ----------

def clean_smtp(value: Optional[str]) -> Optional[str]:
    """Strict cleaning for SMTP fields (ASCII only, no whitespace)."""
    if value is None:
        return None
    value = re.sub(r"\s+", "", value, flags=re.UNICODE)  # remove ALL whitespace
    return value.encode("ascii", "ignore").decode()      # force ASCII


def clean_ascii(value: str) -> str:
    """Force any text to ASCII (removes NBSP, emojis, etc.)."""
    if value is None:
        return ""
    value = value.replace("\xa0", " ")
    return value.encode("ascii", "ignore").decode().strip()


# ---------- Email Sender ----------

def send_email(to_email: str, subject: str, html_body: str, text_body: str = "") -> None:
    host = clean_smtp(os.environ.get("SMTP_HOST", "smtp.gmail.com"))
    port = int(clean_smtp(os.environ.get("SMTP_PORT", "587")) or 587)

    user = clean_smtp(os.environ.get("SMTP_USER"))
    password = clean_smtp(os.environ.get("SMTP_PASSWORD"))
    from_addr = clean_smtp(os.environ.get("SMTP_FROM")) or user
    to_email = clean_smtp(to_email)

    if not user or not password:
        print(f"[email_sender] SMTP not configured. Skipping email to {to_email}.")
        return

    if not from_addr or not to_email:
        raise ValueError("Invalid email address.")

    # FORCE ASCII subject (no emoji, no NBSP)
    subject = clean_ascii(subject)

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = from_addr
    msg["To"] = to_email

    msg.set_content(clean_ascii(text_body or "View this email in an HTML-capable client."))
    msg.add_alternative(html_body, subtype="html")

    try:
        with smtplib.SMTP(host, port) as server:
            server.ehlo()
            server.starttls()
            server.ehlo()
            server.login(user, password)
            server.send_message(msg)
    except Exception as e:
        print(f"[email_sender] Failed to send email: {e}")


# ---------- Email Renderer ----------

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
    portfolio_name = clean_ascii(str(portfolio.get("name", "Portfolio")))

    # ---------- Trades ----------
    if trades_today:
        trades_rows = ""
        for t in trades_today:
            side = clean_ascii(str(t.get("side", ""))).lower()
            side_color = "#16a34a" if side == "buy" else "#dc2626"

            trades_rows += f"""
            <tr>
              <td>{clean_ascii(str(t.get('ticker', '')))}</td>
              <td style="color:{side_color};">{side}</td>
              <td style="text-align:right;">{t.get('shares', 0):.4f}</td>
              <td style="text-align:right;">${t.get('price', 0):.2f}</td>
              <td>{clean_ascii(str(t.get('reason', '')))}</td>
            </tr>
            """
    else:
        trades_rows = """
        <tr><td colspan="5" style="text-align:center;">No trades today - hold.</td></tr>
        """

    # ---------- Holdings ----------
    if positions:
        holdings_rows = ""
        for p in positions:
            pnl = p.get("unrealized_pnl", 0)
            pnl_color = "#16a34a" if pnl >= 0 else "#dc2626"

            holdings_rows += f"""
            <tr>
              <td>{clean_ascii(str(p.get('ticker', '')))}</td>
              <td style="text-align:right;">{p.get('shares', 0):.4f}</td>
              <td style="text-align:right;">${p.get('current_price', 0):.2f}</td>
              <td style="text-align:right;">${p.get('market_value', 0):,.2f}</td>
              <td style="text-align:right;color:{pnl_color};">
                {p.get('unrealized_pnl_pct', 0):+.2f}%
              </td>
            </tr>
            """
    else:
        holdings_rows = """
        <tr><td colspan="5" style="text-align:center;">All in cash.</td></tr>
        """

    # ---------- Subject (ASCII ONLY) ----------
    subject = clean_ascii(
        f"{portfolio_name}: ${total_value:,.2f} ({pnl_sign}{day_pnl_pct:.2f}% today)"
    )

    # ---------- HTML ----------
    html = f"""
<html>
<body>
  <h2>{portfolio_name}</h2>
  <p>{today}</p>

  <h3>Trades Today</h3>
  <table border="1" cellspacing="0" cellpadding="6">
    {trades_rows}
  </table>

  <h3>Current Holdings</h3>
  <table border="1" cellspacing="0" cellpadding="6">
    {holdings_rows}
  </table>

  <p style="font-size:12px;">Paper trading only. Not financial advice.</p>
</body>
</html>
"""

    return subject, html
