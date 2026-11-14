"""
cf.py  -  item-based collaborative filtering
============================================

"People who liked movie A also liked movie B."

Two sources of user behaviour are combined:
  1. MovieLens ratings (100,000+ real ratings from ~600 users), turned into
     an item-item similarity table by scripts/build_cf_model.py and saved
     to data/cf_neighbors.json.  (Optional: if the file is missing the app
     still works, using only source 2.)
  2. Likes / ratings made by users of THIS app, read live from the database.

Item-item similarity (adjusted cosine):
  for every user, subtract their mean rating;  sim(A, B) = cosine of the
  two movies' rating columns.  We keep the top 50 neighbours per movie.

CF score of a candidate movie for a user:
  average of sim(liked movie, candidate) over the user's liked movies.
"""

import json
import os
from collections import defaultdict

import numpy as np
from scipy.sparse import csr_matrix


def item_item_neighbors(user_ids, item_ids, values, top_k=50, min_common=1, center=True):
    """
    Build {item: [(neighbour, similarity), ...]} from (user, item, value) triples.
    Used both by build_cf_model.py (MovieLens) and live for in-app likes.
    """
    if len(item_ids) == 0:
        return {}
    users = {u: i for i, u in enumerate(sorted(set(user_ids)))}
    items = sorted(set(item_ids))
    item_idx = {m: i for i, m in enumerate(items)}
    vals = np.asarray(values, dtype=float)
    u_idx = np.array([users[u] for u in user_ids])
    if center:
        sums = np.bincount(u_idx, weights=vals, minlength=len(users))
        counts = np.bincount(u_idx, minlength=len(users))
        vals = vals - (sums / np.maximum(counts, 1))[u_idx]
    m = csr_matrix((vals, ([item_idx[i] for i in item_ids], u_idx)),
                   shape=(len(items), len(users)))
    norms = np.sqrt(np.asarray(m.multiply(m).sum(axis=1)).ravel())
    norms[norms == 0] = 1.0
    binary = (m != 0).astype(float)
    sims = (m @ m.T).toarray().astype(np.float32) / np.outer(norms, norms).astype(np.float32)
    common = (binary @ binary.T).toarray().astype(np.float32)
    np.fill_diagonal(sims, 0)
    sims[common < min_common] = 0
    # shrink similarities that rest on very few common users (significance weighting)
    sims *= common / (common + 5.0)

    out = {}
    for i, movie in enumerate(items):
        row = sims[i]
        top = np.argsort(-row)[:top_k]
        nb = [(int(items[j]), round(float(row[j]), 4)) for j in top if row[j] > 0]
        if nb:
            out[int(movie)] = nb
    return out


class CollaborativeModel:
    def __init__(self, neighbors_path=None):
        self.ml_neighbors = {}
        if neighbors_path and os.path.exists(neighbors_path):
            with open(neighbors_path) as f:
                raw = json.load(f)
            self.ml_neighbors = {int(k): [(int(a), float(b)) for a, b in v] for k, v in raw.items()}
        self.app_neighbors = {}

    @property
    def available(self):
        return bool(self.ml_neighbors or self.app_neighbors)

    def refresh_from_app(self, interactions):
        """interactions: list of (user_id, movie_id, value) with value 1..5 (like = 5)."""
        if len({u for u, _, _ in interactions}) < 2:
            self.app_neighbors = {}
            return
        u, i, v = zip(*interactions)
        self.app_neighbors = item_item_neighbors(u, i, v, top_k=50, center=False)

    def neighbours(self, movie_id):
        merged = defaultdict(float)
        for nb, s in self.ml_neighbors.get(movie_id, []):
            merged[nb] += s
        for nb, s in self.app_neighbors.get(movie_id, []):
            merged[nb] += 0.5 * s          # in-app data is smaller -> lower weight
        return merged

    def scores(self, liked_ids, candidate_ids):
        """
        Returns (scores array aligned with candidate_ids, best_source dict)
        best_source[candidate] = the liked movie that contributed most.
        """
        if not liked_ids or not self.available:
            return None, {}
        pos = {m: k for k, m in enumerate(candidate_ids)}
        total = np.zeros(len(candidate_ids))
        best = {}
        for liked in liked_ids:
            for nb, s in self.neighbours(int(liked)).items():
                k = pos.get(nb)
                if k is None:
                    continue
                total[k] += s
                if s > best.get(nb, (None, 0))[1]:
                    best[nb] = (int(liked), s)
        if not total.any():
            return None, {}
        return total / len(liked_ids), {m: b[0] for m, b in best.items()}
