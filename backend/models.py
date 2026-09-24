"""
models.py
Thin data-access helpers around the SQLite tables. Kept as plain functions
(no ORM) to stay dependency-light and easy to follow for a college project.
"""
from database import get_db


# ---------------------------------------------------------------- users ----
def create_user(name, phone, email, password_hash, telegram_chat_id,
                 notification_preference, emergency_contact_name,
                 emergency_contact_phone):
    conn = get_db()
    cur = conn.execute(
        """INSERT INTO users
           (name, phone, email, password_hash, telegram_chat_id,
            notification_preference, emergency_contact_name, emergency_contact_phone)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (name, phone, email, password_hash, telegram_chat_id,
         notification_preference, emergency_contact_name, emergency_contact_phone),
    )
    conn.commit()
    user_id = cur.lastrowid
    conn.close()
    return user_id


def get_user_by_email_or_phone(identifier):
    conn = get_db()
    row = conn.execute(
        "SELECT * FROM users WHERE email = ? OR phone = ?", (identifier, identifier)
    ).fetchone()
    conn.close()
    return row


def get_user_by_id(user_id):
    conn = get_db()
    row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    conn.close()
    return row


def get_user_by_telegram_chat_id(chat_id):
    conn = get_db()
    row = conn.execute(
        "SELECT * FROM users WHERE telegram_chat_id = ?", (str(chat_id),)
    ).fetchone()
    conn.close()
    return row


def update_user_settings(user_id, **fields):
    if not fields:
        return
    conn = get_db()
    cols = ", ".join(f"{k} = ?" for k in fields)
    values = list(fields.values()) + [user_id]
    conn.execute(f"UPDATE users SET {cols} WHERE id = ?", values)
    conn.commit()
    conn.close()


# ------------------------------------------------------------ medicines ----
def create_medicine(user_id, medicine_name, dosage, food_instruction, frequency,
                     morning, afternoon, night, morning_time, afternoon_time,
                     night_time, start_date, end_date, needs_verification=0):
    conn = get_db()
    cur = conn.execute(
        """INSERT INTO medicines
           (user_id, medicine_name, dosage, food_instruction, frequency,
            morning, afternoon, night, morning_time, afternoon_time, night_time,
            start_date, end_date, needs_verification)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (user_id, medicine_name, dosage, food_instruction, frequency,
         int(morning), int(afternoon), int(night), morning_time, afternoon_time,
         night_time, start_date, end_date, int(needs_verification)),
    )
    conn.commit()
    med_id = cur.lastrowid
    conn.close()
    return med_id


def get_medicines_for_user(user_id, active_only=False):
    conn = get_db()
    q = "SELECT * FROM medicines WHERE user_id = ?"
    if active_only:
        q += " AND active = 1"
    q += " ORDER BY created_at DESC"
    rows = conn.execute(q, (user_id,)).fetchall()
    conn.close()
    return rows


def get_medicine(medicine_id, user_id):
    conn = get_db()
    row = conn.execute(
        "SELECT * FROM medicines WHERE id = ? AND user_id = ?", (medicine_id, user_id)
    ).fetchone()
    conn.close()
    return row


def update_medicine(medicine_id, user_id, **fields):
    if not fields:
        return
    conn = get_db()
    cols = ", ".join(f"{k} = ?" for k in fields)
    values = list(fields.values()) + [medicine_id, user_id]
    conn.execute(f"UPDATE medicines SET {cols} WHERE id = ? AND user_id = ?", values)
    conn.commit()
    conn.close()


def delete_medicine(medicine_id, user_id):
    conn = get_db()
    conn.execute("DELETE FROM medicines WHERE id = ? AND user_id = ?", (medicine_id, user_id))
    conn.commit()
    conn.close()


# ------------------------------------------------------------ reminders ----
def create_reminder(user_id, medicine_id, reminder_date, reminder_time,
                     notification_method, parent_reminder_id=None):
    conn = get_db()
    cur = conn.execute(
        """INSERT INTO reminders
           (user_id, medicine_id, reminder_date, reminder_time,
            notification_method, parent_reminder_id)
           VALUES (?,?,?,?,?,?)""",
        (user_id, medicine_id, reminder_date, reminder_time,
         notification_method, parent_reminder_id),
    )
    conn.commit()
    rid = cur.lastrowid
    conn.close()
    return rid


def get_due_reminders(now_date, now_time):
    """Pending reminders whose scheduled datetime has arrived and were not yet
    notified. Joined against medicines so a Disabled medicine's still-queued
    reminders stop firing immediately, instead of continuing to send until
    their rows are separately cleaned up."""
    conn = get_db()
    rows = conn.execute(
        """SELECT r.* FROM reminders r
           JOIN medicines m ON r.medicine_id = m.id
           WHERE r.status = 'Pending' AND r.notified_at IS NULL AND m.active = 1
             AND (r.reminder_date < ? OR (r.reminder_date = ? AND r.reminder_time <= ?))""",
        (now_date, now_date, now_time),
    ).fetchall()
    conn.close()
    return rows


def delete_future_pending_reminders(medicine_id, user_id, from_date):
    """Remove not-yet-notified Pending reminders for a medicine from
    from_date onward. Used before regenerating a medicine's reminders after
    the user edits its times/dates, so the edit actually takes effect
    instead of the old schedule silently continuing to fire."""
    conn = get_db()
    conn.execute(
        """DELETE FROM reminders
           WHERE medicine_id = ? AND user_id = ? AND status = 'Pending'
             AND notified_at IS NULL AND reminder_date >= ?""",
        (medicine_id, user_id, from_date),
    )
    conn.commit()
    conn.close()


def mark_reminder_notified(reminder_id, notified_at):
    conn = get_db()
    conn.execute("UPDATE reminders SET notified_at = ? WHERE id = ?", (notified_at, reminder_id))
    conn.commit()
    conn.close()


def get_reminder(reminder_id):
    conn = get_db()
    row = conn.execute("SELECT * FROM reminders WHERE id = ?", (reminder_id,)).fetchone()
    conn.close()
    return row


def update_reminder_status(reminder_id, status, follow_up_sent=None):
    conn = get_db()
    if follow_up_sent is not None:
        conn.execute(
            "UPDATE reminders SET status = ?, follow_up_sent = ? WHERE id = ?",
            (status, int(follow_up_sent), reminder_id),
        )
    else:
        conn.execute("UPDATE reminders SET status = ? WHERE id = ?", (status, reminder_id))
    conn.commit()
    conn.close()


def get_reminders_awaiting_followup(cutoff_date, cutoff_time):
    """Notified, still-Pending reminders whose follow-up window has elapsed."""
    conn = get_db()
    rows = conn.execute(
        """SELECT r.* FROM reminders r
           JOIN medicines m ON r.medicine_id = m.id
           WHERE r.status = 'Pending' AND r.notified_at IS NOT NULL
             AND r.follow_up_sent = 0 AND m.active = 1
             AND r.notified_at <= ?""",
        (f"{cutoff_date} {cutoff_time}",),
    ).fetchall()
    conn.close()
    return rows


def get_reminder_chain(reminder_id):
    """Return every reminder in the same follow-up chain (the original
    reminder plus all follow-ups created from it), oldest first. Follow-ups
    point at the previous link via parent_reminder_id, so walk up to the
    root and then back down."""
    conn = get_db()
    row = conn.execute("SELECT * FROM reminders WHERE id = ?", (reminder_id,)).fetchone()
    if not row:
        conn.close()
        return []
    while row["parent_reminder_id"] is not None:
        parent = conn.execute(
            "SELECT * FROM reminders WHERE id = ?", (row["parent_reminder_id"],)
        ).fetchone()
        if not parent:
            break
        row = parent
    chain = [row]
    while True:
        child = conn.execute(
            "SELECT * FROM reminders WHERE parent_reminder_id = ? ORDER BY id ASC LIMIT 1",
            (chain[-1]["id"],),
        ).fetchone()
        if not child:
            break
        chain.append(child)
    conn.close()
    return chain


def get_medicine_notification_method(medicine_id):
    """The notification_method the medicine's reminders were created with."""
    conn = get_db()
    row = conn.execute(
        """SELECT notification_method FROM reminders
           WHERE medicine_id = ? AND notification_method IS NOT NULL
             AND notification_method != ''
           ORDER BY id DESC LIMIT 1""",
        (medicine_id,),
    ).fetchone()
    conn.close()
    return row["notification_method"] if row else None


def get_todays_reminders(user_id, date_str):
    conn = get_db()
    rows = conn.execute(
        """SELECT r.*, m.medicine_name, m.dosage, m.food_instruction
           FROM reminders r JOIN medicines m ON r.medicine_id = m.id
           WHERE r.user_id = ? AND r.reminder_date = ? AND r.parent_reminder_id IS NULL
           ORDER BY r.reminder_time ASC""",
        (user_id, date_str),
    ).fetchall()
    conn.close()
    return rows


# --------------------------------------------------------------- history ----
def add_history(user_id, medicine_id, reminder_id, scheduled_time, taken_time,
                 status, notification_method):
    conn = get_db()
    conn.execute(
        """INSERT INTO history
           (user_id, medicine_id, reminder_id, scheduled_time, taken_time, status, notification_method)
           VALUES (?,?,?,?,?,?,?)""",
        (user_id, medicine_id, reminder_id, scheduled_time, taken_time, status, notification_method),
    )
    conn.commit()
    conn.close()


def get_history(user_id, start_date=None, end_date=None, medicine_id=None, status=None):
    conn = get_db()
    q = """SELECT h.*, m.medicine_name, m.dosage FROM history h
           JOIN medicines m ON h.medicine_id = m.id WHERE h.user_id = ?"""
    params = [user_id]
    if start_date:
        q += " AND date(h.scheduled_time) >= ?"
        params.append(start_date)
    if end_date:
        q += " AND date(h.scheduled_time) <= ?"
        params.append(end_date)
    if medicine_id:
        q += " AND h.medicine_id = ?"
        params.append(medicine_id)
    if status:
        q += " AND h.status = ?"
        params.append(status)
    q += " ORDER BY h.scheduled_time DESC"
    rows = conn.execute(q, params).fetchall()
    conn.close()
    return rows


def count_recent_missed(user_id, medicine_id, limit=5):
    conn = get_db()
    rows = conn.execute(
        """SELECT status FROM history WHERE user_id = ? AND medicine_id = ?
           ORDER BY scheduled_time DESC LIMIT ?""",
        (user_id, medicine_id, limit),
    ).fetchall()
    conn.close()
    return sum(1 for r in rows if r["status"] == "Missed")


# ---------------------------------------------------------- browser push ----
def queue_browser_notification(user_id, reminder_id, title, body):
    conn = get_db()
    conn.execute(
        """INSERT INTO pending_browser_notifications (user_id, reminder_id, title, body)
           VALUES (?,?,?,?)""",
        (user_id, reminder_id, title, body),
    )
    conn.commit()
    conn.close()


def pull_pending_browser_notifications(user_id):
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM pending_browser_notifications WHERE user_id = ? AND delivered = 0",
        (user_id,),
    ).fetchall()
    conn.execute(
        "UPDATE pending_browser_notifications SET delivered = 1 WHERE user_id = ? AND delivered = 0",
        (user_id,),
    )
    conn.commit()
    conn.close()
    return rows
