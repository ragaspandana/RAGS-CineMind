"""
cache_posters.py  -  download every poster once into data/image_cache/
======================================================================

Run on your computer (needs internet once):

    caffeinate -i python3 scripts/cache_posters.py

After this, posters load from your own server even with no internet,
and even if your network blocks image.tmdb.org. It skips files already
downloaded, so you can stop it (Ctrl + C) and run it again any time.

About 5,300 posters at w342 size, roughly 150-250 MB in total.
Add --backdrops to also download ALL large background images (about 1 GB), or
--top-backdrops 400 to save backdrops only for the 400 most popular movies
(about 100 MB). Those are the ones the Spotlight banner and demos show, so the
site looks complete even with no internet.
"""

import argparse
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor

import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from cinemind.images import NAME_RE, fetch  # noqa: E402

CATALOG = os.path.join(ROOT, "data", "movies.csv")
CACHE = os.path.join(ROOT, "data", "image_cache")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--backdrops", action="store_true", help="all backdrops (large)")
    ap.add_argument("--top-backdrops", type=int, default=0, help="backdrops for the N most popular movies")
    args = ap.parse_args()

    df = pd.read_csv(CATALOG, usecols=["poster_url", "backdrop_url", "popularity"], keep_default_na=False)
    jobs = [("w342", u.rsplit("/", 1)[-1]) for u in df["poster_url"] if u]
    if args.backdrops:
        jobs += [("w1280", u.rsplit("/", 1)[-1]) for u in df["backdrop_url"] if u]
    elif args.top_backdrops > 0:
        pop = pd.to_numeric(df["popularity"], errors="coerce").fillna(0)
        top = df.loc[pop.sort_values(ascending=False).index[:args.top_backdrops], "backdrop_url"]
        jobs += [("w1280", u.rsplit("/", 1)[-1]) for u in top if u]
    jobs = [j for j in jobs if NAME_RE.match(j[1])]
    todo = [j for j in jobs if not os.path.exists(os.path.join(CACHE, j[0], j[1]))]
    print(f"Images: {len(jobs)}  already saved: {len(jobs) - len(todo)}  to download: {len(todo)}\n")

    start, ok, failed = time.time(), 0, 0
    with ThreadPoolExecutor(max_workers=max(1, min(args.workers, 12))) as pool:
        for n, path in enumerate(pool.map(lambda j: fetch(j[0], j[1], CACHE), todo), 1):
            ok, failed = (ok + 1, failed) if path else (ok, failed + 1)
            if n % 200 == 0 or n == len(todo):
                spent = time.time() - start
                print(f"  {n}/{len(todo)}  saved {ok}, failed {failed}  "
                      f"({spent:.0f}s, about {(len(todo) - n) * spent / n / 60:.0f} min left)")
    print(f"\nDone. Saved {ok} new images, {failed} failed.")
    if failed:
        print("Failed ones will be retried automatically when you run this again "
              "or when the website first shows them.")
    if ok == 0 and todo:
        print("\nNothing could be downloaded: your network may block image.tmdb.org."
              "\nTry your phone hotspot, then run this script again.")


if __name__ == "__main__":
    main()
