"""
sms_service.py
SMS notification provider, designed around the Twilio API but kept generic
so another SMS gateway can be dropped in later. Degrades gracefully - the
app must keep working even if no SMS credentials are configured.
"""
import logging
import os
import re

logger = logging.getLogger("sms_service")

ACCOUNT_SID = os.environ.get("TWILIO_ACCOUNT_SID", "").strip()
AUTH_TOKEN = os.environ.get("TWILIO_AUTH_TOKEN", "").strip()
FROM_NUMBER = os.environ.get("TWILIO_SMS_FROM", "").strip()
# Used when a user typed a local number such as 9876543210 (Twilio needs +91...).
DEFAULT_COUNTRY_CODE = os.environ.get("DEFAULT_COUNTRY_CODE", "+91").strip() or "+91"


def is_configured():
    return bool(ACCOUNT_SID and AUTH_TOKEN and FROM_NUMBER)


def normalize_phone(phone_number):
    """Twilio only accepts E.164 numbers (+<country code><number>). Users
    usually register with a plain 10-digit number, which Twilio rejects, so
    add the default country code when it is missing."""
    if not phone_number:
        return ""
    raw = str(phone_number).strip()
    digits = re.sub(r"\D", "", raw)
    if raw.startswith("+"):
        return "+" + digits
    if raw.startswith("00"):
        return "+" + digits[2:]
    digits = digits.lstrip("0") if len(digits) == 11 and digits.startswith("0") else digits
    return f"{DEFAULT_COUNTRY_CODE}{digits}"


def send_reminder(phone_number, medicine_name, dosage, time_str, food_instruction,
                  follow_up=False, response_link=None):
    if follow_up:
        message = f"Follow-up: you have not confirmed {medicine_name} {dosage}. Please take it now."
    else:
        message = (
            f"Medicine Reminder: Take {medicine_name} {dosage} at {time_str}"
            f"{' ' + food_instruction.lower() if food_instruction else ''}."
        )
    if response_link:
        message += f" Reply Taken / Not Taken here: {response_link}"
    return send_sms(phone_number, message)


def send_sms(phone_number, message):
    if not is_configured():
        return {"ok": False, "reason": "SMS service is not configured (TWILIO_* values missing in backend/.env)."}
    if not phone_number:
        return {"ok": False, "reason": "No phone number on file."}

    to_number = normalize_phone(phone_number)
    try:
        # Imported lazily so the package is only required if SMS is actually used.
        from twilio.rest import Client
        client = Client(ACCOUNT_SID, AUTH_TOKEN)
        msg = client.messages.create(body=message, from_=FROM_NUMBER, to=to_number)
        return {"ok": True, "sid": msg.sid}
    except ImportError:
        return {"ok": False, "reason": "twilio package not installed (pip install twilio)."}
    except Exception as exc:  # noqa: BLE001 - surface any provider error safely
        logger.warning("SMS to %s failed: %s", to_number, exc)
        return {"ok": False, "reason": str(exc)}
