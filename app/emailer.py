"""
Sends email through one of two providers, chosen in .env:

  EMAIL_PROVIDER=smtp   Gmail (or any SMTP server). Easiest for running locally.
  EMAIL_PROVIDER=brevo  Brevo's HTTPS API. Use this when hosted on a platform that
                        blocks SMTP ports (Render's free tier does).

If nothing is configured the message is still saved to the outbox as a draft,
so the process never fails because of email.
"""
import asyncio
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr

import httpx

from . import config
from .samples import SAMPLES


def _send_smtp(to_addr: str, subject: str, body: str):
    msg = EmailMessage()
    msg["From"] = formataddr((config.EMAIL_FROM_NAME, config.EMAIL_FROM))
    msg["To"] = to_addr
    msg["Subject"] = subject
    msg.set_content(body)
    context = ssl.create_default_context()
    if config.SMTP_PORT == 465:
        with smtplib.SMTP_SSL(config.SMTP_HOST, 465, context=context, timeout=20) as s:
            s.login(config.SMTP_USER, config.SMTP_PASSWORD)
            s.send_message(msg)
    else:
        with smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT, timeout=20) as s:
            s.starttls(context=context)
            s.login(config.SMTP_USER, config.SMTP_PASSWORD)
            s.send_message(msg)


async def _send_brevo(to_addr: str, subject: str, body: str):
    payload = {
        "sender": {"name": config.EMAIL_FROM_NAME, "email": config.EMAIL_FROM},
        "to": [{"email": to_addr}],
        "subject": subject,
        "textContent": body,
    }
    async with httpx.AsyncClient(timeout=20) as client:
        resp = await client.post("https://api.brevo.com/v3/smtp/email", json=payload,
                                 headers={"api-key": config.BREVO_API_KEY, "accept": "application/json"})
        if resp.status_code >= 300:
            raise RuntimeError(f"Brevo HTTP {resp.status_code}: {resp.text[:200]}")


SAMPLE_ADDRESSES = {s["fields"]["contact_email"].lower() for s in SAMPLES.values()}


def should_redirect(address: str) -> bool:
    if not config.DEMO_REDIRECT_TO or not address:
        return False
    if address.lower() == config.DEMO_REDIRECT_TO.lower():
        return False
    if config.DEMO_REDIRECT_MODE == "all":
        return True
    return address.lower() in SAMPLE_ADDRESSES


async def send(intended_to: str, subject: str, body: str) -> dict:
    """
    Returns {"status": sent|failed|not_configured, "to": actual recipient,
             "provider": ..., "error": ..., "body": body actually sent}
    """
    to_addr = intended_to
    if should_redirect(intended_to):
        to_addr = config.DEMO_REDIRECT_TO
        body = f"[Demo mode: this email was addressed to {intended_to}]\n\n{body}"

    result = {"to": to_addr, "provider": config.EMAIL_PROVIDER, "error": None, "body": body}
    if not config.email_configured():
        return {**result, "status": "not_configured",
                "error": "Email sending is not configured; saved as draft only"}
    if not to_addr:
        return {**result, "status": "failed", "error": "No recipient address"}
    try:
        if config.EMAIL_PROVIDER == "smtp":
            await asyncio.to_thread(_send_smtp, to_addr, subject, body)
        else:
            await _send_brevo(to_addr, subject, body)
        return {**result, "status": "sent"}
    except Exception as exc:
        return {**result, "status": "failed", "error": f"{type(exc).__name__}: {str(exc)[:200]}"}
