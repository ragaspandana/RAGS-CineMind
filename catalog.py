"""
catalog.py  -  loads data/movies.csv ONCE and prepares the content model
=======================================================================

The prototype rebuilt TF-IDF on every request. Here we build it once when
the server starts, so each recommendation only does fast matrix maths.

Content model (content-based filtering):
  text of a movie = overview + tagline + genres x2 + keywords x2 + director + cast
  -> TF-IDF vector (unigrams + bigrams, English stop words removed)
  similarity between two movies = cosine of their vectors
"""

import json

import numpy as np
import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import linear_kernel

from . import labels
from .images import local_url

LIST_COLS = ("genres", "keywords", "cast", "top_emotions")


def _tokens(items):
    """'Science Fiction' -> 'science_fiction' so multi-word tags stay one token."""
    return " ".join(i.lower().replace(" ", "_").replace("-", "_") for i in items)


class Catalog:
    def __init__(self, csv_path):
        df = pd.read_csv(csv_path, keep_default_na=False)
        for col in LIST_COLS:
            df[col] = df[col].apply(lambda s: [x for x in str(s).split("|") if x])
        for col in ("year", "runtime", "vote_count", "content_level", "estimated_level"):
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0).astype(int)
        for col in ["rating", "popularity", "quality"] + [f"emo_{k}" for k in labels.EMOTION_KEYS]:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0)
        df["id"] = df["id"].astype(int)
        df = df.reset_index(drop=True)
        self.df = df
        self.ids = df["id"].to_numpy()
        self.pos = {mid: i for i, mid in enumerate(self.ids)}     # movie id -> row number
        self.emotion_matrix = df[[f"emo_{k}" for k in labels.EMOTION_KEYS]].to_numpy()

        docs = (df["overview"] + " " + df["tagline"] + " "
                + df["genres"].apply(_tokens).str.repeat(2) + " "
                + df["keywords"].apply(_tokens).str.repeat(2) + " "
                + df["director"].str.replace(" ", "_") + " "
                + df["cast"].apply(lambda c: _tokens(c[:3])))
        self.vectorizer = TfidfVectorizer(stop_words="english", ngram_range=(1, 2),
                                          min_df=2, max_df=0.6, sublinear_tf=True)
        self.tfidf = self.vectorizer.fit_transform(docs)        # rows are L2-normalised

        self.genre_sets = df["genres"].apply(set).tolist()
        self._title_lower = df["title"].str.lower().tolist()

    # ------------------------------------------------------------------
    def __len__(self):
        return len(self.df)

    def has(self, movie_id):
        return int(movie_id) in self.pos

    def rows_for(self, movie_ids):
        return [self.pos[int(m)] for m in movie_ids if int(m) in self.pos]

    def content_similarity(self, row_indices, candidate_rows=None):
        """Mean cosine similarity of candidates to a set of movies (a 'taste centroid')."""
        if not row_indices:
            return None
        centroid = np.asarray(self.tfidf[row_indices].mean(axis=0))
        target = self.tfidf if candidate_rows is None else self.tfidf[candidate_rows]
        return np.asarray(target @ centroid.T).ravel()

    def query_similarity(self, text, candidate_rows=None):
        vec = self.vectorizer.transform([text])
        if vec.nnz == 0:
            return None
        target = self.tfidf if candidate_rows is None else self.tfidf[candidate_rows]
        return linear_kernel(vec, target).ravel()

    def pairwise(self, rows):
        return linear_kernel(self.tfidf[rows], self.tfidf[rows])

    # ------------------------------------------------------------------
    def search(self, text, limit=12, max_level=3):
        """Title search: exact substring first, then description/keyword match."""
        q = str(text).lower().strip()
        if not q:
            return []
        allowed = self.df["content_level"].to_numpy() <= max_level
        starts = [i for i, t in enumerate(self._title_lower) if t.startswith(q) and allowed[i]]
        inside = [i for i, t in enumerate(self._title_lower)
                  if q in t and not t.startswith(q) and allowed[i]]
        hits = starts + inside
        hits.sort(key=lambda i: -self.df.at[i, "vote_count"])
        if len(hits) < limit:
            sims = self.query_similarity(q)
            if sims is not None:
                order = np.argsort(-sims)
                for i in order[: limit * 3]:
                    if sims[i] <= 0.05:
                        break
                    if allowed[i] and i not in hits:
                        hits.append(int(i))
        return hits[:limit]

    # ------------------------------------------------------------------
    def movie_dict(self, row, full=False):
        r = self.df.iloc[row]
        d = {
            "id": int(r["id"]), "title": r["title"], "year": int(r["year"]),
            "genres": r["genres"], "language": r["language"],
            "language_name": labels.LANGUAGES.get(r["language"], r["language"].upper()),
            "runtime": int(r["runtime"]), "rating": float(r["rating"]),
            "vote_count": int(r["vote_count"]),
            "poster_url": local_url(r["poster_url"], "w342"),
            "backdrop_url": local_url(r["backdrop_url"], "w1280"),
            "trailer_key": r["trailer_key"],
            "certification": r["certification"],
            "content_level": int(r["content_level"]),
            "content_level_name": labels.LEVEL_NAMES[int(r["content_level"])],
            "level_source": r["level_source"],
            "top_emotions": [{"key": e, "label": labels.EMOTIONS[e]["display"],
                              "colour": labels.EMOTIONS[e]["colour"]} for e in r["top_emotions"]],
            "overview": r["overview"],
        }
        if full:
            d.update({
                "tagline": r["tagline"], "release_date": r["release_date"],
                "director": r["director"], "cast": r["cast"], "keywords": r["keywords"][:12],
                "emotion_profile": {k: round(float(r[f"emo_{k}"]), 3) for k in labels.EMOTION_KEYS},
                "emotion_evidence": json.loads(r["emotion_evidence"] or "{}"),
            })
        return d
