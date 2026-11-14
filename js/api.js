// =====================================================================
// api.js - every call from the website to the Flask server goes here
// The website and API are served by the same Flask app, so URLs are
// relative ("/api/...") and the login cookie is sent automatically.
// =====================================================================

async function request(method, url, body) {
  const options = { method, headers: {}, credentials: "same-origin" };
  if (body !== undefined) {
    options.headers["Content-Type"] = "application/json";
    options.body = JSON.stringify(body);
  }
  let response;
  try {
    response = await fetch(url, options);
  } catch {
    throw new Error("Can't reach the CineMind server. Is python3 app.py running?");
  }
  let data = {};
  try { data = await response.json(); } catch { /* empty body */ }
  if (!response.ok) {
    const err = new Error(data.error || `Server error (${response.status})`);
    err.status = response.status;
    throw err;
  }
  return data;
}

const qs = (params) => new URLSearchParams(
  Object.entries(params).filter(([, v]) => v !== undefined && v !== null && v !== "")
).toString();

export const api = {
  options: () => request("GET", "/api/options"),
  recommend: (prefs) => request("POST", "/api/recommend", prefs),
  surprise: (prefs) => request("POST", "/api/surprise", prefs),
  search: (q, audience) => request("GET", `/api/search?${qs({ q, audience })}`),
  trending: (audience) => request("GET", `/api/trending?${qs({ audience })}`),
  movie: (id, audience) => request("GET", `/api/movies/${id}?${qs({ audience })}`),
  interact: (id, kind, on, value) => request("POST", `/api/movies/${id}/interact`, { kind, on, value }),
  ask: (text) => request("POST", "/api/ask", { text }),
  genie: (message, state) => request("POST", "/api/genie", { message, state }),
  forYou: () => request("GET", "/api/for-you"),

  me: () => request("GET", "/api/auth/me"),
  login: (username, password) => request("POST", "/api/auth/login", { username, password }),
  register: (username, password, display_name) =>
    request("POST", "/api/auth/register", { username, password, display_name }),
  logout: () => request("POST", "/api/auth/logout"),

  profile: () => request("GET", "/api/me/profile"),
  library: () => request("GET", "/api/me/library"),
  history: () => request("GET", "/api/me/history"),
  clearHistory: () => request("DELETE", "/api/me/history"),
  settings: (changes) => request("PATCH", "/api/me/settings", changes),
  deleteAccount: () => request("DELETE", "/api/me"),
};
