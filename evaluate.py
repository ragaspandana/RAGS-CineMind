"""
evaluate.py  -  measure recommendation quality (numbers for your report)
=======================================================================

Run on your computer AFTER build_cf_model.py has downloaded MovieLens:

    python3 scripts/evaluate.py

PART A - Ranking quality (offline evaluation on MovieLens)
  Protocol
    * MovieLens ratings mapped to our catalogue (links.csv -> TMDB id).
    * "Relevant" = the user rated the movie 4.0 or more.
    * Temporal split per user: the first 80% of their ratings (by time) are
      TRAIN, the last 20% are TEST.  We predict the future from the past.
    * Users are split 50/50 into VALIDATION users (used only to choose the
      hybrid weights) and TEST users (used only to report results), so the
      reported numbers are not tuned on the data they are measured on.
    * Collaborative filtering is re-built from TRAIN ratings only.
  Methods compared
    Popularity      most-liked movies overall (non-personal baseline)
    Top rated       highest weighted rating (non-personal baseline)
    Content (TF-IDF)  similarity to the user's liked movies
    Item CF         "people who liked X also liked Y"
    CineMind hybrid   a*CF + b*Content + c*Quality  (a,b,c tuned on validation)
  Metrics (K = 10)
    Precision@K, Recall@K, NDCG@K, HitRate@K, catalogue coverage

PART B - Audience-safety rule accuracy
  For movies that have an OFFICIAL certificate (after enrich_tmdb.py), we
  compare our rule-based estimate (labels.estimate_level) with the official
  level, and report accuracy, a confusion matrix, and the most important
  safety number: how often an official Teen/Adult movie would have been
  wrongly estimated as All-ages.

Outputs:  reports/evaluation_results.md  and  reports/evaluation_results.json
"""

import argparse
import itertools
import json
import math
import os
import sys
import time
from collections import defaultdict

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from cinemind import labels  # noqa: E402
from cinemind.catalog import Catalog  # noqa: E402
from cinemind.cf import item_item_neighbors  # noqa: E402

ML_DIR = os.path.join(ROOT, "data", "raw", "ml-latest-small")
CATALOG = os.path.join(ROOT, "data", "movies.csv")
REPORT_DIR = os.path.join(ROOT, "reports")
K = 10
REL = 4.0


# ---------------------------------------------------------------------------
# metrics
# ---------------------------------------------------------------------------
def metrics_at_k(ranked, relevant, k=K):
    top = ranked[:k]
    hits = [1 if m in relevant else 0 for m in top]
    n_hit = sum(hits)
    dcg = sum(h / math.log2(i + 2) for i, h in enumerate(hits))
    idcg = sum(1 / math.log2(i + 2) for i in range(min(len(relevant), k)))
    return {"precision": n_hit / k, "recall": n_hit / len(relevant),
            "ndcg": dcg / idcg if idcg else 0.0, "hit": 1.0 if n_hit else 0.0}


def norm(x):
    m = x.max()
    return x / m if m > 0 else x


# ---------------------------------------------------------------------------
# data
# ---------------------------------------------------------------------------
def load_split(ratings_path, links_path, catalog):
    r = pd.read_csv(ratings_path)
    links = pd.read_csv(links_path).dropna(subset=["tmdbId"])
    links["tmdbId"] = links["tmdbId"].astype(int)
    r = r.merge(links[["movieId", "tmdbId"]], on="movieId")
    r = r[r["tmdbId"].isin(set(catalog.ids))]
    r = r.sort_values(["userId", "timestamp"])

    train_parts, test = [], {}
    for uid, g in r.groupby("userId"):
        cut = int(len(g) * 0.8)
        tr, te = g.iloc[:cut], g.iloc[cut:]
        rel = set(te.loc[te["rating"] >= REL, "tmdbId"])
        if len(tr[tr["rating"] >= REL]) >= 5 and len(rel) >= 2:
            test[uid] = rel
        train_parts.append(tr)
    train = pd.concat(train_parts)
    return train, test


class Methods:
    def __init__(self, catalog, train):
        self.cat = catalog
        self.items = np.array(sorted(set(train["tmdbId"])))          # candidate pool
        self.rows = np.array(catalog.rows_for(self.items))
        self.quality = catalog.df["quality"].to_numpy()[self.rows]
        pos = train[train["rating"] >= REL]
        pop = pos.groupby("tmdbId").size()
        self.popularity = np.array([pop.get(i, 0) for i in self.items], dtype=float)
        self.user_train = train.groupby("userId")["tmdbId"].apply(set).to_dict()
        self.user_liked = pos.groupby("userId")["tmdbId"].apply(list).to_dict()
        t = time.time()
        self.nb = item_item_neighbors(train["userId"].tolist(), train["tmdbId"].tolist(),
                                      train["rating"].tolist(), top_k=50, min_common=3)
        print(f"  item-CF built from train ratings in {time.time() - t:.1f}s")
        self.index = {m: k for k, m in enumerate(self.items)}

    def components(self, uid):
        liked = self.user_liked.get(uid, [])
        content = self.cat.content_similarity(self.cat.rows_for(liked), self.rows)
        cf = np.zeros(len(self.items))
        for m in liked:
            for nb, s in self.nb.get(int(m), []):
                k = self.index.get(nb)
                if k is not None:
                    cf[k] += s
        return {"popularity": norm(self.popularity), "quality": self.quality,
                "content": norm(content), "cf": norm(cf)}

    def rank(self, uid, score):
        seen = self.user_train.get(uid, set())
        order = np.argsort(-score)
        out = []
        for k in order:
            m = int(self.items[k])
            if m not in seen:
                out.append(m)
                if len(out) == K:
                    break
        return out


def evaluate(methods, users, test, scorers):
    sums = {name: defaultdict(float) for name in scorers}
    recommended = {name: set() for name in scorers}
    for uid in users:
        comp = methods.components(uid)
        for name, f in scorers.items():
            ranked = methods.rank(uid, f(comp))
            recommended[name].update(ranked)
            for metric, v in metrics_at_k(ranked, test[uid]).items():
                sums[name][metric] += v
    n = max(len(users), 1)
    out = {}
    for name in scorers:
        out[name] = {m: round(v / n, 4) for m, v in sums[name].items()}
        out[name]["coverage"] = round(len(recommended[name]) / len(methods.items), 4)
    return out


def part_a(catalog, ratings_path, links_path, seed):
    print("\nPART A - ranking quality")
    train, test = load_split(ratings_path, links_path, catalog)
    print(f"  train ratings: {len(train):,}  evaluable users: {len(test)}")
    methods = Methods(catalog, train)

    users = sorted(test)
    rng = np.random.default_rng(seed)
    rng.shuffle(users)
    half = len(users) // 2
    val_users, test_users = users[:half], users[half:]

    # tune hybrid weights on VALIDATION users only
    grid = [w for w in itertools.product([0, .2, .4, .6, .8, 1.0], repeat=3) if abs(sum(w) - 1) < 1e-9]
    best, best_w = -1, None
    for a, b, c in grid:
        r = evaluate(methods, val_users, test,
                     {"h": lambda comp, a=a, b=b, c=c: a * comp["cf"] + b * comp["content"] + c * comp["quality"]})
        if r["h"]["ndcg"] > best:
            best, best_w = r["h"]["ndcg"], (a, b, c)
    print(f"  best hybrid weights on validation users (cf, content, quality) = {best_w}")
    a, b, c = best_w

    scorers = {
        "Popularity": lambda comp: comp["popularity"],
        "Top rated": lambda comp: comp["quality"],
        "Content (TF-IDF)": lambda comp: comp["content"],
        "Item CF": lambda comp: comp["cf"],
        "CineMind hybrid": lambda comp: a * comp["cf"] + b * comp["content"] + c * comp["quality"],
    }
    results = evaluate(methods, test_users, test, scorers)
    if a + b > 0:   # tell the live engine how to mix CF and content in "Your taste"
        with open(os.path.join(ROOT, "data", "personal_mix.json"), "w") as f:
            json.dump({"cf_share": round(a / (a + b), 3), "source": "scripts/evaluate.py"}, f)
    return {"protocol": {"relevance_threshold": REL, "k": K, "split": "temporal 80/20 per user",
                         "validation_users": len(val_users), "test_users": len(test_users),
                         "train_ratings": int(len(train)), "candidate_movies": int(len(methods.items)),
                         "hybrid_weights_cf_content_quality": best_w},
            "results": results}


def part_b(catalog):
    print("\nPART B - audience rule accuracy")
    df = catalog.df[catalog.df["level_source"] == "official"]
    if len(df) < 30:
        print("  Skipped: fewer than 30 movies have official certificates. Run enrich_tmdb.py first.")
        return None
    est, off = df["estimated_level"].to_numpy(), df["content_level"].to_numpy()
    conf = pd.crosstab(pd.Series(off, name="official"), pd.Series(est, name="estimated"))
    mature = off >= 2
    unsafe = int(((est == 0) & mature).sum())
    return {
        "movies_with_official_certificate": int(len(df)),
        "exact_accuracy": round(float((est == off).mean()), 4),
        "within_one_level": round(float((abs(est - off) <= 1).mean()), 4),
        "never_less_strict_rate": round(float((est >= off).mean()), 4),
        "teen_or_adult_estimated_all_ages": unsafe,
        "teen_or_adult_estimated_all_ages_rate": round(unsafe / max(int(mature.sum()), 1), 4),
        "confusion_matrix": {f"official {labels.LEVEL_NAMES[int(i)]}":
                             {labels.LEVEL_NAMES[int(j)]: int(conf.loc[i, j]) for j in conf.columns}
                             for i in conf.index},
    }


def write_report(a, b):
    os.makedirs(REPORT_DIR, exist_ok=True)
    with open(os.path.join(REPORT_DIR, "evaluation_results.json"), "w") as f:
        json.dump({"ranking": a, "audience_rule": b}, f, indent=2)
    lines = ["# RAGS CineMind - Evaluation results", ""]
    if a:
        p = a["protocol"]
        lines += ["## A. Ranking quality (MovieLens, K = 10)", "",
                  f"Temporal 80/20 split per user. Relevant = rating >= {p['relevance_threshold']}. "
                  f"{p['test_users']} test users, {p['validation_users']} validation users, "
                  f"{p['candidate_movies']} candidate movies. Hybrid weights (CF, content, quality) "
                  f"= {p['hybrid_weights_cf_content_quality']}, chosen on validation users only.", "",
                  "| Method | Precision@10 | Recall@10 | NDCG@10 | HitRate@10 | Coverage |",
                  "|---|---|---|---|---|---|"]
        for name, r in a["results"].items():
            lines.append(f"| {name} | {r['precision']:.4f} | {r['recall']:.4f} | {r['ndcg']:.4f} | "
                         f"{r['hit']:.4f} | {r['coverage']:.4f} |")
        lines.append("")
    if b:
        lines += ["## B. Audience-safety rule vs official certificates", "",
                  f"- Movies with an official certificate: {b['movies_with_official_certificate']}",
                  f"- Exact level accuracy: {b['exact_accuracy']:.2%}",
                  f"- Within one level: {b['within_one_level']:.2%}",
                  f"- Estimate at least as strict as official: {b['never_less_strict_rate']:.2%}",
                  f"- Teen/Adult films wrongly estimated as All-ages: {b['teen_or_adult_estimated_all_ages']} "
                  f"({b['teen_or_adult_estimated_all_ages_rate']:.2%})", ""]
    path = os.path.join(REPORT_DIR, "evaluation_results.md")
    with open(path, "w") as f:
        f.write("\n".join(lines))
    print(f"\nSaved {path}")
    print("\n".join(lines))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ratings", default=os.path.join(ML_DIR, "ratings.csv"))
    ap.add_argument("--links", default=os.path.join(ML_DIR, "links.csv"))
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()
    catalog = Catalog(CATALOG)
    a = None
    if os.path.exists(args.ratings):
        a = part_a(catalog, args.ratings, args.links, args.seed)
    else:
        print("MovieLens not found - run  python3 scripts/build_cf_model.py  first (Part A skipped).")
    b = part_b(catalog)
    write_report(a, b)


if __name__ == "__main__":
    main()
