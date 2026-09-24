"""
email_service.py
Email notification provider, built on Python's standard-library smtplib so
no extra package is required. Works with any SMTP server (Gmail, Outlook,
a college mail relay, etc). Degrades gracefully — the app must keep working
even if no SMTP credentials are configured.
"""
import logging
import os
import smtplib
import ssl
from email.message import EmailMessage

logger = logging.getLogger("email_service")

SMTP_HOST = os.environ.get("SMTP_HOST", "").strip()
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587") or "587")
SMTP_USERNAME = os.environ.get("SMTP_USERNAME", "").strip()
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "").strip()
SMTP_FROM = (os.environ.get("SMTP_FROM", "").strip() or SMTP_USERNAME)
# "tls" (STARTTLS, typical for port 587) or "ssl" (implicit TLS, typical for port 465)
SMTP_SECURITY = os.environ.get("SMTP_SECURITY", "tls").strip().lower()


def is_configured():
    return bool(SMTP_HOST and SMTP_USERNAME and SMTP_PASSWORD and SMTP_FROM)


def _send(to_email, subject, body):
    if not is_configured():
        return {"ok": False, "reason": "Email service is not configured (SMTP_HOST / SMTP_USERNAME / SMTP_PASSWORD missing in backend/.env)."}
    if not to_email:
        return {"ok": False, "reason": "No email address on file."}

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = SMTP_FROM
    msg["To"] = to_email
    msg.set_content(body)

    try:
        if SMTP_SECURITY == "ssl":
            with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, context=ssl.create_default_context(), timeout=20) as server:
                server.login(SMTP_USERNAME, SMTP_PASSWORD)
                server.send_message(msg)
        else:
            with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=20) as server:
                server.ehlo()
                server.starttls(context=ssl.create_default_context())
                server.ehlo()
                server.login(SMTP_USERNAME, SMTP_PASSWORD)
                server.send_message(msg)
        return {"ok": True}
    except Exception as exc:  # noqa: BLE001 - surface any provider error safely
        logger.warning("Email to %s failed: %s", to_email, exc)
        return {"ok": False, "reason": str(exc)}


def send_reminder(to_email, patient_name, medicine_name, dosage, time_str,
                   food_instruction, follow_up=False, response_link=None):
    answer = (
        f"\n\nAnswer here (Taken / Not Taken): {response_link}\n\n" if response_link else "\n\n"
    )
    if follow_up:
        subject = f"Follow-up: You still haven't confirmed {medicine_name}"
        body = (
            f"Hello {patient_name},\n\n"
            "You have not confirmed your medicine yet.\n\n"
            f"Medicine: {medicine_name}\n"
            f"Dosage: {dosage}\n\n"
            "Please take your medicine and confirm it."
            f"{answer}"
            "— AI Medicine Reminder"
        )
    else:
        subject = f"Medicine Reminder: {medicine_name} at {time_str}"
        body = (
            f"Hello {patient_name},\n\n"
            "It is time to take:\n\n"
            f"Medicine: {medicine_name}\n"
            f"Dosage: {dosage}\n"
            f"Time: {time_str}\n"
            f"Instruction: {food_instruction or 'As advised'}\n\n"
            "Please take your medicine."
            f"{answer}"
            "— AI Medicine Reminder"
        )
    return _send(to_email, subject, body)


def send_alert(to_email, patient_name, subject, text):
    body = f"{text}\n\n— AI Medicine Reminder"
    return _send(to_email, subject, body)
