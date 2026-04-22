from __future__ import annotations

import os
import re
import smtplib
from datetime import datetime
from email.message import EmailMessage
from email import policy


def clean_smtp(value: str | None) -> str | None:
    if value is None:
        return None
    return re.sub(r"\s+", "", value, flags=re.UNICODE)


def clean_text(value: str) -> str:
    if value is None:
        return ""
    return value.replace("\xa0", " ").strip()


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

    # ✅ Use UTF-8 capable policy
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

            # ✅ This is the key: send as bytes with UTF-8
            server.login(user, password)
            server.send_message(msg)
    except Exception as e:
        print(f"[email_sender] Failed to send email: {e}")
