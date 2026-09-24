"""
browser_notification.py
Browser notifications can't be pushed directly from a Python backend without
websockets, so we queue them in SQLite and the frontend polls
/api/notifications/pending every few seconds, then shows a native
Notification + plays an alarm sound. This module just manages the queue.
"""
import models


def queue(user_id, reminder_id, medicine_name, dosage, follow_up=False):
    title = "⚠️ Medicine Follow-up" if follow_up else "💊 Medicine Reminder"
    body = f"Time to take {medicine_name} {dosage}." if not follow_up else \
        f"You haven't confirmed {medicine_name} {dosage} yet."
    models.queue_browser_notification(user_id, reminder_id, title, body)
    return {"ok": True}


def pull_pending(user_id):
    rows = models.pull_pending_browser_notifications(user_id)
    return [dict(r) for r in rows]
