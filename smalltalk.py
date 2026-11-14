"""
smalltalk.py  -  RAGS Genie's built-in conversation skills
==========================================================

Lets the Genie chat like a friendly person, with no internet or AI service:
greetings, "how are you", who made it, jokes, movie trivia from our own
database, its "favourite" films, kindness when someone had a bad day,
compliments, goodbyes, and a polite answer to off-topic questions.

respond(text, genie_state, catalog) -> dict or None
    None means "this is not small talk" and the Genie treats the message as a
    movie request instead.

Every movie mentioned here comes from the CineMind catalogue, so nothing is
made up. (When a Gemini key is set, genie.py lets Gemini chat instead and
uses these replies only as the fallback.)
"""

import random
import re

import numpy as np

from . import labels

pick = random.choice

START = ["Something funny for my family", "I'm feeling low, cheer me up",
         "Movies like Interstellar", "A Telugu thriller under 2 hours"]

JOKES = [
    "Why did the movie fan bring a ladder to the cinema? They heard the film had a **high** rating. 🪜",
    "I tried to watch a movie about a broken pencil... it had no point. ✏️",
    "Why don't horror films ever get cold? They're full of chills. 🥶",
    "My friend asked if I'd seen *Titanic*. I said yes, it was a sinking feeling. 🚢",
    "Why was the popcorn so good at exams? It always knew how to pop the answer. 🍿",
    "I'd tell you a joke about a time-travel movie, but you didn't like it. ⏳",
    "Why did the scarecrow win an award? He was outstanding in his field... and in the credits. 🌾",
    "What's a ghost's favourite kind of movie? A boo-graphy. 👻",
    "Why are movie theatres always so cool? They're full of fans. 🎬",
    "I asked the cinema for a seat near the front. They said they'd see what they could row. 💺",
]

# (pattern, kind). Checked in order; the first match wins.
PATTERNS = [
    (r"^(hi+|hey+|hello+|hii+|yo|namaste|good (morning|afternoon|evening))\b[\s!.]*(genie|there|bro|bud|buddy)?[\s!.]*$", "greet"),
    (r"\b(how are (you|u)|how r u|how('?s| is) it going|how('?s| is) your day|what'?s up|wassup|sup)\b", "how_are_you"),
    (r"\b(who|what) (made|created|built|developed|designed) (you|this|cinemind)|\byour (creator|developers?|makers?)\b|who (are|is) (the )?(team|developers?)", "creator"),
    (r"\b(are you|r u) (a |an )?(real|human|person|bot|robot|ai|machine|chat ?gpt|alive)\b", "are_you_ai"),
    (r"\b(who are you|what are you|what('?s| is) your name|your name)\b", "who"),
    (r"\b(joke|jokes|make me laugh|say something funny)\b", "joke"),
    (r"\b(fun fact|trivia|movie fact|another fact|more facts?|something interesting|did you know)\b", "fact"),
    (r"\b(your|ur) (fav(ou?rite)?|best|top) (movie|film)s?\b|what (movie|film)s? do you (like|love)|best (movie|film) (ever|of all time)|greatest (movie|film)", "favourite"),
    (r"\b(bad|rough|tough|long|terrible|awful|horrible) (day|week)\b|\b(heart ?broken|break ?up|broke up|failed|i'?m (so )?(sad|upset|tired|exhausted|lonely|bored|stressed|depressed|down))\b|\bnot feeling (good|well|great)\b", "bad_day"),
    (r"\b(good|great|awesome|amazing|happy|fantastic) (day|news)\b|\bi'?m (so )?(happy|excited|great|good)\b|\b(i passed|got (a |the )?job|got selected)\b", "good_day"),
    (r"\b(you'?re|you are|ur|u r) (so )?(great|awesome|amazing|smart|cool|the best|good|nice|helpful|genius)\b|\b(good|nice|great) (bot|job|genie)\b|\b(love|like) you\b", "compliment"),
    (r"\b(you'?re|you are|ur|u r) (so )?(stupid|dumb|useless|bad|slow|boring|annoying)\b|\b(bad|stupid|useless) (bot|genie)\b", "insult"),
    (r"\b(bye+|good ?bye|good night|gn|see (you|ya)|talk later|cya|ttyl)\b", "bye"),
    (r"\b(how old are you|your age|where do you live|where are you from|do you sleep|do you eat)\b", "about_me"),
]

DECLINES = {"no", "no thanks", "nope", "not now", "just talk", "nah", "no thank you", "maybe later"}
ACCEPTS = {"yes", "yeah", "yes please", "sure", "ok", "okay", "yep", "please", "go ahead", "yes, cheer me up", "cheer me up"}

QUESTION = re.compile(r"\?\s*$|^(what|who|why|when|where|how|which|can|could|do|does|did|is|are|will|would|should)\b")


def _title(cat, row):
    r = cat.df.iloc[row]
    return f"**{r['title']}** ({int(r['year'])})"


def favourites(cat, n=10, max_level=2):
    """Well-loved movies: high rating with many votes, suitable for most viewers."""
    df = cat.df
    score = df["rating"].to_numpy() * np.log10(df["vote_count"].to_numpy() + 10)
    ok = (df["content_level"].to_numpy() <= max_level) & (df["vote_count"].to_numpy() >= 3000)
    rows = [int(r) for r in np.argsort(-score) if ok[r]][:n]
    return rows


def fact(cat):
    """A true fact computed from the CineMind catalogue."""
    df = cat.df
    kind = pick(["oldest", "longest", "votes", "indian", "count", "shortest", "emotion"])
    if kind == "oldest":
        r = int(df["year"].to_numpy().argmin())
        return f"The oldest film in my collection is {_title(cat, r)}. Still loved after all these years! 🎞️", [r]
    if kind == "longest":
        r = int(df["runtime"].to_numpy().argmax())
        return f"The longest film I know is {_title(cat, r)} at {int(df.iloc[r]['runtime'])} minutes. Bring snacks! 🍿", [r]
    if kind == "shortest":
        ok = np.flatnonzero(df["runtime"].to_numpy() >= 60)
        r = int(ok[df["runtime"].to_numpy()[ok].argmin()])
        return f"Short on time? {_title(cat, r)} runs just {int(df.iloc[r]['runtime'])} minutes. ⏱️", [r]
    if kind == "votes":
        r = int(df["vote_count"].to_numpy().argmax())
        return (f"The most-rated film in my collection is {_title(cat, r)}, with "
                f"{int(df.iloc[r]['vote_count']):,} votes on TMDB. 🗳️"), [r]
    if kind == "indian":
        indian = df["language"].isin(["hi", "te", "ta", "ml", "kn", "bn", "mr", "pa"]).to_numpy()
        idx = np.flatnonzero(indian & (df["vote_count"].to_numpy() >= 200))
        if len(idx):
            r = int(idx[df["rating"].to_numpy()[idx].argmax()])
            return (f"I know {int(indian.sum()):,} Indian films. The best rated one with enough votes is {_title(cat, r)}, "
                    f"at {df.iloc[r]['rating']}/10. 🇮🇳"), [r]
    if kind == "emotion":
        key = pick(labels.EMOTION_KEYS)
        i = labels.EMOTION_KEYS.index(key)
        r = int(cat.emotion_matrix[:, i].argmax())
        return (f"If you want to feel **{labels.EMOTIONS[key]['display'].lower()}**, my strongest match is "
                f"{_title(cat, r)}. I score every film on 15 feelings! 🎨"), [r]
    return (f"I know {len(df):,} movies in {df['language'].nunique()} languages, and I score each one on 15 feelings "
            "like happy, scary and nostalgic. 🎬"), []


def respond(text, state, cat):
    """Built-in small talk. Returns {reply, suggestions, movie_rows, set_mood} or None."""
    low = re.sub(r"\s+", " ", text.lower()).strip()
    plain = low.strip(" !.?")

    # answers to the Genie's own offer ("Want something to cheer you up?")
    if state.get("offer") and plain in ACCEPTS:
        return None                                    # genie.py turns the offer into a recommendation
    if state.get("offer") and plain in DECLINES:
        state.pop("offer", None)
        return {"reply": pick(["No problem. I'm right here if you change your mind 🧞",
                               "Okay! Sometimes just talking helps too. I'm here whenever you want a movie 💛"]),
                "suggestions": ["Tell me a joke", "Fun movie fact", "Show me something relaxing"]}

    kind = next((k for p, k in PATTERNS if re.search(p, low)), None)
    if kind is None:
        return None
    out = _answer(kind, low, state, cat)
    if out:
        out["kind"] = kind
    return out


def _answer(kind, low, state, cat):
    if kind == "greet":
        return {"reply": pick(["Hey there! 👋 I'm RAGS Genie. How's your day going? Tell me how you want to feel and I'll find the perfect movie.",
                               "Hello! 🧞 Your wish is my command. What kind of movie are you in the mood for?",
                               "Hi! 😊 Ready for a great movie? Tell me who's watching and how you'd like to feel."]),
                "suggestions": START}
    if kind == "how_are_you":
        return {"reply": pick([f"I'm doing great, thanks for asking! 😊 I just finished sorting {len(cat.df):,} movies by feeling, so I'm in a cheerful mood. How about you?",
                               "Feeling magical as always ✨ Living in a lamp full of movies isn't bad! How's your day been?",
                               "All good here! 🧞 Ready to grant some movie wishes. How are you feeling today?"]),
                "suggestions": ["I'm good!", "I had a bad day", "I'm bored"]}
    if kind == "creator":
        return {"reply": ("I was built by the RAGS CineMind team: **Chandra Abhiram Reddy**, **Gannoj Brahma Teja** and "
                          "**Medikonda Raga Spandana**, IV CSE (AI & ML) students at AVIT, guided by **Dr. Ramu K**. 🎓 "
                          "They taught me to match movies to how you feel, who's watching and what you love."),
                "suggestions": ["What can you do?", "How do you pick movies?", "Tell me a joke"]}
    if kind == "are_you_ai":
        return {"reply": ("I'm an AI movie assistant, not a person 🤖 I understand what you type, then CineMind's recommendation "
                          "engine scores thousands of real movies for you. Every pick I show is a real film with a reason."),
                "suggestions": ["What can you do?", "Surprise me with a movie"]}
    if kind == "who":
        return {"reply": "I'm **RAGS Genie** 🧞, the movie assistant of RAGS CineMind. Tell me your mood, who's watching or a film you love, and I'll grant you the perfect movie.",
                "suggestions": START}
    if kind == "joke":
        return {"reply": pick(JOKES) + " Want another one, or shall I find you a comedy?",
                "suggestions": ["Another joke", "Find me a comedy", "Fun movie fact"]}
    if kind == "fact":
        reply, rows = fact(cat)
        return {"reply": reply, "movie_rows": rows, "suggestions": ["Another fact", "Tell me a joke", "Movies like this"]}
    if kind == "favourite":
        rows = random.sample(favourites(cat), 3)
        names = ", ".join(_title(cat, r) for r in rows[1:])
        return {"reply": (f"Tough one! A genie can't pick just one 😄 Right now I'd say {_title(cat, rows[0])}. "
                          f"I also love {names}. All are loved by thousands of viewers."),
                "movie_rows": rows, "suggestions": ["Why the first one?", "Where can I watch the first one?", "Something different"]}
    if kind == "bad_day":
        mood = "sad"
        if re.search(r"tired|exhausted|long day", low):
            mood = "tired"
        elif re.search(r"stress|exam|work|college|office", low):
            mood = "stressed"
        elif re.search(r"lonely|alone", low):
            mood = "lonely"
        elif re.search(r"bored", low):
            mood = "bored"
        state["offer"] = mood
        lines = {
            "sad": "I'm sorry you're feeling down 💛 That's okay, everyone has days like that.",
            "tired": "Sounds like a long day 😴 You deserve to put your feet up.",
            "stressed": "That sounds stressful 😮‍💨 Take a deep breath, you made it through the day.",
            "lonely": "I'm here with you 💛 A good movie can feel like good company.",
            "bored": "Boredom? Not on my watch! 🎬",
        }
        return {"reply": lines[mood] + " Want me to find something that will gently lift your mood?",
                "suggestions": ["Yes, cheer me up", "Something relaxing", "Just talk"]}
    if kind == "good_day":
        return {"reply": pick(["That's wonderful! 🎉 Let's keep the good mood going. Want something fun or exciting to celebrate?",
                               "Love to hear that! 😄 Shall I find a movie to make the day even better?"]),
                "suggestions": ["Something exciting", "Something funny", "A feel-good movie"]}
    if kind == "compliment":
        return {"reply": pick(["Aww, thank you! 😊 You just made this genie's lamp glow brighter ✨",
                               "Thank you! 🧞 Granting movie wishes is my favourite thing to do."]),
                "suggestions": ["Show me more", "Surprise me with a movie"]}
    if kind == "insult":
        return {"reply": "Oops, sorry I missed the mark 😅 Tell me a bit more, like a feeling, a language or a movie you love, and I'll try again.",
                "suggestions": START}
    if kind == "bye":
        return {"reply": pick(["Bye! Enjoy your movie 🍿 Come back anytime.", "See you soon! 🧞 Happy watching."]),
                "suggestions": []}
    if kind == "about_me":
        return {"reply": pick(["I'm as old as this project, and I live inside the CineMind lamp 🧞 I don't eat, but I'd never say no to popcorn 🍿",
                               "I live in a lamp full of movies 🪔 No sleep needed. I'm always ready for your next movie night!"]),
                "suggestions": ["Tell me a joke", "Find me a movie"]}
    return None


def off_topic(text):
    """A polite answer for questions that have nothing to do with movies."""
    if QUESTION.search(text.strip().lower()):
        return {"reply": pick(["That's outside my lamp, I'm afraid 🧞 I only know movies, but I know them really well! "
                               "Want a recommendation?",
                               "Good question! But I'm a movie genie, so I'll leave that to the experts 😄 Shall I find you a movie instead?"]),
                "suggestions": START}
    return None
