"""
SMTP-based email sender with an HTML digest template.

- Handles Gmail app-password quirks (removes all whitespace, including NBSP)
- Ensures proper UTF-8 encoding for email headers (fixes ascii errors)
- Adds basic error handling and safer dict access
"""

from __future__ import annotations

import os
import re
import smtplib
from datetime import datetime
from email.message import EmailMessage
from email.header import Header
from typing import Optional


# ---------- Cleaning Utilities ----------

def clean_smtp(value: Optional[str]) -> Optional[str]:
    """Clean SMTP credentials (strict ASCII, no whitespace)."""
    if value is None:
        return None
    value = re.sub(r"\s+", "", value, flags=re.UNICODE)  # remove ALL whitespace incl. NBSP
    return value.encode("ascii", "ignore").decode()


def clean_text(value: str) -> str:
    """Clean display text (preserve spaces, remove NBSP)."""
    return value.replace("\xa0", " ").strip()


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

    # Clean subject (fix NBSP issue) + encode properly
    subject = clean_text(subject)

    msg = EmailMessage()
    msg["Subject"] = str(Header(subject, "utf-8"))  # FIX: prevents ascii errors
    msg["From"] = from_addr
    msg["To"] = to_email

    msg.set_content(text_body or "View this email in an HTML-capable client.")
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
    """Return (subject, html_body) for the daily digest email."""

    today = datetime.utcnow().strftime("%A, %B %d, %Y")

    color_pnl = "#16a34a" if day_pnl >= 0 else "#dc2626"
    color_total = "#16a34a" if total_return_pct >= 0 else "#dc2626"
    pnl_sign = "+" if day_pnl >= 0 else ""

    portfolio_name = clean_text(portfolio.get("name", "Portfolio"))

    # ---------- Trades ----------
    if trades_today:
        trades_rows = ""
        for t in trades_today:
            side = str(t.get("side", "")).lower()
            side_color = "#16a34a" if side == "buy" else "#dc2626"

            trades_rows += f"""
            <tr>
              <td style="padding:8px 12px;border-bottom:1px solid #eee;">{clean_text(str(t.get('ticker', '')))}</td>
              <td style="padding:8px 12px;border-bottom:1px solid #eee;color:{side_color};font-weight:600;text-transform:uppercase;">{side}</td>
              <td style="padding:8px 12px;border-bottom:1px solid #eee;text-align:right;">{t.get('shares', 0):.4f}</td>
              <td style="padding:8px 12px;border-bottom:1px solid #eee;text-align:right;">${t.get('price', 0):.2f}</td>
              <td style="padding:8px 12px;border-bottom:1px solid #eee;font-size:12px;color:#64748b;">{clean_text(str(t.get('reason', '')))}</td>
            </tr>
            """
    else:
        trades_rows = """
        <tr>
          <td colspan="5" style="padding:16px;text-align:center;color:#64748b;">
            No trades today &mdash; strategy said hold.
          </td>
        </tr>
        """

    # ---------- Holdings ----------
    if positions:
        holdings_rows = ""
        for p in positions:
            pnl = p.get("unrealized_pnl", 0)
            pnl_color = "#16a34a" if pnl >= 0 else "#dc2626"

            holdings_rows += f"""
            <tr>
              <td style="padding:8px 12px;border-bottom:1px solid #eee;">{clean_text(str(p.get('ticker', '')))}</td>
              <td style="padding:8px 12px;border-bottom:1px solid #eee;text-align:right;">{p.get('shares', 0):.4f}</td>
              <td style="padding:8px 12px;border-bottom:1px solid #eee;text-align:right;">${p.get('current_price', 0):.2f}</td>
              <td style="padding:8px 12px;border-bottom:1px solid #eee;text-align:right;">${p.get('market_value', 0):,.2f}</td>
              <td style="padding:8px 12px;border-bottom:1px solid #eee;text-align:right;color:{pnl_color};">
                {p.get('unrealized_pnl_pct', 0):+.2f}%
              </td>
            </tr>
            """
    else:
        holdings_rows = """
        <tr>
          <td colspan="5" style="padding:16px;text-align:center;color:#64748b;">
            All in cash.
          </td>
        </tr>
        """

    # ---------- Subject ----------
    subject = f"📈 {portfolio_name}: ${total_value:,.2f} ({pnl_sign}{day_pnl_pct:.2f}% today)"

    # ---------- HTML ----------
    html = f"""
<html>
<body style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:#f8fafc;margin:0;padding:24px;">
  <div style="max-width:640px;margin:0 auto;background:white;border-radius:12px;overflow:hidden;">
    
    <div style="background:linear-gradient(135deg,#0f172a,#1e293b);padding:32px;color:white;">
      <div style="font-size:11px;opacity:0.6;">Digital Twin Investor · {today}</div>
      <h1>{portfolio_name}</h1>
      <div>Strategy: {clean_text(strategy_display)}</div>
    </div>

    <div style="padding:24px;">
      <h3>Trades Today</h3>
      <table style="width:100%;border-collapse:collapse;">
        <tbody>{trades_rows}</tbody>
      </table>

      <h3 style="margin-top:20px;">Current Holdings</h3>
      <table style="width:100%;border-collapse:collapse;">
        <tbody>{holdings_rows}</tbody>
      </table>

      <div style="margin-top:20px;font-size:12px;color:#94a3b8;text-align:center;">
        Paper trading only. Not financial advice.
      </div>
    </div>

  </div>
</body>
</html>
"""

    return subject, html
