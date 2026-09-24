"""
telegram_service.py
Optional Telegram Bot notification provider. Never crashes the app if the
bot token or the user's chat id is missing — it just reports "not configured".
"""
import os
import requests

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
API_BASE = f"https://api.telegram.org/bot{BOT_TOKEN}" if BOT_TOKEN else None


def is_configured():
    return bool(BOT_TOKEN)


def send_reminder(chat_id, patient_name, medicine_name, dosage, time_str,
                   food_instruction, reminder_id, follow_up=False):
    """Send a medicine reminder with inline Taken / Not Taken buttons."""
    if not is_configured() or not chat_id:
        return {"ok": False, "reason": "Telegram not configured"}

    if follow_up:
        text = (
            "⚠️ MEDICINE FOLLOW-UP\n\n"
            "You have not confirmed your medicine yet.\n\n"
            f"Medicine: {medicine_name}\n"
            f"Dosage: {dosage}\n\n"
            "Please take your medicine and confirm."
        )
    else:
        text = (
            "💊 MEDICINE REMINDER\n\n"
            f"Hello {patient_name},\n\n"
            "It is time to take:\n\n"
            f"Medicine: {medicine_name}\n"
            f"Dosage: {dosage}\n"
            f"Time: {time_str}\n"
            f"Instruction: {food_instruction or 'As advised'}\n\n"
            "Please take your medicine."
        )

    payload = {
        "chat_id": chat_id,
        "text": text,
        "reply_markup": {
            "inline_keyboard": [[
                {"text": "✅ TAKEN", "callback_data": f"taken:{reminder_id}"},
                {"text": "❌ NOT TAKEN", "callback_data": f"nottaken:{reminder_id}"},
            ]]
        },
    }
    try:
        resp = requests.post(f"{API_BASE}/sendMessage", json=payload, timeout=10)
        return {"ok": resp.ok, "response": resp.json() if resp.ok else resp.text}
    except requests.RequestException as exc:
        return {"ok": False, "reason": str(exc)}


def send_alert(chat_id, text):
    if not is_configured() or not chat_id:
        return {"ok": False, "reason": "Telegram not configured"}
    try:
        resp = requests.post(f"{API_BASE}/sendMessage",
                              json={"chat_id": chat_id, "text": text}, timeout=10)
        return {"ok": resp.ok}
    except requests.RequestException as exc:
        return {"ok": False, "reason": str(exc)}


def answer_callback_query(callback_query_id, text=""):
    if not is_configured():
        return
    try:
        requests.post(f"{API_BASE}/answerCallbackQuery",
                       json={"callback_query_id": callback_query_id, "text": text}, timeout=10)
    except requests.RequestException:
        pass


def set_webhook(webhook_url):
    if not is_configured():
        return {"ok": False, "reason": "Telegram not configured"}
    resp = requests.post(f"{API_BASE}/setWebhook", json={"url": webhook_url}, timeout=10)
    return resp.json()
