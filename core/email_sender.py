"""
SMTP-based email sender with an HTML digest template.

Configure via env vars:
    SMTP_HOST (default smtp.gmail.com)
    SMTP_PORT (default 587)
    SMTP_USER
    SMTP_PASSWORD   (Gmail app password, NOT your Google account password)
    SMTP_FROM       (defaults to SMTP_USER)

For Gmail: turn on 2FA and create an app password at
https://myaccount.google.com/apppasswords
"""
from __future__ import annotations

import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.header import Header
from datetime import datetime


def send_email(to_email: str, subject: str, html_body: str, text_body: str = "") -> None:
    host = os.environ.get("SMTP_HOST", "smtp.gmail.com")
    port = int(os.environ.get("SMTP_PORT", 587))
    user = os.environ.get("SMTP_USER")
    password = os.environ.get("SMTP_PASSWORD")
    from_addr = os.environ.get("SMTP_FROM", user)

    if not user or not password:
        print(f"[email_sender] SMTP not configured. Skipping email to {to_email}.")
        return

    msg = MIMEMultipart("alternative")
    msg["Subject"] = Header(subject, "utf-8")
    msg["From"] = from_addr
    msg["To"] = to_email
    if text_body:
        msg.attach(MIMEText(text_body, "plain", "utf-8"))
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    with smtplib.SMTP(host, port) as server:
        server.starttls()
        server.login(user, password)
        server.sendmail(from_addr, [to_email], msg.as_string())


def render_daily_email(
    user_email: str,
    portfolio: dict,
    total_value: float,
    day_pnl: float,
    day_pnl_pct: float,
    total_return_pct: float,
    trades_today: list[dict],
    positions: list[dict],
    strategy_display: str,
) -> tuple[str, str]:
    """Return (subject, html_body) for the morning digest email."""
    today = datetime.utcnow().strftime("%A, %B %d, %Y")
    color_pnl = "#16a34a" if day_pnl >= 0 else "#dc2626"
    color_total = "#16a34a" if total_return_pct >= 0 else "#dc2626"
    pnl_sign = "+" if day_pnl >= 0 else ""

    trades_rows = ""
    if trades_today:
        for t in trades_today:
            side_color = "#16a34a" if t["side"] == "buy" else "#dc2626"
            trades_rows += f"""
            <tr>
              <td style="padding:8px 12px;border-bottom:1px solid #eee;">{t['ticker']}</td>
              <td style="padding:8px 12px;border-bottom:1px solid #eee;color:{side_color};font-weight:600;text-transform:uppercase;">{t['side']}</td>
              <td style="padding:8px 12px;border-bottom:1px solid #eee;text-align:right;">{t['shares']:.4f}</td>
              <td style="padding:8px 12px;border-bottom:1px solid #eee;text-align:right;">${t['price']:.2f}</td>
              <td style="padding:8px 12px;border-bottom:1px solid #eee;font-size:12px;color:#64748b;">{t.get('reason', '')}</td>
            </tr>"""
    else:
        trades_rows = """<tr><td colspan="5" style="padding:16px;text-align:center;color:#64748b;">No trades today &mdash; strategy said hold.</td></tr>"""

    holdings_rows = ""
    if positions:
        for p in positions:
            pnl_color = "#16a34a" if p["unrealized_pnl"] >= 0 else "#dc2626"
            holdings_rows += f"""
            <tr>
              <td style="padding:8px 12px;border-bottom:1px solid #eee;">{p['ticker']}</td>
              <td style="padding:8px 12px;border-bottom:1px solid #eee;text-align:right;">{p['shares']:.4f}</td>
              <td style="padding:8px 12px;border-bottom:1px solid #eee;text-align:right;">${p['current_price']:.2f}</td>
              <td style="padding:8px 12px;border-bottom:1px solid #eee;text-align:right;">${p['market_value']:,.2f}</td>
              <td style="padding:8px 12px;border-bottom:1px solid #eee;text-align:right;color:{pnl_color};">{p['unrealized_pnl_pct']:+.2f}%</td>
            </tr>"""
    else:
        holdings_rows = """<tr><td colspan="5" style="padding:16px;text-align:center;color:#64748b;">All in cash.</td></tr>"""

    subject = f"\U0001F4C8 {portfolio['name']}: ${total_value:,.2f} ({pnl_sign}{day_pnl_pct:.2f}% today)"

    html = f"""
<html>
<body style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:#f8fafc;margin:0;padding:24px;">
  <div style="max-width:640px;margin:0 auto;background:white;border-radius:12px;overflow:hidden;box-shadow:0 2px 8px rgba(0,0,0,0.04);">
    <div style="background:linear-gradient(135deg,#0f172a,#1e293b);padding:32px 28px;color:white;">
      <div style="font-size:11px;letter-spacing:2px;text-transform:uppercase;opacity:0.6;">Digital Twin Investor &middot; {today}</div>
      <h1 style="margin:8px 0 4px 0;fon
