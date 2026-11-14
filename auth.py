"""
auth.py  -  register / login / logout
=====================================

* Passwords are never stored. We store a salted hash made by Werkzeug
  (scrypt / pbkdf2), which is the standard Flask way.
* After login, Flask keeps the user id in a signed, HttpOnly session cookie.
* Simple protection against password guessing: 8 failed logins for one
  username within 10 minutes -> that username is blocked for 10 minutes.
"""

import re
import time
from collections import defaultdict
from functools import wraps

from flask import Blueprint, jsonify, request, session
from werkzeug.security import check_password_hash, generate_password_hash

from . import db

bp = Blueprint("auth", __name__, url_prefix="/api/auth")

USERNAME_RE = re.compile(r"^[A-Za-z0-9_.]{3,24}$")
_failures = defaultdict(list)
MAX_FAILS, WINDOW = 8, 600


def current_user_id():
    return session.get("user_id")


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not current_user_id() or not db.user_by_id(current_user_id()):
            session.clear()
            return jsonify({"error": "Please log in first."}), 401
        return view(*args, **kwargs)
    return wrapped


def public_user(row):
    import json
    try:
        platforms = json.loads(row["platforms"]) if "platforms" in row.keys() else []
    except (TypeError, ValueError):
        platforms = []
    return {"id": row["id"], "username": row["username"], "display_name": row["display_name"],
            "default_audience": row["default_audience"], "created_at": row["created_at"],
            "platforms": platforms}


def _body():
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}      # bad JSON or a list -> treat as empty


@bp.post("/register")
def register():
    data = _body()
    username = str(data.get("username", "")).strip()
    password = str(data.get("password", ""))
    display = str(data.get("display_name", "")).strip()[:40] or username
    if not USERNAME_RE.match(username):
        return jsonify({"error": "Username: 3-24 letters, numbers, _ or ."}), 400
    if len(password) < 6 or len(password) > 128:
        return jsonify({"error": "Password must be at least 6 characters."}), 400
    if db.user_by_name(username):
        return jsonify({"error": "That username is taken."}), 409
    uid = db.create_user(username, display, generate_password_hash(password))
    session.clear()
    session["user_id"] = uid
    session.permanent = True
    return jsonify({"user": public_user(db.user_by_id(uid))}), 201


@bp.post("/login")
def login():
    data = _body()
    username = str(data.get("username", "")).strip()
    password = str(data.get("password", ""))
    key = username.lower()
    recent = [t for t in _failures[key] if time.time() - t < WINDOW]
    _failures[key] = recent
    if len(recent) >= MAX_FAILS:
        return jsonify({"error": "Too many attempts. Try again in a few minutes."}), 429
    user = db.user_by_name(username)
    if not user or not check_password_hash(user["password_hash"], password):
        _failures[key].append(time.time())
        return jsonify({"error": "Wrong username or password."}), 401
    _failures.pop(key, None)
    session.clear()
    session["user_id"] = user["id"]
    session.permanent = True
    return jsonify({"user": public_user(user)})


@bp.post("/logout")
def logout():
    session.clear()
    return jsonify({"ok": True})


@bp.get("/me")
def me():
    uid = current_user_id()
    user = db.user_by_id(uid) if uid else None
    return jsonify({"user": public_user(user) if user else None})
