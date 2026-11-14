"""
nlu.py  -  understands what people type ("natural language understanding")
==========================================================================

Turns a sentence such as
    "something funny for my family in Telugu under 2 hours"
into CineMind preferences:
    {"audience": "family", "emotions": ["funny"], "languages": ["te"], "max_runtime": 120}

It is rule based: lists of words and patterns for every slot (audience,
feeling, current mood, genre, language, length, era, platform, "like <movie>").
Because it uses no outside service it is fast, free, works offline and
every decision can be explained. RAGS Genie uses it on every message; the
optional Gemini mode (genie.py) only helps when this parser finds nothing.
"""

import re

from . import labels

# ---------------------------------------------------------------------------
# word lists  (phrase -> value). Longer phrases are matched first.
# ---------------------------------------------------------------------------
AUDIENCE_WORDS = {
    "kids": ["kid", "kids", "child", "children", "my son", "my daughter", "little one", "cartoon",
             "toddler", "5 year old", "8 year old", "10 year old", "my kids", "for kids"],
    "family": ["family", "families", "my parents", "parents", "whole family", "with family", "family night",
               "relatives", "cousins", "festival"],
    "teenagers": ["teen", "teens", "teenager", "teenagers", "my teenage", "school friends", "13 year old",
                  "15 year old"],
    "adults": ["adult", "adults", "grown up", "18+", "mature", "date", "date night", "my girlfriend",
               "my boyfriend", "my wife", "my husband", "partner", "colleagues"],
    "seniors": ["senior", "seniors", "grandparents", "grandma", "grandpa", "grandmother", "grandfather",
                "elderly", "old parents"],
    "everyone": ["everyone", "friends", "group", "all of us", "mixed group", "roommates"],
}
EMOTION_WORDS = {
    "happy": ["happy", "cheerful", "feel good", "feel-good", "joyful", "uplift", "smile", "wholesome", "positive"],
    "sad": ["sad", "cry", "crying", "tearjerker", "tear jerker", "make me cry", "emotional cry", "heartbreaking"],
    "excited": ["exciting", "excited", "adrenaline", "action packed", "action-packed", "thrill ride", "pumped",
                "high energy", "mass", "fight scenes", "explosive"],
    "relaxed": ["relax", "relaxed", "relaxing", "calm", "chill", "chilled", "easy watch", "light watch", "cozy",
                "cosy", "lazy", "comfort"],
    "emotional": ["emotional", "touching", "heartfelt", "moving", "heart touching", "sentimental"],
    "romantic": ["romantic", "romance", "love story", "love", "date night", "cute couple", "rom com", "romcom"],
    "funny": ["funny", "comedy", "laugh", "laughing", "hilarious", "lol", "humour", "humor", "comic", "light hearted",
              "lighthearted", "fun"],
    "angry": ["intense", "revenge", "raw", "gritty action", "rage", "angry"],
    "scary": ["scary", "horror", "ghost", "haunted", "spooky", "scare", "creepy", "frightening", "terrifying"],
    "hopeful": ["hopeful", "hope", "optimistic", "second chance", "uplifting"],
    "inspiring": ["inspiring", "inspirational", "motivating", "motivational", "motivate", "true story",
                  "biopic", "based on true", "sports drama", "real story"],
    "suspenseful": ["suspense", "suspenseful", "thriller", "twist", "twists", "edge of my seat", "mystery",
                    "whodunit", "mind bending", "mind-bending", "investigation", "detective"],
    "nostalgic": ["nostalgic", "nostalgia", "old school", "childhood", "retro", "classic"],
    "adventurous": ["adventure", "adventurous", "quest", "journey", "explore", "epic", "fantasy world",
                    "treasure", "space adventure"],
    "dark": ["dark", "gritty", "disturbing", "bleak", "psychological"],
}
MOOD_PATTERNS = [   # "I feel ___" -> current mood (how they feel now, not what they want)
    (r"\b(i am|i'm|im|feeling|i feel|i'm feeling|feel)\s+(so\s+|very\s+|really\s+|a bit\s+|kinda\s+)?(sad|down|low|upset|depressed)\b", "sad"),
    (r"\b(i am|i'm|im|feeling|i feel|feel)\s+(so\s+|very\s+|really\s+|a bit\s+)?(stressed|tense|overwhelmed|exam stress)\b", "stressed"),
    (r"\b(i am|i'm|im|feeling|i feel|feel)\s+(so\s+|very\s+|really\s+|a bit\s+)?(angry|mad|frustrated|irritated)\b", "angry"),
    (r"\b(i am|i'm|im|feeling|i feel|feel)\s+(so\s+|very\s+|really\s+|a bit\s+)?(anxious|worried|nervous)\b", "anxious"),
    (r"\b(i am|i'm|im|feeling|i feel|feel)\s+(so\s+|very\s+|really\s+|a bit\s+)?(lonely|alone)\b", "lonely"),
    (r"\b(i am|i'm|im|feeling|i feel|feel)\s+(so\s+|very\s+|really\s+|a bit\s+)?(tired|sleepy|exhausted)\b", "tired"),
    (r"\b(i am|i'm|im|feeling|i feel|feel)\s+(so\s+|very\s+|really\s+|a bit\s+)?(bored)\b", "bored"),
    (r"\bbad day\b", "stressed"),
    (r"\bbreak ?up\b", "sad"),
]
GENRE_WORDS = {
    "Action": ["action"], "Adventure": ["adventure"], "Animation": ["animated", "animation", "cartoon", "anime"],
    "Comedy": ["comedy", "comedies"], "Crime": ["crime", "gangster", "heist"], "Documentary": ["documentary", "documentaries"],
    "Drama": ["drama"], "Family": ["family movie", "family film"], "Fantasy": ["fantasy", "magic", "magical"],
    "History": ["history", "historical", "period"], "Horror": ["horror"], "Music": ["musical", "music"],
    "Mystery": ["mystery"], "Romance": ["romance", "romcom", "rom com"], "Science Fiction": ["sci-fi", "sci fi", "scifi", "science fiction", "space", "alien", "aliens", "robot", "robots", "time travel"],
    "Thriller": ["thriller", "thrillers"], "War": ["war"], "Western": ["western", "cowboy"],
}
LANGUAGE_WORDS = {code: [name.lower()] for code, name in labels.LANGUAGES.items()}
LANGUAGE_WORDS["hi"] += ["bollywood"]
LANGUAGE_WORDS["te"] += ["tollywood"]
LANGUAGE_WORDS["ta"] += ["kollywood"]
LANGUAGE_WORDS["ml"] += ["mollywood"]
LANGUAGE_WORDS["kn"] += ["sandalwood"]
LANGUAGE_WORDS["en"] += ["hollywood"]
LANGUAGE_WORDS["ko"] += ["k-drama", "kdrama"]
PLATFORM_WORDS = {
    "Netflix": ["netflix"], "Amazon Prime Video": ["prime video", "amazon prime", "prime"],
    "JioHotstar": ["hotstar", "jiohotstar", "jio hotstar", "disney"], "Zee5": ["zee5", "zee 5"],
    "Sony Liv": ["sonyliv", "sony liv"], "Apple TV": ["apple tv"], "aha": ["aha video", "aha"],
    "Sun Nxt": ["sun nxt", "sunnxt"], "YouTube": ["youtube"],
}
ERA_PATTERNS = [
    (r"\b(old|classic|vintage|black and white|60s|70s|1960s|1970s|before 1980)\b", "classic"),
    (r"\b(80s|90s|1980s|1990s|eighties|nineties)\b", "80s90s"),
    (r"\b(2000s|early 2000s)\b", "2000s"),
    (r"\b(new|recent|latest|modern|2010s|2020s|this decade)\b", "2010s"),
]
STOP = set("""a an the i me my we us our you your it is are was be to of for in on at with and or but so
some something anything movie movies film films show watch want wanna like need give find suggest recommend
please can could would should tonight today now time good nice best great any one kind sort type that this
feel feeling mood im i'm am do please pls plz yes no ok okay maybe also more less very really just
from made released around after before since than then where which what who how us
about story stories based hours hour mins minutes min short quick night evening weekend sunday
someone something watching watched seen""".split())


def _has(text, phrase):
    return re.search(r"(?<![a-z0-9])" + re.escape(phrase) + r"(?![a-z0-9])", text) is not None


def _match_words(text, table, limit=None):
    found, spans = [], []
    phrases = sorted(((p, v) for v, ps in table.items() for p in ps), key=lambda x: -len(x[0]))
    for phrase, value in phrases:
        if _has(text, phrase) and value not in found:
            # skip if this phrase sits inside a longer phrase we already used
            m = re.search(r"(?<![a-z0-9])" + re.escape(phrase) + r"(?![a-z0-9])", text)
            if any(a <= m.start() and m.end() <= b for a, b in spans):
                continue
            found.append(value)
            spans.append((m.start(), m.end()))
    return found[:limit] if limit else found


def parse(text, catalog=None):
    """
    Returns {"prefs": {...}, "understood": [human-readable chips], "intent": str, "movie_id": int|None}
    intent is one of: recommend, similar, where, about, why, greet, thanks, help, more, refine
    """
    raw = str(text or "")[:300]
    t = " " + raw.lower().replace("’", "'") + " "
    prefs, chips = {}, []

    # ---- intents that are not "recommend"
    intent = "recommend"
    if re.search(r"^\s*(hi|hello|hey|hii+|namaste|hola|yo)\b[\s!.]*$", t):
        intent = "greet"
    elif re.search(r"\b(thanks|thank you|thx|ty|great thanks)\b", t) and len(t.split()) <= 6:
        intent = "thanks"
    elif re.search(r"\b(what can you do|help|how does this work|how do you work|who are you)\b", t):
        intent = "help"
    elif re.search(r"\b(where (can|to) (i )?(watch|stream)|is .+ on (netflix|prime|hotstar|zee5)|which (app|ott|platform))\b", t):
        intent = "where"
    elif re.search(r"^\s*why\b|\b(why (did you|this)|why .+ (suggest|recommend|pick))\b", t):
        intent = "why"
    elif re.search(r"\b(tell me about|what is .+ about|who (directed|acted|is in)|details (of|about)|plot of)\b", t):
        intent = "about"
    elif re.search(r"\b(more|another|other|different|something else|next|show more)\b", t) and len(t.split()) <= 5:
        intent = "more"

    # ---- find a movie title in the sentence (only where a title is expected)
    movie_id = None
    TITLE_PATTERNS = {
        "similar": r"\b(?:like|similar to|same as)\s+(.+?)(?:\s+(?:but|in|for|on|with|under|and)\b|[?.!,]|$)",
        "where": r"\b(?:watch|stream|is|find|get)\s+(.+?)(?:\s+(?:on|in|online)\b|[?.!,]|$)",
        "about": r"\b(?:about|directed|is in|acted in|details of|plot of|story of)\s+(.+?)(?:[?.!,]|$)",
        "why": r"\b(?:suggest|suggested|recommend|recommended|pick|picked|show|showed)\s+(?:me\s+)?(.+?)(?:[?.!,]|$)",
    }
    wants_similar = re.search(r"\b(like|similar to|same as)\s+[a-z0-9]", t) and not re.search(r"\b(i'd like|would like|i like to|feel like|looks like)\b", t)
    key = "similar" if (intent == "recommend" and wants_similar) else intent
    if catalog is not None and key in TITLE_PATTERNS:
        m = re.search(TITLE_PATTERNS[key], t)
        cand = re.sub(r"^(the movie|the film|movie|film)\s+", "", m.group(1).strip()) if m else ""
        cand = re.sub(r"\s+(movie|film)$", "", cand)
        if len(cand) >= 2 and cand not in STOP:
            exact = [i for i, title in enumerate(catalog._title_lower) if title == cand]
            starts = [i for i, title in enumerate(catalog._title_lower) if len(cand) >= 4 and title.startswith(cand)]
            hit = exact or sorted(starts, key=lambda i: -catalog.df.at[i, "vote_count"])
            if hit:
                movie_id = int(catalog.ids[hit[0]])
                if key == "similar":
                    intent = "similar"
                    prefs["seed_movie_id"] = movie_id
                    chips.append("Like " + catalog.df.at[hit[0], "title"])
                t = t.replace(" " + cand, " ")          # the title is not part of the description

    # ---- slots
    aud = _match_words(t, AUDIENCE_WORDS, 1)
    if aud:
        prefs["audience"] = aud[0]
        chips.append(labels.AUDIENCES[aud[0]][0])
    for pattern, mood in MOOD_PATTERNS:
        if re.search(pattern, t):
            prefs["current_mood"] = mood
            chips.append("Feeling " + labels.CURRENT_MOODS[mood]["display"].lower())
            break
    t_for_emotion = t
    if prefs.get("current_mood"):      # "I feel sad" is the current mood, not the wanted feeling
        for pattern, _ in MOOD_PATTERNS:
            t_for_emotion = re.sub(pattern, " ", t_for_emotion)
    emos = _match_words(t_for_emotion, EMOTION_WORDS, 2)
    if emos:
        prefs["emotions"] = emos
        chips += ["Feel " + labels.EMOTIONS[e]["display"].lower() for e in emos]
    elif prefs.get("current_mood"):    # default wish for a mood: its first "bridge" feeling
        bridge = labels.CURRENT_MOODS[prefs["current_mood"]]["bridge"][0]
        prefs["emotions"] = [bridge]
        chips.append("Feel " + labels.EMOTIONS[bridge]["display"].lower())
    genres = [g for g in _match_words(t, GENRE_WORDS, 3)
              if not (g == "Comedy" and "funny" in prefs.get("emotions", []))
              and not (g == "Horror" and "scary" in prefs.get("emotions", []))
              and not (g == "Romance" and "romantic" in prefs.get("emotions", []))
              and not (g == "Thriller" and "suspenseful" in prefs.get("emotions", []))
              and not (g == "Adventure" and "adventurous" in prefs.get("emotions", []))]
    if genres:
        prefs["genres"] = genres
        chips += [labels.GENRE_DISPLAY.get(g, g) for g in genres]
    langs = _match_words(t, LANGUAGE_WORDS)
    if langs:
        prefs["languages"] = langs[:1]
        chips.append(labels.LANGUAGES[langs[0]])
    plats = _match_words(t, PLATFORM_WORDS)
    if plats and intent != "where":
        prefs["platforms"] = plats
        chips += ["On " + p for p in plats]

    # ---- length: "under 2 hours", "less than 90 min", "short", "quick"
    m = re.search(r"\b(?:under|less than|below|within|max|maximum|upto|up to|not more than)\s+(\d+(?:\.\d+)?)\s*(h|hr|hrs|hour|hours|m|min|mins|minutes)\b", t)
    if m:
        n = float(m.group(1))
        minutes = int(n * 60) if m.group(2).startswith("h") else int(n)
        prefs["max_runtime"] = max(60, min(minutes, 240))
    elif re.search(r"\b(short|quick|small)\b", t):
        prefs["max_runtime"] = 100
    elif re.search(r"\b(i have|only have|got)\s+(an|one|1)\s+hour\b", t):
        prefs["max_runtime"] = 90
    if prefs.get("max_runtime"):
        h, mm = divmod(prefs["max_runtime"], 60)
        chips.append(f"Up to {h} h {mm} min" if mm else f"Up to {h} h")
    for pattern, era in ERA_PATTERNS:
        if re.search(pattern, t):
            prefs["era"] = era
            chips.append({"classic": "Before 1980", "80s90s": "80s & 90s", "2000s": "2000s", "2010s": "2010 onwards"}[era])
            break

    # ---- leftover descriptive words become a free-text description for TF-IDF
    rest = t
    for table in (AUDIENCE_WORDS, EMOTION_WORDS, GENRE_WORDS, LANGUAGE_WORDS, PLATFORM_WORDS):
        for phrase in sorted((p for ps in table.values() for p in ps), key=len, reverse=True):
            rest = re.sub(r"(?<![a-z0-9])" + re.escape(phrase) + r"(?![a-z0-9])", " ", rest)
    for pattern, _ in MOOD_PATTERNS + ERA_PATTERNS:
        rest = re.sub(pattern, " ", rest)
    rest = re.sub(r"\b(?:under|less than|below|within|max|maximum|upto|up to|not more than)\s+\d+(?:\.\d+)?\s*\w+", " ", rest)
    words = [w for w in re.findall(r"[a-z][a-z'-]+", rest) if w not in STOP and len(w) > 2]
    if words and intent == "recommend":
        prefs["query"] = " ".join(words[:12])

    chips = list(dict.fromkeys(chips))                      # "Family" audience + "Family" genre -> once
    return {"prefs": prefs, "understood": chips, "intent": intent, "movie_id": movie_id}
