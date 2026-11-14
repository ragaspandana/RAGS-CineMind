"""
fetch_watch_providers.py  -  which OTT platforms have each movie (India)
=========================================================================

Run on your computer (needs internet and your TMDB key):

    export TMDB_API_KEY="your-key"
    caffeinate -i python3 scripts/fetch_watch_providers.py

For every movie in data/movies.csv it asks TMDB which platforms offer it
in India (stream / free / with ads / rent / buy). TMDB gets this data from
JustWatch, so the website shows "Availability data by JustWatch".
It also downloads each platform's small logo into data/image_cache/w92/.

Saves data/watch_providers.json. Restart app.py afterwards.

Availability changes over time (movies leave and join platforms), so run
this again before your demo to refresh it. Use --region US for the USA.
"""

import argparse
import json
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date

import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts"))
from enrich_tmdb import TMDB  # noqa: E402  (same retrying, keep-alive client)
from cinemind.images import fetch as fetch_image  # noqa: E402

CATALOG = os.path.join(ROOT, "data", "movies.csv")
OUT = os.path.join(ROOT, "data", "watch_providers.json")
IMG_CACHE = os.path.join(ROOT, "data", "image_cache")
KINDS = {"flatrate": "stream", "free": "free", "ads": "ads", "rent": "rent", "buy": "buy"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--region", default="IN", help="country code, default IN (India)")
    ap.add_argument("--workers", type=int, default=8)
    args = ap.parse_args()
    key = os.environ.get("TMDB_API_KEY", "")
    if not key:
        sys.exit('Set your key first:  export TMDB_API_KEY="your-key"')

    ids = pd.read_csv(CATALOG, usecols=["id"])["id"].astype(int).tolist()
    print(f"Checking {len(ids)} movies for platforms in region {args.region} ...\n")
    local = threading.local()

    def work(movie_id):
        if not hasattr(local, "tmdb"):
            local.tmdb = TMDB(key)
        d = local.tmdb.get(f"/movie/{movie_id}/watch/providers")
        region = ((d or {}).get("results") or {}).get(args.region)
        if not region:
            return movie_id, None
        rec = {"link": region.get("link", "")}
        for api_kind, kind in KINDS.items():
            items = sorted(region.get(api_kind) or [], key=lambda p: p.get("display_priority", 99))
            if items:
                rec[kind] = [{"id": p["provider_id"], "name": p["provider_name"],
                              "logo": p.get("logo_path") or ""} for p in items]
        return movie_id, rec

    result, start = {}, time.time()
    with ThreadPoolExecutor(max_workers=max(1, min(args.workers, 12))) as pool:
        for n, (movie_id, rec) in enumerate(pool.map(work, ids), 1):
            if rec and len(rec) > 1:
                result[str(movie_id)] = rec
            if n % 250 == 0 or n == len(ids):
                spent = time.time() - start
                print(f"  {n}/{len(ids)}  on a platform: {len(result)}  "
                      f"({spent:.0f}s, about {(len(ids) - n) * spent / n / 60:.0f} min left)")

    logos = {p["logo"].lstrip("/") for rec in result.values() for k in KINDS.values()
             for p in rec.get(k, []) if p["logo"]}
    print(f"\nDownloading {len(logos)} platform logos ...")
    ok = sum(1 for name in logos if fetch_image("w92", name, IMG_CACHE))
    with open(OUT, "w") as f:
        json.dump({"region": args.region, "updated": date.today().isoformat(), "movies": result}, f)

    platforms = {}
    for rec in result.values():
        for p in rec.get("stream", []):
            platforms[p["name"]] = platforms.get(p["name"], 0) + 1
    print(f"Logos saved: {ok}/{len(logos)}")
    print(f"\nMovies available on at least one platform in {args.region}: {len(result)} of {len(ids)}")
    print("Top streaming platforms:")
    for name, count in sorted(platforms.items(), key=lambda x: -x[1])[:10]:
        print(f"  {name:32} {count}")
    print(f"\nSaved {OUT}\nNow restart:  python3 app.py")


if __name__ == "__main__":
    main()
