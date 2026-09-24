"""
call_service.py
Automated voice-call notification provider, designed around Twilio Voice.
Optional — the app must run normally even when call credentials are absent.
"""
import os

import sms_service

ACCOUNT_SID = os.environ.get("TWILIO_ACCOUNT_SID", "").strip()
AUTH_TOKEN = os.environ.get("TWILIO_AUTH_TOKEN", "").strip()
FROM_NUMBER = os.environ.get("TWILIO_CALL_FROM", "").strip()
PUBLIC_BASE_URL = os.environ.get("PUBLIC_BASE_URL", "").strip()  # needed for Twilio to fetch TwiML


def is_configured():
    return bool(ACCOUNT_SID and AUTH_TOKEN and FROM_NUMBER)


def build_twiml(patient_name, medicine_name, dosage, food_instruction):
    """Return the TwiML voice script Twilio should read out during the call."""
    message = (
        f"Hello {patient_name}. This is your medicine reminder. "
        f"It is time to take {medicine_name}, {dosage}. "
        f"Please take your medicine {food_instruction.lower() if food_instruction else ''}. "
        "Press 1 after taking your medicine. Press 2 if you have not taken your medicine."
    )
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Gather numDigits="1" action="/telegram/webhook" method="POST" timeout="10">
    <Say voice="alice">{message}</Say>
  </Gather>
  <Say voice="alice">We did not receive your response. Goodbye.</Say>
</Response>"""


def trigger_call(phone_number, patient_name, medicine_name, dosage, food_instruction):
    if not is_configured():
        return {"ok": False, "reason": "Automated phone-call service is not configured."}
    if not phone_number:
        return {"ok": False, "reason": "No phone number on file."}
    if not PUBLIC_BASE_URL:
        return {"ok": False, "reason": "PUBLIC_BASE_URL not set - Twilio needs a reachable TwiML URL."}

    try:
        from twilio.rest import Client
        client = Client(ACCOUNT_SID, AUTH_TOKEN)
        call = client.calls.create(
            twiml=build_twiml(patient_name, medicine_name, dosage, food_instruction),
            to=sms_service.normalize_phone(phone_number),
            from_=FROM_NUMBER,
        )
        return {"ok": True, "sid": call.sid}
    except ImportError:
        return {"ok": False, "reason": "twilio package not installed."}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "reason": str(exc)}
