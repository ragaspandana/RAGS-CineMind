"""
labels.py  -  ONE shared vocabulary for the whole project
=========================================================

The prototype broke because the dropdowns said "sad" / "sci-fi" / "senior"
while the dataset said "Emotional" / "Science Fiction" / (nothing).

Everything that names an audience, emotion, genre or language now comes
from THIS file:
  * the dataset builder uses it to label movies,
  * the engine uses it to match movies,
  * the API sends it to the website to build the pickers.
So the three can never disagree again.

This file also documents the two labelling rules used in the report:
  1. EMOTION PROFILE  - how a movie gets a score for each of 15 emotions.
  2. AUDIENCE LEVEL   - how a movie gets a content-suitability level.
"""

import re

# ---------------------------------------------------------------------------
# GENRES  (exactly the TMDB genre names, plus a short display label)
# ---------------------------------------------------------------------------
GENRES = [
    "Action", "Adventure", "Animation", "Comedy", "Crime", "Documentary",
    "Drama", "Family", "Fantasy", "History", "Horror", "Music", "Mystery",
    "Romance", "Science Fiction", "Thriller", "War", "Western",
]
GENRE_DISPLAY = {"Science Fiction": "Sci-Fi"}


# ---------------------------------------------------------------------------
# LANGUAGES  (ISO 639-1 codes used by TMDB -> readable names)
# ---------------------------------------------------------------------------
LANGUAGES = {
    "en": "English", "hi": "Hindi", "te": "Telugu", "ta": "Tamil",
    "ml": "Malayalam", "kn": "Kannada", "bn": "Bengali", "mr": "Marathi",
    "fr": "French", "es": "Spanish", "de": "German", "it": "Italian",
    "ja": "Japanese", "ko": "Korean", "zh": "Chinese", "cn": "Cantonese",
    "ru": "Russian", "pt": "Portuguese",
}


# ---------------------------------------------------------------------------
# AUDIENCE  ->  maximum allowed content level
# ---------------------------------------------------------------------------
# Content levels (higher = more mature):
#   0 = All ages          (US G,  India U)
#   1 = Parental guidance (US PG, India UA / UA 7+)
#   2 = Teen              (US PG-13, India UA 13+ / UA 16+)
#   3 = Adult             (US R / NC-17, India A)
LEVEL_NAMES = {0: "All ages", 1: "Parental guidance", 2: "Teen (13+)", 3: "Adult (18+)"}

AUDIENCES = {
    # key        : (display,       max_level, description)
    "kids":      ("Kids",          0, "Only all-ages movies"),
    "family":    ("Family",        1, "All ages + parental guidance"),
    "everyone":  ("Everyone",      1, "Safe for a mixed group"),
    "teenagers": ("Teenagers",     2, "Up to teen-rated movies"),
    "adults":    ("Adults",        3, "No content restriction"),
    "seniors":   ("Seniors",       3, "No restriction, gentler picks ranked higher"),
}

# Official certificates -> content level
CERT_LEVEL = {
    # USA
    "G": 0, "TV-Y": 0, "TV-G": 0,
    "PG": 1, "TV-PG": 1,
    "PG-13": 2, "TV-14": 2,
    "R": 3, "NC-17": 3, "TV-MA": 3, "NR": None, "": None,
    # India (CBFC)
    "U": 0, "UA": 1, "U/A": 1, "UA 7+": 1, "UA 13+": 2, "UA 16+": 2, "A": 3, "S": 3,
}

# Keywords that indicate mature content (used ONLY when there is no
# official certificate). Conservative on purpose.
ADULT_FLAGS = {
    "sex", "sex scene", "nudity", "female nudity", "male nudity", "rape",
    "gore", "torture", "slasher", "serial killer", "prostitute", "prostitution",
    "drug", "drugs", "drug dealer", "drug addiction", "cocaine", "heroin",
    "erotic", "adult animation", "incest", "pornography", "brutality",
    "splatter", "strip club", "stripper", "suicide", "sadism", "extreme violence",
}
TEEN_FLAGS = {
    "violence", "murder", "blood", "shootout", "gun", "killer", "assassin",
    "hitman", "terrorist", "war", "death", "kidnapping", "revenge", "gangster",
    "mafia", "alcohol", "alcoholism", "zombie", "vampire", "demon", "monster",
    "dark comedy", "explosion", "fight", "martial arts",
}
MATURE_GENRES = {"Horror", "Crime", "Thriller", "War"}


def cert_to_level(cert):
    """Official certificate text -> level (or None if unknown)."""
    if cert is None:
        return None
    return CERT_LEVEL.get(str(cert).strip().upper(), None)


def estimate_level(genres, keywords):
    """
    Rule-based content level when NO official certificate exists.

    Rules (applied in order, first match wins):
      R1  any ADULT_FLAG keyword or genre Horror            -> 3 (Adult)
      R2  genre Family and no mature genre / teen keyword   -> 0 (All ages)
      R3  genre Family (but some action / peril)            -> 1 (PG)
      R4  any mature genre or TEEN_FLAG keyword             -> 2 (Teen)
      R5  everything else                                   -> 2 (Teen)
    R5 is deliberately cautious: an unknown live-action movie is NOT shown
    to kids. Note: "Animation" alone never makes a movie kid-safe
    (e.g. Anomalisa, Sausage Party are adult animated films).
    """
    g = set(genres)
    k = {x.lower() for x in keywords}
    if k & ADULT_FLAGS or "Horror" in g:
        return 3
    if "Family" in g and not (g & MATURE_GENRES) and not (k & TEEN_FLAGS):
        return 0
    if "Family" in g:
        return 1
    return 2


# ---------------------------------------------------------------------------
# EMOTIONS  -  "How do you want to feel?"
# ---------------------------------------------------------------------------
# The user picks the feeling they want FROM the movie.
# Each emotion is defined by:
#   genres   : genre -> weight (how strongly that genre suggests the feeling)
#   keywords : TMDB keywords / overview words that are evidence for it
#   colour   : used by the website for the mood theme
#
# Emotion score of a movie (see build_dataset.py):
#   raw = sum(genre weights) + 1.0 * (#keyword hits) + 0.5 * (#overview word hits)
#   score = percentile rank of raw among all movies (0..1)
# This makes scores comparable between emotions, and every label can be
# explained by the evidence words that produced it.

EMOTIONS = {
    "happy": {
        "display": "Happy", "colour": "#FFC845",
        "description": "Light, cheerful, feel-good",
        "genres": {"Comedy": 1.5, "Family": 1.2, "Animation": 1.0, "Music": 0.8, "Romance": 0.3},
        "keywords": ["friendship", "feel-good", "best friend", "party", "holiday",
                     "christmas", "wedding", "musical", "dancing", "summer", "fun",
                     "happiness", "joy", "celebration"],
    },
    "sad": {
        "display": "Sad", "colour": "#5B7DB1",
        "description": "A good cry, tearjerkers",
        "genres": {"Drama": 1.2, "Romance": 0.5, "War": 0.6},
        "keywords": ["dying and death", "death", "cancer", "funeral", "grief",
                     "loss of father", "loss of mother", "loss of loved one",
                     "tragedy", "terminal illness", "loneliness", "depression",
                     "heartbreak", "suicide", "mourning", "loss of lover"],
    },
    "excited": {
        "display": "Excited", "colour": "#FF5A36",
        "description": "Adrenaline, high energy",
        "genres": {"Action": 1.6, "Adventure": 0.9, "Science Fiction": 0.6, "Thriller": 0.5},
        "keywords": ["explosion", "chase", "car chase", "fight", "battle", "race",
                     "superhero", "martial arts", "heist", "escape", "shootout",
                     "rescue", "mission", "speed", "competition"],
    },
    "relaxed": {
        "display": "Relaxed", "colour": "#7FC8A9",
        "description": "Calm, cosy, easy watching",
        "genres": {"Comedy": 0.6, "Family": 0.6, "Romance": 0.6, "Documentary": 0.6,
                   "Animation": 0.5, "Music": 0.5},
        "keywords": ["small town", "road trip", "village", "nature", "food",
                     "cooking", "restaurant", "slice of life", "travel", "beach",
                     "garden", "countryside", "dog", "cat", "friendship"],
    },
    "emotional": {
        "display": "Emotional", "colour": "#C86B98",
        "description": "Moving, heartfelt stories",
        "genres": {"Drama": 1.5, "Romance": 0.7, "Family": 0.4, "History": 0.4},
        "keywords": ["father son relationship", "mother daughter relationship",
                     "father daughter relationship", "parents kids relationship",
                     "family relationships", "redemption", "sacrifice", "illness",
                     "coming of age", "orphan", "love", "reunion", "forgiveness"],
    },
    "romantic": {
        "display": "Romantic", "colour": "#FF6F91",
        "description": "Love stories",
        "genres": {"Romance": 2.0, "Drama": 0.3, "Comedy": 0.2},
        "keywords": ["love", "romance", "romantic comedy", "new love", "falling in love",
                     "love of one's life", "first love", "kiss", "wedding", "marriage",
                     "love triangle", "secret love", "relationship", "lovers"],
    },
    "funny": {
        "display": "Funny", "colour": "#F9A03F",
        "description": "Laugh out loud",
        "genres": {"Comedy": 2.0, "Animation": 0.4},
        "keywords": ["spoof", "parody", "slapstick", "dark comedy", "satire",
                     "romantic comedy", "comedy", "buddy comedy", "mockumentary",
                     "stand-up comedy", "farce", "prank", "hilarious"],
    },
    "angry": {
        "display": "Intense", "colour": "#D7263D",
        "description": "Rage, revenge, raw intensity",
        "genres": {"Crime": 0.9, "Thriller": 0.7, "Action": 0.6, "War": 0.6, "Drama": 0.2},
        "keywords": ["revenge", "vengeance", "corruption", "injustice", "prison",
                     "violence", "gang", "street gang", "fight", "betrayal", "rage",
                     "vigilante", "police brutality", "racism", "oppression"],
    },
    "scary": {
        "display": "Scary", "colour": "#7A3E9D",
        "description": "Frights and chills",
        "genres": {"Horror": 2.2, "Thriller": 0.6, "Mystery": 0.4},
        "keywords": ["ghost", "haunted house", "supernatural", "demon", "zombie",
                     "vampire", "monster", "slasher", "possession", "witch", "curse",
                     "nightmare", "serial killer", "found footage", "exorcism", "terror"],
    },
    "hopeful": {
        "display": "Hopeful", "colour": "#8BD3E6",
        "description": "Uplifting, things get better",
        "genres": {"Drama": 0.5, "Family": 0.5, "Science Fiction": 0.2, "Romance": 0.2},
        "keywords": ["hope", "second chance", "new beginning", "redemption", "survival",
                     "rescue", "dream", "overcoming", "recovery", "underdog",
                     "saving the world", "faith", "good vs evil", "fresh start"],
    },
    "inspiring": {
        "display": "Inspiring", "colour": "#3DDC97",
        "description": "True stories, achievement",
        "genres": {"Documentary": 1.0, "History": 0.9, "Drama": 0.4, "Music": 0.3},
        "keywords": ["based on true story", "biography", "sport", "historical figure",
                     "underdog", "coach", "teacher", "training", "competition",
                     "civil rights", "leadership", "determination", "baseball",
                     "boxing", "american football", "olympics", "true story"],
    },
    "suspenseful": {
        "display": "Suspenseful", "colour": "#4E5FD9",
        "description": "Edge of your seat",
        "genres": {"Thriller": 1.6, "Mystery": 1.3, "Crime": 0.6},
        "keywords": ["suspense", "investigation", "detective", "conspiracy", "kidnapping",
                     "hostage", "mystery", "twist", "spy", "secret", "amnesia",
                     "murder", "neo-noir", "whodunit", "paranoia", "cat and mouse"],
    },
    "nostalgic": {
        "display": "Nostalgic", "colour": "#D9A66B",
        "description": "Classics, childhood, memories",
        "genres": {"Family": 0.4, "Music": 0.3, "Western": 0.6, "History": 0.3},
        "keywords": ["childhood", "nostalgia", "coming of age", "1950s", "1960s",
                     "1970s", "1980s", "high school", "summer camp", "memory",
                     "flashback", "small town", "teenager", "first love"],
        # classics also get a bonus by release year (see build_dataset.py)
    },
    "adventurous": {
        "display": "Adventurous", "colour": "#2EC4B6",
        "description": "Quests and new worlds",
        "genres": {"Adventure": 2.0, "Fantasy": 0.9, "Science Fiction": 0.7, "Western": 0.4},
        "keywords": ["quest", "treasure", "journey", "exploration", "island", "jungle",
                     "space travel", "pirate", "expedition", "magic", "dragon",
                     "time travel", "desert", "mountain", "survival", "road trip"],
    },
    "dark": {
        "display": "Dark", "colour": "#5C5C70",
        "description": "Bleak, gritty, disturbing",
        "genres": {"Crime": 0.8, "Thriller": 0.6, "Horror": 0.6, "War": 0.5, "Drama": 0.2},
        "keywords": ["dystopia", "post-apocalyptic", "psychopath", "obsession", "neo-noir",
                     "dark comedy", "drug addiction", "murder", "serial killer", "torture",
                     "corruption", "nihilism", "despair", "madness", "violence"],
    },
}

EMOTION_KEYS = list(EMOTIONS.keys())


# ---------------------------------------------------------------------------
# MOOD SHIFT  -  "Right now I feel ___"  (how the viewer feels BEFORE watching)
# ---------------------------------------------------------------------------
# Research on affective recommendation separates the viewer's current mood
# from the feeling they want. When someone feels low, a sudden jump to a
# loud, intense film is often not what helps. For each current mood we list
#   bridge : feelings that gently help move from this mood
#   avoid  : feelings that usually make this mood worse
# shift score = 0.6 x mean(bridge feelings) + 0.4 x (1 - strongest avoid feeling)
CURRENT_MOODS = {
    "sad":      {"display": "Sad",      "bridge": ["hopeful", "happy", "relaxed"],    "avoid": ["dark", "scary", "sad"]},
    "stressed": {"display": "Stressed", "bridge": ["relaxed", "funny", "happy"],      "avoid": ["suspenseful", "dark", "scary"]},
    "angry":    {"display": "Angry",    "bridge": ["relaxed", "funny", "hopeful"],    "avoid": ["angry", "dark"]},
    "anxious":  {"display": "Anxious",  "bridge": ["relaxed", "happy"],               "avoid": ["scary", "suspenseful", "dark"]},
    "lonely":   {"display": "Lonely",   "bridge": ["emotional", "romantic", "hopeful"], "avoid": ["dark"]},
    "tired":    {"display": "Tired",    "bridge": ["relaxed", "funny"],               "avoid": ["suspenseful", "dark"]},
    "bored":    {"display": "Bored",    "bridge": ["excited", "adventurous", "funny"], "avoid": ["relaxed"]},
}


# ---------------------------------------------------------------------------
# Normalisation helpers - accept anything the user/website might send
# ---------------------------------------------------------------------------
def _clean(text):
    return re.sub(r"[^a-z0-9]", "", str(text).lower())


_GENRE_ALIASES = {_clean(g): g for g in GENRES}
_GENRE_ALIASES.update({"scifi": "Science Fiction", "sciencefiction": "Science Fiction",
                       "sf": "Science Fiction", "kids": "Family", "musical": "Music",
                       "historical": "History", "romcom": "Romance"})
_EMOTION_ALIASES = {_clean(k): k for k in EMOTIONS}
_EMOTION_ALIASES.update({_clean(v["display"]): k for k, v in EMOTIONS.items()})
_EMOTION_ALIASES.update({"exciting": "excited", "inspirational": "inspiring",
                         "inspired": "inspiring", "scared": "scary", "fear": "scary",
                         "romance": "romantic", "comedy": "funny", "calm": "relaxed",
                         "suspense": "suspenseful", "adventure": "adventurous"})
_AUDIENCE_ALIASES = {_clean(k): k for k in AUDIENCES}
_AUDIENCE_ALIASES.update({"kid": "kids", "children": "kids", "child": "kids",
                          "teen": "teenagers", "teens": "teenagers", "adult": "adults",
                          "senior": "seniors", "all": "everyone"})


def normalize_genre(value):
    return _GENRE_ALIASES.get(_clean(value))


def normalize_emotion(value):
    return _EMOTION_ALIASES.get(_clean(value))


def normalize_audience(value):
    return _AUDIENCE_ALIASES.get(_clean(value))


def normalize_current_mood(value):
    v = _clean(value)
    aliases = {"low": "sad", "down": "sad", "upset": "sad", "depressed": "sad", "tense": "stressed",
               "worried": "anxious", "nervous": "anxious", "alone": "lonely", "sleepy": "tired",
               "exhausted": "tired", "mad": "angry", "frustrated": "angry"}
    v = aliases.get(v, v)
    return v if v in CURRENT_MOODS else None


def options_payload():
    """Everything the website needs to build its pickers."""
    return {
        "current_moods": [{"key": k, "label": v["display"]} for k, v in CURRENT_MOODS.items()],
        "audiences": [{"key": k, "label": v[0], "max_level": v[1], "description": v[2]}
                      for k, v in AUDIENCES.items()],
        "emotions": [{"key": k, "label": v["display"], "colour": v["colour"],
                      "description": v["description"]} for k, v in EMOTIONS.items()],
        "genres": [{"key": g, "label": GENRE_DISPLAY.get(g, g)} for g in GENRES],
        "languages": [{"key": k, "label": v} for k, v in LANGUAGES.items()],
        "levels": LEVEL_NAMES,
    }
