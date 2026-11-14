"""
genie.py  -  RAGS Genie, the CineMind chat assistant
====================================================

How one chat turn works
  0. CHAT        greetings, jokes, "how are you", a bad day, trivia...
                 Built-in: smalltalk.py (always works, no internet).
                 With GEMINI_API_KEY: Google Gemini holds the conversation
                 (it remembers the last few messages) and hands real movie
                 requests back to step 4 - it never invents a movie list.
  1. UNDERSTAND  the message with nlu.parse()  (built-in, always available).
                 Optional: if GEMINI_API_KEY is set and the built-in parser
                 understood nothing, Google Gemini turns the sentence into the
                 same preference fields (JSON). Gemini never chooses movies.
  2. REMEMBER    the conversation: preferences so far, movies already shown.
                 The browser sends this "state" back with every message, so
                 the server stays simple (no chat storage needed).
  3. DECIDE      what to do: answer a question (where to watch, about a film,
                 why it was picked), ask ONE follow-up question, or recommend.
  4. RECOMMEND   always with CineMind's own hybrid engine (engine.py), so every
                 title is real, suitable for the audience and explainable.
  5. REPLY       with a friendly message (templates; optionally reworded by
                 Gemini, which may only mention the titles we give it).

If Gemini is not configured, slow, or offline, step 1 and 5 simply use the
built-in versions - the Genie never stops working.
"""

import json
import os
import random
import re
import urllib.error
import urllib.request

from . import labels, nlu, smalltalk

ORDINALS = {"first": 0, "1st": 0, "second": 1, "2nd": 1, "third": 2, "3rd": 2, "fourth": 3, "4th": 3,
            "fifth": 4, "5th": 4, "sixth": 5, "6th": 5, "last": -1}
FEELING_CHIPS = ["Happy", "Funny", "Excited", "Inspiring", "Romantic", "Scary", "Relaxed", "Suspenseful"]
AUDIENCE_CHIPS = ["Just me", "With family", "With kids", "With friends"]
START_CHIPS = ["Something funny for my family", "I'm feeling low, cheer me up",
               "Movies like Interstellar", "A Telugu thriller under 2 hours", "Tell me a joke"]
SHOW = 6


def pick(*options):
    return random.choice(options)


class Genie:
    def __init__(self, engine, watch=None, gemini_key=None):
        self.engine = engine
        self.cat = engine.cat
        self.watch = watch
        self.gemini_key = (gemini_key if gemini_key is not None else os.environ.get("GEMINI_API_KEY", "")).strip()
        self.gemini_model = os.environ.get("GEMINI_MODEL", "gemini-3.5-flash-lite").strip()
        self._titles = None

    def title_row(self, title):
        """Exact (case-insensitive) title -> catalogue row, preferring the best-known film."""
        if self._titles is None:
            df = self.cat.df
            order = df["vote_count"].to_numpy().argsort()          # most-voted last, so it wins
            self._titles = {str(df.iloc[i]["title"]).lower(): int(i) for i in order}
        return self._titles.get(str(title).strip().lower())

    @property
    def brain(self):
        return "gemini" if self.gemini_key else "built-in"

    # ------------------------------------------------------------------
    def reply(self, message, state=None, user=None, default_audience=None):
        out = self._reply(message, state, user, default_audience)
        said = str(message or "").strip()[:300]
        if said:                                   # short memory of the chat (for Gemini)
            hist = out["state"].setdefault("history", [])
            hist.append([said, re.sub(r"\s+", " ", out["reply"])[:300]])
            out["state"]["history"] = hist[-6:]
        return out

    def _reply(self, message, state=None, user=None, default_audience=None):
        state = self._clean_state(state)
        text = str(message or "").strip()[:300]
        if not text:
            return self._out(state, pick("Hi! I'm **RAGS Genie** 🧞 Ask me for a movie in your own words, or just chat. "
                                         "I know jokes and movie facts too!",
                                         "Hello! I'm **RAGS Genie** 🧞 Tell me how your day was, or how you'd like to feel, "
                                         "and I'll grant you the perfect movie."),
                             suggestions=START_CHIPS)
        low = text.lower()

        # quick answers to the Genie's own follow-up chips
        chip_map = {"just me": {"audience": "adults"}, "with family": {"audience": "family"},
                    "with kids": {"audience": "kids"}, "with friends": {"audience": "everyone"}}
        if low in chip_map:
            state["prefs"].update(chip_map[low])
            state["asked_audience"] = True
            return self._recommend(state, user, said=text)

        if re.search(r"^(start over|reset|new search|forget (it|that|everything)|clear)\b", low):
            state = self._clean_state(None)
            return self._out(state, "Fresh start ✨ What are you in the mood for?", suggestions=START_CHIPS)

        if re.search(r"\b(movies|films|more|something) like (this|that|it)\b", low) and state.get("last"):
            state["prefs"].update({"seed_movie_id": state["last"][0]})
            for k in ("emotions", "genres", "query", "current_mood"):
                state["prefs"].pop(k, None)
            state["shown"] = []
            return self._recommend(state, user, said=text, default_audience=default_audience)
        parsed = nlu.parse(text, self.cat)
        brain_used = "built-in"

        # ---- 0. chit-chat ----------------------------------------------------
        plain = low.strip(" !.?")
        if state.get("offer") and plain in smalltalk.ACCEPTS:       # "Yes, cheer me up"
            state["prefs"].update({"current_mood": state.pop("offer")})
            for k in ("emotions", "genres", "seed_movie_id", "query"):
                state["prefs"].pop(k, None)
            state["shown"] = []
            return self._recommend(state, user, said=text, default_audience=default_audience)
        real_wish = any(parsed["prefs"].get(k) for k in ("emotions", "genres", "seed_movie_id", "languages", "platforms"))
        weak = not real_wish and parsed["intent"] in ("recommend", "greet", "thanks", "help") and not parsed["movie_id"]
        talk = smalltalk.respond(text, state, self.cat)
        last_reply = state["history"][-1][1] if state.get("history") else ""
        for _ in range(4):                                         # don't repeat the same joke / fact twice in a row
            if not talk or re.sub(r"\s+", " ", talk["reply"])[:300] != last_reply:
                break
            talk = smalltalk.respond(text, state, self.cat)
        asks_for_movie = re.search(r"\b(movies?|films?|watch|show me|suggest|recommend|cheer me up|comedy|thriller)\b", low)
        if talk and talk.get("kind") in ("bad_day", "good_day") and (asks_for_movie or any(
                parsed["prefs"].get(k) for k in ("genres", "seed_movie_id", "languages", "platforms"))):
            talk = None                                            # "bad day, show me a comedy" = a movie request
        if talk is None and weak and parsed["intent"] == "recommend" and not parsed["prefs"].get("current_mood"):
            talk = smalltalk.off_topic(text)
        if (talk or (weak and parsed["intent"] == "recommend")) and self.gemini_key:
            chat = self._gemini_chat(text, state)
            if chat:
                if chat["action"] == "recommend" and chat["prefs"]:
                    for k in ("emotions", "genres", "seed_movie_id", "query", "current_mood"):
                        state["prefs"].pop(k, None)
                    state["prefs"].update(chat["prefs"])
                    state.pop("offer", None)
                    state["shown"] = []
                    return self._recommend(state, user, said=text, chips=self._chips_for(chat["prefs"]),
                                           brain_used="gemini", default_audience=default_audience)
                return self._out(state, chat["reply"], results=chat["movies"], brain_used="gemini",
                                 suggestions=talk["suggestions"] if talk else START_CHIPS[:3])
        if talk:
            if talk.get("kind") not in ("bad_day",):
                state.pop("offer", None)
            movies = [self.cat.movie_dict(r) for r in talk.get("movie_rows", [])]
            if movies:
                state["last"] = [m["id"] for m in movies]
            return self._out(state, talk["reply"], results=movies, suggestions=talk["suggestions"])
        state.pop("offer", None)
        meaningful = parsed["prefs"] or parsed["intent"] != "recommend" or parsed["movie_id"]
        if not meaningful and self.gemini_key and len(text.split()) >= 3:
            extra = self._gemini_parse(text)
            if extra:
                parsed["prefs"], brain_used = extra, "gemini"
                parsed["understood"] = self._chips_for(extra)

        intent = parsed["intent"]
        movie_id = parsed["movie_id"] or self._movie_from_reference(low, state)
        if intent == "greet":
            return self._out(state, pick("Hi! I'm RAGS Genie 🧞 Tell me who's watching and how you want to feel, and I'll grant you the perfect movie.",
                                         "Hello! I'm RAGS Genie 🧞 Your wish is my command - what kind of movie today?"),
                             suggestions=START_CHIPS)
        if intent == "thanks":
            return self._out(state, pick("Enjoy the movie! 🍿 Ask me anytime.", "Happy watching! 🎬 I'm here if you want more."),
                             suggestions=["Show me more", "Something different"])
        if intent == "help":
            return self._out(state, "I can find movies by mood, audience, language, length and genre, suggest films like one you love, "
                                    "tell you where to watch a movie in India, and explain why I picked it. Try one of these:",
                             suggestions=START_CHIPS)
        if intent in ("where", "about", "why"):
            if not movie_id:
                return self._out(state, "Which movie do you mean? Tell me the title, or say \"the first one\" after I show results.")
            return {"where": self._where, "about": self._about, "why": self._why}[intent](movie_id, state, user)
        if intent == "more":
            return self._recommend(state, user, said=text, more=True)

        # refinements that only make sense with a previous request
        p = state["prefs"]
        if re.search(r"\b(shorter|less long)\b", low):
            p["max_runtime"] = max(80, (p.get("max_runtime") or 140) - 20)
        if re.search(r"\b(longer|any length|no time limit)\b", low):
            p.pop("max_runtime", None)
        if re.search(r"\b(newer|more recent|latest)\b", low):
            p["era"] = "2010s"
        if re.search(r"\b(older|classics?)\b", low) and "era" not in parsed["prefs"]:
            p["era"] = "80s90s"
        if re.search(r"\b(any language|all languages)\b", low):
            p.pop("languages", None)

        new = parsed["prefs"]
        if new.get("emotions") or new.get("genres") or new.get("seed_movie_id") or new.get("query"):
            # a new main wish replaces the old one; audience/language/platforms are kept
            for k in ("emotions", "genres", "seed_movie_id", "query", "current_mood"):
                p.pop(k, None)
            state["shown"] = []
        p.update(new)
        if not default_audience and new.get("audience"):
            state["asked_audience"] = True
        return self._recommend(state, user, said=text, chips=parsed["understood"],
                               brain_used=brain_used, default_audience=default_audience)

    # ------------------------------------------------------------------
    def _recommend(self, state, user, said="", more=False, chips=None, brain_used="built-in", default_audience=None):
        p = state["prefs"]
        has_wish = any(p.get(k) for k in ("emotions", "genres", "seed_movie_id", "query", "current_mood"))
        if not has_wish:
            return self._out(state, pick("Sounds good! How do you want to feel?", "Got it. What kind of feeling are you after?"),
                             chips=chips, suggestions=FEELING_CHIPS)
        if not p.get("audience"):
            if default_audience:
                p["audience"] = default_audience
            elif not state.get("asked_audience"):
                state["asked_audience"] = True
                return self._out(state, pick("Great choice! Who's watching?", "Nice! Who are you watching with?"),
                                 chips=chips, suggestions=AUDIENCE_CHIPS)
            else:
                p["audience"] = "everyone"
        query = dict(p, limit=SHOW, exclude_ids=state["shown"] if more else [])
        res = self.engine.recommend(query, user or {})
        movies = res["results"]
        if not movies:
            return self._out(state, "Hmm, nothing fits all of that. Try removing the language or time limit, or pick another feeling.",
                             chips=chips, suggestions=["Any language", "Longer", "Start over"])
        state["shown"] = (state["shown"] + [m["id"] for m in movies])[-60:]
        state["last"] = [m["id"] for m in movies]
        top = movies[0]
        summary = self._summary(res["prefs"])
        if more:
            text = pick(f"Here are {len(movies)} more ✨", f"{len(movies)} more coming up 🍿", "More picks for you ✨")
        else:
            text = pick(f"Your wish is granted 🧞 {summary}.", f"Got it - {summary}. Here's what I found 🍿",
                        f"Perfect, {summary}. Take a look ✨")
        text += f" My top pick is **{top['title']}** ({top['year']}, {top['match']}% match)"
        reason = next((r for r in top.get("reasons", []) if not r.startswith(("Estimated", "Rated"))), "")
        text += f": {reason[0].lower() + reason[1:]}." if reason else "."
        if res["relaxed"]:
            names = {"votes": "lesser-known films", "era": "release year", "runtime": "length",
                     "language": "language", "platforms": "your platforms"}
            text += " (I widened " + ", ".join(names[r] for r in res["relaxed"]) + " to find enough.)"
        if self.gemini_key and brain_used != "fallback":
            better = self._gemini_reply(said, summary, movies)
            if better:
                text, brain_used = better, "gemini"
        return self._out(state, text, results=movies, chips=chips, brain_used=brain_used,
                         suggestions=["Show me more", "Shorter", "Why the first one?", "Where can I watch the first one?"])

    def _summary(self, p):
        parts = []
        if p.get("group"):
            parts.append("for the group")
        elif p.get("audience"):
            parts.append("for " + labels.AUDIENCES[p["audience"]][0].lower())
        if p.get("current_mood"):
            parts.append("a gentle lift from feeling " + labels.CURRENT_MOODS[p["current_mood"]]["display"].lower())
        if p.get("emotions"):
            parts.append(" and ".join(labels.EMOTIONS[e]["display"].lower() for e in p["emotions"]))
        if p.get("genres"):
            parts.append(", ".join(labels.GENRE_DISPLAY.get(g, g) for g in p["genres"]))
        if p.get("seed_movie_id") and self.cat.has(p["seed_movie_id"]):
            parts.append("like " + self.cat.df.iloc[self.cat.pos[p["seed_movie_id"]]]["title"])
        if p.get("languages"):
            parts.append("in " + labels.LANGUAGES.get(p["languages"][0], p["languages"][0]))
        if p.get("max_runtime"):
            parts.append(f"under {p['max_runtime']} minutes")
        if p.get("platforms"):
            parts.append("on " + ", ".join(p["platforms"]))
        return ", ".join(parts) if parts else "great picks"

    # ------------------------------------------------------------------
    def _movie_from_reference(self, low, state):
        last = state.get("last") or []
        if not last:
            return None
        for word, idx in ORDINALS.items():
            if re.search(r"\b" + word + r"\b", low):
                try:
                    return last[idx]
                except IndexError:
                    return None
        if re.search(r"\b(it|that|this|that one|this one|top pick)\b", low):
            return last[0]
        return None

    def _card(self, movie_id):
        return self.cat.movie_dict(self.cat.pos[movie_id]) if self.cat.has(movie_id) else None

    def _where(self, movie_id, state, user):
        m = self._card(movie_id)
        info = self.watch.for_movie(movie_id, m["title"], m["year"]) if self.watch else None
        if not info:
            text = f"I don't have streaming data yet. Open **{m['title']}** and use \"See all watch options\"."
        elif not info["groups"]:
            text = f"**{m['title']}** isn't on any streaming, rental or purchase platform in India right now."
        else:
            bits = [f"{g['label'].lower()} on " + ", ".join(p["name"] for p in g["platforms"][:4]) for g in info["groups"]]
            text = f"You can {'; '.join(bits)}. 📺 Tap the movie to open its \"Where to watch\" buttons."
            text = f"**{m['title']}**: " + text
        state["last"] = [movie_id]
        return self._out(state, text, results=[m], suggestions=["Movies like this", "Tell me about it", "Show me more"])

    def _about(self, movie_id, state, user):
        r = self.cat.movie_dict(self.cat.pos[movie_id], full=True)
        feelings = ", ".join(e["label"].lower() for e in r["top_emotions"]) or "mixed"
        cert = (r["certification"] + ", " if r["certification"] else "") + r["content_level_name"].lower()
        overview = r["overview"] if len(r["overview"]) < 260 else r["overview"][:257].rsplit(" ", 1)[0] + "…"
        text = (f"**{r['title']}** ({r['year']}) is {', '.join(r['genres'][:3]).lower()}"
                + (f", directed by {r['director']}" if r["director"] else "")
                + (f" with {', '.join(r['cast'][:2])}" if r["cast"] else "")
                + f". It feels {feelings}, is rated {r['rating']}/10 and is {cert}. {overview}")
        state["last"] = [movie_id]
        return self._out(state, text, results=[self._card(movie_id)],
                         suggestions=["Where can I watch it?", "Movies like this", "Something different"])

    def _why(self, movie_id, state, user):
        p = dict(state["prefs"], limit=30, diversify=False, exclude_ids=[])
        if p.get("audience") is None:
            p["audience"] = "adults"
        res = self.engine.recommend(p, user or {}) if any(state["prefs"].values()) else {"results": []}
        hit = next((m for m in res["results"] if m["id"] == movie_id), None)
        m = self._card(movie_id)
        if hit:
            parts = [f"{b['label'].lower()} {int(round(b['value'] * b['weight'] * 100))}" for b in hit["breakdown"].values()]
            text = (f"I picked **{m['title']}** with a {hit['match']}% match. Score parts: " + ", ".join(parts) + ". "
                    + " ".join(r + "." for r in hit["reasons"][:3]))
        else:
            feelings = ", ".join(e["label"].lower() for e in m["top_emotions"]) or "mixed"
            text = (f"**{m['title']}** feels {feelings} and is {m['content_level_name'].lower()}. "
                    "Open it to see the full score breakdown.")
        state["last"] = [movie_id] + [x for x in state.get("last", []) if x != movie_id]
        return self._out(state, text, results=[m], suggestions=["Where can I watch it?", "Movies like this", "Show me more"])

    # ------------------------------------------------------------------
    @staticmethod
    def _clean_state(state):
        state = state if isinstance(state, dict) else {}
        prefs = state.get("prefs") if isinstance(state.get("prefs"), dict) else {}
        allowed = {"audience", "emotions", "genres", "languages", "max_runtime", "era", "query",
                   "seed_movie_id", "current_mood", "platforms", "group"}
        prefs = {k: v for k, v in prefs.items() if k in allowed}
        ids = lambda v: [int(x) for x in (v if isinstance(v, list) else [])[:60]
                         if isinstance(x, (int, str)) and str(x).lstrip("-").isdigit()]
        out = {"prefs": prefs, "shown": ids(state.get("shown")), "last": ids(state.get("last")),
               "asked_audience": bool(state.get("asked_audience"))}
        if isinstance(state.get("offer"), str) and state["offer"] in labels.CURRENT_MOODS:
            out["offer"] = state["offer"]
        hist = state.get("history") if isinstance(state.get("history"), list) else []
        out["history"] = [[str(u)[:300], str(g)[:300]] for u, g in
                          (h for h in hist[-6:] if isinstance(h, (list, tuple)) and len(h) == 2)]
        return out

    def _chips_for(self, prefs):
        chips = []
        if prefs.get("audience"):
            chips.append(labels.AUDIENCES[prefs["audience"]][0])
        chips += ["Feel " + labels.EMOTIONS[e]["display"].lower() for e in prefs.get("emotions", [])]
        chips += [labels.GENRE_DISPLAY.get(g, g) for g in prefs.get("genres", [])]
        chips += [labels.LANGUAGES[l] for l in prefs.get("languages", []) if l in labels.LANGUAGES]
        return chips

    def _out(self, state, text, results=None, chips=None, suggestions=None, brain_used="built-in"):
        return {"reply": text, "results": results or [], "understood": chips or [],
                "suggestions": suggestions or [], "state": state, "brain": brain_used}

    # ------------------------------------------------------------------
    # optional Google Gemini helpers  (only used when GEMINI_API_KEY is set)
    # ------------------------------------------------------------------
    FALLBACK_MODEL = "gemini-2.5-flash-lite"

    def _gemini(self, system, prompt, timeout=8, history=None, temperature=0.3):
        contents = []
        for u, g in history or []:
            contents += [{"role": "user", "parts": [{"text": u}]}, {"role": "model", "parts": [{"text": g}]}]
        contents.append({"role": "user", "parts": [{"text": prompt}]})
        body = {"systemInstruction": {"parts": [{"text": system}]}, "contents": contents,
                "generationConfig": {"temperature": temperature, "responseMimeType": "application/json"}}
        for model in dict.fromkeys([self.gemini_model, self.FALLBACK_MODEL]):
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
            req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"), method="POST",
                                         headers={"Content-Type": "application/json", "x-goog-api-key": self.gemini_key})
            try:
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                return json.loads(data["candidates"][0]["content"]["parts"][0]["text"])
            except urllib.error.HTTPError as e:
                if e.code != 404:          # 404 = model name not available -> try the fallback model
                    return None
            except Exception:
                return None                # any problem -> the built-in brain answers instead
        return None

    def _gemini_chat(self, text, state):
        """Free conversation with Gemini. Returns {reply, action, prefs, movies} or None."""
        system = (
            "You are RAGS Genie, the warm, playful movie assistant inside RAGS CineMind, a movie recommendation web app "
            "made as a college mini project by Chandra Abhiram Reddy, Gannoj Brahma Teja and Medikonda Raga Spandana "
            "(IV CSE AI & ML, AVIT, Chennai), guided by Dr. Ramu K. CineMind picks movies by the feeling you want, who is "
            f"watching (age-safe) and your taste, from {len(self.cat):,} real films, and shows where to watch them in India.\n"
            "Talk naturally like a friendly person: 1 to 3 short sentences, at most two emoji. You can chit-chat, joke, "
            "comfort someone, and share movie trivia, then gently bring the talk back to movies. Never pretend to be human. "
            "Do not give medical, legal or money advice; if someone seems in real distress, be kind and suggest talking "
            "to someone they trust.\n"
            "If the user wants movie suggestions now (or says yes to your offer), set action to \"recommend\" and fill "
            "prefs; do NOT list movies yourself, the app's engine picks real ones. Otherwise action is \"chat\". "
            "Whenever you name a specific film in chat, write its exact title in **bold**.\n"
            f"prefs fields (all optional): audience one of {list(labels.AUDIENCES)}; emotions up to 2 of "
            f"{labels.EMOTION_KEYS}; genres up to 3 of {labels.GENRES}; languages up to 1 of {list(labels.LANGUAGES)}; "
            f"current_mood one of {list(labels.CURRENT_MOODS)}; max_runtime in minutes; query 2-8 story keywords.\n"
            'Return only JSON: {"reply": "...", "action": "chat" or "recommend", "prefs": {...}}')
        out = self._gemini(system, text, timeout=10, history=state.get("history"), temperature=0.8)
        if not isinstance(out, dict) or not isinstance(out.get("reply"), str) or not out["reply"].strip():
            return None
        reply = out["reply"].strip()[:500]
        action = "recommend" if out.get("action") == "recommend" else "chat"
        prefs = self._clean_prefs(out.get("prefs")) if action == "recommend" else None
        # titles Gemini named: real ones become movie cards, unknown ones lose their bold
        rows = []
        for t in dict.fromkeys(re.findall(r"\*\*(.+?)\*\*", reply)):
            r = self.title_row(re.sub(r"\s*\(\d{4}\)$", "", t))
            if r is None:
                reply = reply.replace(f"**{t}**", t)
            elif r not in rows:
                rows.append(r)
        movies = [self.cat.movie_dict(r) for r in rows[:4]]
        if movies:
            state["last"] = [m["id"] for m in movies]
        return {"reply": reply, "action": action, "prefs": prefs or {}, "movies": movies}

    def _gemini_parse(self, text):
        system = ("You convert a movie request into JSON for a recommender. Only use these values. "
                  f"audience: one of {list(labels.AUDIENCES)}. emotions: up to 2 of {labels.EMOTION_KEYS}. "
                  f"genres: up to 3 of {labels.GENRES}. languages: up to 1 of {list(labels.LANGUAGES)} (ISO codes). "
                  f"current_mood: one of {list(labels.CURRENT_MOODS)} if the user says how they feel now. "
                  "max_runtime: minutes if a length is given. query: 2-8 descriptive keywords about the story. "
                  "Leave out fields that are not mentioned. Return only the JSON object.")
        return self._clean_prefs(self._gemini(system, text))

    @staticmethod
    def _clean_prefs(out):
        """Keep only valid preference values from Gemini's JSON."""
        if not isinstance(out, dict):
            return None
        clean = {}
        aud = labels.normalize_audience(out.get("audience", ""))
        if aud:
            clean["audience"] = aud
        emos = [e for e in (labels.normalize_emotion(x) for x in (out.get("emotions") or [])) if e][:2]
        if emos:
            clean["emotions"] = emos
        gens = [g for g in (labels.normalize_genre(x) for x in (out.get("genres") or [])) if g][:3]
        if gens:
            clean["genres"] = gens
        langs = [l for l in (out.get("languages") or []) if l in labels.LANGUAGES][:1]
        if langs:
            clean["languages"] = langs
        mood = labels.normalize_current_mood(out.get("current_mood", ""))
        if mood:
            clean["current_mood"] = mood
        try:
            if out.get("max_runtime"):
                clean["max_runtime"] = max(60, min(int(out["max_runtime"]), 240))
        except (TypeError, ValueError):
            pass
        if isinstance(out.get("query"), str) and out["query"].strip():
            clean["query"] = out["query"].strip()[:120]
        return clean or None

    def _gemini_reply(self, said, summary, movies):
        listed = [{"title": m["title"], "year": m["year"], "match": m["match"],
                   "why": next((r for r in m.get("reasons", []) if not r.startswith(("Estimated", "Rated"))), "")}
                  for m in movies[:SHOW]]
        system = ("You are RAGS Genie, a cheerful movie assistant inside the RAGS CineMind app. Write a short reply "
                  "(max 2 sentences, one emoji) introducing the recommended movies. You may ONLY mention titles from the "
                  "given list - never invent or add other movies. The top pick is the FIRST movie in the list: name it first and in **bold**. "
                  'Return JSON: {"reply": "..."}')
        out = self._gemini(system, json.dumps({"user_message": said, "understood": summary, "movies": listed}))
        reply = out.get("reply") if isinstance(out, dict) else None
        if not reply or not isinstance(reply, str):
            return None
        allowed = {m["title"].lower() for m in movies}
        bolded = [b.strip().lower() for b in re.findall(r"\*\*(.+?)\*\*", reply)]
        # keep Gemini's wording only if it names OUR top pick first and no film we didn't give;
        # otherwise the built-in sentence is used, so the text always matches the list
        if not bolded or bolded[0] != movies[0]["title"].lower() or not set(bolded) <= allowed:
            return None
        return reply.strip()[:400]
