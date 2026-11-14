"""
enrich_tmdb.py  -  fetch REAL posters, trailers and official age certificates
=============================================================================

Run ONCE on your own computer (needs internet + a free TMDB API key):

    export TMDB_API_KEY="paste-your-key-here"        # Mac / Linux
    python3 scripts/enrich_tmdb.py --indian 150
    python3 scripts/build_dataset.py                 # rebuild with the new data

What it does
  * For every movie in the TMDB 5000 dataset, asks TMDB for:
      - poster and backdrop image paths
      - the official YouTube trailer
      - official age certificates (USA and India)
  * With --indian N it also adds the N most-voted movies in each of
    Hindi, Telugu, Tamil, Malayalam and Kannada (the 5000 dataset has
    almost none).
  * Saves everything to data/tmdb_cache.jsonl. The file is appended as it
    goes, so if your internet drops just run the command again - it
    continues where it stopped.

Get a key: themoviedb.org -> sign up -> Settings -> API -> request a
"Developer" key. Either the "API Key" or the "API Read Access Token" works.
Never put this key in the website (frontend) code.

TMDB terms: show "This product uses the TMDB API but is not endorsed or
certified by TMDB." (already in the website footer). Non-commercial use.
"""

import argparse
import json
import os
import sys
import http.client
import threading
import time
from concurrent.futures import ThreadPoolExecutor
import urllib.parse

import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE_FILE = os.path.join(ROOT, "data", "tmdb_cache.jsonl")
MOVIES_FILE = os.path.join(ROOT, "data", "raw", "tmdb_5000_movies.csv")
API = "https://api.themoviedb.org/3"
INDIAN_LANGS = ["hi", "te", "ta", "ml", "kn"]


class TMDB:
    """
    Talks to TMDB over ONE reused (keep-alive) connection. Opening a new
    connection for every movie can exhaust the Mac's network ports and
    cause "OSError: [Errno 49] Can't assign requested address".
    Any network error (Wi-Fi drop, Mac sleep, reset) is retried with a
    growing wait; a movie that still fails is skipped, never crashing the run.
    """
    HOST = "api.themoviedb.org"

    def __init__(self, key):
        self.key = key.strip()
        self.is_token = len(self.key) > 40      # v4 read-access tokens are long JWTs
        self.conn = None

    def _connect(self):
        if self.conn is not None:
            try:
                self.conn.close()
            except Exception:
                pass
        self.conn = http.client.HTTPSConnection(self.HOST, timeout=20)

    def get(self, path, **params):
        if not self.is_token:
            params["api_key"] = self.key
        url = f"/3{path}?{urllib.parse.urlencode(params)}"
        headers = {"accept": "application/json", "Connection": "keep-alive"}
        if self.is_token:
            headers["Authorization"] = f"Bearer {self.key}"
        for attempt in range(8):
            try:
                if self.conn is None:
                    self._connect()
                self.conn.request("GET", url, headers=headers)
                resp = self.conn.getresponse()
                body = resp.read()
                if resp.status == 200:
                    return json.loads(body.decode("utf-8"))
                if resp.status == 404:
                    return None
                if resp.status == 401:
                    sys.exit("TMDB said 401 Unauthorized - check your TMDB_API_KEY.")
                wait = 2 + attempt * 2            # 429 rate limit or 5xx server error
            except (OSError, http.client.HTTPException, ValueError) as e:
                wait = min(5 * (attempt + 1), 30)  # network problem -> reconnect
                print(f"    network problem ({type(e).__name__}), retrying in {wait}s ...")
                self.conn = None
            time.sleep(wait)
        print(f"    skipped {path} after repeated errors (run again later to retry it)")
        return None


def best_trailer(videos):
    items = (videos or {}).get("results", [])
    yt = [v for v in items if v.get("site") == "YouTube"]
    for want in (lambda v: v["type"] == "Trailer" and v.get("official"),
                 lambda v: v["type"] == "Trailer",
                 lambda v: v["type"] == "Teaser"):
        for v in yt:
            if want(v):
                return v["key"]
    return ""


def certificates(release_dates):
    out = {}
    for country in (release_dates or {}).get("results", []):
        code = country.get("iso_3166_1")
        if code not in ("US", "IN", "GB"):
            continue
        # prefer theatrical (type 3), then any non-empty certificate
        rels = sorted(country.get("release_dates", []), key=lambda r: r.get("type") != 3)
        for r in rels:
            if r.get("certification"):
                out[code] = r["certification"].strip()
                break
    return out


def fetch_movie(tmdb, movie_id, full=False):
    extra = "videos,release_dates" + (",keywords,credits" if full else "")
    d = tmdb.get(f"/movie/{movie_id}", append_to_response=extra)
    if not d:
        return None
    rec = {
        "id": movie_id,
        "poster_path": d.get("poster_path") or "",
        "backdrop_path": d.get("backdrop_path") or "",
        "trailer_key": best_trailer(d.get("videos")),
        "certs": certificates(d.get("release_dates")),
    }
    if full:   # movie is NOT in the 5000 CSV, so keep all its details
        crew = (d.get("credits") or {}).get("crew", [])
        rec.update({
            "title": d.get("title", ""), "overview": d.get("overview", ""),
            "tagline": d.get("tagline", ""), "release_date": d.get("release_date", ""),
            "original_language": d.get("original_language", ""),
            "runtime": d.get("runtime"), "vote_average": d.get("vote_average"),
            "vote_count": d.get("vote_count"), "popularity": d.get("popularity"),
            "genres": [g["name"] for g in d.get("genres", [])],
            "keywords": [k["name"] for k in (d.get("keywords") or {}).get("keywords", [])],
            "cast": [c["name"] for c in (d.get("credits") or {}).get("cast", [])[:6]],
            "director": next((c["name"] for c in crew if c.get("job") == "Director"), ""),
        })
    return rec


def discover_ids(tmdb, lang, count):
    ids, page = [], 1
    while len(ids) < count and page <= 20:
        d = tmdb.get("/discover/movie", with_original_language=lang,
                     sort_by="vote_count.desc", page=page)
        if not d or not d.get("results"):
            break
        ids += [m["id"] for m in d["results"]]
        page += 1
    return ids[:count]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--indian", type=int, default=0,
                    help="add the N most-voted movies per Indian language (e.g. 150)")
    ap.add_argument("--limit", type=int, default=0, help="only process N movies (testing)")
    ap.add_argument("--workers", type=int, default=4, help="parallel connections (1-8, default 4)")
    args = ap.parse_args()

    key = os.environ.get("TMDB_API_KEY", "")
    if not key:
        sys.exit("Set your key first:  export TMDB_API_KEY=\"your-key\"")
    tmdb = TMDB(key)

    done = set()
    if os.path.exists(CACHE_FILE):
        with open(CACHE_FILE, encoding="utf-8") as f:
            for line in f:
                try:
                    done.add(int(json.loads(line)["id"]))
                except (ValueError, KeyError):
                    pass
    print(f"Already cached: {len(done)} movies")

    base_ids = pd.read_csv(MOVIES_FILE)["id"].astype(int).tolist()
    jobs = [(i, False) for i in base_ids if i not in done]

    if args.indian:
        base = set(base_ids)
        for lang in INDIAN_LANGS:
            ids = discover_ids(tmdb, lang, args.indian)
            new = [(i, True) for i in ids if i not in done and i not in base]
            print(f"  {lang}: {len(ids)} found, {len(new)} new")
            jobs += new
    if args.limit:
        jobs = jobs[:args.limit]

    workers = max(1, min(args.workers, 8))
    print(f"To fetch now: {len(jobs)} movies using {workers} parallel connections "
          f"(roughly {len(jobs) // (workers * 3) // 60 + 1} min)\n")
    os.makedirs(os.path.dirname(CACHE_FILE), exist_ok=True)
    start = time.time()

    local = threading.local()          # one reused connection per worker thread

    def work(job):
        if not hasattr(local, "tmdb"):
            local.tmdb = TMDB(key)
        movie_id, full = job
        return fetch_movie(local.tmdb, movie_id, full=full)

    with open(CACHE_FILE, "a", encoding="utf-8") as out, \
            ThreadPoolExecutor(max_workers=workers) as pool:
        for n, rec in enumerate(pool.map(work, jobs), 1):
            if rec:
                out.write(json.dumps(rec, ensure_ascii=False) + "\n")
            if n % 20 == 0:
                out.flush()                 # progress is saved every 20 movies
            if n % 100 == 0 or n == len(jobs):
                spent = time.time() - start
                left = (len(jobs) - n) * spent / n
                print(f"  {n}/{len(jobs)}  ({spent:.0f}s, about {left / 60:.0f} min left)")
    print(f"\nDone. Cache: {CACHE_FILE}")
    print("Now run:  python3 scripts/build_dataset.py")


if __name__ == "__main__":
    main()
