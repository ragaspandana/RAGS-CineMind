"""
db.py  -  SQLite database (users, likes/ratings, history)
=========================================================

Tables
  users           one row per account (password stored only as a secure hash)
  interactions    like / dislike / watchlist / watched / rating, per user per movie
  search_history  every recommendation request a logged-in user made
  view_history    every movie details page a logged-in user opened

SQLite is a single file (instance/cinemind.db) - no database server needed.
"""

import json
import os
import sqlite3
from datetime import datetime, timezone

from flask import current_app, g

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    username         TEXT NOT NULL UNIQUE COLLATE NOCASE,
    display_name     TEXT NOT NULL,
    password_hash    TEXT NOT NULL,
    default_audience TEXT NOT NULL DEFAULT 'adults',
    created_at       TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS interactions (
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    movie_id   INTEGER NOT NULL,
    kind       TEXT    NOT NULL CHECK (kind IN ('like','dislike','watchlist','watched','rating')),
    value      INTEGER NOT NULL DEFAULT 1,
    created_at TEXT    NOT NULL,
    PRIMARY KEY (user_id, movie_id, kind)
);
CREATE TABLE IF NOT EXISTS search_history (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    prefs_json TEXT    NOT NULL,
    result_ids TEXT    NOT NULL,
    created_at TEXT    NOT NULL
);
CREATE TABLE IF NOT EXISTS view_history (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    movie_id   INTEGER NOT NULL,
    created_at TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_inter_user ON interactions(user_id);
CREATE INDEX IF NOT EXISTS idx_search_user ON search_history(user_id, created_at);
CREATE INDEX IF NOT EXISTS idx_view_user ON view_history(user_id, created_at);
"""


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def get_db():
    if "db" not in g:
        path = current_app.config["DATABASE"]
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        g.db = sqlite3.connect(path)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


def close_db(_exc=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db(app):
    app.teardown_appcontext(close_db)
    with app.app_context():
        db = get_db()
        db.executescript(SCHEMA)
        cols = {r[1] for r in db.execute("PRAGMA table_info(users)")}
        if "platforms" not in cols:          # added later: the user's OTT apps (JSON list)
            db.execute("ALTER TABLE users ADD COLUMN platforms TEXT NOT NULL DEFAULT '[]'")
        db.commit()


# ---------------------------------------------------------------------------
# users
# ---------------------------------------------------------------------------
def create_user(username, display_name, password_hash):
    db = get_db()
    cur = db.execute(
        "INSERT INTO users (username, display_name, password_hash, created_at) VALUES (?,?,?,?)",
        (username, display_name, password_hash, now()))
    db.commit()
    return cur.lastrowid


def user_by_name(username):
    return get_db().execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()


def user_by_id(user_id):
    return get_db().execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()


def update_user(user_id, display_name=None, default_audience=None, platforms=None):
    db = get_db()
    if platforms is not None:
        db.execute("UPDATE users SET platforms=? WHERE id=?", (json.dumps(platforms), user_id))
    if display_name is not None:
        db.execute("UPDATE users SET display_name=? WHERE id=?", (display_name, user_id))
    if default_audience is not None:
        db.execute("UPDATE users SET default_audience=? WHERE id=?", (default_audience, user_id))
    db.commit()


def delete_user(user_id):
    db = get_db()
    db.execute("DELETE FROM users WHERE id=?", (user_id,))
    db.commit()


# ---------------------------------------------------------------------------
# interactions
# ---------------------------------------------------------------------------
OPPOSITE = {"like": "dislike", "dislike": "like"}


def set_interaction(user_id, movie_id, kind, on=True, value=1):
    db = get_db()
    if on:
        db.execute("INSERT OR REPLACE INTO interactions VALUES (?,?,?,?,?)",
                   (user_id, movie_id, kind, int(value), now()))
        if kind in OPPOSITE:
            db.execute("DELETE FROM interactions WHERE user_id=? AND movie_id=? AND kind=?",
                       (user_id, movie_id, OPPOSITE[kind]))
        if kind == "rating" or kind == "like":
            db.execute("DELETE FROM interactions WHERE user_id=? AND movie_id=? AND kind='watchlist'",
                       (user_id, movie_id))
    else:
        db.execute("DELETE FROM interactions WHERE user_id=? AND movie_id=? AND kind=?",
                   (user_id, movie_id, kind))
    db.commit()


def interactions_for(user_id):
    rows = get_db().execute(
        "SELECT movie_id, kind, value, created_at FROM interactions WHERE user_id=? "
        "ORDER BY created_at DESC", (user_id,)).fetchall()
    return [dict(r) for r in rows]


def movie_state(user_id, movie_id):
    rows = get_db().execute("SELECT kind, value FROM interactions WHERE user_id=? AND movie_id=?",
                            (user_id, movie_id)).fetchall()
    state = {"like": False, "dislike": False, "watchlist": False, "watched": False, "rating": 0}
    for r in rows:
        if r["kind"] == "rating":
            state["rating"] = r["value"]
        else:
            state[r["kind"]] = True
    return state


def user_context(user_id):
    """What the recommender needs to know about a user."""
    liked, disliked, watched = [], [], []
    for r in interactions_for(user_id):
        k, v, m = r["kind"], r["value"], r["movie_id"]
        if k == "like" or (k == "rating" and v >= 4):
            liked.append(m)
        elif k == "dislike" or (k == "rating" and v <= 2):
            disliked.append(m)
        if k == "watched" or k == "rating":
            watched.append(m)
    return {"liked": list(dict.fromkeys(liked)), "disliked": list(dict.fromkeys(disliked)),
            "watched": list(dict.fromkeys(watched))}


def all_positive_interactions():
    """(user, movie, value) for every like / good rating - feeds in-app CF."""
    rows = get_db().execute(
        "SELECT user_id, movie_id, CASE WHEN kind='like' THEN 5 ELSE value END AS v "
        "FROM interactions WHERE kind='like' OR (kind='rating' AND value>=4)").fetchall()
    return [(r[0], r[1], r[2]) for r in rows]


# ---------------------------------------------------------------------------
# history
# ---------------------------------------------------------------------------
def log_search(user_id, prefs, result_ids):
    db = get_db()
    db.execute("INSERT INTO search_history (user_id, prefs_json, result_ids, created_at) VALUES (?,?,?,?)",
               (user_id, json.dumps(prefs), json.dumps(result_ids), now()))
    db.commit()


def log_view(user_id, movie_id):
    db = get_db()
    last = db.execute("SELECT movie_id FROM view_history WHERE user_id=? ORDER BY id DESC LIMIT 1",
                      (user_id,)).fetchone()
    if last and last[0] == movie_id:
        return                                   # don't log the same movie twice in a row
    db.execute("INSERT INTO view_history (user_id, movie_id, created_at) VALUES (?,?,?)",
               (user_id, movie_id, now()))
    db.commit()


def searches(user_id, limit=30):
    rows = get_db().execute(
        "SELECT id, prefs_json, result_ids, created_at FROM search_history WHERE user_id=? "
        "ORDER BY id DESC LIMIT ?", (user_id, limit)).fetchall()
    return [{"id": r["id"], "prefs": json.loads(r["prefs_json"]),
             "result_ids": json.loads(r["result_ids"]), "created_at": r["created_at"]} for r in rows]


def views(user_id, limit=30):
    rows = get_db().execute(
        "SELECT movie_id, MAX(created_at) AS at FROM view_history WHERE user_id=? "
        "GROUP BY movie_id ORDER BY at DESC LIMIT ?", (user_id, limit)).fetchall()
    return [{"movie_id": r[0], "created_at": r[1]} for r in rows]


def clear_history(user_id):
    db = get_db()
    db.execute("DELETE FROM search_history WHERE user_id=?", (user_id,))
    db.execute("DELETE FROM view_history WHERE user_id=?", (user_id,))
    db.commit()


def counts(user_id):
    db = get_db()
    c = {k: 0 for k in ("like", "dislike", "watchlist", "watched", "rating")}
    for r in db.execute("SELECT kind, COUNT(*) FROM interactions WHERE user_id=? GROUP BY kind", (user_id,)):
        c[r[0]] = r[1]
    c["searches"] = db.execute("SELECT COUNT(*) FROM search_history WHERE user_id=?", (user_id,)).fetchone()[0]
    c["views"] = db.execute("SELECT COUNT(DISTINCT movie_id) FROM view_history WHERE user_id=?", (user_id,)).fetchone()[0]
    return c
