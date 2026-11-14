"""
watch.py  -  "Where to watch" (OTT platforms) for each movie
=============================================================

Data comes from data/watch_providers.json, made by
scripts/fetch_watch_providers.py (TMDB, which gets it from JustWatch).

TMDB does not give a direct link to the movie's page on each platform.
So each platform button links to:
  * the platform's own search, with the movie title already filled in,
    for platforms whose search address is public and stable; or
  * TMDB's "watch" page for the movie, which has the exact links,
    for every other platform.
"""

import json
import os
import re
from urllib.parse import quote_plus

from .images import local_url

# platform name (lower case, without punctuation) -> search address
SEARCH = {
    "netflix": "https://www.netflix.com/search?q={q}",
    "netflixbasicwithads": "https://www.netflix.com/search?q={q}",
    "amazonprimevideo": "https://www.primevideo.com/search?phrase={q}",
    "amazonprimevideowithads": "https://www.primevideo.com/search?phrase={q}",
    "amazonvideo": "https://www.primevideo.com/search?phrase={q}",
    "appletv": "https://tv.apple.com/search?term={q}",
    "appletvplus": "https://tv.apple.com/search?term={q}",
    "youtube": "https://www.youtube.com/results?search_query={q}+full+movie",
    "youtubepremium": "https://www.youtube.com/results?search_query={q}+full+movie",
    "googleplaymovies": "https://play.google.com/store/search?q={q}&c=movies",
}
KIND_LABELS = {"stream": "Stream", "free": "Free", "ads": "Free with ads", "rent": "Rent", "buy": "Buy"}


def _key(name):
    return re.sub(r"[^a-z0-9]", "", name.lower())


class WatchProviders:
    def __init__(self, path):
        self.region, self.updated, self.movies = "", "", {}
        if path and os.path.exists(path):
            with open(path) as f:
                data = json.load(f)
            self.region = data.get("region", "")
            self.updated = data.get("updated", "")
            self.movies = data.get("movies", {})

    @property
    def available(self):
        return bool(self.movies)

    def for_movie(self, movie_id, title, year=None):
        """Data for the website, or None if no data was fetched at all."""
        if not self.available:
            return None
        rec = self.movies.get(str(movie_id))
        tmdb_link = (rec or {}).get("link") or f"https://www.themoviedb.org/movie/{movie_id}/watch?locale={self.region}"
        groups = []
        for kind, label in KIND_LABELS.items():
            items = []
            for p in (rec or {}).get(kind, []):
                template = SEARCH.get(_key(p["name"]))
                items.append({
                    "name": p["name"],
                    "logo": local_url("https://image.tmdb.org/t/p/w92" + p["logo"], "w92") if p.get("logo") else "",
                    "url": template.format(q=quote_plus(title)) if template else tmdb_link,
                    "direct_search": bool(template),
                })
            if items:
                groups.append({"kind": kind, "label": label, "platforms": items})
        return {"region": self.region, "updated": self.updated, "groups": groups,
                "all_link": tmdb_link, "source": "JustWatch"}

    def logos(self):
        """platform name -> small logo address (for badges on movie cards)."""
        out = {}
        for rec in self.movies.values():
            for k in ("stream", "free", "ads"):
                for p in rec.get(k, []):
                    if p.get("logo") and p["name"] not in out:
                        out[p["name"]] = local_url("https://image.tmdb.org/t/p/w92" + p["logo"], "w92")
        return out

    def platforms_of(self, movie_id):
        rec = self.movies.get(str(movie_id)) or {}
        return {p["name"] for k in ("stream", "free", "ads") for p in rec.get(k, [])}
