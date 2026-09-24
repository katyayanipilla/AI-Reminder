"""
reminder_service.py
Turns a confirmed medicine entry (with morning/afternoon/night flags and a
date range) into individual reminder rows in the database.
"""
import logging
import os
from datetime import datetime, timedelta

import models

logger = logging.getLogger("reminder_service")

# How many times a dose is re-sent (every follow-up interval, default 5 min)
# while the patient has not answered Taken / Not Taken. After that the dose
# is marked Missed. 6 x 5 min = the dose keeps nagging for ~30 minutes.
MAX_FOLLOWUPS = int(os.environ.get("MAX_FOLLOWUPS", "6") or "6")


def _daterange(start_date, end_date):
    start = datetime.strptime(start_date, "%Y-%m-%d")
    end = datetime.strptime(end_date, "%Y-%m-%d")
    days = (end - start).days
    if days < 0:
        days = 0
    for i in range(days + 1):
        yield (start + timedelta(days=i)).strftime("%Y-%m-%d")


def generate_reminders_for_medicine(medicine_row, notification_method):
    """Create one reminder per active time-slot per day for the medicine's date range."""
    user_id = medicine_row["user_id"]
    medicine_id = medicine_row["id"]
    slots = []
    if medicine_row["morning"]:
        slots.append(medicine_row["morning_time"])
    if medicine_row["afternoon"]:
        slots.append(medicine_row["afternoon_time"])
    if medicine_row["night"]:
        slots.append(medicine_row["night_time"])

    if not slots:
        return 0

    start_date = medicine_row["start_date"]
    end_date = medicine_row["end_date"]
    created = 0
    for day in _daterange(start_date, end_date):
        for time_str in slots:
            models.create_reminder(
                user_id=user_id,
                medicine_id=medicine_id,
                reminder_date=day,
                reminder_time=time_str,
                notification_method=notification_method,
            )
            created += 1
    return created


def regenerate_future_reminders(medicine_row, notification_method, from_date=None):
    """Re-create a medicine's not-yet-sent reminders from its *current*
    settings. Call this after the user edits a medicine's times, days, or
    start/end dates - without it, reminders already generated at creation
    time keep firing at the old time/date and the edit has no real effect
    (the app used to just warn the user about this instead of fixing it).
    Reminders that were already notified (sent) are left untouched so
    history/adherence stats aren't disturbed.
    """
    from_date = from_date or datetime.now().strftime("%Y-%m-%d")
    models.delete_future_pending_reminders(medicine_row["id"], medicine_row["user_id"], from_date)

    slots = []
    if medicine_row["morning"]:
        slots.append(medicine_row["morning_time"])
    if medicine_row["afternoon"]:
        slots.append(medicine_row["afternoon_time"])
    if medicine_row["night"]:
        slots.append(medicine_row["night_time"])
    if not slots:
        return 0

    end_date = medicine_row["end_date"]
    if not end_date or end_date < from_date:
        return 0
    start = max(from_date, medicine_row["start_date"] or from_date)

    created = 0
    for day in _daterange(start, end_date):
        for time_str in slots:
            models.create_reminder(
                user_id=medicine_row["user_id"],
                medicine_id=medicine_row["id"],
                reminder_date=day,
                reminder_time=time_str,
                notification_method=notification_method,
            )
            created += 1
    return created


def create_followup(original_reminder, delay_minutes):
    """Schedule the next reminder in a follow-up chain.

    delay_minutes is how long from now (or from the original's scheduled time,
    if that is still in the future) the follow-up should fire. The scheduler
    passes 0 because the wait already elapsed; the user tapping "Not Taken"
    passes the follow-up interval.
    """
    now = datetime.now()
    sched = datetime.strptime(
        f"{original_reminder['reminder_date']} {original_reminder['reminder_time']}",
        "%Y-%m-%d %H:%M",
    )
    followup_dt = max(now, sched) + timedelta(minutes=delay_minutes)
    return models.create_reminder(
        user_id=original_reminder["user_id"],
        medicine_id=original_reminder["medicine_id"],
        reminder_date=followup_dt.strftime("%Y-%m-%d"),
        reminder_time=followup_dt.strftime("%H:%M"),
        notification_method=original_reminder["notification_method"],
        parent_reminder_id=original_reminder["id"],
    )


def resolve_chain(reminder_id, status, overwrite_missed=False):
    """A response (or final miss) on any link settles the whole chain: every
    link that is still open takes the final status, so the original reminder
    shown on the dashboard reflects the outcome and no queued follow-up keeps
    firing after the patient has answered."""
    open_states = ("Pending", "Not Taken") + (("Missed",) if overwrite_missed else ())
    for row in models.get_reminder_chain(reminder_id):
        if row["status"] in open_states:
            models.update_reminder_status(row["id"], status, follow_up_sent=1)


def mark_missed(reminder):
    """Final outcome when a dose was re-sent MAX_FOLLOWUPS times with no answer."""
    resolve_chain(reminder["id"], "Missed")
    user = models.get_user_by_id(reminder["user_id"])
    medicine = models.get_medicine(reminder["medicine_id"], reminder["user_id"])
    models.add_history(
        user_id=reminder["user_id"], medicine_id=reminder["medicine_id"],
        reminder_id=reminder["id"],
        scheduled_time=f"{reminder['reminder_date']} {reminder['reminder_time']}",
        taken_time=None, status="Missed",
        notification_method=reminder["notification_method"],
    )
    _maybe_send_miss_alert(user, medicine)


def _maybe_send_miss_alert(user, medicine):
    if not user or not medicine or not user["miss_alert_enabled"]:
        return
    missed_count = models.count_recent_missed(user["id"], medicine["id"], limit=5)
    if missed_count >= 2 and user["emergency_contact_phone"]:
        import telegram_service
        alert_text = (
            "Medication Alert\n\n"
            f"Patient: {user['name']}\n\n"
            "The patient has missed multiple medicine reminders.\n\n"
            f"Medicine: {medicine['medicine_name']}"
        )
        if user["telegram_chat_id"]:
            telegram_service.send_alert(user["telegram_chat_id"], alert_text)
