"""
database.py
SQLite connection helper and schema initialization for AI Medicine Reminder.
"""
import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "database.db")


def get_db():
    """Return a new SQLite connection with row access by column name."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    """Create all tables if they do not already exist."""
    conn = get_db()
    cur = conn.cursor()

    cur.executescript(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            phone TEXT NOT NULL UNIQUE,
            email TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            telegram_chat_id TEXT,
            notification_preference TEXT DEFAULT 'browser',
            emergency_contact_name TEXT,
            emergency_contact_phone TEXT,
            follow_up_minutes INTEGER DEFAULT 5,
            miss_alert_enabled INTEGER DEFAULT 1,
            created_at TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS medicines (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            medicine_name TEXT NOT NULL,
            dosage TEXT,
            food_instruction TEXT,
            frequency TEXT,
            morning INTEGER DEFAULT 0,
            afternoon INTEGER DEFAULT 0,
            night INTEGER DEFAULT 0,
            morning_time TEXT DEFAULT '08:00',
            afternoon_time TEXT DEFAULT '14:00',
            night_time TEXT DEFAULT '20:00',
            start_date TEXT,
            end_date TEXT,
            active INTEGER DEFAULT 1,
            needs_verification INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS reminders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            medicine_id INTEGER NOT NULL,
            reminder_date TEXT NOT NULL,
            reminder_time TEXT NOT NULL,
            notification_method TEXT,
            status TEXT DEFAULT 'Pending',
            follow_up_sent INTEGER DEFAULT 0,
            parent_reminder_id INTEGER,
            notified_at TEXT,
            created_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE,
            FOREIGN KEY (medicine_id) REFERENCES medicines (id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            medicine_id INTEGER NOT NULL,
            reminder_id INTEGER,
            scheduled_time TEXT,
            taken_time TEXT,
            status TEXT,
            notification_method TEXT,
            created_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE,
            FOREIGN KEY (medicine_id) REFERENCES medicines (id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS pending_browser_notifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            reminder_id INTEGER NOT NULL,
            title TEXT,
            body TEXT,
            delivered INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now'))
        );
        """
    )
    # One-time migration: the follow-up interval used to default to 10 minutes.
    # The product requirement is "ask again after 5 minutes", so move anyone
    # still on the old default to 5 (they can pick 10/15 again in Settings).
    already = cur.execute("PRAGMA user_version").fetchone()[0]
    if already < 1:
        cur.execute("UPDATE users SET follow_up_minutes = 5 WHERE follow_up_minutes = 10 OR follow_up_minutes IS NULL")
        cur.execute("PRAGMA user_version = 1")
    conn.commit()
    conn.close()
