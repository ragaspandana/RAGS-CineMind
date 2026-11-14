"""
app.py  -  starts the RAGS CineMind server
==========================================

Run (from THIS folder):
    python3 app.py
Then open  http://127.0.0.1:5000  in your browser.

Flask serves BOTH the website (frontend/ folder) and the API (/api/...),
so there is no CORS setup and no Live Server needed any more.
"""

import os
import secrets
import time
from datetime import timedelta

from flask import Flask, send_from_directory

from cinemind import api, auth, db, images
from cinemind.catalog import Catalog
from cinemind.cf import CollaborativeModel
from cinemind.engine import Recommender
from cinemind.watch import WatchProviders
from cinemind.genie import Genie

BASE = os.path.dirname(os.path.abspath(__file__))


def _secret_key():
    """Use SECRET_KEY from the environment; otherwise create one and keep it in instance/."""
    if os.environ.get("SECRET_KEY"):
        return os.environ["SECRET_KEY"]
    path = os.path.join(BASE, "instance", "secret_key.txt")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if not os.path.exists(path):
        with open(path, "w") as f:
            f.write(secrets.token_hex(32))
    with open(path) as f:
        return f.read().strip()


def create_app(test_config=None):
    app = Flask(__name__, static_folder=os.path.join(BASE, "frontend"), static_url_path="")
    app.config.update(
        SECRET_KEY=_secret_key(),
        DATABASE=os.environ.get("DATABASE_PATH", os.path.join(BASE, "instance", "cinemind.db")),
        MOVIES_CSV=os.environ.get("MOVIES_CSV", os.path.join(BASE, "data", "movies.csv")),
        CF_NEIGHBORS=os.path.join(BASE, "data", "cf_neighbors.json"),
        IMAGE_CACHE=os.path.join(BASE, "data", "image_cache"),
        WATCH_PROVIDERS=os.path.join(BASE, "data", "watch_providers.json"),
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=os.environ.get("COOKIE_SECURE", "0") == "1",
        PERMANENT_SESSION_LIFETIME=timedelta(days=30),
        JSON_SORT_KEYS=False,
        CF_REFRESH_SECONDS=30,
    )
    if test_config:
        app.config.update(test_config)

    # ---- load data + models once
    started = time.time()
    catalog = Catalog(app.config["MOVIES_CSV"])
    cf_model = CollaborativeModel(app.config["CF_NEIGHBORS"])
    cf_share = 0.5
    mix_file = os.path.join(BASE, "data", "personal_mix.json")
    if os.path.exists(mix_file):
        import json
        with open(mix_file) as f:
            cf_share = float(json.load(f).get("cf_share", 0.5))
    app.extensions["cinemind_engine"] = Recommender(catalog, cf_model, cf_share=cf_share)
    app.extensions["cinemind_watch"] = WatchProviders(app.config["WATCH_PROVIDERS"])
    app.extensions["cinemind_engine"].set_watch(app.extensions["cinemind_watch"])
    # optional Gemini key for RAGS Genie: environment variable, or the private file instance/gemini_key.txt
    gemini_key = os.environ.get("GEMINI_API_KEY", "")
    key_file = os.path.join(BASE, "instance", "gemini_key.txt")
    if not gemini_key and os.path.exists(key_file) and not test_config:
        with open(key_file) as f:
            gemini_key = f.read().strip()
    app.extensions["cinemind_genie"] = Genie(app.extensions["cinemind_engine"], app.extensions["cinemind_watch"],
                                             gemini_key=gemini_key)
    app.extensions["cinemind_cf_state"] = {"dirty": True, "at": 0.0,
                                           "every": app.config["CF_REFRESH_SECONDS"]}

    db.init_db(app)
    app.register_blueprint(auth.bp)
    app.register_blueprint(api.bp)
    app.register_blueprint(images.bp)

    @app.get("/")
    def index():
        return send_from_directory(app.static_folder, "index.html")

    @app.after_request
    def security_headers(resp):
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        resp.headers.setdefault("X-Frame-Options", "DENY")
        return resp

    print("\n==============================================")
    print("  RAGS CineMind is ready")
    print(f"  Movies loaded        : {len(catalog)}")
    print(f"  MovieLens CF table   : {'yes' if cf_model.ml_neighbors else 'no (optional)'}")
    wp = app.extensions["cinemind_watch"]
    print(f"  Where-to-watch data  : {str(len(wp.movies)) + ' movies (' + wp.region + ', ' + wp.updated + ')' if wp.available else 'no (optional)'}")
    print(f"  RAGS Genie brain     : {'built-in + Gemini' if app.extensions['cinemind_genie'].gemini_key else 'built-in'}")
    print(f"  Startup time         : {time.time() - started:.1f}s")
    print("==============================================\n")
    return app


if __name__ == "__main__":
    app = create_app()
    port = int(os.environ.get("PORT", 5000))
    print(f"Open http://127.0.0.1:{port} in your browser\n")
    app.run(host="127.0.0.1", port=port, debug=os.environ.get("FLASK_DEBUG") == "1")
