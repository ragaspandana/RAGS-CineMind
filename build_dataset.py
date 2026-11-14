"""
build_dataset.py  -  builds data/movies.csv (the catalogue the app uses)
=======================================================================

Run from the project folder:
    python3 scripts/build_dataset.py

Inputs
  data/raw/tmdb_5000_movies.csv     (TMDB 5000 dataset - movies)
  data/raw/tmdb_5000_credits.csv    (TMDB 5000 dataset - cast & crew)
  data/tmdb_cache.jsonl             (OPTIONAL - created by scripts/enrich_tmdb.py:
                                     real posters, trailers, official age
                                     certificates and extra Indian movies)

Output
  data/movies.csv
  data/dataset_report.json          (numbers for your project report)

Steps
  1. Load and JOIN movies + credits on the movie id (not the title -
     titles are not unique, e.g. there are two different "The Host").
  2. Merge the optional TMDB enrichment cache.
  3. Clean: drop movies without a description or genre.
  4. Compute a quality score (IMDb-style weighted rating).
  5. Compute the 15-emotion profile for every movie (rules in labels.py).
  6. Compute the content level (official certificate, else rule estimate).
  7. Save.
"""

import json
import os
import sys

import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from cinemind import labels  # noqa: E402

RAW_DIR = os.path.join(ROOT, "data", "raw")
MOVIES_FILE = os.path.join(RAW_DIR, "tmdb_5000_movies.csv")
CREDITS_FILE = os.path.join(RAW_DIR, "tmdb_5000_credits.csv")
CACHE_FILE = os.path.join(ROOT, "data", "tmdb_cache.jsonl")
OUTPUT_FILE = os.path.join(ROOT, "data", "movies.csv")
REPORT_FILE = os.path.join(ROOT, "data", "dataset_report.json")

IMG_BASE = "https://image.tmdb.org/t/p/"
INDIAN_LANGS = {"hi", "te", "ta", "ml", "kn", "bn", "mr"}


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def names(json_text, limit=None):
    try:
        items = json.loads(json_text)
    except (TypeError, ValueError):
        return []
    out = [i["name"] for i in items if "name" in i]
    return out[:limit] if limit else out


def director_of(json_text):
    try:
        for person in json.loads(json_text):
            if person.get("job") == "Director":
                return person["name"]
    except (TypeError, ValueError):
        pass
    return ""


def load_cache():
    """Read the optional enrichment cache (one JSON object per line)."""
    cache = {}
    if not os.path.exists(CACHE_FILE):
        return cache
    with open(CACHE_FILE, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    rec = json.loads(line)
                    cache[int(rec["id"])] = rec
                except (ValueError, KeyError):
                    continue
    return cache


def pick_certificate(certs, language):
    """Choose India's certificate for Indian-language films, else USA's."""
    if not certs:
        return "", ""
    order = ["IN", "US", "GB"] if language in INDIAN_LANGS else ["US", "IN", "GB"]
    for country in order:
        cert = certs.get(country, "")
        if cert and labels.cert_to_level(cert) is not None:
            return cert, country
    return "", ""


# ---------------------------------------------------------------------------
# 1. load + join
# ---------------------------------------------------------------------------
def load_base():
    movies = pd.read_csv(MOVIES_FILE)
    credits = pd.read_csv(CREDITS_FILE)
    df = movies.merge(credits[["movie_id", "cast", "crew"]],
                      left_on="id", right_on="movie_id", how="left")

    out = pd.DataFrame({
        "id": df["id"].astype(int),
        "title": df["title"].fillna(""),
        "release_date": df["release_date"].fillna(""),
        "overview": df["overview"].fillna(""),
        "tagline": df["tagline"].fillna(""),
        "genres": df["genres"].apply(names),
        "keywords": df["keywords"].apply(names),
        "language": df["original_language"].fillna("xx"),
        "runtime": pd.to_numeric(df["runtime"], errors="coerce"),
        "rating": pd.to_numeric(df["vote_average"], errors="coerce"),
        "vote_count": pd.to_numeric(df["vote_count"], errors="coerce"),
        "popularity": pd.to_numeric(df["popularity"], errors="coerce"),
        "cast": df["cast"].apply(lambda x: names(x, 6)),
        "director": df["crew"].apply(director_of),
    })
    return out


def add_cache_movies(df, cache):
    """Movies that exist only in the enrichment cache (e.g. Indian films)."""
    have = set(df["id"])
    extra = []
    for mid, rec in cache.items():
        if mid in have or not rec.get("title"):
            continue
        extra.append({
            "id": mid, "title": rec.get("title", ""),
            "release_date": rec.get("release_date", ""),
            "overview": rec.get("overview", ""), "tagline": rec.get("tagline", ""),
            "genres": rec.get("genres", []), "keywords": rec.get("keywords", []),
            "language": rec.get("original_language", "xx"),
            "runtime": rec.get("runtime"), "rating": rec.get("vote_average"),
            "vote_count": rec.get("vote_count"), "popularity": rec.get("popularity"),
            "cast": rec.get("cast", [])[:6], "director": rec.get("director", ""),
        })
    if extra:
        df = pd.concat([df, pd.DataFrame(extra)], ignore_index=True)
    return df, len(extra)


# ---------------------------------------------------------------------------
# 4. quality  (weighted rating: WR = v/(v+m)*R + m/(v+m)*C)
# ---------------------------------------------------------------------------
def quality_scores(df):
    C = df["rating"].mean()
    m = df["vote_count"].quantile(0.60)
    v = df["vote_count"]
    wr = (v / (v + m)) * df["rating"] + (m / (v + m)) * C
    return ((wr - wr.min()) / (wr.max() - wr.min())).round(4), float(C), float(m)


# ---------------------------------------------------------------------------
# 5. emotion profile
# ---------------------------------------------------------------------------
def emotion_profile(row):
    """Return {emotion: raw_score} and {emotion: [evidence words]}."""
    genres = set(row["genres"])
    kw = {k.lower() for k in row["keywords"]}
    text = f" {row['overview']} {row['tagline']} ".lower()
    year = row["year"]

    raw, evidence = {}, {}
    for key, spec in labels.EMOTIONS.items():
        score, ev = 0.0, []
        for g, w in spec["genres"].items():
            if g in genres:
                score += w
                ev.append(labels.GENRE_DISPLAY.get(g, g))
        for word in spec["keywords"]:
            if word in kw:
                score += 1.0
                ev.append(word)
            elif f" {word} " in text or f" {word}." in text or f" {word}," in text:
                score += 0.5
                ev.append(word)
        if key == "nostalgic" and year and year < 1995:
            score += 1.0 + (0.5 if year < 1980 else 0)
            ev.append(f"classic ({year})")
        raw[key] = score
        evidence[key] = ev[:5]
    return raw, evidence


def add_emotions(df):
    raws, evs = zip(*df.apply(emotion_profile, axis=1))
    raw_df = pd.DataFrame(list(raws))
    # absolute strength: raw / (95th percentile of that emotion), capped at 1
    absolute = pd.DataFrame({k: (raw_df[k] / max(raw_df[k].quantile(0.95), 1e-9)).clip(0, 1)
                             for k in labels.EMOTION_KEYS})
    # relative strength: how dominant the emotion is inside this movie
    relative = absolute.div(absolute.max(axis=1).replace(0, 1), axis=0)
    for key in labels.EMOTION_KEYS:
        df[f"emo_{key}"] = (0.7 * absolute[key] + 0.3 * relative[key]).round(4).values
    emo_cols = [f"emo_{k}" for k in labels.EMOTION_KEYS]

    def top3(r):
        scores = sorted(((r[f"emo_{k}"], k) for k in labels.EMOTION_KEYS), reverse=True)
        return [k for s, k in scores[:3] if s >= 0.45]

    df["top_emotions"] = df[emo_cols + []].apply(top3, axis=1)
    df["emotion_evidence"] = [json.dumps(e) for e in evs]
    return df


# ---------------------------------------------------------------------------
# 6. content level
# ---------------------------------------------------------------------------
def add_levels(df, cache):
    certs, countries, levels, sources, estimates = [], [], [], [], []
    for _, r in df.iterrows():
        est = labels.estimate_level(r["genres"], r["keywords"])
        rec = cache.get(int(r["id"]), {})
        cert, country = pick_certificate(rec.get("certs", {}), r["language"])
        lvl = labels.cert_to_level(cert)
        certs.append(cert)
        countries.append(country)
        estimates.append(est)
        if lvl is None:
            levels.append(est)
            sources.append("estimated")
        else:
            levels.append(lvl)
            sources.append("official")
    df["certification"] = certs
    df["cert_country"] = countries
    df["content_level"] = levels
    df["level_source"] = sources
    df["estimated_level"] = estimates      # kept so we can measure the rule's accuracy
    return df


def add_media(df, cache):
    posters, backdrops, trailers = [], [], []
    for mid in df["id"]:
        rec = cache.get(int(mid), {})
        posters.append(IMG_BASE + "w500" + rec["poster_path"] if rec.get("poster_path") else "")
        backdrops.append(IMG_BASE + "w1280" + rec["backdrop_path"] if rec.get("backdrop_path") else "")
        trailers.append(rec.get("trailer_key", "") or "")
    df["poster_url"] = posters
    df["backdrop_url"] = backdrops
    df["trailer_key"] = trailers
    return df


# ---------------------------------------------------------------------------
def main():
    print("\n=== RAGS CineMind dataset builder ===")
    for path in (MOVIES_FILE, CREDITS_FILE):
        if not os.path.exists(path):
            sys.exit(f"Missing {path}\nCopy the TMDB 5000 CSV files into data/raw/ first.")

    df = load_base()
    print(f"TMDB 5000 movies joined with credits : {len(df)}")

    cache = load_cache()
    print(f"Enrichment cache records             : {len(cache)}"
          + ("" if cache else "  (run scripts/enrich_tmdb.py for posters/trailers)"))
    df, n_extra = add_cache_movies(df, cache)
    if n_extra:
        print(f"Extra movies added from cache        : {n_extra}")

    # ---- clean
    before = len(df)
    df = df[df["overview"].str.strip().str.len() > 0]
    df = df[df["genres"].apply(len) > 0]
    df = df[df["vote_count"].fillna(0) >= 5]
    df = df.drop_duplicates(subset="id").reset_index(drop=True)
    print(f"Removed (no overview / genre / <5 votes): {before - len(df)}")

    df["year"] = pd.to_datetime(df["release_date"], errors="coerce").dt.year
    df["year"] = df["year"].fillna(0).astype(int)
    df["runtime"] = df["runtime"].fillna(0).astype(int)
    df["rating"] = df["rating"].fillna(0).round(1)
    df["vote_count"] = df["vote_count"].fillna(0).astype(int)
    df["popularity"] = df["popularity"].fillna(0).round(3)

    df["quality"], C, m = quality_scores(df)
    df = add_emotions(df)
    df = add_levels(df, cache)
    df = add_media(df, cache)

    # lists -> pipe-separated text for CSV
    for col in ("genres", "keywords", "cast", "top_emotions"):
        df[col] = df[col].apply(lambda xs: "|".join(xs))

    cols = ["id", "title", "year", "release_date", "overview", "tagline", "genres",
            "keywords", "language", "runtime", "rating", "vote_count", "popularity",
            "quality", "cast", "director", "poster_url", "backdrop_url", "trailer_key",
            "certification", "cert_country", "content_level", "level_source",
            "estimated_level", "top_emotions", "emotion_evidence"] + \
           [f"emo_{k}" for k in labels.EMOTION_KEYS]
    df = df[cols]
    os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)
    df.to_csv(OUTPUT_FILE, index=False)

    # ---- report numbers (real counts, for the project report)
    report = {
        "total_movies": int(len(df)),
        "languages": df["language"].value_counts().head(15).to_dict(),
        "with_poster": int((df["poster_url"] != "").sum()),
        "with_trailer": int((df["trailer_key"] != "").sum()),
        "official_certificate": int((df["level_source"] == "official").sum()),
        "content_levels": {labels.LEVEL_NAMES[int(k)]: int(v)
                           for k, v in df["content_level"].value_counts().sort_index().items()},
        "weighted_rating_C_mean": round(C, 3),
        "weighted_rating_m_min_votes": round(m, 1),
        "movies_per_top_emotion": {k: int(df["top_emotions"].str.contains(k).sum())
                                   for k in labels.EMOTION_KEYS},
    }
    with open(REPORT_FILE, "w") as f:
        json.dump(report, f, indent=2)

    print(f"\nSaved {len(df)} movies -> {OUTPUT_FILE}")
    print(f"Posters: {report['with_poster']}  Trailers: {report['with_trailer']}  "
          f"Official certificates: {report['official_certificate']}")
    print(f"Report -> {REPORT_FILE}\n")


if __name__ == "__main__":
    main()
