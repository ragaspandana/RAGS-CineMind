"""
build_cf_model.py  -  build the collaborative-filtering table from MovieLens
==========================================================================

Run ONCE on your own computer (needs internet the first time):

    python3 scripts/build_cf_model.py

It downloads the MovieLens "latest-small" dataset (about 1 MB, 100,000+
ratings by ~600 real users, from GroupLens, University of Minnesota),
maps MovieLens movies to our catalogue using links.csv (tmdbId), and saves
the top-50 similar movies for every catalogue movie to
data/cf_neighbors.json.  The app picks the file up automatically on the
next start.

Citation for your report:
  F. Maxwell Harper and Joseph A. Konstan. 2015. The MovieLens Datasets:
  History and Context. ACM Transactions on Interactive Intelligent Systems
  (TiiS) 5, 4: 19:1-19:19.
"""

import io
import json
import os
import sys
import urllib.request
import zipfile

import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from cinemind.cf import item_item_neighbors  # noqa: E402

ML_URL = "https://files.grouplens.org/datasets/movielens/ml-latest-small.zip"
ML_DIR = os.path.join(ROOT, "data", "raw", "ml-latest-small")
CATALOG = os.path.join(ROOT, "data", "movies.csv")
OUT = os.path.join(ROOT, "data", "cf_neighbors.json")


def ensure_movielens():
    if os.path.exists(os.path.join(ML_DIR, "ratings.csv")):
        return
    print("Downloading MovieLens latest-small ...")
    with urllib.request.urlopen(ML_URL, timeout=60) as resp:
        data = resp.read()
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        z.extractall(os.path.dirname(ML_DIR))
    print("Saved to", ML_DIR)


def load_ratings_in_catalog():
    """MovieLens ratings mapped to TMDB ids that exist in our catalogue."""
    ratings = pd.read_csv(os.path.join(ML_DIR, "ratings.csv"))
    links = pd.read_csv(os.path.join(ML_DIR, "links.csv")).dropna(subset=["tmdbId"])
    links["tmdbId"] = links["tmdbId"].astype(int)
    catalog_ids = set(pd.read_csv(CATALOG, usecols=["id"])["id"].astype(int))
    r = ratings.merge(links[["movieId", "tmdbId"]], on="movieId")
    r = r[r["tmdbId"].isin(catalog_ids)]
    return r


def main():
    ensure_movielens()
    r = load_ratings_in_catalog()
    print(f"Ratings matched to catalogue: {len(r):,}  users: {r.userId.nunique()}  "
          f"movies: {r.tmdbId.nunique()}")
    nb = item_item_neighbors(r["userId"].tolist(), r["tmdbId"].tolist(),
                             r["rating"].tolist(), top_k=50, min_common=3)
    with open(OUT, "w") as f:
        json.dump({str(k): v for k, v in nb.items()}, f)
    print(f"Saved neighbours for {len(nb):,} movies -> {OUT}")


if __name__ == "__main__":
    main()
