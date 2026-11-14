// =====================================================================
// ui.js - small reusable pieces: escaping, icons, cards, toasts, light
// =====================================================================

// Always escape text from the server before putting it into HTML.
export function esc(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;").replaceAll("'", "&#39;");
}

export const $ = (sel, root = document) => root.querySelector(sel);
export const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

const path = (d) => `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${d}</svg>`;
export const icon = {
  heart: path('<path d="M20.8 4.6a5.5 5.5 0 0 0-7.8 0L12 5.7l-1-1.1a5.5 5.5 0 0 0-7.8 7.8l1 1.1L12 21l7.8-7.5 1-1.1a5.5 5.5 0 0 0 0-7.8z"/>'),
  thumbsDown: path('<path d="M10 15v4a3 3 0 0 0 3 3l4-9V2H5.7a2 2 0 0 0-2 1.7l-1.4 9A2 2 0 0 0 4.3 15z"/><path d="M17 2h3a2 2 0 0 1 2 2v7a2 2 0 0 1-2 2h-3"/>'),
  bookmark: path('<path d="M19 21l-7-5-7 5V5a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2z"/>'),
  eye: path('<path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/>'),
  play: path('<polygon points="6 3 20 12 6 21 6 3"/>'),
  search: path('<circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3"/>'),
  shuffle: path('<path d="M16 3h5v5M4 20 21 3M21 16v5h-5M15 15l6 6M4 4l5 5"/>'),
  // audiences
  kids: path('<circle cx="12" cy="7" r="4"/><path d="M8 21v-3a4 4 0 0 1 8 0v3"/><path d="M9 7h.01M15 7h.01"/>'),
  family: path('<circle cx="7" cy="6" r="3"/><circle cx="17" cy="6" r="3"/><circle cx="12" cy="13" r="2"/><path d="M3 21v-4a4 4 0 0 1 8 0M13 21v-4a4 4 0 0 1 8 0"/>'),
  everyone: path('<circle cx="12" cy="12" r="10"/><path d="M8 14s1.5 2 4 2 4-2 4-2M9 9h.01M15 9h.01"/>'),
  teenagers: path('<path d="M3 18v-6a9 9 0 0 1 18 0v6"/><path d="M21 19a2 2 0 0 1-2 2h-1v-6h3zM3 19a2 2 0 0 0 2 2h1v-6H3z"/>'),
  adults: path('<circle cx="12" cy="8" r="5"/><path d="M3 21a9 9 0 0 1 18 0"/>'),
  seniors: path('<path d="M17 8h1a4 4 0 1 1 0 8h-1"/><path d="M3 8h14v9a4 4 0 0 1-4 4H7a4 4 0 0 1-4-4z"/><path d="M6 2v2M10 2v2M14 2v2"/>'),
};

// ---- the room light -------------------------------------------------
export function setLight(colour) {
  document.documentElement.style.setProperty("--light", colour || "#F2B544");
}

// ---- toasts ---------------------------------------------------------
export function toast(message, kind = "") {
  const el = document.createElement("div");
  el.className = `toast ${kind}`;
  el.textContent = message;
  $("#toasts").appendChild(el);
  setTimeout(() => el.remove(), 2700);
}

// ---- formatting -----------------------------------------------------
export function runtime(min) {
  if (!min) return "";
  const h = Math.floor(min / 60), m = min % 60;
  return h ? `${h} h ${m ? m + " min" : ""}`.trim() : `${m} min`;
}

export function timeAgo(iso) {
  const s = (Date.now() - new Date(iso).getTime()) / 1000;
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)} min ago`;
  if (s < 86400) return `${Math.floor(s / 3600)} h ago`;
  if (s < 86400 * 7) return `${Math.floor(s / 86400)} days ago`;
  return new Date(iso).toLocaleDateString();
}

// ---- OTT badges on posters ------------------------------------------
let LOGOS = {};
export function setPlatformLogos(map) { LOGOS = map || {}; }
function ottHTML(names) {
  if (!names?.length) return "";
  return `<span class="ott" title="Streaming on ${esc(names.join(", "))}">${names.slice(0, 2).map((n) => LOGOS[n]
      ? `<img src="${esc(LOGOS[n])}" alt="${esc(n)}" loading="lazy" onerror="this.remove()">`
      : `<i>${esc(n.split(" ")[0])}</i>`).join("")}</span>`;
}

// ---- poster (real image, or a designed fallback) --------------------
export function posterHTML(movie, { match } = {}) {
  const colour = movie.top_emotions?.[0]?.colour || "#F2B544";
  const long = (movie.title || "").length > 24 ? " long" : "";
  const fallback = `<div class="poster-fallback${long}" style="--c:${esc(colour)}">
      <strong>${esc(movie.title)}</strong><small>${esc(movie.year || "")}</small></div>`;
  const img = movie.poster_url
    ? `<img src="${esc(movie.poster_url)}" alt="" loading="lazy" onerror="this.remove()">`
    : "";
  const badge = match !== undefined ? `<span class="match"><b>${match}%</b> match</span>` : "";
  return `<div class="poster">${fallback}${img}${badge}${ottHTML(movie.streaming)}</div>`;
}

// ---- movie card -----------------------------------------------------
export function cardHTML(movie, { showMatch = false, showReason = false, index = 0, extra = "" } = {}) {
  const reason = showReason && movie.reasons?.length
    ? `<span class="card-reason">${esc(movie.reasons[0])}</span>` : "";
  const fit = movie.group_fit?.length
    ? `<span class="card-fit">${movie.group_fit.map((g) => `<span style="--c:${esc(g.colour)}" title="${esc(g.name)} wants ${esc(g.emotion.toLowerCase())}: ${g.value}% fit"><i style="width:${Math.max(6, g.value)}%"></i>${esc(g.name)}</span>`).join("")}</span>` : "";
  return `<button class="card" data-movie="${movie.id}" style="--i:${index}"
            aria-label="${esc(movie.title)}${movie.year ? ", " + movie.year : ""}">
      ${posterHTML(movie, { match: showMatch ? movie.match : undefined })}
      <span class="card-title">${esc(movie.title)}</span>
      <span class="card-meta"><span>${esc(movie.year || "")}</span><span>${esc(movie.genres?.slice(0, 2).join(", "))}</span>${extra}</span>
      ${reason}${fit}
    </button>`;
}

export function skeletonGrid(n = 8) {
  return Array.from({ length: n }, () => `<div><div class="skeleton"></div></div>`).join("");
}

// ---- 3D tilt: posters lean toward the cursor and catch the light -----
// Only on devices with a mouse, and never when "reduce motion" is on.
export function enableTilt() {
  const fine = matchMedia("(hover: hover) and (pointer: fine)").matches;
  if (!fine || matchMedia("(prefers-reduced-motion: reduce)").matches) return;
  let current = null, frame = 0, last = null;
  const reset = (poster) => { poster.style.removeProperty("--rx"); poster.style.removeProperty("--ry"); };
  document.addEventListener("pointermove", (e) => {
    last = e;
    if (frame) return;
    frame = requestAnimationFrame(() => {
      frame = 0;
      const poster = last.target.closest?.(".card")?.querySelector(".poster");
      if (current && current !== poster) reset(current);
      current = poster;
      if (!poster) return;
      const r = poster.getBoundingClientRect();
      const x = Math.min(Math.max((last.clientX - r.left) / r.width, 0), 1);
      const y = Math.min(Math.max((last.clientY - r.top) / r.height, 0), 1);
      poster.style.setProperty("--ry", `${(x - 0.5) * 16}deg`);
      poster.style.setProperty("--rx", `${(0.5 - y) * 14}deg`);
      poster.style.setProperty("--gx", `${x * 100}%`);
      poster.style.setProperty("--gy", `${y * 100}%`);
    });
  }, { passive: true });
  document.addEventListener("pointerleave", () => { if (current) reset(current); current = null; });
}
