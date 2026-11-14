"""
api.py  -  all the JSON endpoints the website calls
===================================================

Public
  GET  /api/health                  server + dataset status
  GET  /api/options                 audiences, emotions, genres, languages
  POST /api/recommend               main recommendation (saves history if logged in)
  POST /api/surprise                one random strong match
  GET  /api/search?q=...            title / description search
  GET  /api/trending                popular + well rated
  GET  /api/movies/<id>             full details + similar movies + where to watch (+ your status)
  POST /api/ask                     Ask bar: one sentence -> preferences
  POST /api/genie                   RAGS Genie chat: message + conversation state -> reply + movies

Logged-in users
  GET    /api/for-you               personal rows on the home page
  POST   /api/movies/<id>/interact  like / dislike / watchlist / watched / rating
  GET    /api/me/profile            stats + taste profile
  GET    /api/me/library            liked, watchlist, watched, rated
  GET    /api/me/history            past searches and viewed movies
  DELETE /api/me/history            clear history
  PATCH  /api/me/settings           display name, default audience, OTT apps
  DELETE /api/me                    delete account and all data
"""

import time
from collections import Counter

from flask import Blueprint, current_app, jsonify, request

from . import db, labels
from .auth import current_user_id, login_required

bp = Blueprint("api", __name__, url_prefix="/api")


def body():
    """The request's JSON object, or {} for anything else (no body, bad JSON, a list...)."""
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}


def engine():
    return current_app.extensions["cinemind_engine"]


def catalog():
    return engine().cat


def refresh_cf_if_needed():
    """Rebuild in-app collaborative filtering at most every 30 s after changes."""
    state = current_app.extensions["cinemind_cf_state"]
    if state["dirty"] and time.time() - state["at"] > state["every"]:
        engine().cf.refresh_from_app(db.all_positive_interactions())
        state.update(dirty=False, at=time.time())


def user_ctx():
    uid = current_user_id()
    return db.user_context(uid) if uid and db.user_by_id(uid) else {}


def max_level_param():
    aud = labels.normalize_audience(request.args.get("audience", "")) or "adults"
    return labels.AUDIENCES[aud][1]


def movies_from_ids(ids):
    cat = catalog()
    return [cat.movie_dict(cat.pos[m]) for m in ids if cat.has(m)]


# ---------------------------------------------------------------------------
@bp.get("/health")
def health():
    eng = engine()
    return jsonify({"status": "ok", "movies": len(eng.cat),
                    "collaborative_filtering": {"movielens_items": len(eng.cf.ml_neighbors),
                                                "app_items": len(eng.cf.app_neighbors)}})


@bp.get("/options")
def options():
    data = labels.options_payload()
    eng = engine()
    watch = current_app.extensions.get("cinemind_watch")
    logos = current_app.extensions.setdefault("cinemind_logos", watch.logos() if watch else {})
    data["platforms"] = [{"name": n, "count": c, "logo": logos.get(n, "")} for n, c in eng.platform_counts()[:14]]
    data["platform_logos"] = logos
    data["emotion_posters"] = current_app.extensions.setdefault("cinemind_emotion_posters", eng.emotion_posters())
    genie = current_app.extensions.get("cinemind_genie")
    data["genie_brain"] = genie.brain if genie else "built-in"
    return jsonify(data)


@bp.post("/ask")
def ask():
    """Ask CineMind bar: one sentence -> preferences (the website then runs /recommend)."""
    from . import nlu
    text = str(body().get("text", ""))[:300]
    parsed = nlu.parse(text, catalog())
    return jsonify({"prefs": parsed["prefs"], "understood": parsed["understood"], "intent": parsed["intent"],
                    "movie_id": parsed["movie_id"]})


@bp.post("/genie")
def genie_chat():
    """RAGS Genie chat: one message + conversation state -> reply, movies, new state."""
    data = body()
    refresh_cf_if_needed()
    uid = current_user_id()
    user = db.user_by_id(uid) if uid else None
    out = current_app.extensions["cinemind_genie"].reply(
        data.get("message", ""), data.get("state"), user_ctx(),
        default_audience=user["default_audience"] if user else None)
    for m in out["results"]:
        m.pop("breakdown", None)
    return jsonify(out)


@bp.post("/recommend")
def recommend():
    raw = body()
    refresh_cf_if_needed()
    result = engine().recommend(raw, user_ctx())
    uid = current_user_id()
    if uid and result["results"]:
        db.log_search(uid, result["prefs"], [m["id"] for m in result["results"]])
    return jsonify(result)


@bp.post("/surprise")
def surprise():
    raw = body()
    movie = engine().surprise(raw, user_ctx())
    return jsonify({"movie": movie})


@bp.get("/search")
def search():
    q = request.args.get("q", "")[:80]
    rows = catalog().search(q, limit=16, max_level=max_level_param())
    return jsonify({"query": q, "results": [catalog().movie_dict(r) for r in rows]})


@bp.get("/trending")
def trending():
    lang = request.args.get("language") or None
    return jsonify({"results": engine().trending(max_level_param(), limit=16, language=lang)})


@bp.get("/movies/<int:movie_id>")
def movie_detail(movie_id):
    cat = catalog()
    if not cat.has(movie_id):
        return jsonify({"error": "Movie not found"}), 404
    movie = cat.movie_dict(cat.pos[movie_id], full=True)
    uid = current_user_id()
    ctx = user_ctx()
    movie["similar"] = engine().similar_to(movie_id, max_level=max_level_param(), limit=10, user=ctx)
    for s in movie["similar"]:
        s.pop("breakdown", None)
    movie["state"] = db.movie_state(uid, movie_id) if uid else None
    watch = current_app.extensions.get("cinemind_watch")
    movie["watch"] = watch.for_movie(movie_id, movie["title"], movie["year"]) if watch else None
    if uid:
        db.log_view(uid, movie_id)
    return jsonify(movie)


# ---------------------------------------------------------------------------
@bp.get("/for-you")
@login_required
def for_you():
    uid = current_user_id()
    user = db.user_by_id(uid)
    ctx = db.user_context(uid)
    refresh_cf_if_needed()
    rows = []
    if ctx["liked"]:
        picks = engine().recommend({"audience": user["default_audience"], "limit": 14}, ctx)["results"]
        rows.append({"title": "Picked for your taste", "results": picks})
        seed = ctx["liked"][0]
        if catalog().has(seed):
            name = catalog().df.iloc[catalog().pos[seed]]["title"]
            shown = {m["id"] for m in picks}
            sim = engine().similar_to(seed, labels.AUDIENCES[user["default_audience"]][1], 40, ctx)
            sim = [m for m in sim if m["id"] not in shown][:14]     # no repeats between rows
            if sim:
                rows.append({"title": f"Because you liked {name}", "results": sim})
    watch = [i["movie_id"] for i in db.interactions_for(uid) if i["kind"] == "watchlist"]
    if watch:
        rows.append({"title": "On your watchlist", "results": movies_from_ids(watch[:14])})
    return jsonify({"rows": rows, "has_history": bool(ctx["liked"])})


@bp.post("/movies/<int:movie_id>/interact")
@login_required
def interact(movie_id):
    if not catalog().has(movie_id):
        return jsonify({"error": "Movie not found"}), 404
    data = body()
    kind = data.get("kind")
    if kind not in ("like", "dislike", "watchlist", "watched", "rating"):
        return jsonify({"error": "Unknown action"}), 400
    on = bool(data.get("on", True))
    value = 1
    if kind == "rating":
        try:
            value = int(data.get("value", 0))
        except (TypeError, ValueError):
            value = 0
        if value == 0:
            on = False
        elif not 1 <= value <= 5:
            return jsonify({"error": "Rating must be 1-5"}), 400
    uid = current_user_id()
    db.set_interaction(uid, movie_id, kind, on, value)
    current_app.extensions["cinemind_cf_state"]["dirty"] = True
    return jsonify({"state": db.movie_state(uid, movie_id)})


@bp.get("/me/profile")
@login_required
def profile():
    uid = current_user_id()
    cat = catalog()
    ctx = db.user_context(uid)
    taste_ids = [m for m in ctx["liked"] if cat.has(m)]
    genres, emotions, langs = Counter(), Counter(), Counter()
    for m in taste_ids:
        r = cat.df.iloc[cat.pos[m]]
        genres.update(r["genres"])
        emotions.update(r["top_emotions"])
        langs[r["language"]] += 1
    return jsonify({
        "user": {k: db.user_by_id(uid)[k] for k in ("username", "display_name", "default_audience", "created_at")},
        "counts": db.counts(uid),
        "taste": {
            "genres": [{"label": labels.GENRE_DISPLAY.get(g, g), "count": c} for g, c in genres.most_common(6)],
            "emotions": [{"key": e, "label": labels.EMOTIONS[e]["display"], "colour": labels.EMOTIONS[e]["colour"],
                          "count": c} for e, c in emotions.most_common(6)],
            "languages": [{"label": labels.LANGUAGES.get(l, l), "count": c} for l, c in langs.most_common(4)],
        },
    })


@bp.get("/me/library")
@login_required
def library():
    uid = current_user_id()
    groups = {"like": [], "watchlist": [], "watched": [], "rating": [], "dislike": []}
    ratings = {}
    for i in db.interactions_for(uid):
        groups[i["kind"]].append(i["movie_id"])
        if i["kind"] == "rating":
            ratings[i["movie_id"]] = i["value"]
    out = {k: movies_from_ids(v) for k, v in groups.items()}
    for m in out["rating"]:
        m["my_rating"] = ratings[m["id"]]
    return jsonify(out)


@bp.get("/me/history")
@login_required
def history():
    uid = current_user_id()
    cat = catalog()
    searches = db.searches(uid)
    for s in searches:
        s["top_titles"] = [cat.df.iloc[cat.pos[m]]["title"] for m in s["result_ids"][:4] if cat.has(m)]
        s["first_poster"] = next((cat.df.iloc[cat.pos[m]]["poster_url"] for m in s["result_ids"] if cat.has(m)), "")
    viewed = db.views(uid)
    movies = {m["id"]: m for m in movies_from_ids([v["movie_id"] for v in viewed])}
    return jsonify({"searches": searches,
                    "viewed": [dict(movies[v["movie_id"]], viewed_at=v["created_at"])
                               for v in viewed if v["movie_id"] in movies]})


@bp.delete("/me/history")
@login_required
def clear_history():
    db.clear_history(current_user_id())
    return jsonify({"ok": True})


@bp.patch("/me/settings")
@login_required
def settings():
    data = body()
    name = data.get("display_name")
    aud = data.get("default_audience")
    platforms = data.get("platforms")
    if platforms is not None:
        if not isinstance(platforms, list):
            return jsonify({"error": "platforms must be a list"}), 400
        platforms = [str(x)[:40] for x in platforms][:12]
    if name is not None:
        name = str(name).strip()[:40]
        if not name:
            return jsonify({"error": "Name cannot be empty"}), 400
    if aud is not None:
        aud = labels.normalize_audience(aud)
        if not aud:
            return jsonify({"error": "Unknown audience"}), 400
    db.update_user(current_user_id(), name, aud, platforms)
    return jsonify({"ok": True})


@bp.delete("/me")
@login_required
def delete_me():
    from flask import session
    db.delete_user(current_user_id())
    current_app.extensions["cinemind_cf_state"]["dirty"] = True
    session.clear()
    return jsonify({"ok": True})


@bp.errorhandler(Exception)
def on_error(err):
    from werkzeug.exceptions import HTTPException
    if isinstance(err, HTTPException):
        return jsonify({"error": err.description}), err.code
    current_app.logger.exception("API error")
    return jsonify({"error": "Something went wrong on the server."}), 500
