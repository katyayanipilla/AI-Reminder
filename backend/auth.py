"""
auth.py
Registration / login helpers. Uses Werkzeug's password hashing and
Flask's signed session cookie for authentication (simple & dependency-light).
"""
from functools import wraps
from flask import session, jsonify
from werkzeug.security import generate_password_hash, check_password_hash

import models


def register_user(data):
    required = ["name", "phone", "email", "password"]
    missing = [f for f in required if not data.get(f)]
    if missing:
        return None, f"Missing required fields: {', '.join(missing)}"

    if models.get_user_by_email_or_phone(data["email"]) or models.get_user_by_email_or_phone(data["phone"]):
        return None, "An account with this email or phone already exists."

    password_hash = generate_password_hash(data["password"])
    user_id = models.create_user(
        name=data["name"],
        phone=data["phone"],
        email=data["email"],
        password_hash=password_hash,
        telegram_chat_id=data.get("telegram_chat_id") or None,
        notification_preference=data.get("notification_preference", "browser"),
        emergency_contact_name=data.get("emergency_contact_name"),
        emergency_contact_phone=data.get("emergency_contact_phone"),
    )
    return user_id, None


def authenticate_user(identifier, password):
    user = models.get_user_by_email_or_phone(identifier)
    if not user:
        return None, "No account found with that email/phone."
    if not check_password_hash(user["password_hash"], password):
        return None, "Incorrect password."
    return user, None


def login_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not session.get("user_id"):
            return jsonify({"error": "Authentication required"}), 401
        return fn(*args, **kwargs)
    return wrapper


def current_user():
    uid = session.get("user_id")
    if not uid:
        return None
    return models.get_user_by_id(uid)
