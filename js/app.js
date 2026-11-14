// =====================================================================
// app.js - pages, routing, login, and the movie details sheet
// Pages are switched with the URL hash:  #/  #/discover  #/search
// #/me  #/about   (no page reloads, no build tools needed)
// =====================================================================

import { api } from "./api.js";
import { $, $$, esc, icon, setLight, toast, runtime, timeAgo, cardHTML, posterHTML, skeletonGrid, setPlatformLogos, enableTilt } from "./ui.js";
import { initGenie, askGenie } from "./genie.js";

const freshPrefs = () => ({
  audience: state.user?.default_audience || "adults", emotions: [], genres: [], languages: [],
  max_runtime: 0, era: "any", query: "", group: [], current_mood: "", seed_movie_id: null,
  platforms: state.prefs?.platforms || [],               // your OTT apps stay chosen
});

const state = {
  user: null,
  options: null,
  lastResults: new Map(),        // movie id -> recommendation (keeps the score breakdown)
  together: false,               // Watch Together (group) mode on the Discover page
  understood: [],                // what the Ask bar understood from your sentence
  prefs: null,
};
state.prefs = freshPrefs();

const view = $("#view");
const emotionByKey = (k) => state.options.emotions.find((e) => e.key === k);
const audienceLabel = (k) => state.options.audiences.find((a) => a.key === k)?.label || k;
const GENRE_LABEL = (g) => state.options.genres.find((x) => x.key === g)?.label || g;

// ---------------------------------------------------------------------
// start
// ---------------------------------------------------------------------
async function boot() {
  try {
    const [options, me] = await Promise.all([api.options(), api.me()]);
    state.options = options;
    setPlatformLogos(options.platform_logos);
    setUser(me.user);
  } catch (e) {
    view.innerHTML = `<section class="page"><div class="empty"><h3>CineMind can't load</h3>
      <p>${esc(e.message)}</p></div></section>`;
    return;
  }
  if (!state.user) {
    try { state.prefs.platforms = JSON.parse(localStorage.getItem("cinemind.platforms") || "[]"); } catch { /* ignore */ }
  }
  enableTilt();
  initGenie({ onRemember: (m) => state.lastResults.set(m.id, m), getOptions: () => state.options });
  window.addEventListener("hashchange", route);
  document.addEventListener("click", onGlobalClick);
  route();
}

function setUser(user) {
  state.user = user;
  if (user?.default_audience) state.prefs.audience = user.default_audience;
  if (user?.platforms?.length) state.prefs.platforms = [...user.platforms];
  const box = $("#account");
  if (user) {
    box.innerHTML = `<a class="avatar" href="#/me" title="My movies">${esc(user.display_name[0]?.toUpperCase() || "?")}</a>
      <button class="btn btn-ghost" id="logoutBtn">Log out</button>`;
    $("#logoutBtn").onclick = async () => {
      await api.logout();
      setUser(null);
      toast("Logged out");
      location.hash = "#/";
    };
  } else {
    box.innerHTML = `<button class="btn btn-ghost" data-auth="login">Log in</button>
      <button class="btn btn-primary" data-auth="register">Sign up</button>`;
  }
}

function route() {
  const [path, query] = location.hash.replace(/^#\/?/, "").split("?");
  const params = new URLSearchParams(query || "");
  $$(".nav a").forEach((a) => a.classList.toggle("active", a.dataset.nav === (path || "home")));
  const pages = { "": home, discover, search, me, about };
  const page = pages[path] || home;
  if (path !== "discover") setLight(null);
  window.scrollTo({ top: 0 });
  page(params);
  view.focus({ preventScroll: true });
}

function onGlobalClick(e) {
  const card = e.target.closest("[data-movie]");
  if (card) {
    const from = card.querySelector(".poster, .gm-poster") || card;
    openMovie(Number(card.dataset.movie), { from });
    return;
  }
  const auth = e.target.closest("[data-auth]");
  if (auth) openAuth(auth.dataset.auth);
}

// ---------------------------------------------------------------------
// ASK CINEMIND - one sentence -> filters  (used on Home and Discover)
// ---------------------------------------------------------------------
const ASK_EXAMPLES = ["a funny family movie under 2 hours", "I'm stressed, something light on Netflix",
  "a Telugu thriller from the 2010s", "movies like Interstellar", "a romantic movie for date night"];

// (on Discover it sits inside the preferences form, and forms can't be nested, so it is a <div>)
function askHTML(compact = false) {
  const tag = compact ? "div" : "form";
  return `<${tag} class="ask${compact ? " compact" : ""}" data-ask role="search">
      ${icon.search}
      <input type="text" name="ask" maxlength="200" autocomplete="off" aria-label="Describe the movie you want in one sentence"
        placeholder="${compact ? "Or just type it in one line" : `Try: “${ASK_EXAMPLES[0]}”`}">
      <button class="btn btn-primary" type="${compact ? "button" : "submit"}" data-ask-go>Ask</button>
    </${tag}>`;
}

function wireAsk(root) {
  $$("[data-ask]", root).forEach((form) => {
    const input = form.querySelector("input");
    if (!form.classList.contains("compact")) {          // gently rotate example sentences
      let i = 0;
      const t = setInterval(() => {
        if (!document.body.contains(input)) return clearInterval(t);
        if (document.activeElement !== input && !input.value) input.placeholder = `Try: “${ASK_EXAMPLES[++i % ASK_EXAMPLES.length]}”`;
      }, 3500);
    }
    const go = async (e) => {
      e.preventDefault();
      e.stopPropagation();
      const text = input.value.trim();
      if (!text) { input.focus(); return; }
      const btn = form.querySelector("[data-ask-go]");
      btn.disabled = true;
      try {
        const r = await api.ask(text);
        if (r.movie_id && ["where", "about", "why"].includes(r.intent)) {
          openMovie(r.movie_id, { section: r.intent === "where" ? "watch" : null });
          return;
        }
        if (!r.understood.length && !r.prefs.query) {
          toast("I didn't catch that. Try “a funny movie for my family”.", "error");
          return;
        }
        state.prefs = Object.assign(freshPrefs(), r.prefs);
        state.together = false;
        state.understood = r.understood.length ? r.understood : [`“${r.prefs.query}”`];
        if (location.hash.startsWith("#/discover")) discover(new URLSearchParams("run=1"));
        else location.hash = "#/discover?run=1";
      } catch (err) { toast(err.message, "error"); }
      finally { btn.disabled = false; }
    };
    if (form.tagName === "FORM") form.addEventListener("submit", go);
    else {
      form.querySelector("[data-ask-go]").addEventListener("click", go);
      input.addEventListener("keydown", (e) => { if (e.key === "Enter") go(e); });
    }
  });
}

// ---------------------------------------------------------------------
// HOME - headline, ask bar, the spectrum of feelings, occasions, spotlight
// ---------------------------------------------------------------------
const OCCASIONS = [
  { key: "family", label: "Family Sunday", note: "Happy, for all ages", prefs: { audience: "family", emotions: ["happy", "funny"] } },
  { key: "date", label: "Date night", note: "Romantic, under 2½ h", prefs: { audience: "adults", emotions: ["romantic"], max_runtime: 150 } },
  { key: "study", label: "Study break", note: "Light and short", prefs: { emotions: ["funny", "relaxed"], max_runtime: 110 } },
  { key: "festival", label: "Festival time", note: "Big, joyful family films", prefs: { audience: "family", emotions: ["happy", "emotional"], query: "family celebration wedding festival" } },
  { key: "friends", label: "Friends' night", note: "Laughs and action", prefs: { audience: "adults", emotions: ["funny", "excited"] } },
  { key: "rainy", label: "Rainy day", note: "Cosy and nostalgic", prefs: { emotions: ["relaxed", "nostalgic"] } },
  { key: "kids", label: "Kids' party", note: "Fun adventures", prefs: { audience: "kids", emotions: ["funny", "adventurous"] } },
  { key: "late", label: "Late-night thriller", note: "Edge of your seat", prefs: { audience: "adults", emotions: ["suspenseful", "scary"] } },
];

async function home() {
  const emotions = state.options.emotions;
  view.innerHTML = `
    <section class="hero">
      <div class="hero-collage" id="collage" aria-hidden="true"></div>
      <h1>Find me a movie that feels <span class="feeling-word" id="feelingWord">right</span></h1>
      <p>Pick a feeling, or just tell CineMind in your own words.</p>
      ${askHTML()}
      <div class="spectrum" role="group" aria-label="Choose a feeling">
        ${emotions.map((e) => `<button style="--c:${e.colour}" data-feel="${e.key}"
            aria-label="${esc(e.label)}: ${esc(e.description)}"><span>${esc(e.label)}</span></button>`).join("")}
      </div>
      <p class="spectrum-hint">Choose a feeling to see movies for it.</p>
    </section>
    <section class="page" style="padding-top:0">
      <div class="row-block occasions-block">
        <div class="row-head"><h2>Or pick an occasion</h2></div>
        <div class="occasions">${OCCASIONS.map((o) => { const c = emotionByKey(o.prefs.emotions[0]).colour;
          return `<button class="occasion" style="--c:${c}" data-occasion="${o.key}"><b>${esc(o.label)}</b><small>${esc(o.note)}</small></button>`; }).join("")}</div>
      </div>
      <div id="spotlight"></div>
      <div id="personalRows"></div>
      <div class="row-block">
        <div class="row-head"><h2>Popular right now</h2><a class="btn btn-ghost" href="#/discover">Set your own filters</a></div>
        <div class="scroller" id="trending">${skeletonGrid(7)}</div>
      </div>
    </section>`;

  wireAsk(view);
  const word = $("#feelingWord");
  const collage = $("#collage");
  let shown = "";
  const showCollage = (key) => {
    const posters = state.options.emotion_posters?.[key] || [];
    if (!posters.length) return;
    if (shown !== key) {
      collage.innerHTML = posters.map((u, i) => `<img src="${esc(u)}" alt="" style="--n:${i}" onerror="this.remove()">`).join("");
      shown = key;
    }
    collage.classList.add("show");
  };
  $$(".spectrum button").forEach((b) => {
    const e = emotionByKey(b.dataset.feel);
    const preview = () => { word.textContent = e.label.toLowerCase(); setLight(e.colour); showCollage(e.key); };
    b.addEventListener("mouseenter", preview);
    b.addEventListener("focus", preview);
    b.addEventListener("click", () => {
      state.prefs = Object.assign(freshPrefs(), { audience: state.prefs.audience, emotions: [e.key] });
      state.together = false; state.understood = [];
      location.hash = `#/discover?run=1`;
    });
  });
  $(".spectrum").addEventListener("mouseleave", () => { word.textContent = "right"; setLight(null); collage.classList.remove("show"); });

  $$("[data-occasion]").forEach((b) => b.addEventListener("click", () => {
    const o = OCCASIONS.find((x) => x.key === b.dataset.occasion);
    state.prefs = Object.assign(freshPrefs(), o.prefs);
    state.together = false;
    state.understood = [o.label];
    location.hash = "#/discover?run=1";
  }));

  api.trending(state.prefs.audience).then((d) => {
    $("#trending").innerHTML = d.results.map((m) => cardHTML(m)).join("");
    renderSpotlight(d.results);
  }).catch(() => { $("#trending").innerHTML = ""; });

  if (state.user) {
    try {
      const fy = await api.forYou();
      const box = $("#personalRows");
      if (!box) return;
      if (!fy.has_history) {
        box.innerHTML = `<div class="row-block"><div class="empty"><h3>Welcome, ${esc(state.user.display_name)}</h3>
          <p>Like or rate a few movies and this space fills with picks made for you.</p>
          <a class="btn btn-primary" href="#/discover">Find movies to like</a></div></div>`;
      }
      box.innerHTML += fy.rows.map((row) => `<div class="row-block">
          <div class="row-head"><h2>${esc(row.title)}</h2></div>
          <div class="scroller">${row.results.map((m) => { state.lastResults.set(m.id, m); return cardHTML(m); }).join("")}</div>
        </div>`).join("");
    } catch { /* not critical */ }
  }
}

// Spotlight: one popular movie with its backdrop, trailer and where to watch
function renderSpotlight(movies) {
  const box = $("#spotlight");
  if (!box) return;
  const withArt = movies.filter((m) => m.backdrop_url && m.overview).slice(0, 6);
  const pool = withArt.length ? withArt : movies.filter((m) => m.overview).slice(0, 6);
  if (!pool.length) return;
  const withTrailer = pool.filter((m) => m.trailer_key);
  const list = withTrailer.length ? withTrailer : pool;
  const m = list[Math.floor(Math.random() * list.length)];
  const colour = m.top_emotions?.[0]?.colour || "var(--gold)";
  box.innerHTML = `<section class="spotlight" style="--c:${esc(colour)}" aria-label="Spotlight: ${esc(m.title)}">
      ${m.backdrop_url ? `<img class="spot-bg" src="${esc(m.backdrop_url)}" alt="" onerror="this.remove()">` : ""}
      <div class="spot-body">
        <span class="spot-label">Spotlight</span>
        <h2>${esc(m.title)}</h2>
        <p class="spot-meta">${[m.year, m.genres.slice(0, 3).join(", "), m.runtime ? runtime(m.runtime) : "", `★ ${m.rating}`].filter(Boolean).map(esc).join(" · ")}</p>
        <p class="spot-overview">${esc(m.overview)}</p>
        <div class="spot-actions">
          ${m.trailer_key ? `<button class="btn btn-primary" data-spot="play">${icon.play}<span>Play trailer</span></button>` : ""}
          <button class="btn" data-spot="watch">Where to watch</button>
          <button class="btn btn-ghost" data-spot="info">More info</button>
        </div>
      </div>
    </section>`;
  box.querySelector(".spotlight").addEventListener("click", (e) => {
    const b = e.target.closest("[data-spot]");
    if (!b) return;
    const from = box.querySelector(".spotlight");
    openMovie(m.id, { from, play: b.dataset.spot === "play", section: b.dataset.spot === "watch" ? "watch" : null });
  });
}

// ---------------------------------------------------------------------
// DISCOVER - preferences panel + results
// ---------------------------------------------------------------------
const ERAS = [["any", "Any time"], ["classic", "Before 1980"], ["80s90s", "80s & 90s"], ["2000s", "2000s"], ["2010s", "2010 onwards"]];

function discover(params) {
  const o = state.options, p = state.prefs;
  if (!p.group.length) {
    p.group = [{ name: state.user?.display_name?.split(" ")[0] || "Me", audience: p.audience, emotion: p.emotions[0] || "happy" },
               { name: "Friend", audience: "adults", emotion: "excited" }];
  }
  view.innerHTML = `
    <section class="page discover">
      <form class="panel" id="prefsForm" aria-label="Your preferences">
        <h1>What's the plan?</h1>
        ${askHTML(true)}

        <div class="field">
          <div class="field-label">Who's watching</div>
          <div class="segmented mode-switch" id="modeSwitch">
            <button type="button" data-mode="solo" aria-pressed="${!state.together}">One audience</button>
            <button type="button" data-mode="group" aria-pressed="${state.together}">Watch together</button>
          </div>
          <div id="whoBox"></div>
        </div>

        <div class="field" id="feelField">
          <div class="field-label">How you want to feel <small>pick up to 2</small></div>
          <div class="chips">${o.emotions.map((e) => `<button type="button" class="chip mood" style="--c:${e.colour}"
              data-emo="${e.key}" aria-pressed="${p.emotions.includes(e.key)}" title="${esc(e.description)}">
              <span class="dot"></span>${esc(e.label)}</button>`).join("")}</div>
        </div>

        <label class="field mood-now">
          <span class="field-label">Right now I feel <small>optional</small></span>
          <select id="moodNow"><option value="">Skip this</option>
            ${(o.current_moods || []).map((m) => `<option value="${m.key}" ${p.current_mood === m.key ? "selected" : ""}>${esc(m.label)}</option>`).join("")}
          </select>
          <small class="hint" id="moodHint"></small>
        </label>

        <div class="field">
          <div class="field-label">Genre <small>optional, up to 3</small></div>
          <div class="chips">${o.genres.map((g) => `<button type="button" class="chip" data-genre="${esc(g.key)}"
              aria-pressed="${p.genres.includes(g.key)}">${esc(g.label)}</button>`).join("")}</div>
        </div>

        ${o.platforms?.length ? `<div class="field">
          <div class="field-label">My OTT apps <small>${state.user ? "saved to your account" : "saved on this device"}</small></div>
          <div class="chips">${o.platforms.map((x) => `<button type="button" class="chip ott-chip" data-ott="${esc(x.name)}"
              aria-pressed="${p.platforms.includes(x.name)}">${x.logo ? `<img src="${esc(x.logo)}" alt="" onerror="this.remove()">` : ""}${esc(x.name)}</button>`).join("")}</div>
          <p class="audience-note">When you pick apps, CineMind shows movies streaming on them first.</p>
        </div>` : ""}

        <details class="more" ${p.languages.length || p.max_runtime || p.era !== "any" || p.query ? "open" : ""}>
          <summary>More filters</summary>
          <div class="more-body">
            <label class="field"><span class="field-label">Language</span>
              <select id="language"><option value="">Any language</option>
                ${o.languages.map((l) => `<option value="${l.key}" ${p.languages[0] === l.key ? "selected" : ""}>${esc(l.label)}</option>`).join("")}
              </select></label>
            <label class="field"><span class="field-label">Time you have <small id="rtLabel"></small></span>
              <input type="range" id="runtime" min="60" max="250" step="10" value="${p.max_runtime || 250}"></label>
            <div class="field"><div class="field-label">Released</div>
              <div class="segmented" id="era">${ERAS.map(([k, l]) => `<button type="button" data-era="${k}" aria-pressed="${p.era === k}">${l}</button>`).join("")}</div></div>
            <label class="field"><span class="field-label">Describe it <small>optional</small></span>
              <textarea id="query" maxlength="200" placeholder="e.g. a heist with a clever twist, or friendship on a long road trip">${esc(p.query)}</textarea></label>
          </div>
        </details>

        <div class="panel-actions">
          <button class="btn btn-primary" type="submit" id="findBtn">Find movies</button>
          <button class="btn" type="button" id="surpriseBtn" title="Open one strong match at random">${icon.shuffle}<span>Surprise me</span></button>
        </div>
      </form>

      <section aria-live="polite" id="results">
        <div class="empty"><h3>Your picks will appear here</h3>
          <p>Choose who's watching and a feeling, then press Find movies. Or ask
          <button type="button" class="link-btn" id="askGenieLink">RAGS Genie</button> in your own words.</p></div>
      </section>
    </section>`;

  const form = $("#prefsForm");
  wireAsk(form);
  $("#askGenieLink").addEventListener("click", () => askGenie());

  const renderWho = () => {
    $("#feelField").hidden = state.together;
    if (!state.together) {
      const a = o.audiences.find((x) => x.key === p.audience);
      $("#whoBox").innerHTML = `<div class="audience-grid">
          ${o.audiences.map((x) => `<button type="button" data-aud="${x.key}" aria-pressed="${p.audience === x.key}" title="${esc(x.description)}">
            ${icon[x.key] || ""}<span>${esc(x.label)}</span></button>`).join("")}
        </div>
        <p class="audience-note">${esc(a.description)}. Movies above this level are never shown.</p>`;
      return;
    }
    $("#whoBox").innerHTML = `<div class="group-list">
        ${p.group.map((m, i) => `<div class="person" data-person="${i}">
          <input type="text" maxlength="20" value="${esc(m.name)}" aria-label="Name of person ${i + 1}" data-pf="name">
          <select data-pf="audience" aria-label="Age group of ${esc(m.name)}">${o.audiences.map((x) => `<option value="${x.key}" ${m.audience === x.key ? "selected" : ""}>${esc(x.label)}</option>`).join("")}</select>
          <select data-pf="emotion" aria-label="What ${esc(m.name)} wants to feel" style="--c:${emotionByKey(m.emotion)?.colour || "var(--muted)"}">${o.emotions.map((e) => `<option value="${e.key}" ${m.emotion === e.key ? "selected" : ""}>${esc(e.label)}</option>`).join("")}</select>
          ${p.group.length > 2 ? `<button type="button" class="person-remove" data-remove="${i}" aria-label="Remove ${esc(m.name)}">&times;</button>` : "<span></span>"}
        </div>`).join("")}
        ${p.group.length < 4 ? `<button type="button" class="btn btn-ghost add-person" id="addPerson">+ Add a person</button>` : ""}
        <p class="audience-note">Everyone gets a say: picks must suit the youngest viewer, and a movie that leaves one person out scores lower.</p>
      </div>`;
  };

  const updateMood = () => {
    const key = $("#moodNow").value;
    p.current_mood = key;
    const mood = (o.current_moods || []).find((m) => m.key === key);
    $("#moodHint").textContent = mood ? `We'll lift you gently instead of matching "${mood.label.toLowerCase()}".` : "";
  };
  const updateRuntime = () => {
    const v = Number($("#runtime").value);
    p.max_runtime = v >= 250 ? 0 : v;
    $("#rtLabel").textContent = p.max_runtime ? `up to ${runtime(v)}` : "any length";
  };
  const updateLight = () => {
    const key = state.together ? p.group[0]?.emotion : p.emotions[0];
    setLight(key ? emotionByKey(key).colour : null);
  };
  renderWho(); updateMood(); updateRuntime(); updateLight();

  let saveTimer;
  const savePlatforms = () => {
    clearTimeout(saveTimer);
    saveTimer = setTimeout(() => {
      if (state.user) api.settings({ platforms: p.platforms }).catch(() => {});
      else { try { localStorage.setItem("cinemind.platforms", JSON.stringify(p.platforms)); } catch { /* ignore */ } }
    }, 400);
  };

  form.addEventListener("click", (e) => {
    const t = e.target.closest("button");
    if (!t || t.type === "submit") return;
    if (t.dataset.mode) {
      state.together = t.dataset.mode === "group";
      $$("[data-mode]", form).forEach((b) => b.setAttribute("aria-pressed", b === t));
      renderWho(); updateLight();
    } else if (t.dataset.aud) {
      p.audience = t.dataset.aud;
      renderWho();
    } else if (t.dataset.remove) {
      p.group.splice(Number(t.dataset.remove), 1);
      renderWho(); updateLight();
    } else if (t.id === "addPerson") {
      p.group.push({ name: `Person ${p.group.length + 1}`, audience: "adults", emotion: "funny" });
      renderWho();
    } else if (t.dataset.emo) {
      toggleLimited(p.emotions, t.dataset.emo, 2);
      $$("[data-emo]", form).forEach((b) => b.setAttribute("aria-pressed", p.emotions.includes(b.dataset.emo)));
      updateLight();
    } else if (t.dataset.genre) {
      toggleLimited(p.genres, t.dataset.genre, 3);
      $$("[data-genre]", form).forEach((b) => b.setAttribute("aria-pressed", p.genres.includes(b.dataset.genre)));
    } else if (t.dataset.ott) {
      toggleLimited(p.platforms, t.dataset.ott, 12);
      t.setAttribute("aria-pressed", p.platforms.includes(t.dataset.ott));
      savePlatforms();
    } else if (t.dataset.era) {
      p.era = t.dataset.era;
      $$("[data-era]", form).forEach((b) => b.setAttribute("aria-pressed", b === t));
    }
  });
  $("#whoBox").addEventListener("input", (e) => {
    const row = e.target.closest("[data-person]");
    if (!row) return;
    const m = p.group[Number(row.dataset.person)];
    m[e.target.dataset.pf] = e.target.value;
    if (e.target.dataset.pf === "emotion") { e.target.style.setProperty("--c", emotionByKey(m.emotion).colour); updateLight(); }
  });
  $("#moodNow").addEventListener("change", updateMood);
  $("#runtime").addEventListener("input", updateRuntime);
  $("#language").addEventListener("change", (e) => { p.languages = e.target.value ? [e.target.value] : []; });
  $("#query").addEventListener("input", (e) => { p.query = e.target.value; });

  form.addEventListener("submit", (e) => { e.preventDefault(); state.understood = []; runRecommend(); });
  $("#surpriseBtn").addEventListener("click", async () => {
    try {
      const { movie } = await api.surprise(requestPrefs());
      if (movie) { state.lastResults.set(movie.id, movie); openMovie(movie.id); }
      else toast("No match for these filters. Try removing one.", "error");
    } catch (err) { toast(err.message, "error"); }
  });

  if (params.get("run")) runRecommend();
}

function toggleLimited(list, value, max) {
  const i = list.indexOf(value);
  if (i >= 0) list.splice(i, 1);
  else { list.push(value); if (list.length > max) list.shift(); }
}

// what we send to the server (the group only counts in Watch Together mode)
function requestPrefs() {
  const p = state.prefs;
  return { ...p, group: state.together ? p.group.map((m) => ({ ...m, name: m.name.trim() || "Someone" })) : [] };
}

const RELAX_TEXT = { votes: "lesser-known titles", era: "release date", runtime: "length", language: "language", platforms: "your OTT apps" };

// Big results title: "12 picks to feel happy" with the feeling in its own colour
function resultsTitle(data) {
  const p = data.prefs;
  const feelSpan = (k) => { const e = emotionByKey(k); return `<span class="feel" style="--c:${e.colour}">${esc(e.label.toLowerCase())}</span>`; };
  const n = data.results.length;
  if (p.group?.length) {
    const names = p.group.map((m) => `<span class="feel" style="--c:${emotionByKey(m.emotion)?.colour || "inherit"}">${esc(m.name)}</span>`);
    const who = names.length > 1 ? `${names.slice(0, -1).join(", ")} &amp; ${names.at(-1)}` : names[0];
    return `${n} picks for ${who}`;
  }
  if (p.seed_movie_id && state.lastResults.get(p.seed_movie_id)) return `${n} picks like ${esc(state.lastResults.get(p.seed_movie_id).title)}`;
  if (p.emotions.length) return `${n} picks to feel ${p.emotions.map(feelSpan).join(" &amp; ")}`;
  if (p.genres.length) return `${n} ${esc(p.genres.map(GENRE_LABEL).join(" & ").toLowerCase())} picks`;
  return `${n} picks for you`;
}

async function runRecommend() {
  const box = $("#results");
  const btn = $("#findBtn");
  btn.disabled = true; btn.textContent = "Finding…";
  box.innerHTML = `<div class="grid">${skeletonGrid(8)}</div>`;
  try {
    const data = await api.recommend(requestPrefs());
    const p = data.prefs;
    if (!data.results.length) {
      box.innerHTML = `<div class="empty"><h3>No movies fit all of that</h3>
        <p>Try a different audience or remove the language filter.</p></div>`;
      return;
    }
    data.results.forEach((m) => state.lastResults.set(m.id, m));
    const colourKey = p.emotions[0];
    if (colourKey) setLight(emotionByKey(colourKey).colour);
    const mood = (state.options.current_moods || []).find((m) => m.key === p.current_mood);
    const sub = [
      `Suitable for ${esc(audienceLabel(p.audience))}`,
      p.genres.length && !(p.emotions.length === 0) ? esc(p.genres.map(GENRE_LABEL).join(", ")) : "",
      mood ? `a gentle lift for feeling ${esc(mood.label.toLowerCase())}` : "",
      p.platforms.length ? `on ${esc(p.platforms.join(", "))} first` : "",
    ].filter(Boolean).join(" · ");
    const relaxed = data.relaxed.length
      ? `<p>Not enough exact matches, so we widened: ${data.relaxed.map((r) => RELAX_TEXT[r] || r).join(", ")}.</p>` : "";
    const understood = state.understood.length
      ? `<div class="understood"><span>CineMind understood</span>${state.understood.map((u) => `<b>${esc(u)}</b>`).join("")}</div>` : "";
    box.innerHTML = `
      <div class="results-head"><div>
        ${understood}
        <h2 class="results-title">${resultsTitle(data)}</h2>
        <p>${sub}. Chosen from ${data.candidates.toLocaleString()} suitable movies.${state.user ? "" : " Log in to make these personal."}</p>
        ${relaxed}
      </div></div>
      <div class="grid">${data.results.map((m, i) => cardHTML(m, { showMatch: true, showReason: true, index: i })).join("")}</div>`;
  } catch (e) {
    box.innerHTML = `<div class="empty"><h3>Couldn't get recommendations</h3><p>${esc(e.message)}</p></div>`;
  } finally {
    btn.disabled = false; btn.textContent = "Find movies";
  }
}

// ---------------------------------------------------------------------
// SEARCH
// ---------------------------------------------------------------------
function search(params) {
  view.innerHTML = `<section class="page">
      <h2>Find a movie</h2>
      <div class="search-box">${icon.search}
        <input type="search" id="q" placeholder="Title, actor or what it's about" value="${esc(params.get("q") || "")}" aria-label="Search movies" autocomplete="off">
      </div>
      <div id="searchResults"></div>
    </section>`;
  const input = $("#q");
  let timer;
  const runSearch = async () => {
    const q = input.value.trim();
    const box = $("#searchResults");
    if (q.length < 2) { box.innerHTML = `<p class="lead">Type at least two letters.</p>`; return; }
    try {
      const d = await api.search(q, state.user?.default_audience || "adults");
      if ($("#q")?.value.trim() !== q) return;
      box.innerHTML = d.results.length
        ? `<div class="grid">${d.results.map((m, i) => cardHTML(m, { index: i })).join("")}</div>`
        : `<div class="empty"><h3>Nothing called "${esc(q)}"</h3><p>Check the spelling, or describe the story instead.</p></div>`;
    } catch (e) { box.innerHTML = `<div class="empty"><p>${esc(e.message)}</p></div>`; }
  };
  input.addEventListener("input", () => { clearTimeout(timer); timer = setTimeout(runSearch, 250); });
  input.focus();
  runSearch();
}

// ---------------------------------------------------------------------
// MY MOVIES - taste, library, history, settings
// ---------------------------------------------------------------------
const TABS = [["taste", "Taste"], ["like", "Liked"], ["watchlist", "Watchlist"], ["watched", "Watched"],
  ["rating", "Rated"], ["history", "History"], ["settings", "Settings"]];

async function me(params) {
  if (!state.user) {
    view.innerHTML = `<section class="page"><div class="empty"><h3>Your movies live here</h3>
      <p>Log in to keep likes, ratings, a watchlist and your history.</p>
      <button class="btn btn-primary" data-auth="login">Log in</button></div></section>`;
    return;
  }
  const tab = params.get("tab") || "taste";
  view.innerHTML = `<section class="page"><div id="meHead"></div>
      <div class="tabs" role="tablist">${TABS.map(([k, l]) => `<button role="tab" aria-selected="${k === tab}" data-tab="${k}">${l}</button>`).join("")}</div>
      <div id="meBody">${`<div class="grid">${skeletonGrid(6)}</div>`}</div></section>`;
  $$(".tabs button").forEach((b) => b.addEventListener("click", () => { location.hash = `#/me?tab=${b.dataset.tab}`; }));

  const prof = await api.profile();
  const c = prof.counts;
  $("#meHead").innerHTML = `<div class="me-head"><div><h1>${esc(prof.user.display_name)}</h1>
      <p class="lead">Member since ${new Date(prof.user.created_at).toLocaleDateString()}. Default audience: ${esc(audienceLabel(prof.user.default_audience))}.</p></div>
      <div class="stats">
        <div class="stat"><strong>${c.like}</strong><span>liked</span></div>
        <div class="stat"><strong>${c.rating}</strong><span>rated</span></div>
        <div class="stat"><strong>${c.watchlist}</strong><span>to watch</span></div>
        <div class="stat"><strong>${c.searches}</strong><span>searches</span></div>
      </div></div>`;

  const body = $("#meBody");
  if (tab === "taste") return renderTaste(body, prof);
  if (tab === "history") return renderHistory(body);
  if (tab === "settings") return renderSettings(body, prof);

  const lib = await api.library();
  const list = lib[tab] || [];
  const emptyText = {
    like: "Movies you like show up here and teach CineMind your taste.",
    watchlist: "Save movies for later with the bookmark button.",
    watched: "Mark movies as watched so they stop appearing in picks.",
    rating: "Rate movies from 1 to 5 stars on their details page.",
  }[tab];
  body.innerHTML = list.length
    ? `<div class="grid">${list.map((m, i) => cardHTML(m, { index: i,
        extra: m.my_rating ? `<span>${"★".repeat(m.my_rating)}</span>` : "" })).join("")}</div>`
    : `<div class="empty"><h3>Nothing here yet</h3><p>${emptyText}</p><a class="btn btn-primary" href="#/discover">Discover movies</a></div>`;
}

function barsHTML(items, max) {
  return `<div class="bars">${items.map((x) => `<div class="bar"><span>${esc(x.label)}</span>
      <span class="bar-track"><span class="bar-fill" style="--c:${x.colour || "var(--light)"}" data-w="${Math.round((x.value / max) * 100)}"></span></span>
      <span class="bar-num">${x.num ?? x.value}</span></div>`).join("")}</div>`;
}
function animateBars(root) {
  requestAnimationFrame(() => $$(".bar-fill", root).forEach((b) => { b.style.width = b.dataset.w + "%"; }));
}

function renderTaste(body, prof) {
  const t = prof.taste;
  if (!t.genres.length) {
    body.innerHTML = `<div class="empty"><h3>Your taste profile is empty</h3>
      <p>Like or rate at least one movie (4 or 5 stars) and CineMind starts learning what you enjoy.</p>
      <a class="btn btn-primary" href="#/discover">Find movies</a></div>`;
    return;
  }
  const block = (title, items) => {
    const max = Math.max(...items.map((x) => x.count), 1);
    return `<section><h3>${title}</h3>${barsHTML(items.map((x) => ({ label: x.label, value: x.count, colour: x.colour })), max)}</section>`;
  };
  body.innerHTML = `<div class="taste">
      ${block("Genres you like", t.genres)}
      ${block("Feelings you go for", t.emotions)}
      ${block("Languages", t.languages)}
    </div>
    <p class="lead">Built from the movies you liked or rated 4 stars and above.</p>`;
  if (t.emotions[0]) setLight(t.emotions[0].colour);
  animateBars(body);
}

async function renderHistory(body) {
  const h = await api.history();
  const searchItems = h.searches.map((s) => {
    const p = s.prefs;
    const pills = [
      `<span class="pill">${esc(audienceLabel(p.audience))}</span>`,
      ...p.emotions.map((k) => { const e = emotionByKey(k); return `<span class="pill" style="--c:${e.colour}"><span class="dot"></span>${esc(e.label)}</span>`; }),
      ...p.genres.map((g) => `<span class="pill">${esc(GENRE_LABEL(g))}</span>`),
      p.query ? `<span class="pill">"${esc(p.query)}"</span>` : "",
    ].join("");
    return `<li class="history-item"><div>
        <div class="when">${timeAgo(s.created_at)}</div>
        <div>${pills}</div>
        <div class="got">Got ${esc(s.top_titles.join(", "))}${s.result_ids.length > 4 ? " and more" : ""}</div>
      </div><button class="btn" data-rerun="${s.id}">Run again</button></li>`;
  }).join("");
  body.innerHTML = `
    <div class="row-block" style="margin-top:0">
      <div class="row-head"><h2>Recently opened</h2>
        ${h.searches.length || h.viewed.length ? `<button class="btn btn-ghost" id="clearHist">Clear history</button>` : ""}</div>
      ${h.viewed.length ? `<div class="scroller">${h.viewed.map((m) => cardHTML(m, { extra: `<span>${timeAgo(m.viewed_at)}</span>` })).join("")}</div>`
        : `<p class="lead">Movies you open will be listed here.</p>`}
    </div>
    <div class="row-block"><div class="row-head"><h2>Past searches</h2></div>
      ${h.searches.length ? `<ul class="history-list">${searchItems}</ul>` : `<p class="lead">Your recommendation searches will be listed here.</p>`}
    </div>`;
  $$("[data-rerun]", body).forEach((b) => b.addEventListener("click", () => {
    const s = h.searches.find((x) => String(x.id) === b.dataset.rerun).prefs;
    state.prefs = Object.assign(freshPrefs(), { audience: s.audience, emotions: s.emotions || [], genres: s.genres || [],
      languages: s.languages || [], max_runtime: s.max_runtime || 0, era: s.era || "any", query: s.query || "",
      current_mood: s.current_mood || "", group: s.group || [] });
    state.together = Boolean(s.group?.length);
    state.understood = [];
    location.hash = "#/discover?run=1";
  }));
  $("#clearHist")?.addEventListener("click", async () => {
    if (!confirm("Clear your search and viewing history? Likes and ratings are kept.")) return;
    await api.clearHistory();
    toast("History cleared");
    renderHistory(body);
  });
}

function renderSettings(body, prof) {
  body.innerHTML = `<form class="settings form" id="settingsForm">
      <label>Display name <input type="text" id="sName" maxlength="40" value="${esc(prof.user.display_name)}"></label>
      <label>Usually watching with
        <select id="sAud">${state.options.audiences.map((a) => `<option value="${a.key}" ${a.key === prof.user.default_audience ? "selected" : ""}>${esc(a.label)}</option>`).join("")}</select>
      </label>
      <div><button class="btn btn-primary" type="submit">Save settings</button></div>
    </form>
    <div class="danger-zone">
      <button class="btn btn-danger" id="delAcc">Delete my account</button>
    </div>`;
  $("#settingsForm").addEventListener("submit", async (e) => {
    e.preventDefault();
    try {
      await api.settings({ display_name: $("#sName").value, default_audience: $("#sAud").value });
      const { user } = await api.me();
      setUser(user);
      toast("Settings saved");
      me(new URLSearchParams("tab=settings"));
    } catch (err) { toast(err.message, "error"); }
  });
  $("#delAcc").addEventListener("click", async () => {
    if (!confirm("Delete your account, likes, ratings and history for good?")) return;
    await api.deleteAccount();
    setUser(null);
    toast("Account deleted");
    location.hash = "#/";
  });
}

// ---------------------------------------------------------------------
// HOW IT WORKS
// ---------------------------------------------------------------------
function about() {
  view.innerHTML = `<section class="page">
    <h2>How CineMind picks movies</h2>
    <p class="lead">Every recommendation goes through the same four steps, and every pick shows the scores that put it there.</p>
    <ol class="steps">
      <li><h3>Keep it suitable</h3><p>Movies above the audience's content level are removed first, using official age certificates where available and a cautious rule where not. This filter is never relaxed.</p></li>
      <li><h3>Score the fit</h3><p>Each remaining movie gets scores for genre, feeling, your description, your taste and its rating. Feelings come from genres, TMDB keywords and the plot summary.</p></li>
      <li><h3>Learn from people</h3><p>Collaborative filtering adds "people who liked this also liked that", from MovieLens ratings and from likes on CineMind.</p></li>
      <li><h3>Keep it varied</h3><p>A diversity step stops the list filling up with five sequels of the same film.</p></li>
      <li><h3>Watch together</h3><p>For a group, each person's feeling is scored separately. The group score mixes the average with the lowest score, so no one is left out.</p></li>
      <li><h3>Ask in your words</h3><p>The Ask bar and RAGS Genie turn a sentence like "funny family movie under 2 hours" into these same filters.</p></li>
    </ol>
    <div class="row-block">
      <h3>Score weights</h3>
      <table class="weights-table"><thead><tr><th>Signal</th><th>Weight</th><th>Used when</th></tr></thead><tbody>
        <tr><td>Genre match</td><td>0.25</td><td>you pick a genre</td></tr>
        <tr><td>Mood match</td><td>0.25</td><td>you pick a feeling</td></tr>
        <tr><td>Similar to your pick</td><td>0.20</td><td>you ask for more like a movie</td></tr>
        <tr><td>Your taste (content + collaborative)</td><td>0.20</td><td>you are logged in and have liked movies</td></tr>
        <tr><td>Matches your description</td><td>0.15</td><td>you type a description</td></tr>
        <tr><td>Gentle mood lift</td><td>0.15</td><td>you say how you feel right now</td></tr>
        <tr><td>Critic and audience rating</td><td>0.15</td><td>always</td></tr>
      </tbody></table>
      <p class="lead">Signals that aren't in use share their weight with the rest, so the match percentage is always out of 100.</p>
    </div>
  </section>`;
}

// ---------------------------------------------------------------------
// MOVIE DETAILS SHEET
// ---------------------------------------------------------------------
const sheet = $("#movieSheet");
sheet.addEventListener("click", (e) => { if (e.target === sheet) sheet.close(); });
sheet.addEventListener("close", () => { sheet.innerHTML = ""; });

// The sheet grows out of the poster you clicked (a FLIP animation)
function growFrom(el) {
  if (!el || !el.isConnected || matchMedia("(prefers-reduced-motion: reduce)").matches) return;
  const a = el.getBoundingClientRect(), b = sheet.getBoundingClientRect();
  if (!a.width || !b.width) return;
  sheet.animate([
    { transformOrigin: "top left", opacity: 0.35, borderRadius: "14px",
      transform: `translate(${a.left - b.left}px, ${a.top - b.top}px) scale(${a.width / b.width}, ${a.height / b.height})` },
    { transformOrigin: "top left", opacity: 1, transform: "none" },
  ], { duration: 420, easing: "cubic-bezier(.2,.8,.2,1)" });
}

async function openMovie(id, { from = null, play = false, section = null } = {}) {
  state.openMovieId = id;
  const known = state.lastResults.get(id);
  const wasOpen = sheet.open;
  // show the poster and title at once, then fill in the details
  sheet.innerHTML = `<header class="sheet-hero"><div class="sheet-top">${known ? posterHTML(known) : '<div class="poster skeleton"></div>'}
      <div>${known ? `<h2 class="sheet-title">${esc(known.title)}</h2>` : ""}<div class="skeleton" style="height:28px;width:60%;margin-top:14px;aspect-ratio:auto"></div></div></div></header>
    <div class="sheet-body"><div><div class="skeleton" style="height:120px;aspect-ratio:auto"></div></div><div></div></div>`;
  if (!wasOpen) {
    sheet.classList.toggle("grow", Boolean(from));
    sheet.showModal();
    if (from) growFrom(from);
  }
  sheet.scrollTop = 0;
  let m;
  try { m = await api.movie(id, state.prefs.audience); }
  catch (e) { sheet.innerHTML = `<div class="empty" style="margin:28px"><h3>Couldn't open this movie</h3><p>${esc(e.message)}</p></div>`; return; }
  const rec = state.lastResults.get(id);
  const colour = m.top_emotions[0]?.colour;
  const ev = m.emotion_evidence || {};

  const emoItems = Object.entries(m.emotion_profile).sort((a, b) => b[1] - a[1]).slice(0, 5)
    .map(([k, v]) => { const e = emotionByKey(k); return { label: e.label, value: v, num: Math.round(v * 100), colour: e.colour }; });
  const breakdown = rec?.breakdown ? Object.values(rec.breakdown)
    .map((b) => ({ label: b.label, value: b.value * b.weight, num: Math.round(b.value * b.weight * 100) })) : null;
  const trailer = m.trailer_key
    ? `<button class="btn btn-primary" id="playTrailer">${icon.play}<span>Play trailer</span></button>`
    : `<a class="btn" target="_blank" rel="noopener" href="https://www.youtube.com/results?search_query=${encodeURIComponent(m.title + " " + (m.year || "") + " trailer")}">${icon.play}<span>Search YouTube for the trailer</span></a>`;

  sheet.innerHTML = `
    <button class="sheet-close" aria-label="Close" id="closeSheet">&times;</button>
    <header class="sheet-hero" style="${m.backdrop_url ? `background-image:url('${esc(m.backdrop_url)}')` : `background:radial-gradient(80% 120% at 20% 0%, ${colour || "#F2B544"}55, transparent 70%)`}">
      <div class="sheet-top">
        ${posterHTML(m)}
        <div>
          <h2 class="sheet-title">${esc(m.title)}</h2>
          ${m.tagline ? `<p class="sheet-tagline">${esc(m.tagline)}</p>` : ""}
          <div class="facts">
            ${m.year ? `<span class="fact">${m.year}</span>` : ""}
            ${m.runtime ? `<span class="fact">${runtime(m.runtime)}</span>` : ""}
            <span class="fact">${esc(m.language_name)}</span>
            <span class="fact">${m.rating}/10 from ${m.vote_count.toLocaleString()} votes</span>
            <span class="fact cert" title="${m.level_source === "official" ? "Official certificate" : "Estimated from genres and keywords"}">${m.certification ? esc(m.certification) + ", " : ""}${esc(m.content_level_name)}${m.level_source === "official" ? "" : " (estimated)"}</span>
            ${rec?.match !== undefined ? `<span class="fact"><b>${rec.match}%</b> match</span>` : ""}
          </div>
        </div>
      </div>
    </header>
    <div class="sheet-body">
      <div>
        <p class="overview">${esc(m.overview)}</p>
        <p class="people">${m.director ? `Directed by <b>${esc(m.director)}</b>. ` : ""}${m.cast.length ? `Starring <b>${esc(m.cast.slice(0, 4).join(", "))}</b>.` : ""}</p>
        <div>${m.genres.map((g) => `<span class="pill">${esc(GENRE_LABEL(g))}</span>`).join("")}</div>
        <div class="actions" id="actions"></div>
        <div style="margin-top:18px" id="trailerBox">${trailer}</div>
        ${groupFitHTML(rec)}
        ${watchHTML(m)}
        ${rec?.reasons ? `<h3>Why this pick</h3><ul class="reasons">${rec.reasons.map((r) => `<li>${esc(r)}</li>`).join("")}</ul>` : ""}
      </div>
      <div>
        ${breakdown ? `<h3>Score breakdown</h3>${barsHTML(breakdown, Math.max(...breakdown.map((b) => b.value), 0.01))}
          <p class="evidence">Each bar is that signal's share of the ${rec.match}% match.</p>` : ""}
        <h3>Feelings this movie gives</h3>
        ${barsHTML(emoItems, 1)}
        <p class="evidence">${emoItems.slice(0, 2).map((e) => { const key = state.options.emotions.find((x) => x.label === e.label).key; return ev[key]?.length ? `${esc(e.label)}: ${esc(ev[key].join(", "))}` : ""; }).filter(Boolean).join(". ")}</p>
      </div>
    </div>
    ${m.similar.length ? `<div class="sheet-similar"><div class="row-head"><h2>More like this</h2></div>
      <div class="scroller">${m.similar.map((s) => { state.lastResults.set(s.id, s); return cardHTML(s); }).join("")}</div></div>` : ""}`;

  if (colour) setLight(colour);
  $("#closeSheet").onclick = () => sheet.close();
  $("#playTrailer")?.addEventListener("click", () => {
    $("#trailerBox").innerHTML = `<iframe class="trailer-frame" src="https://www.youtube-nocookie.com/embed/${encodeURIComponent(m.trailer_key)}?autoplay=1&rel=0"
      title="${esc(m.title)} trailer" allow="autoplay; encrypted-media; picture-in-picture" allowfullscreen></iframe>`;
  });
  renderActions(m);
  animateBars(sheet);
  sheet.scrollTop = 0;
  if (play) $("#playTrailer")?.click();
  if (section === "watch") requestAnimationFrame(() => $("#watchSec")?.scrollIntoView({ behavior: "smooth", block: "start" }));
}

// Watch Together: how well this movie fits each person
function groupFitHTML(rec) {
  if (!rec?.group_fit?.length) return "";
  return `<h3>How it fits each person</h3>${barsHTML(rec.group_fit.map((g) => ({ label: `${g.name} · ${g.emotion}`, value: g.value / 100, num: g.value, colour: g.colour })), 1)}`;
}

// "Where to watch" - OTT platforms for this movie (data by JustWatch, via TMDB)
function watchHTML(m) {
  const w = m.watch;
  if (!w) return "";                                   // no availability data fetched yet
  const region = w.region === "IN" ? "India" : w.region;
  const updated = w.updated ? new Date(w.updated).toLocaleDateString() : "";
  if (!w.groups.length) {
    return `<section class="watch" id="watchSec"><h3>Where to watch</h3>
      <p class="watch-none">Not on any streaming, rental or purchase platform in ${esc(region)} right now.</p>
      <p class="watch-note">Availability data by JustWatch${updated ? `, checked ${esc(updated)}` : ""}.</p></section>`;
  }
  const groups = w.groups.map((g) => `<div class="watch-group"><span class="watch-kind">${esc(g.label)}</span>
      <div class="watch-list">${g.platforms.map((p) => `<a class="platform" href="${esc(p.url)}" target="_blank" rel="noopener"
          title="${p.direct_search ? `Search ${esc(p.name)} for this movie` : `Open the ${esc(p.name)} link`}">
          ${p.logo ? `<img src="${esc(p.logo)}" alt="" loading="lazy" onerror="this.remove()">` : ""}<span>${esc(p.name)}</span></a>`).join("")}</div></div>`).join("");
  return `<section class="watch" id="watchSec"><h3>Where to watch in ${esc(region)}</h3>${groups}
    <a class="btn btn-ghost watch-all" href="${esc(w.all_link)}" target="_blank" rel="noopener">See all watch options</a>
    <p class="watch-note">Availability data by JustWatch${updated ? `, checked ${esc(updated)}` : ""}. Platforms change their catalogues, so a title may have moved.</p>
  </section>`;
}

function renderActions(m) {
  const box = $("#actions");
  if (!state.user) {
    box.innerHTML = `<button class="btn" data-auth="login">Log in to like, rate or save this</button>`;
    return;
  }
  const s = m.state;
  const t = (kind, label, ic) => `<button class="toggle" data-kind="${kind}" aria-pressed="${s[kind]}">${ic}<span>${label}</span></button>`;
  box.innerHTML = `${t("like", "Like", icon.heart)}${t("dislike", "Not for me", icon.thumbsDown)}
    ${t("watchlist", "Watchlist", icon.bookmark)}${t("watched", "Watched", icon.eye)}
    <span class="stars" role="group" aria-label="Your rating">${[1, 2, 3, 4, 5].map((n) =>
      `<button data-star="${n}" class="${n <= s.rating ? "lit" : ""}" aria-label="${n} star${n > 1 ? "s" : ""}">★</button>`).join("")}
      <span class="stars-label">${s.rating ? "Your rating" : "Rate it"}</span></span>`;

  const MESSAGES = { like: "Liked. Your picks will learn from this.", dislike: "Got it. We'll show fewer like this.",
    watchlist: "Added to your watchlist", watched: "Marked as watched" };
  box.onclick = async (e) => {
    const b = e.target.closest("button");
    if (!b) return;
    try {
      let res;
      if (b.dataset.star) {
        const v = Number(b.dataset.star);
        res = await api.interact(m.id, "rating", true, v === s.rating ? 0 : v);
        toast(v === s.rating ? "Rating removed" : `Rated ${v} star${v > 1 ? "s" : ""}`);
      } else {
        const kind = b.dataset.kind;
        const on = !s[kind];
        res = await api.interact(m.id, kind, on);
        if (on) toast(MESSAGES[kind]);
      }
      m.state = res.state;
      renderActions(m);
      const again = b.dataset.kind ? $(`[data-kind="${b.dataset.kind}"]`, box) : null;
      again?.classList.add("pop");
    } catch (err) {
      if (err.status === 401) { setUser(null); openAuth("login"); }
      else toast(err.message, "error");
    }
  };
}

// ---------------------------------------------------------------------
// LOGIN / SIGN UP
// ---------------------------------------------------------------------
const authDialog = $("#authDialog");
authDialog.addEventListener("click", (e) => { if (e.target === authDialog) authDialog.close(); });

function openAuth(mode = "login") {
  const isLogin = mode === "login";
  authDialog.innerHTML = `
    <h2>${isLogin ? "Welcome back" : "Create your account"}</h2>
    <p>${isLogin ? "Log in to see your picks, watchlist and history." : "Your likes, ratings and history make every pick more personal."}</p>
    <div class="auth-tabs segmented">
      <button type="button" data-mode="login" aria-pressed="${isLogin}">Log in</button>
      <button type="button" data-mode="register" aria-pressed="${!isLogin}">Sign up</button>
    </div>
    <form class="form" id="authForm" novalidate>
      ${isLogin ? "" : `<label>Your name <input type="text" name="display_name" maxlength="40" autocomplete="name"></label>`}
      <label>Username <input type="text" name="username" required minlength="3" maxlength="24" autocomplete="username" pattern="[A-Za-z0-9_.]+"></label>
      <label>Password <input type="password" name="password" required minlength="6" autocomplete="${isLogin ? "current-password" : "new-password"}"></label>
      <p class="error" id="authError"></p>
      <button class="btn btn-primary" type="submit">${isLogin ? "Log in" : "Create account"}</button>
    </form>`;
  if (!authDialog.open) authDialog.showModal();
  $$("[data-mode]", authDialog).forEach((b) => b.addEventListener("click", () => openAuth(b.dataset.mode)));
  const form = $("#authForm");
  form.querySelector("input").focus();
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const f = new FormData(form);
    const btn = form.querySelector("button[type=submit]");
    btn.disabled = true;
    try {
      const { user } = isLogin
        ? await api.login(f.get("username"), f.get("password"))
        : await api.register(f.get("username"), f.get("password"), f.get("display_name"));
      setUser(user);
      authDialog.close();
      toast(isLogin ? `Welcome back, ${user.display_name}` : `Account created. Welcome, ${user.display_name}`);
      const reopen = sheet.open ? state.openMovieId : null;
      route();
      if (reopen) openMovie(reopen);       // show the like / rate buttons now
    } catch (err) {
      $("#authError").textContent = err.message;
    } finally { btn.disabled = false; }
  });
}

boot();
