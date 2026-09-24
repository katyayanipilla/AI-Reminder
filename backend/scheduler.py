"""
scheduler.py
Runs inside the Flask backend process using APScheduler. It continuously
polls SQLite for due reminders and dispatches notifications, independent
of whether any browser tab is open.

Follow-up flow for one dose:
    reminder sent -> no Taken / Not Taken answer within N minutes (default 5)
    -> send the reminder again -> still no answer after N minutes -> again ...
The chain stops as soon as the patient answers, or after MAX_FOLLOWUPS
repeats, at which point the dose is marked Missed. Every day / time-slot of
the medicine's duration has its own reminder row, so this repeats for each
dose until the end date.
"""
import logging
from datetime import datetime, timedelta

from apscheduler.schedulers.background import BackgroundScheduler

import models
import notification_service
import reminder_service
from database import get_db

logger = logging.getLogger("scheduler")

DEFAULT_FOLLOWUP_MINUTES = 5
MAX_FOLLOWUPS = reminder_service.MAX_FOLLOWUPS


def _check_due_reminders():
    now = datetime.now()
    now_date, now_time = now.strftime("%Y-%m-%d"), now.strftime("%H:%M")

    for reminder in models.get_due_reminders(now_date, now_time):
        try:
            user = models.get_user_by_id(reminder["user_id"])
            medicine = models.get_medicine(reminder["medicine_id"], reminder["user_id"])
            if not user or not medicine:
                continue

            is_followup = reminder["parent_reminder_id"] is not None
            # Mark as notified first so a slow/failed provider can never cause
            # the same reminder to be picked up and sent again on the next tick.
            models.mark_reminder_notified(reminder["id"], now.strftime("%Y-%m-%d %H:%M:%S"))
            report = notification_service.dispatch(user, medicine, reminder, follow_up=is_followup)
            logger.info("Reminder %s (%s) dispatched: %s", reminder["id"],
                        medicine["medicine_name"], {k: v.get("ok") for k, v in report.items()})
            models.add_history(
                user_id=user["id"], medicine_id=medicine["id"], reminder_id=reminder["id"],
                scheduled_time=f"{reminder['reminder_date']} {reminder['reminder_time']}",
                taken_time=None, status="Pending", notification_method=reminder["notification_method"],
            )
        except Exception:  # noqa: BLE001 - one bad reminder must not block the rest
            logger.exception("Failed to process reminder %s", reminder["id"])


def _followup_minutes_by_user():
    conn = get_db()
    users = conn.execute("SELECT id, follow_up_minutes FROM users").fetchall()
    conn.close()
    return {u["id"]: (u["follow_up_minutes"] or DEFAULT_FOLLOWUP_MINUTES) for u in users}


def _check_followups_and_missed():
    now = datetime.now()
    minutes_by_user = _followup_minutes_by_user()

    # Fetch everything notified at least a minute ago; the exact per-user
    # window is applied below.
    cutoff = now - timedelta(minutes=1)
    candidates = models.get_reminders_awaiting_followup(
        cutoff.strftime("%Y-%m-%d"), cutoff.strftime("%H:%M:%S")
    )

    for reminder in candidates:
        try:
            minutes = minutes_by_user.get(reminder["user_id"], DEFAULT_FOLLOWUP_MINUTES)
            notified_at = datetime.strptime(reminder["notified_at"], "%Y-%m-%d %H:%M:%S")
            if (now - notified_at).total_seconds() < minutes * 60:
                continue

            followups_so_far = len(models.get_reminder_chain(reminder["id"])) - 1
            if followups_so_far < MAX_FOLLOWUPS:
                # No answer -> remind again right now (the wait has elapsed).
                models.update_reminder_status(reminder["id"], "Not Taken", follow_up_sent=1)
                reminder_service.create_followup(reminder, 0)
                logger.info("No answer to reminder %s after %s min - follow-up %s/%s queued",
                            reminder["id"], minutes, followups_so_far + 1, MAX_FOLLOWUPS)
            else:
                reminder_service.mark_missed(reminder)
        except Exception:  # noqa: BLE001
            logger.exception("Follow-up check failed for reminder %s", reminder["id"])


def start_scheduler():
    scheduler = BackgroundScheduler(daemon=True)
    scheduler.add_job(_check_due_reminders, "interval", seconds=10, id="check_due_reminders",
                      max_instances=1, coalesce=True)
    scheduler.add_job(_check_followups_and_missed, "interval", seconds=10, id="check_followups",
                      max_instances=1, coalesce=True)
    scheduler.start()
    logger.info("APScheduler started: checking due reminders and follow-ups every 10s.")
    return scheduler
