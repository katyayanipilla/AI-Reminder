"""
action_links.py
Signed "Taken / Not Taken" links for channels that have no buttons (email,
SMS). Each link carries a signed token that identifies one reminder, so the
recipient can answer straight from the message without logging in.

Links are built from PUBLIC_BASE_URL. For a phone to open them, that must be
an address the phone can reach (a LAN IP such as http://192.168.1.20:5000 on
the same Wi-Fi, or an ngrok/hosted URL) - not 127.0.0.1.
"""
import os

from itsdangerous import URLSafeSerializer, BadSignature

_SALT = "reminder-action"


def _serializer():
    return URLSafeSerializer(os.environ.get("SECRET_KEY", "dev-secret-change-me"), salt=_SALT)


def base_url():
    return (os.environ.get("PUBLIC_BASE_URL", "").strip() or "http://127.0.0.1:5000").rstrip("/")


def make_token(reminder_id):
    return _serializer().dumps(int(reminder_id))


def read_token(token):
    """Return the reminder id inside a token, or None if it was tampered with."""
    try:
        return int(_serializer().loads(token))
    except (BadSignature, ValueError, TypeError):
        return None


def response_url(reminder_id):
    """One link that opens a tiny page with Taken / Not Taken buttons."""
    return f"{base_url()}/r/{make_token(reminder_id)}"
