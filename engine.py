"""
engine.py  -  the RAGS CineMind hybrid recommender
==================================================

STEP 1  HARD FILTERS  (a movie that fails any of these is never shown)
        * content level <= the audience's maximum   (never relaxed)
        * language, runtime, release era            (relaxed only if <limit results)
        * at least 20 votes                          (relaxed only if needed)
        * not disliked / not already watched (optional)

STEP 2  SCORE EACH REMAINING MOVIE  (every component is between 0 and 1)
        genre     share of the selected genres the movie has
        emotion   the movie's score for the selected feeling(s)  (labels.py)
        text      TF-IDF similarity to what the user typed (optional)
        similar   TF-IDF similarity to a chosen "more like this" movie
        personal  0.5 x content similarity to the user's liked movies
                + 0.5 x collaborative-filtering score       (logged-in users)
        quality   IMDb-style weighted rating

        final = sum(weight x component) over the components that are ACTIVE
                (weights of inactive components are shared out, so the final
                 score is always 0..1 and "match %" = final x 100)

STEP 3  DIVERSITY RE-RANKING (Maximal Marginal Relevance)
        pick the best movie, then repeatedly pick the movie that balances a
        high score against being too similar to ones already picked.

STEP 4  EXPLAIN  every pick gets reasons + a per-component breakdown.
"""

import random

import numpy as np

from . import labels

DEFAULT_WEIGHTS = {
    "genre": 0.25,
    "emotion": 0.25,
    "text": 0.15,
    "similar": 0.20,
    "personal": 0.20,
    "quality": 0.15,
    "shift": 0.15,
}
COMPONENT_LABELS = {
    "genre": "Genre match", "emotion": "Mood match", "text": "Matches your description",
    "similar": "Similar to your pick", "personal": "Your taste", "quality": "Critic & audience rating",
    "shift": "Gentle mood lift",
}
ERAS = {
    "any": (0, 9999), "classic": (0, 1979), "80s90s": (1980, 1999),
    "2000s": (2000, 2009), "2010s": (2010, 9999),
}
MIN_VOTES = 20
MMR_LAMBDA = 0.75


class Recommender:
    def __init__(self, catalog, cf_model, weights=None, cf_share=0.5):
        self.cat = catalog
        self.cf = cf_model
        self.weights = dict(DEFAULT_WEIGHTS, **(weights or {}))
        self.cf_share = cf_share          # CF vs content inside "personal" (tuned by evaluate.py)
        df = catalog.df
        self._level = df["content_level"].to_numpy()
        self._lang = df["language"].to_numpy()
        self._runtime = df["runtime"].to_numpy()
        self._year = df["year"].to_numpy()
        self._votes = df["vote_count"].to_numpy()
        self._quality = df["quality"].to_numpy()
        self._horror = np.array(["Horror" in g for g in catalog.genre_sets])
        self._platforms = [set() for _ in range(len(df))]     # filled by set_watch()

    def set_watch(self, watch):
        """Index which streaming platforms (India) carry each movie."""
        self._platforms = [watch.platforms_of(int(mid)) if watch else set() for mid in self.cat.ids]

    def platform_counts(self):
        counts = {}
        for ps in self._platforms:
            for name in ps:
                counts[name] = counts.get(name, 0) + 1
        return sorted(counts.items(), key=lambda x: -x[1])

    # ------------------------------------------------------------------
    # preferences in -> clean preferences out
    # ------------------------------------------------------------------
    @staticmethod
    def parse_prefs(raw):
        raw = raw or {}

        def as_list(v):
            if v is None or v == "":
                return []
            return v if isinstance(v, list) else [v]

        audience = labels.normalize_audience(raw.get("audience", "")) or "everyone"
        emotions = [e for e in (labels.normalize_emotion(x) for x in as_list(raw.get("emotions") or raw.get("emotion"))) if e][:2]
        genres = [g for g in (labels.normalize_genre(x) for x in as_list(raw.get("genres") or raw.get("genre"))) if g][:3]
        languages = [str(x).lower() for x in as_list(raw.get("languages") or raw.get("language")) if str(x).lower() in labels.LANGUAGES]
        try:
            max_runtime = int(raw.get("max_runtime") or 0)
        except (TypeError, ValueError):
            max_runtime = 0
        era = raw.get("era") if isinstance(raw.get("era"), str) and raw.get("era") in ERAS else "any"
        try:
            seed = int(raw["seed_movie_id"]) if raw.get("seed_movie_id") else None
        except (TypeError, ValueError):
            seed = None
        try:
            limit = max(1, min(int(raw.get("limit", 12)), 30))
        except (TypeError, ValueError):
            limit = 12
        # Watch Together: up to 4 people, each with their own audience and feeling
        group = []
        for i, person in enumerate(as_list(raw.get("group"))[:4]):
            if not isinstance(person, dict):
                continue
            g_aud = labels.normalize_audience(person.get("audience", "")) or "adults"
            g_emo = labels.normalize_emotion(person.get("emotion", ""))
            name = str(person.get("name") or f"Person {i + 1}").strip()[:20] or f"Person {i + 1}"
            group.append({"name": name, "audience": g_aud, "emotion": g_emo})
        if group:
            # the strictest audience in the group decides what is suitable
            audience = min((m["audience"] for m in group), key=lambda a: labels.AUDIENCES[a][1])
            emotions = list(dict.fromkeys(m["emotion"] for m in group if m["emotion"]))
        platforms = [str(x)[:40] for x in as_list(raw.get("platforms"))][:12]
        return {
            "group": group, "platforms": platforms,
            "current_mood": labels.normalize_current_mood(raw.get("current_mood", "")),
            "audience": audience, "emotions": emotions, "genres": genres,
            "languages": languages, "max_runtime": max_runtime, "era": era,
            "query": str(raw.get("query", ""))[:200].strip(),
            "seed_movie_id": seed, "exclude_watched": bool(raw.get("exclude_watched", True)),
            "exclude_ids": [int(x) for x in as_list(raw.get("exclude_ids"))[:200] if str(x).isdigit()],
            "limit": limit, "diversify": bool(raw.get("diversify", True)),
        }

    # ------------------------------------------------------------------
    def _filter(self, p, user, relax=()):
        max_level = labels.AUDIENCES[p["audience"]][1]
        mask = self._level <= max_level
        if p["languages"] and "language" not in relax:
            mask &= np.isin(self._lang, p["languages"])
        if p["max_runtime"] and "runtime" not in relax:
            mask &= (self._runtime > 0) & (self._runtime <= p["max_runtime"])
        if p["era"] != "any" and "era" not in relax:
            lo, hi = ERAS[p["era"]]
            mask &= (self._year >= lo) & (self._year <= hi)
        if "votes" not in relax:
            mask &= self._votes >= MIN_VOTES
        if p["platforms"] and "platforms" not in relax:
            wanted = set(p["platforms"])
            mask &= np.array([bool(ps & wanted) for ps in self._platforms])
        excluded = set(user.get("disliked", [])) | set(p.get("exclude_ids", []))
        if p["exclude_watched"]:
            excluded |= set(user.get("watched", [])) | set(user.get("liked", []))
        if p["seed_movie_id"]:
            excluded.add(p["seed_movie_id"])
        for r in self.cat.rows_for(excluded):
            mask[r] = False
        return np.flatnonzero(mask)

    # ------------------------------------------------------------------
    def recommend(self, raw_prefs, user=None):
        p = self.parse_prefs(raw_prefs)
        user = user or {}
        liked = [m for m in user.get("liked", []) if self.cat.has(m)]

        # STEP 1: filters, relaxing soft ones step by step if too few results
        relaxed = []
        rows = self._filter(p, user)
        for step in ("votes", "era", "runtime", "language", "platforms"):
            if len(rows) >= p["limit"]:
                break
            relaxed.append(step)
            rows = self._filter(p, user, relax=relaxed)
        if len(rows) == 0:
            return {"prefs": p, "results": [], "relaxed": relaxed, "weights": {}}

        # STEP 2: components
        comp = {}
        if p["genres"]:
            sel = set(p["genres"])
            comp["genre"] = np.array([len(self.cat.genre_sets[r] & sel) / len(sel) for r in rows])
        group_fit = None
        members = [m for m in p["group"] if m["emotion"]]
        if members:
            # each person's fit = the movie's score for that person's feeling.
            # group score = 0.6 x average + 0.4 x lowest, so nobody is left out
            # (a mix of the "average" and "least misery" group strategies)
            cols = [labels.EMOTION_KEYS.index(m["emotion"]) for m in members]
            group_fit = self.cat.emotion_matrix[rows][:, cols]
            comp["emotion"] = 0.6 * group_fit.mean(axis=1) + 0.4 * group_fit.min(axis=1)
        elif p["emotions"]:
            cols = [labels.EMOTION_KEYS.index(e) for e in p["emotions"]]
            comp["emotion"] = self.cat.emotion_matrix[rows][:, cols].mean(axis=1)
        if p["current_mood"]:
            spec = labels.CURRENT_MOODS[p["current_mood"]]
            emo = self.cat.emotion_matrix[rows]
            bridge = emo[:, [labels.EMOTION_KEYS.index(e) for e in spec["bridge"]]].mean(axis=1)
            avoid = emo[:, [labels.EMOTION_KEYS.index(e) for e in spec["avoid"]]].max(axis=1)
            comp["shift"] = 0.6 * bridge + 0.4 * (1 - avoid)
        if p["query"]:
            s = self.cat.query_similarity(p["query"], rows)
            if s is not None and s.max() > 0:
                comp["text"] = s / s.max()
        if p["seed_movie_id"] and self.cat.has(p["seed_movie_id"]):
            s = self.cat.content_similarity(self.cat.rows_for([p["seed_movie_id"]]), rows)
            cfs, _ = self.cf.scores([p["seed_movie_id"]], self.cat.ids[rows].tolist())
            s = s / s.max() if s.max() > 0 else s
            if cfs is not None and cfs.max() > 0:
                s = 0.6 * s + 0.4 * (cfs / cfs.max())
            comp["similar"] = s
        because = {}
        if liked:
            content = self.cat.content_similarity(self.cat.rows_for(liked), rows)
            content = content / content.max() if content.max() > 0 else content
            cfs, because = self.cf.scores(liked, self.cat.ids[rows].tolist())
            if cfs is not None and cfs.max() > 0:
                comp["personal"] = (1 - self.cf_share) * content + self.cf_share * (cfs / cfs.max())
            else:
                comp["personal"] = content
        comp["quality"] = self._quality[rows]

        active = {k: self.weights[k] for k in comp}
        total_w = sum(active.values())
        active = {k: w / total_w for k, w in active.items()}
        final = sum(active[k] * comp[k] for k in comp)
        if p["audience"] == "seniors":                 # gentler picks first
            final = final * np.where(self._horror[rows], 0.85, 1.0)

        # STEP 3: diversity re-ranking
        order = np.argsort(-final)[: max(60, p["limit"] * 4)]
        if p["diversify"] and len(order) > p["limit"]:
            chosen = self._mmr(rows[order], final[order], p["limit"])
            picked = [order[i] for i in chosen]
        else:
            picked = list(order[: p["limit"]])

        # STEP 4: explanations
        results = []
        for k in picked:
            row = rows[k]
            breakdown = {c: {"label": COMPONENT_LABELS[c], "value": round(float(comp[c][k]), 3),
                             "weight": round(active[c], 3)} for c in comp}
            movie = self.cat.movie_dict(row)
            movie["match"] = int(round(float(final[k]) * 100))
            movie["breakdown"] = breakdown
            movie["reasons"] = self._reasons(row, p, comp, k, because, liked)
            if group_fit is not None:
                movie["group_fit"] = [{"name": m["name"], "emotion": labels.EMOTIONS[m["emotion"]]["display"],
                                       "colour": labels.EMOTIONS[m["emotion"]]["colour"],
                                       "value": int(round(float(group_fit[k][j]) * 100))}
                                      for j, m in enumerate(members)]
            streams = sorted(self._platforms[row])
            wanted = set(p["platforms"])
            movie["streaming"] = ([x for x in streams if x in wanted] + [x for x in streams if x not in wanted])[:3]
            results.append(movie)
        return {"prefs": p, "results": results, "relaxed": relaxed,
                "weights": {c: round(w, 3) for c, w in active.items()},
                "candidates": int(len(rows))}

    # ------------------------------------------------------------------
    def _mmr(self, rows, scores, k):
        sim = self.cat.pairwise(list(rows))
        chosen = [int(np.argmax(scores))]
        while len(chosen) < k:
            max_sim = sim[:, chosen].max(axis=1)
            mmr = MMR_LAMBDA * scores - (1 - MMR_LAMBDA) * max_sim
            mmr[chosen] = -np.inf
            chosen.append(int(np.argmax(mmr)))
        return chosen

    def _reasons(self, row, p, comp, k, because, liked):
        r = self.cat.df.iloc[row]
        out = []
        if "genre" in comp and comp["genre"][k] > 0:
            hit = [labels.GENRE_DISPLAY.get(g, g) for g in p["genres"] if g in self.cat.genre_sets[row]]
            out.append(f"{', '.join(hit)} - the genre you picked")
        if "emotion" in comp:
            import json
            ev = json.loads(r["emotion_evidence"] or "{}")
            for e in p["emotions"]:
                strength = r[f"emo_{e}"]
                if strength >= 0.35:
                    words = ", ".join(ev.get(e, [])[:3])
                    tag = "Strongly" if strength >= 0.7 else "Fits"
                    out.append(f"{tag} {labels.EMOTIONS[e]['display'].lower()}"
                               + (f" (signals: {words})" if words else ""))
        if p["group"] and "emotion" in comp and comp["emotion"][k] >= 0.35:
            out.insert(0, "Works for the whole group")
        if "shift" in comp and comp["shift"][k] >= 0.5:
            out.append(f"Gentle lift for when you feel {labels.CURRENT_MOODS[p['current_mood']]['display'].lower()}")
        if p["platforms"] and self._platforms[row] & set(p["platforms"]):
            out.append("On " + ", ".join(sorted(self._platforms[row] & set(p["platforms"]))[:2]) + " - your platforms")
        if "text" in comp and comp["text"][k] >= 0.4:
            out.append("Close to what you described")
        if "similar" in comp and comp["similar"][k] >= 0.4:
            seed = self.cat.df.iloc[self.cat.pos[p["seed_movie_id"]]]["title"]
            out.append(f"Similar to {seed}")
        if "personal" in comp and comp["personal"][k] >= 0.4:
            src = because.get(int(r["id"]))
            if src and self.cat.has(src):
                out.append(f"Because you liked {self.cat.df.iloc[self.cat.pos[src]]['title']}")
            else:
                out.append("Matches the movies you liked")
        if r["rating"] >= 7.5 and r["vote_count"] >= 500:
            out.append(f"Highly rated: {r['rating']}/10 from {r['vote_count']:,} votes")
        level = int(r["content_level"])
        aud = labels.AUDIENCES[p["audience"]][0]
        if r["level_source"] == "official":
            out.append(f"Rated {r['certification']} - suitable for {aud}")
        else:
            out.append(f"Estimated {labels.LEVEL_NAMES[level].lower()} - suitable for {aud}")
        return out

    # ------------------------------------------------------------------
    # extra discovery features
    # ------------------------------------------------------------------
    def similar_to(self, movie_id, max_level=3, limit=10, user=None):
        return self.recommend({"seed_movie_id": movie_id, "audience": _audience_for(max_level),
                               "limit": limit, "exclude_watched": False}, user)["results"]

    def emotion_posters(self, per_emotion=8):
        """A few well-known posters for each feeling (home page hover collage)."""
        df = self.cat.df
        ok = (df["poster_url"] != "") & (df["vote_count"] >= 800) & (df["content_level"] <= 2)
        out = {}
        for i, key in enumerate(labels.EMOTION_KEYS):
            score = self.cat.emotion_matrix[:, i] * (0.5 + df["quality"].to_numpy())
            rows = [r for r in np.argsort(-score) if ok.iat[r]][:per_emotion]
            out[key] = [self.cat.movie_dict(r)["poster_url"] for r in rows]
        return out

    def trending(self, max_level=3, limit=12, language=None):
        mask = (self._level <= max_level) & (self._votes >= 200)
        if language:
            mask &= self._lang == language
        rows = np.flatnonzero(mask)
        if not len(rows):
            return []                                    # e.g. a language with no popular films
        pop = self.cat.df["popularity"].to_numpy()[rows]
        score = 0.6 * (pop / pop.max()) + 0.4 * self._quality[rows]
        return [self.cat.movie_dict(r) for r in rows[np.argsort(-score)[:limit]]]

    def surprise(self, raw_prefs, user=None):
        res = self.recommend(dict(raw_prefs or {}, limit=10, diversify=True), user)
        pool = res["results"]
        return random.choice(pool) if pool else None


def _audience_for(max_level):
    for key, (_, lvl, _) in labels.AUDIENCES.items():
        if lvl == max_level:
            return key
    return "adults"
