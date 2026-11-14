// =====================================================================
// genie.js - RAGS Genie, the chat assistant
// A floating button on every page opens a small chat panel.
// The server keeps no chat memory: the browser sends the conversation
// "state" with every message and gets the new state back.
// =====================================================================

import { api } from "./api.js";
import { $, esc } from "./ui.js";

const STORE = "ragsGenie.v1";
let chat = { state: null, messages: [] };      // messages: {who:"me"|"genie", text, results, understood, suggestions}
let busy = false;
let remember = () => {};                        // app.js gives us a way to keep result scores for the details sheet
let lookup = () => null;                        // and a way to find the options (brain name)

function save() {
  try { sessionStorage.setItem(STORE, JSON.stringify({ state: chat.state, messages: chat.messages.slice(-30) })); } catch { /* private mode */ }
}
function load() {
  try { const d = JSON.parse(sessionStorage.getItem(STORE) || "null"); if (d?.messages) chat = d; } catch { /* ignore */ }
}

// **bold** -> <b>bold</b>, new lines -> <br>  (text is escaped first)
function rich(text) {
  return esc(text).replace(/\*\*(.+?)\*\*/g, "<b>$1</b>").replace(/\n/g, "<br>");
}

function miniCard(m) {
  return `<button class="genie-movie" data-movie="${m.id}" aria-label="Open ${esc(m.title)}">
      <span class="gm-poster">${m.poster_url ? `<img src="${esc(m.poster_url)}" alt="" loading="lazy" onerror="this.remove()">` : ""}</span>
      <span class="gm-text"><b>${esc(m.title)}</b>
        <small>${m.year || ""}${m.match !== undefined ? ` · <em>${m.match}% match</em>` : ""}</small>
        ${m.reasons?.[0] ? `<small class="gm-why">${esc(m.reasons[0])}</small>` : ""}</span>
    </button>`;
}

function messageHTML(msg) {
  if (msg.who === "me") return `<div class="gmsg me"><p>${esc(msg.text)}</p></div>`;
  return `<div class="gmsg bot">
      ${msg.understood?.length ? `<div class="g-understood">${msg.understood.map((u) => `<span>${esc(u)}</span>`).join("")}</div>` : ""}
      <p>${rich(msg.text)}</p>
      ${msg.results?.length ? `<div class="genie-movies">${msg.results.map(miniCard).join("")}</div>` : ""}
    </div>`;
}

function render() {
  const log = $("#genieLog");
  log.innerHTML = chat.messages.map(messageHTML).join("") +
    (busy ? `<div class="gmsg bot typing" aria-label="RAGS Genie is typing"><span></span><span></span><span></span></div>` : "");
  const last = [...chat.messages].reverse().find((m) => m.who === "genie");
  $("#genieChips").innerHTML = busy ? "" : (last?.suggestions || [])
    .map((s) => `<button type="button" class="g-chip">${esc(s)}</button>`).join("");
  // show the start of the newest answer (its text first, then the movies below it)
  const newest = log.lastElementChild;
  log.scrollTop = newest && newest.offsetHeight > log.clientHeight * 0.6 ? newest.offsetTop - 12 : log.scrollHeight;
}

async function send(text) {
  text = String(text || "").trim();
  if (busy) return;
  if (text) chat.messages.push({ who: "me", text });
  busy = true; render();
  try {
    const out = await api.genie(text, chat.state);
    chat.state = out.state;
    out.results.forEach((m) => remember(m));
    chat.messages.push({ who: "genie", text: out.reply, results: out.results,
                         understood: out.understood, suggestions: out.suggestions });
    setBrain(out.brain);
  } catch (e) {
    chat.messages.push({ who: "genie", text: `Sorry, I couldn't reach CineMind (${e.message}).`, suggestions: ["Try again"] });
  } finally {
    busy = false; render(); save();
  }
}

function setBrain(used) {
  const configured = lookup()?.genie_brain || "built-in";
  const badge = $("#genieBrain");
  const gem = used === "gemini" || configured.startsWith("gemini");
  badge.textContent = gem ? "Built-in + Gemini" : "Built-in brain";
  badge.title = gem
    ? "Understands your words with CineMind's own rules, and Google Gemini helps with unusual sentences. Movies always come from CineMind's engine."
    : "Understands your words with CineMind's own rules. Movies always come from CineMind's engine.";
}

// Two layouts: a full-height side panel (the page moves left to make room),
// or full screen. The choice is remembered on this device.
let full = false;
try { full = localStorage.getItem("ragsGenie.full") === "1"; } catch { /* ignore */ }

function setFull(on) {
  full = on;
  try { localStorage.setItem("ragsGenie.full", on ? "1" : "0"); } catch { /* ignore */ }
  const panel = $("#geniePanel");
  panel.classList.toggle("full", on);
  document.body.classList.toggle("genie-docked", !panel.hidden && !on);
  const b = $("#genieExpand");
  b.innerHTML = on ? "&#10529;" : "&#10530;";
  b.title = on ? "Side panel" : "Full screen";
  b.setAttribute("aria-label", on ? "Show the chat as a side panel" : "Open the chat full screen");
  $("#genieLog").scrollTop = $("#genieLog").scrollHeight;
}

function open(show, greet = true) {
  const panel = $("#geniePanel"), fab = $("#genieFab");
  panel.hidden = !show;
  setFull(full);
  fab.setAttribute("aria-expanded", String(show));
  fab.classList.toggle("is-open", show);
  if (show) {
    if (!chat.messages.length && greet) send("");      // greeting + starter suggestions
    else render();
    setTimeout(() => $("#genieInput").focus(), 50);
  }
}

export function initGenie({ onRemember, getOptions }) {
  remember = onRemember; lookup = getOptions;
  load();
  setBrain();
  $("#genieFab").addEventListener("click", () => open($("#geniePanel").hidden));
  $("#genieClose").addEventListener("click", () => open(false));
  $("#genieExpand").addEventListener("click", () => setFull(!full));
  $("#genieReset").addEventListener("click", () => {
    chat = { state: null, messages: [] };
    save(); send("");
  });
  $("#genieForm").addEventListener("submit", (e) => {
    e.preventDefault();
    const input = $("#genieInput");
    const text = input.value;
    input.value = "";
    if (text.trim()) send(text);
  });
  $("#genieChips").addEventListener("click", (e) => {
    const b = e.target.closest(".g-chip");
    if (b) send(b.textContent === "Try again" ? ([...chat.messages].reverse().find((m) => m.who === "me")?.text || "") : b.textContent);
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && !$("#geniePanel").hidden && !document.querySelector("dialog[open]")) open(false);
  });
}

// lets other pages hand a sentence to the Genie ("Ask RAGS Genie" links)
export function askGenie(text) {
  open(true, !text);
  if (text) send(text);
}
