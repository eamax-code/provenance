"""Minimal SMTP adapter. Active only when EMAIL_PROVIDER=smtp and SMTP settings exist."""

from __future__ import annotations

import json
import smtplib
from email.message import EmailMessage

from app.core.config import Settings


def send_filing_email(settings: Settings, to_address: str, payload: dict) -> None:
    data = payload["data"]
    msg = EmailMessage()
    msg["Subject"] = f"New SEC filing: {data['form_type']} for CIK {data['cik']}"
    msg["From"] = settings.email_from
    msg["To"] = to_address
    body = (
        "A new SEC filing was detected.\n\n"
        f"CIK: {data['cik']}\nForm: {data['form_type']}\nFiling date: {data['filing_date']}\n"
        f"Accession: {data['accession_number']}\nSource: {data['source_url']}\n\n"
        f"Event: {payload['event_id']}\n\n"
        "Data from SEC EDGAR. This service is independent and not affiliated with the SEC.\n\n"
        + json.dumps(payload, indent=2)
    )
    msg.set_content(body)
    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=10) as smtp:
        if settings.smtp_use_tls:
            smtp.starttls()
        if settings.smtp_username:
            smtp.login(settings.smtp_username, settings.smtp_password)
        smtp.send_message(msg)
