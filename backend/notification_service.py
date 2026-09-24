"""
notification_service.py
Central dispatcher. Fans a single reminder event out to every notification
channel selected for that reminder. Each provider is independent and modular -
new channels can be added by writing a provider module and registering it
in `dispatch()`, without touching the scheduler.
"""
import logging

import telegram_service
import sms_service
import email_service
import call_service
import browser_notification
import action_links

logger = logging.getLogger("notification_service")


def _selected_methods(user, reminder=None):
    """Channels to use for this reminder.

    The method chosen when the reminder was created (the dropdown on the
    upload page) wins; the user's account-level preference is only the
    fallback. Previously the reminder's own choice was ignored, so picking
    "Email" or "SMS" for a prescription did nothing unless the account
    preference happened to include it too.
    """
    pref = None
    if reminder is not None:
        try:
            pref = reminder["notification_method"]
        except (KeyError, IndexError):
            pref = None
    pref = (pref or user["notification_preference"] or "browser").lower()
    methods = [m.strip() for m in pref.split(",") if m.strip() and m.strip() != "sound"]
    return methods or ["browser"]


def _safe(channel, fn, **kwargs):
    """Run one provider; one channel failing must never stop the others."""
    try:
        result = fn(**kwargs)
    except Exception as exc:  # noqa: BLE001
        logger.exception("%s notification crashed", channel)
        result = {"ok": False, "reason": str(exc)}
    if result.get("ok"):
        logger.info("%s notification sent", channel)
    else:
        logger.warning("%s notification NOT sent: %s", channel, result.get("reason") or result)
    return result


def dispatch(user, medicine, reminder, follow_up=False):
    """Send the reminder through every selected channel. Returns a report dict."""
    methods = _selected_methods(user, reminder)
    time_str = reminder["reminder_time"]
    link = action_links.response_url(reminder["id"])
    report = {}

    if "telegram" in methods:
        report["telegram"] = _safe(
            "telegram", telegram_service.send_reminder,
            chat_id=user["telegram_chat_id"],
            patient_name=user["name"],
            medicine_name=medicine["medicine_name"],
            dosage=medicine["dosage"],
            time_str=time_str,
            food_instruction=medicine["food_instruction"],
            reminder_id=reminder["id"],
            follow_up=follow_up,
        )

    if "sms" in methods:
        report["sms"] = _safe(
            "sms", sms_service.send_reminder,
            phone_number=user["phone"],
            medicine_name=medicine["medicine_name"],
            dosage=medicine["dosage"],
            time_str=time_str,
            food_instruction=medicine["food_instruction"],
            follow_up=follow_up,
            response_link=link,
        )

    if "email" in methods:
        report["email"] = _safe(
            "email", email_service.send_reminder,
            to_email=user["email"],
            patient_name=user["name"],
            medicine_name=medicine["medicine_name"],
            dosage=medicine["dosage"],
            time_str=time_str,
            food_instruction=medicine["food_instruction"],
            follow_up=follow_up,
            response_link=link,
        )

    if "call" in methods or "phone" in methods or "automated_call" in methods:
        report["call"] = _safe(
            "call", call_service.trigger_call,
            phone_number=user["phone"],
            patient_name=user["name"],
            medicine_name=medicine["medicine_name"],
            dosage=medicine["dosage"],
            food_instruction=medicine["food_instruction"],
        )

    if "browser" in methods:
        report["browser"] = _safe(
            "browser", browser_notification.queue,
            user_id=user["id"],
            reminder_id=reminder["id"],
            medicine_name=medicine["medicine_name"],
            dosage=medicine["dosage"],
            follow_up=follow_up,
        )

    return report


def send_test(user):
    """Send a test message on every channel in the user's account preference
    so a misconfigured channel (bad SMTP password, unverified Twilio number...)
    shows its real error immediately instead of failing silently later."""
    methods = _selected_methods(user)
    report = {}
    if "email" in methods:
        report["email"] = _safe(
            "email", email_service._send,
            to_email=user["email"], subject="Test: AI Medicine Reminder",
            body=f"Hello {user['name']},\n\nThis is a test message. Email reminders are working.",
        )
    if "sms" in methods:
        report["sms"] = _safe(
            "sms", sms_service.send_sms,
            phone_number=user["phone"],
            message="Test: AI Medicine Reminder SMS is working.",
        )
    if "telegram" in methods:
        report["telegram"] = _safe(
            "telegram", telegram_service.send_alert,
            chat_id=user["telegram_chat_id"],
            text="Test: AI Medicine Reminder Telegram is working.",
        )
    return report


def configured_channels():
    """Used by the settings/dashboard UI to show which providers are live."""
    return {
        "telegram": telegram_service.is_configured(),
        "sms": sms_service.is_configured(),
        "email": email_service.is_configured(),
        "call": call_service.is_configured(),
        "browser": True,
    }
