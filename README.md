# RAGS CineMind (main project)

An AI-powered personalised movie recommendation system based on audience suitability,
emotional context and the user's own taste.

This is the **main project**, a fresh build. Your prototype folder
(`Personalized_Movie_Recommendation_System`) is untouched and stays as the frozen reference.

---

## 1. What's in this folder

```
RAGS_final/
├── app.py                  starts the server (website + API together)
├── wsgi.py                 entry point for hosting (PythonAnywhere / Render)
├── requirements.txt        Python packages to install
├── cinemind/               the backend
│   ├── labels.py           ONE shared list of audiences, 15 emotions, moods, genres, languages + labelling rules
│   ├── catalog.py          loads movies, builds the TF-IDF content model once at start-up
│   ├── cf.py               collaborative filtering ("people who liked X also liked Y")
│   ├── engine.py           the hybrid recommender (filters -> scores -> diversity -> explanations),
│   │                       Watch Together, mood shift and OTT-platform filter
│   ├── watch.py            "Where to watch in India" (OTT platforms, from TMDB / JustWatch)
│   ├── images.py           poster/backdrop proxy + local image cache
│   ├── nlu.py              turns a sentence ("funny family movie under 2 hours") into filters
│   ├── genie.py            RAGS Genie chat assistant (optional Google Gemini)
│   ├── smalltalk.py        Genie's built-in conversation skills
│   ├── db.py               SQLite database: users, likes, ratings, watchlist, history, OTT apps
│   ├── auth.py             sign up / log in / log out (hashed passwords)
│   └── api.py              all /api/... endpoints
├── frontend/               the website (HTML, CSS, JavaScript, no build tools)
│   ├── index.html
│   ├── css/style.css
│   ├── fonts/              Bricolage Grotesque + Manrope (bundled, work offline; SIL OFL licence)
│   └── js/  app.js (pages)  api.js (server calls)  ui.js (cards, 3D tilt)  genie.js (chat panel)
├── scripts/                run these yourself, once
│   ├── build_dataset.py    builds data/movies.csv from the TMDB files
│   ├── enrich_tmdb.py      adds real posters, trailers, age certificates, Indian films (needs TMDB key)
│   ├── build_cf_model.py   downloads MovieLens ratings, builds the collaborative-filtering table
│   ├── evaluate.py         measures Precision / Recall / NDCG and audience-rule accuracy
│   ├── cache_posters.py    saves posters (and popular backdrops) so they load with no internet
│   └── fetch_watch_providers.py  downloads where-to-watch data for India
├── data/
│   ├── raw/                original TMDB 5000 CSV files
│   ├── movies.csv          the catalogue the app uses (5,278 movies)
│   ├── image_cache/        saved posters and backdrops
│   ├── watch_providers.json  OTT availability (India)
│   └── dataset_report.json real counts for your report
├── instance/               private: database, secret key, optional gemini_key.txt (never share)
├── reports/                evaluation results
└── tests/test_cinemind.py  33 automated tests
```

---

## 2. Run it on your Mac (first time, about 5 minutes)

Open **Terminal** (or the VS Code terminal) and type these lines one at a time.

```bash
# 1. go into the project folder (drag the folder onto Terminal to paste its path)
cd ~/Documents/RAGS_final

# 2. create a private Python environment for this project (only the first time)
python3 -m venv .venv

# 3. switch it on (do this every time you open a new Terminal)
source .venv/bin/activate

# 4. install the packages (only the first time)
pip install -r requirements.txt

# 5. start CineMind
python3 app.py
```

You should see `RAGS CineMind is ready` and `Movies loaded : 5278`.
Now open **http://127.0.0.1:5000** in Chrome or Safari.

- You no longer need Live Server. Flask serves the website itself.
- To stop the server, press `Ctrl + C` in the Terminal.
- Always run `python3 app.py` from **inside** the `RAGS_final` folder.

---

## 3. Upgrades to run once (in this order)

The app works without these steps. Each one adds real data. After each one, stop the server
(`Ctrl + C`) and start it again with `python3 app.py`.

### Step A: real posters, trailers, age certificates and Indian movies

1. Create a free account at themoviedb.org. Then go to **Settings → API**, request a
   Developer key, and copy the **API Key**.
2. In Terminal (with `.venv` switched on):

```bash
export TMDB_API_KEY="paste-your-key-here"
python3 scripts/enrich_tmdb.py --indian 150
python3 scripts/build_dataset.py
```

This takes about 10–15 minutes. It adds the 150 most-voted Hindi, Telugu, Tamil, Malayalam
and Kannada films, plus official certificates (U/UA/A in India, G/PG/PG-13/R in the US).
If the internet drops, run the same command again and it continues where it stopped.
**Never paste your key into any frontend file.**

### Step B: collaborative filtering from real users (MovieLens)

```bash
python3 scripts/build_cf_model.py
```

This downloads about 100,000 real ratings from GroupLens and saves `data/cf_neighbors.json`.

### Step C: evaluation (the numbers for your report)

```bash
python3 scripts/evaluate.py
```

Results go to `reports/evaluation_results.md`. **Only use numbers that this script produces.**
It also saves the best CF/content mix to `data/personal_mix.json`, and the app uses it
automatically on the next start.

### Step D: save posters and backdrops (so the demo works offline)

```bash
caffeinate -i python3 scripts/cache_posters.py --top-backdrops 500
```

Saves every poster (about 230 MB) plus the big background pictures of the 500 most popular
movies (about 100 MB), which covers every Spotlight and "Popular right now" movie. It skips
files already saved, so you can run it again any time.

### Step E: where to watch (OTT platforms in India)

```bash
python3 scripts/fetch_watch_providers.py --region IN
```

Uses the same TMDB key as Step A. Data by JustWatch, so keep the JustWatch credit in the footer.

---

## 4. Run the tests

```bash
python3 -m unittest discover tests -v
```

All 33 tests should say `ok`. Among other things, they check every audience × emotion
combination (6 × 15 = 90) and confirm that no unsuitable movie is ever shown.

---

## 5. Put it online: PythonAnywhere (free, recommended)

PythonAnywhere keeps your files, so user accounts and history are **not** wiped.
The free plan gives 1 web app and 512 MB of disk, and the app must be renewed once a month.

1. Sign up at pythonanywhere.com (free Beginner account). Your site will be
   `https://YOURNAME.pythonanywhere.com`.
2. On your Mac, zip the project **without** `.venv`, `instance` and `data/raw`. Those aren't
   needed on the server and keep the upload small. (Free disk is 512 MB: posters + 500
   backdrops + data fit; don't run Step D with `--backdrops` for every movie.)
3. **Files** tab → upload the zip into `/home/YOURNAME/`.
4. **Consoles** tab → start a **Bash** console and run:
   ```bash
   unzip RAGS_final.zip
   cd RAGS_final
   pip3 install --user -r requirements.txt
   ```
5. **Web** tab → **Add a new web app** → **Manual configuration** → pick the newest Python version.
6. On the same page, click the **WSGI configuration file** link. Delete everything in it and paste this:
   ```python
   import os, sys
   path = "/home/YOURNAME/RAGS_final"
   if path not in sys.path:
       sys.path.insert(0, path)
   os.chdir(path)
   os.environ["COOKIE_SECURE"] = "1"
   from wsgi import app as application
   ```
   Replace `YOURNAME` with your username, then click **Save**.
7. Back on the **Web** tab, press **Reload**. Then open your site.
8. Every month, open the Web tab and click **"Run until 1 month from today"** so the site stays on.

If something fails, the **Error log** link on the Web tab shows the reason.

### Alternative: Render.com

`render.yaml` is included. Push the folder to GitHub, then on Render choose
**New → Blueprint** and pick the repository.
Warning: on Render's free plan the app sleeps after 15 minutes without visitors, and the
SQLite database is wiped on every restart or sleep. Use it only for a quick demo.

---

## 6. How the recommendation works (short version)

```
 Website (frontend/)  ──POST /api/recommend──►  Flask (app.py, api.py)
                                                   │
          ┌────────────────────────────────────────┘
          ▼
 1. HARD FILTERS  content level ≤ audience limit (never relaxed),
                  language, runtime, era, ≥20 votes, not disliked/watched
 2. SCORES (0–1)  genre · emotion · description (TF-IDF) · similar-to ·
                  your taste (content + collaborative filtering) · quality
                  final = weighted sum of the active scores  →  match %
 3. DIVERSITY     Maximal Marginal Relevance re-ranking
 4. EXPLAIN       reasons + per-score breakdown shown on every movie
          │
          ▼
 SQLite (instance/cinemind.db): users, likes, ratings, watchlist, history
```

- **Emotion profile:** each of the 15 emotions has genre weights and evidence keywords
  (see `cinemind/labels.py`). Each movie gets a 0–1 score for every emotion, and the
  website shows the evidence words behind it.
- **Audience safety:** official certificates are used when available (Step A). Otherwise a
  cautious rule applies. Animation alone never makes a movie kid-safe, and unknown
  live-action films default to Teen.
- **Collaborative filtering:** item-to-item adjusted cosine similarity built from
  MovieLens ratings (Step B), plus likes from CineMind users. The two sources are combined.

- **Watch Together:** up to 4 people, each with an age group and a feeling. The strictest
  age group decides what is suitable. Group feeling score = 0.6 × average + 0.4 × lowest,
  so no one is left out.
- **Mood shift ("Right now I feel"):** instead of matching a bad mood, CineMind scores
  movies that bridge to a better one: 0.6 × bridge feelings + 0.4 × (1 − feelings to avoid).
- **My OTT apps:** pick your streaming apps; movies on them come first, with badges.
- **Ask bar and RAGS Genie:** a rule-based language parser (`cinemind/nlu.py`) turns a
  sentence into the same filters. RAGS Genie (`cinemind/genie.py`) is a chat assistant on
  every page that uses this parser and the same engine, so every movie it suggests is real
  and explained.

### RAGS Genie: built-in chat + optional Google Gemini

RAGS Genie always works on its own: it understands movie requests (`nlu.py`) and also
chats (`smalltalk.py`): greetings, "how are you", jokes, movie facts from our own
database, its favourite films, kind replies when you had a bad day, and polite answers
to off-topic questions.

With a free Gemini API key (Google AI Studio → Get API key), Genie becomes a real
conversational AI: Gemini holds the chat and remembers the last 6 messages. When you want
movies, Gemini only passes your wishes to CineMind's engine, so every movie shown is
real, age-safe and explained. Any title Gemini names that is not in our catalogue is
never shown as a movie card. If the internet or the key fails, Genie quietly uses the
built-in brain.

Save the key once (it stays private: `instance/` is never uploaded or shared):

```bash
echo "paste-your-key-here" > instance/gemini_key.txt
python3 app.py
```

The start-up box then shows `RAGS Genie brain : built-in + Gemini`, and the chat panel
says "Built-in + Gemini". Never put the key in the website code.

---

## 7. Honest status

| Feature | Status |
|---|---|
| Shared label vocabulary (fixes prototype mismatches) | Done, tested |
| 6 audiences, 15 emotions, 18 genres, language, runtime, era, free-text description | Done, tested |
| Hybrid engine with explanations and diversity | Done, tested |
| Login, likes, dislikes, ratings, watchlist, watched, search and view history | Done, tested |
| Personal home rows, taste profile, "Because you liked…" | Done, tested |
| In-app collaborative filtering from CineMind users' likes | Done, tested |
| Real posters, trailers, official certificates, 742 Indian films | Done (Step A run) |
| MovieLens collaborative filtering | Done (Step B run) |
| Evaluation numbers (P@10, R@10, NDCG@10, audience accuracy) | Done (Step C run, see `reports/`) |
| Where to watch in India (3,460 movies) with OTT filter and badges | Done, tested |
| Watch Together (up to 4 people), mood shift, occasions, Ask bar, Spotlight | Done, tested |
| RAGS Genie chat (built-in + optional Gemini), side panel and full screen | Done, tested |
| Dark rustic theme, bundled fonts, 3D poster tilt, mobile layout | Done, checked in browser |
| Online deployment | Config done. **You follow section 5** |

---

## 8. Troubleshooting

| Problem | Fix |
|---|---|
| `ModuleNotFoundError: flask` (or pandas) | Switch on the environment (`source .venv/bin/activate`), then `pip install -r requirements.txt` |
| `Address already in use` or a blank 403 page on port 5000 | macOS AirPlay Receiver uses port 5000. Run `PORT=5050 python3 app.py` and open http://127.0.0.1:5050, or turn off AirPlay Receiver in System Settings → General → AirDrop & Handoff |
| `Missing .../data/raw/tmdb_5000_movies.csv` | Copy the two TMDB CSV files into `data/raw/` |
| `TMDB said 401 Unauthorized` | The key is wrong or not set. Run the `export TMDB_API_KEY=...` line again |
| Website says "Can't reach the CineMind server" | The Terminal running `python3 app.py` was closed. Start it again |
| Spotlight or details show no background picture | That backdrop isn't saved yet. Run Step D, or connect to the internet once |
| RAGS Genie says "Built-in brain" after adding a key | `instance/gemini_key.txt` must contain only the key (no quotes or spaces). Restart `python3 app.py` |
| Want a quick public link (e.g. to show on a phone) | In a second terminal: `cd ~` then `./cloudflared tunnel --url http://127.0.0.1:5000`. The link changes each time and works only while both terminals run |

## Data sources and credits

- TMDB 5000 Movie Dataset, and the TMDB API for posters, trailers and certificates. This product
  uses the TMDB API but is not endorsed or certified by TMDB.
- MovieLens latest-small: F. Maxwell Harper and Joseph A. Konstan. 2015. *The MovieLens Datasets:
  History and Context.* ACM TiiS 5(4).
