"""
images.py  -  serves movie posters and backdrops from our own server
=====================================================================

Why: some internet providers block image.tmdb.org, so the browser cannot
load posters directly. Instead the website asks OUR server for
/img/w342/abc.jpg. The server:
  1. returns the saved copy from data/image_cache/ if it already has it,
  2. otherwise downloads it once from TMDB, saves it, and returns it.
After the first view (or after running scripts/cache_posters.py) the
posters work with no internet at all - useful for the viva demo.
"""

import os
import re
import urllib.request

from flask import Blueprint, abort, current_app, send_file

bp = Blueprint("images", __name__)

TMDB_IMG = "https://image.tmdb.org/t/p/"
SIZES = {"w92", "w185", "w342", "w500", "w780", "w1280"}
NAME_RE = re.compile(r"^[A-Za-z0-9_\-]{5,64}\.(jpg|jpeg|png)$")


def cache_dir():
    path = current_app.config["IMAGE_CACHE"]
    os.makedirs(path, exist_ok=True)
    return path


def local_url(tmdb_url, size):
    """https://image.tmdb.org/t/p/w500/abc.jpg -> /img/<size>/abc.jpg"""
    if not tmdb_url:
        return ""
    name = tmdb_url.rsplit("/", 1)[-1]
    return f"/img/{size}/{name}" if NAME_RE.match(name) else tmdb_url


def fetch(size, name, folder, timeout=15):
    """Download one image into the cache. Returns the file path or None."""
    target = os.path.join(folder, size, name)
    if os.path.exists(target) and os.path.getsize(target) > 0:
        return target
    os.makedirs(os.path.dirname(target), exist_ok=True)
    req = urllib.request.Request(TMDB_IMG + size + "/" + name, headers={"User-Agent": "RAGS-CineMind"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = resp.read()
    except Exception:
        return None
    if not data:
        return None
    tmp = target + ".part"
    with open(tmp, "wb") as f:
        f.write(data)
    os.replace(tmp, target)
    return target


@bp.get("/img/<size>/<name>")
def image(size, name):
    if size not in SIZES or not NAME_RE.match(name):
        abort(404)
    path = fetch(size, name, cache_dir())
    if not path:
        abort(404)
    resp = send_file(path, mimetype="image/png" if name.endswith(".png") else "image/jpeg")
    resp.headers["Cache-Control"] = "public, max-age=2592000"   # browser keeps it 30 days
    return resp
