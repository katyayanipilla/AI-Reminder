"""
app.py
Main Flask application for AI Medicine Reminder.
Serves the frontend pages, exposes the JSON API, starts the SQLite schema
and boots the APScheduler background reminder checker.
"""
import logging
import os
import uuid
from html import escape
from datetime import datetime, date

from flask import Flask, request, jsonify, session, send_from_directory
from dotenv import load_dotenv

# Load backend/.env explicitly (independent of the folder the server is started
# from) BEFORE importing the service modules, which read credentials on import.
load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

import database
import models
import auth
import action_links
import reminder_service
import notification_service
import browser_notification
import ocr_service
import telegram_service

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(BASE_DIR)
FRONTEND_DIR = os.path.join(PROJECT_ROOT, "frontend")
UPLOAD_DIR = os.path.join(PROJECT_ROOT, "uploads")
ALLOWED_EXT = {"jpg", "jpeg", "png", "pdf"}

os.makedirs(UPLOAD_DIR, exist_ok=True)

app = Flask(__name__, static_folder=None)
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-change-me")

database.init_db()


# ----------------------------------------------------------- frontend ------
@app.route("/")
def index():
    return send_from_directory(FRONTEND_DIR, "index.html")


@app.route("/<path:filename>")
def frontend_files(filename):
    """Serve any frontend html/css/js file directly, e.g. /dashboard.html, /css/style.css."""
    full_path = os.path.join(FRONTEND_DIR, filename)
    if os.path.isfile(full_path):
        return send_from_directory(FRONTEND_DIR, filename)
    return jsonify({"error": "Not found"}), 404


# ---------------------------------------------------------------- auth -----
@app.route("/api/register", methods=["POST"])
def api_register():
    data = request.get_json(force=True)
    user_id, error = auth.register_user(data)
    if error:
        return jsonify({"error": error}), 400
    session["user_id"] = user_id
    return jsonify({"ok": True, "user_id": user_id})


@app.route("/api/login", methods=["POST"])
def api_login():
    data = request.get_json(force=True)
    user, error = auth.authenticate_user(data.get("identifier", ""), data.get("password", ""))
    if error:
        return jsonify({"error": error}), 401
    session["user_id"] = user["id"]
    return jsonify({"ok": True, "user_id": user["id"]})


@app.route("/api/logout", methods=["POST"])
def api_logout():
    session.clear()
    return jsonify({"ok": True})


@app.route("/api/me")
def api_me():
    user = auth.current_user()
    if not user:
        return jsonify({"error": "Not logged in"}), 401
    data = dict(user)
    data.pop("password_hash", None)  # never send the password hash to the browser
    return jsonify(data)


# ------------------------------------------------------------ upload/ocr ---
@app.route("/api/upload", methods=["POST"])
@auth.login_required
def api_upload():
    if "file" not in request.files:
        return jsonify({"error": "No file uploaded"}), 400
    file = request.files["file"]
    ext = file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else ""
    if ext not in ALLOWED_EXT:
        return jsonify({"error": "Unsupported file type. Use JPG, JPEG, PNG or PDF."}), 400

    filename = f"{uuid.uuid4().hex}.{ext}"
    save_path = os.path.join(UPLOAD_DIR, filename)
    file.save(save_path)

    result = ocr_service.process_prescription(save_path)
    if result.get("error"):
        return jsonify({"error": f"Could not read the prescription: {result['error']}"}), 422
    return jsonify({
        "ok": True,
        "file_url": f"/uploads/{filename}",
        "medicines": result["medicines"],
        "engine": result["engine"],
    })


@app.route("/uploads/<path:filename>")
def uploaded_file(filename):
    return send_from_directory(UPLOAD_DIR, filename)


# ---------------------------------------------------------- medicines ------
@app.route("/api/medicines/confirm", methods=["POST"])
@auth.login_required
def api_confirm_medicines():
    """Persist the user-verified list of medicines and generate reminders for each."""
    user = auth.current_user()
    data = request.get_json(force=True)
    medicines = data.get("medicines", [])
    notification_method = (data.get("notification_method") or "").strip() or user["notification_preference"]

    created_medicines, total_reminders = [], 0
    for m in medicines:
        med_id = models.create_medicine(
            user_id=user["id"],
            medicine_name=m["medicine_name"],
            dosage=m.get("dosage", ""),
            food_instruction=m.get("food_instruction", ""),
            frequency=m.get("frequency", ""),
            morning=m.get("morning", False),
            afternoon=m.get("afternoon", False),
            night=m.get("night", False),
            morning_time=m.get("morning_time", "08:00"),
            afternoon_time=m.get("afternoon_time", "14:00"),
            night_time=m.get("night_time", "20:00"),
            start_date=m.get("start_date") or date.today().isoformat(),
            end_date=m.get("end_date") or date.today().isoformat(),
            needs_verification=m.get("needs_verification", False),
        )
        med_row = models.get_medicine(med_id, user["id"])
        count = reminder_service.generate_reminders_for_medicine(med_row, notification_method)
        total_reminders += count
        created_medicines.append(med_id)

    return jsonify({"ok": True, "medicines_created": created_medicines, "reminders_created": total_reminders})


@app.route("/api/medicines", methods=["GET"])
@auth.login_required
def api_list_medicines():
    user = auth.current_user()
    rows = models.get_medicines_for_user(user["id"])
    return jsonify([dict(r) for r in rows])


SCHEDULE_FIELDS = {"morning", "afternoon", "night", "morning_time", "afternoon_time",
                    "night_time", "start_date", "end_date"}


@app.route("/api/medicines/<int:medicine_id>", methods=["PUT"])
@auth.login_required
def api_update_medicine(medicine_id):
    user = auth.current_user()
    data = request.get_json(force=True)
    allowed = {"medicine_name", "dosage", "food_instruction", "frequency", "morning",
               "afternoon", "night", "morning_time", "afternoon_time", "night_time",
               "start_date", "end_date", "active"}
    fields = {k: v for k, v in data.items() if k in allowed}
    models.update_medicine(medicine_id, user["id"], **fields)

    # If the user changed any reminder time, day-of-week toggle, or the
    # start/end date range, the already-generated future reminder rows are
    # now stale (they still hold the old time/date). Regenerate them from
    # the medicine's current settings so the edit actually takes effect.
    regenerated = 0
    if SCHEDULE_FIELDS & fields.keys():
        med_row = models.get_medicine(medicine_id, user["id"])
        if med_row and med_row["active"]:
            method = models.get_medicine_notification_method(medicine_id) or user["notification_preference"]
            regenerated = reminder_service.regenerate_future_reminders(med_row, method)
    return jsonify({"ok": True, "reminders_regenerated": regenerated})


@app.route("/api/medicines/<int:medicine_id>", methods=["DELETE"])
@auth.login_required
def api_delete_medicine(medicine_id):
    user = auth.current_user()
    models.delete_medicine(medicine_id, user["id"])
    return jsonify({"ok": True})


# ---------------------------------------------------------- reminders ------
@app.route("/api/reminders/today")
@auth.login_required
def api_reminders_today():
    user = auth.current_user()
    today = date.today().isoformat()
    rows = models.get_todays_reminders(user["id"], today)
    return jsonify([dict(r) for r in rows])


@app.route("/api/reminders/<int:reminder_id>/taken", methods=["POST"])
@auth.login_required
def api_reminder_taken(reminder_id):
    return _confirm_reminder(reminder_id, taken=True)


@app.route("/api/reminders/<int:reminder_id>/not_taken", methods=["POST"])
@auth.login_required
def api_reminder_not_taken(reminder_id):
    return _confirm_reminder(reminder_id, taken=False)


def _confirm_reminder(reminder_id, taken):
    user = auth.current_user()
    reminder = models.get_reminder(reminder_id)
    if not reminder or reminder["user_id"] != user["id"]:
        return jsonify({"error": "Reminder not found"}), 404
    status = _apply_response(user, reminder, taken)
    return jsonify({"ok": True, "status": status})


def _apply_response(user, reminder, taken):
    """Record a Taken / Not Taken answer (from the dashboard, Telegram, or an
    email/SMS link) and update the whole follow-up chain accordingly.
    Returns the resulting status string."""
    rid = reminder["id"]
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    scheduled = f"{reminder['reminder_date']} {reminder['reminder_time']}"

    if taken:
        if reminder["status"] == "Taken":
            return "Taken"
        # Settles the original reminder and cancels any queued follow-up, so
        # nothing keeps firing once the patient has confirmed (a late "Taken"
        # also corrects a dose that had already been marked Missed).
        reminder_service.resolve_chain(rid, "Taken", overwrite_missed=True)
        models.add_history(
            user_id=user["id"], medicine_id=reminder["medicine_id"], reminder_id=rid,
            scheduled_time=scheduled, taken_time=now, status="Taken",
            notification_method=reminder["notification_method"],
        )
        return "Taken"

    if reminder["status"] in ("Taken", "Missed"):
        return reminder["status"]

    models.update_reminder_status(rid, "Not Taken", follow_up_sent=1)
    models.add_history(
        user_id=user["id"], medicine_id=reminder["medicine_id"], reminder_id=rid,
        scheduled_time=scheduled, taken_time=None, status="Not Taken",
        notification_method=reminder["notification_method"],
    )

    chain = models.get_reminder_chain(rid)
    already_queued = any(r["id"] > rid and r["status"] == "Pending" for r in chain)
    if not already_queued:
        if len(chain) - 1 < reminder_service.MAX_FOLLOWUPS:
            reminder_service.create_followup(reminder, user["follow_up_minutes"] or 5)
        else:
            reminder_service.mark_missed(reminder)
            return "Missed"
    return "Not Taken"


# --------------------------------------- answer from email / SMS link ------
def _answer_page(title, message, buttons_for=None):
    buttons = ""
    if buttons_for:
        buttons = (
            f'<form method="post" action="/r/{buttons_for}/taken" style="margin:10px 0">'
            '<button style="width:100%;padding:16px;font-size:18px;background:#16a34a;color:#fff;border:0;border-radius:10px">✅ Taken</button></form>'
            f'<form method="post" action="/r/{buttons_for}/nottaken" style="margin:10px 0">'
            '<button style="width:100%;padding:16px;font-size:18px;background:#dc2626;color:#fff;border:0;border-radius:10px">❌ Not Taken</button></form>'
        )
    return (
        '<!doctype html><html><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f"<title>{escape(title)}</title></head>"
        '<body style="font-family:system-ui,sans-serif;max-width:420px;margin:40px auto;padding:0 16px;text-align:center">'
        f"<h2>{escape(title)}</h2><p>{escape(message)}</p>{buttons}</body></html>"
    )


@app.route("/r/<token>", methods=["GET"])
def reminder_link_page(token):
    """Shows Taken / Not Taken buttons. Nothing is recorded on GET, so link
    previews and mail scanners that open URLs can't answer for the patient."""
    rid = action_links.read_token(token)
    reminder = models.get_reminder(rid) if rid else None
    if not reminder:
        return _answer_page("Link not valid", "This reminder link is invalid or has expired."), 404
    medicine = models.get_medicine(reminder["medicine_id"], reminder["user_id"])
    name = medicine["medicine_name"] if medicine else "your medicine"
    dosage = (medicine["dosage"] if medicine else "") or ""
    return _answer_page(f"{name} {dosage}".strip(), "Did you take this medicine?", buttons_for=token)


@app.route("/r/<token>/<action>", methods=["POST"])
def reminder_link_answer(token, action):
    rid = action_links.read_token(token)
    reminder = models.get_reminder(rid) if rid else None
    if not reminder or action not in ("taken", "nottaken"):
        return _answer_page("Link not valid", "This reminder link is invalid or has expired."), 404
    user = models.get_user_by_id(reminder["user_id"])
    status = _apply_response(user, reminder, taken=(action == "taken"))
    if status == "Taken":
        return _answer_page("Recorded ✅", "Marked as taken. Thank you!")
    if status == "Missed":
        return _answer_page("Recorded", "Marked as not taken.")
    return _answer_page("Recorded", "Marked as not taken. We'll remind you again shortly.")


# -------------------------------------------------------------- history ----
@app.route("/api/history")
@auth.login_required
def api_history():
    user = auth.current_user()
    rows = models.get_history(
        user["id"],
        start_date=request.args.get("start_date"),
        end_date=request.args.get("end_date"),
        medicine_id=request.args.get("medicine_id"),
        status=request.args.get("status"),
    )
    return jsonify([dict(r) for r in rows])


# ------------------------------------------------------------ dashboard ----
@app.route("/api/dashboard/stats")
@auth.login_required
def api_dashboard_stats():
    user = auth.current_user()
    today = date.today().isoformat()
    todays = models.get_todays_reminders(user["id"], today)
    taken = sum(1 for r in todays if r["status"] == "Taken")
    missed = sum(1 for r in todays if r["status"] == "Missed")
    pending = sum(1 for r in todays if r["status"] in ("Pending", "Not Taken"))
    total = len(todays)
    adherence = round((taken / total) * 100) if total else 0

    upcoming = [r for r in todays if r["status"] == "Pending"]
    next_med = dict(upcoming[0]) if upcoming else None

    return jsonify({
        "total_today": total, "taken": taken, "pending": pending, "missed": missed,
        "adherence": adherence, "next_medicine": next_med,
        "todays_medicines": [dict(r) for r in todays],
        "channels": notification_service.configured_channels(),
    })


@app.route("/api/statistics")
@auth.login_required
def api_statistics():
    user = auth.current_user()
    rows = models.get_history(user["id"])
    taken = sum(1 for r in rows if r["status"] == "Taken")
    missed = sum(1 for r in rows if r["status"] == "Missed")
    pending = sum(1 for r in rows if r["status"] in ("Pending", "Not Taken"))
    total = len(rows)
    adherence = round((taken / total) * 100) if total else 0
    medicines = models.get_medicines_for_user(user["id"])

    return jsonify({
        "total_medicines": len(medicines), "total_reminders": total,
        "taken": taken, "missed": missed, "pending": pending, "adherence": adherence,
    })


# --------------------------------------------------------------- settings --
@app.route("/api/settings/notifications", methods=["GET", "POST"])
@auth.login_required
def api_settings_notifications():
    user = auth.current_user()
    if request.method == "GET":
        return jsonify({
            "notification_preference": user["notification_preference"],
            "telegram_chat_id": user["telegram_chat_id"],
            "follow_up_minutes": user["follow_up_minutes"],
            "miss_alert_enabled": bool(user["miss_alert_enabled"]),
            "emergency_contact_name": user["emergency_contact_name"],
            "emergency_contact_phone": user["emergency_contact_phone"],
            "channels": notification_service.configured_channels(),
        })

    data = request.get_json(force=True)
    fields = {}
    for key in ("notification_preference", "telegram_chat_id", "follow_up_minutes",
                "emergency_contact_name", "emergency_contact_phone"):
        if key in data:
            fields[key] = data[key]
    if "miss_alert_enabled" in data:
        fields["miss_alert_enabled"] = int(bool(data["miss_alert_enabled"]))
    models.update_user_settings(user["id"], **fields)
    return jsonify({"ok": True})


@app.route("/api/settings/test_notification", methods=["POST"])
@auth.login_required
def api_test_notification():
    """Send a test message on the user's email / SMS / Telegram channels and
    report the real provider error for any that fail."""
    user = auth.current_user()
    report = notification_service.send_test(user)
    return jsonify({"ok": True, "report": report})


# ------------------------------------------------------- browser polling ---
@app.route("/api/notifications/pending")
@auth.login_required
def api_notifications_pending():
    user = auth.current_user()
    return jsonify(browser_notification.pull_pending(user["id"]))


# ----------------------------------------------------------- telegram ------
@app.route("/telegram/webhook", methods=["POST"])
def telegram_webhook():
    """Handles Taken/Not Taken inline-button callbacks from Telegram."""
    update = request.get_json(silent=True) or {}
    callback = update.get("callback_query")
    if not callback:
        return jsonify({"ok": True})

    data = callback.get("data", "")
    chat_id = callback["message"]["chat"]["id"]
    user = models.get_user_by_telegram_chat_id(chat_id)
    if not user:
        telegram_service.answer_callback_query(callback["id"], "Account not linked.")
        return jsonify({"ok": True})

    if ":" not in data:
        return jsonify({"ok": True})
    action, reminder_id_str = data.split(":", 1)
    try:
        reminder_id = int(reminder_id_str)
    except ValueError:
        return jsonify({"ok": True})

    reminder = models.get_reminder(reminder_id)
    if reminder and reminder["user_id"] == user["id"]:
        taken = action == "taken"
        _apply_response(user, reminder, taken)
        telegram_service.answer_callback_query(
            callback["id"], "Marked as taken ✅" if taken else "Marked as not taken ❌"
        )
    return jsonify({"ok": True})


# -------------------------------------------------------------- demo mode --
@app.route("/api/demo/seed", methods=["POST"])
@auth.login_required
def api_demo_seed():
    """Populate the logged-in account with sample medicines for a quick expo demo."""
    user = auth.current_user()
    today = date.today().isoformat()
    samples = [
        {"medicine_name": "Paracetamol", "dosage": "500 mg", "food_instruction": "After Food",
         "frequency": "3 times a day", "morning": True, "afternoon": True, "night": True,
         "morning_time": "08:00", "afternoon_time": "14:00", "night_time": "20:00"},
        {"medicine_name": "Vitamin Tablet", "dosage": "1 Tablet", "food_instruction": "After Food",
         "frequency": "once a day", "morning": False, "afternoon": True, "night": False,
         "morning_time": "08:00", "afternoon_time": "14:00", "night_time": "20:00"},
    ]
    created = 0
    for m in samples:
        med_id = models.create_medicine(
            user_id=user["id"], medicine_name=m["medicine_name"], dosage=m["dosage"],
            food_instruction=m["food_instruction"], frequency=m["frequency"],
            morning=m["morning"], afternoon=m["afternoon"], night=m["night"],
            morning_time=m["morning_time"], afternoon_time=m["afternoon_time"],
            night_time=m["night_time"], start_date=today, end_date=today,
        )
        med_row = models.get_medicine(med_id, user["id"])
        created += reminder_service.generate_reminders_for_medicine(med_row, user["notification_preference"])
    return jsonify({"ok": True, "reminders_created": created})


@app.route("/api/demo/test_reminder", methods=["POST"])
@auth.login_required
def api_demo_test_reminder():
    """Create (or reuse) a demo medicine and schedule one reminder N minutes from now."""
    user = auth.current_user()
    data = request.get_json(force=True)
    minutes = int(data.get("minutes", 1))

    from datetime import timedelta
    fire_at = datetime.now() + timedelta(minutes=minutes)
    today = date.today().isoformat()

    med_id = models.create_medicine(
        user_id=user["id"], medicine_name="Test Medicine", dosage="1 Tablet",
        food_instruction="After Food", frequency="Test", morning=False, afternoon=False,
        night=False, morning_time="08:00", afternoon_time="14:00", night_time="20:00",
        start_date=today, end_date=today,
    )
    reminder_id = models.create_reminder(
        user_id=user["id"], medicine_id=med_id,
        reminder_date=fire_at.strftime("%Y-%m-%d"), reminder_time=fire_at.strftime("%H:%M"),
        notification_method=user["notification_preference"],
    )
    return jsonify({"ok": True, "fires_at": fire_at.strftime("%Y-%m-%d %H:%M"), "reminder_id": reminder_id})


if __name__ == "__main__":
    from scheduler import start_scheduler
    start_scheduler()
    app.run(debug=True, host="127.0.0.1", port=5000, use_reloader=False)
