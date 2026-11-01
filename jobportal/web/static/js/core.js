/* core.js: the shared toolkit. It loads first, so every other file can use what's defined here.

   - Helpers: $ and $$ find elements, esc() makes text safe inside HTML, safeUrl() keeps only web and mail links, api()
     calls the server, store reads and writes browser storage, plus small formatters.
   - Focus: focusKey() and refocus() keep a keyboard user's place when a live update redraws a part of the page, and
     typingIn() tells a redraw to leave a text box alone while you type in it.
   - md(): a small Markdown renderer for the text the AI writes.
   - icon(): the line icons of the design, drawn in the color of the text around them.
   - S: the app state that every page reads and writes.
   - toast() for short messages, openDialog() for dialogs, and small pop-up menus.
   - The own window: the desktop app (desktop()) or a browser window in app mode (appWindow).
   - The action registry: onAction() for clicks and onChange() for selects, checkboxes and file pickers.

   How clicks work: any element with data-act="name" runs the handler registered with onAction("name", fn), wherever it
   is: a page in <main>, a dialog, the sidebar or the top bar. Each file registers its own handlers at the bottom, and
   main.js holds the one listener that calls them.
   APIs: only POST /api/open-external (openUrl, in a browser app window). Everything else calls the server through api(). */
"use strict";

// ---------------------------------------------------------------- helpers
const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];

// Makes text safe to put inside HTML. Every value from the server or the user goes through esc() before it lands in a
// template, so a job posting can't inject markup into the dashboard.
const HTML_ESCAPES = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" };
const esc = (text) => String(text ?? "").replace(/[&<>"']/g, (c) => HTML_ESCAPES[c]);

// Returns the URL only when it's a web or mail link (else ""), so a "javascript:" link in scraped data never becomes a link.
const safeUrl = (url) => (/^(https?:\/\/|mailto:)/i.test(String(url || "").trim()) ? String(url).trim() : "");

// A deep copy of plain JSON data.
const clone = (obj) => JSON.parse(JSON.stringify(obj));

// <main>: every page draws itself in here, and marks it with data-page so a new address on the same page can update it
// in place instead of drawing it again.
const main = $("#main");

// Browser storage for small preferences (the open filter, the theme, skipped questions). It can be unavailable (a
// locked-down window, a private mode), so every read and write is wrapped: a failed read gives the fallback, a failed
// write is skipped, and JobPortal works the same either way.
const store = {
  get(key, fallback = null) {
    try {
      const value = localStorage.getItem(key);
      return value === null ? fallback : value;
    } catch (_) {
      return fallback;
    }
  },
  set(key, value) {
    try {
      localStorage.setItem(key, value);
    } catch (_) {}
  },
  list(key) {  // a saved JSON list, or [] when there's none or it can't be read
    try {
      const value = JSON.parse(store.get(key, "[]"));
      return Array.isArray(value) ? value : [];
    } catch (_) {
      return [];
    }
  },
};

// Calls the JobPortal server. An object body is sent as JSON. Returns the parsed JSON (or text). When the request fails it
// throws an Error carrying the server's message (and its status), so callers can show it in a toast.
async function api(path, opts = {}) {
  const request = { headers: {}, ...opts };
  if (request.body && typeof request.body !== "string" && !(request.body instanceof Blob)) {
    request.body = JSON.stringify(request.body);
    request.headers["Content-Type"] = "application/json";
  }
  const response = await fetch(path, request);
  if (!response.ok) {
    let message = response.statusText;
    try {
      const body = await response.json();
      message = body.detail || JSON.stringify(body);
    } catch (_) {}  // the error wasn't JSON: keep the status text
    const error = new Error(message);
    error.status = response.status;
    throw error;
  }
  const type = response.headers.get("content-type") || "";
  return type.includes("json") ? response.json() : response.text();
}

// Sends a file as the raw body of a PUT and returns the JSON reply. (A JSON body would turn the file into text.)
const uploadFile = (url, file) => api(url, { method: "PUT", body: file });

// Returns a version of fn that waits until the calls stop for ms milliseconds, then runs once with the last arguments.
// Used for search boxes and live previews, so typing doesn't send a request per key.
const debounce = (fn, ms) => {
  let timer;
  return (...args) => {
    clearTimeout(timer);
    timer = setTimeout(() => fn(...args), ms);
  };
};

// Reads or writes a nested value by a dotted path: getPath(cfg, "sources.linkedin.enabled"). setPath creates missing levels.
const getPath = (obj, path) => path.split(".").reduce((value, key) => (value == null ? value : value[key]), obj);
function setPath(obj, path, value) {
  const keys = path.split(".");
  let node = obj;
  keys.slice(0, -1).forEach((key) => (node = node[key] ??= {}));
  node[keys.at(-1)] = value;
}

// Copies text to the clipboard and confirms with a toast that shows (the start of) what was copied.
async function copy(text, label = "Copied") {
  await navigator.clipboard.writeText(text);
  toast(label, text.length > 90 ? text.slice(0, 90) + "…" : text);
}

// ---------------------------------------------------------------- focus
// Live updates and saves redraw parts of a page while you may be using them, and replacing HTML drops the focus.
// focusKey(root) describes the focused element inside root as a CSS selector made of its tag and its id, href, name and
// data-* attributes ("button[data-act="track-open"][data-id="12"]"), or "" when the focus is elsewhere or the element
// has none of them. After root is redrawn, refocus(root, key) focuses the element that matches, so a keyboard user keeps
// their place. It does nothing when something still has the focus.
const FOCUS_ATTRS = /^(id|href|name|data-[\w-]+)$/;
function focusKey(root) {
  const el = document.activeElement;
  if (!el || el === document.body || !root.contains(el)) return "";
  const attrs = [...el.attributes].filter((attr) => FOCUS_ATTRS.test(attr.name)).map((attr) => `[${attr.name}="${CSS.escape(attr.value)}"]`);
  return attrs.length ? el.tagName.toLowerCase() + attrs.join("") : "";
}
function refocus(root, key) {
  const now = document.activeElement;
  if (!key || (now && now !== document.body && now.isConnected)) return;
  $(key, root)?.focus({ preventScroll: true });
}

// True while you're typing in a text box (or text area) inside el. A live redraw keeps such a part as it is, so it never
// eats what you're typing or moves your cursor. Checkboxes and menus don't count: redrawing those loses nothing.
const TEXT_INPUT_TYPES = /^(text|search|email|url|tel|number|password|date)$/;
function typingIn(el) {
  const now = document.activeElement;
  return !!(el && now && el.contains(now) && (now.tagName === "TEXTAREA" || (now.tagName === "INPUT" && TEXT_INPUT_TYPES.test(now.type))));
}

// ---------------------------------------------------------------- formatting
// "today", "1d ago", "12d ago" or "3mo ago" for an ISO date or timestamp. A bare date (2026-10-29) counts from noon.
// "" for no date, or for one that can't be read (a scraped "posted" field can hold anything).
function ago(iso) {
  if (!iso) return "";
  const time = new Date(iso.length <= 10 ? iso + "T12:00:00" : iso).getTime();
  if (isNaN(time)) return "";
  const days = (Date.now() - time) / 86400000;
  if (days < 1) return "today";
  if (days < 2) return "1d ago";
  return days < 60 ? `${Math.floor(days)}d ago` : `${Math.floor(days / 30)}mo ago`;
}

// Days from today until a YYYY-MM-DD date: 0 on the day itself, 1 the day before, -1 the day after. This matches how the
// server counts deadlines and follow-ups. null when there's no date.
function daysUntil(iso) {
  if (!iso || !/^\d{4}-\d{2}-\d{2}/.test(iso)) return null;
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  // round, not floor: a day with a daylight saving change is 23 or 25 hours long
  return Math.round((new Date(iso.slice(0, 10) + "T00:00:00") - today) / 86400000);
}

// "Oct 31" for a YYYY-MM-DD date ("Oct 31, 2025" in another year). Anything else comes back as it is.
function fmtDate(iso) {
  if (!iso || !/^\d{4}-\d{2}-\d{2}/.test(iso)) return iso || "";
  const d = new Date(iso.slice(0, 10) + "T12:00:00");
  const sameYear = d.getFullYear() === new Date().getFullYear();
  return d.toLocaleDateString([], { month: "short", day: "numeric", ...(sameYear ? {} : { year: "numeric" }) });
}

// Server timestamps are UTC (2026-10-29T18:05:09+00:00). These show them in your local time.
// fmtTs: "Oct 29, 2:05 PM" (or "never"). localStamp: "2026-10-29 14:05". localClock: "14:05:09" (now, when iso is empty).
const fmtTs = (ts) => (ts ? new Date(ts).toLocaleString([], { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" }) : "never");
const pad2 = (n) => String(n).padStart(2, "0");
function localStamp(iso) {
  const d = new Date(iso);
  if (isNaN(d)) return String(iso || "").replace("T", " ").slice(0, 16);
  return `${d.getFullYear()}-${pad2(d.getMonth() + 1)}-${pad2(d.getDate())} ${pad2(d.getHours())}:${pad2(d.getMinutes())}`;
}
function localClock(iso) {
  const d = iso ? new Date(iso) : new Date();
  return isNaN(d) ? "" : `${pad2(d.getHours())}:${pad2(d.getMinutes())}:${pad2(d.getSeconds())}`;
}

// "1 question", "3 questions".
const plural = (n, word) => `${n} ${word}${n === 1 ? "" : "s"}`;

// "big_tech_swe" as "Big tech swe": a readable label for a key the dashboard has no name for.
const humanize = (key) => {
  const text = String(key || "").replace(/[_-]+/g, " ").trim();
  return text.charAt(0).toUpperCase() + text.slice(1);
};

// The initials of a name, for avatars: "Jordan Rivera" is "JR". "" for no name.
const initials = (name) => String(name || "").trim().split(/\s+/).filter(Boolean).slice(0, 2).map((word) => word[0]).join("").toUpperCase();

// 950, 45k or 1.2M
const fmtTokens = (n) => (n >= 1e6 ? `${(n / 1e6).toFixed(1)}M` : n >= 1e4 ? `${Math.round(n / 1e3)}k` : (n || 0).toLocaleString());

// The name of an application status ("applied" is "Application sent"). The server sends them in S.meta.status_labels.
const statusLabel = (status) => (S.meta?.status_labels || {})[status] || humanize(status);

// A bullet list of escaped text. cls adds classes such as "good" or "warn", which color the bullets.
const bulletList = (items, cls = "") => `<ul class="bullets${cls ? " " + cls : ""}">${items.map((x) => `<li>${esc(x)}</li>`).join("")}</ul>`;

// The match pill on job cards: the fit score out of 100, tinted by how good it is.
function matchPill(score) {
  const level = score == null ? "none" : score >= 80 ? "high" : score >= 60 ? "mid" : "low";
  return `<div class="match ${level}" title="How well this job fits you, out of 100">`
    + `<strong>${score ?? "-"}</strong>${score == null ? "" : "<small>%</small>"}<span>${score == null ? "NOT SCORED" : "MATCH"}</span></div>`;
}

// An on/off switch. attrs go on the checkbox inside (an id, or data-* attributes that say what it controls).
const toggle = (attrs, on) => `<label class="switch"><input type="checkbox" ${attrs} ${on ? "checked" : ""}><span></span></label>`;

// <option> tags for a <select>. Each choice is a value, or a [value, label] pair. The choice equal to selected is chosen.
function selectOptions(choices, selected) {
  return choices.map((choice) => {
    const [value, label] = Array.isArray(choice) ? choice : [choice, choice];
    return `<option value="${esc(value)}"${String(value) === String(selected ?? "") ? " selected" : ""}>${esc(label)}</option>`;
  }).join("");
}

// A spinner, for anything that's working.
const spinner = () => `<span class="spinner" aria-hidden="true"></span>`;

// ---------------------------------------------------------------- markdown
// A small Markdown renderer for text the AI writes (company briefs, interview prep, the profile). It handles headings,
// bullet and numbered lists, paragraphs, **bold**, *italic*, `code` and links. The text is escaped first, so HTML inside
// it shows as plain text. Put the result in an element with class "prose".
function md(src) {
  const inline = (s) => s
    .replace(/\[([^\]]+)\]\((https?:[^)\s]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>')
    .replace(/(^|[\s(])(https?:\/\/[^\s<)]+)/g, '$1<a href="$2" target="_blank" rel="noopener">$2</a>')
    .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
    .replace(/(^|[^*\w])\*([^*\s][^*]*?)\*(?!\*)/g, "$1<em>$2</em>")
    .replace(/`([^`]+)`/g, "<code>$1</code>");
  const out = [];
  let list = null;  // "ul" or "ol" while inside a list
  const closeList = () => {
    if (list) out.push(`</${list}>`);
    list = null;
  };
  const listItem = (tag, text) => {
    if (list !== tag) {
      closeList();
      out.push(`<${tag}>`);
      list = tag;
    }
    out.push(`<li>${inline(text)}</li>`);
  };
  for (const raw of esc(src || "").split("\n")) {
    const line = raw.trim();
    let m;
    if ((m = line.match(/^(#{1,4})\s+(.*)/))) {
      closeList();
      const level = m[1].length + 2;  // "#" becomes <h3>: the page and its cards already use <h1> and <h2>
      out.push(`<h${level}>${inline(m[2])}</h${level}>`);
    } else if ((m = line.match(/^[-*•]\s+(.*)/))) {
      listItem("ul", m[1]);
    } else if ((m = line.match(/^\d+[.)]\s+(.*)/))) {
      listItem("ol", m[1]);
    } else if (!line) {
      closeList();
    } else {
      closeList();
      out.push(`<p>${inline(line)}</p>`);
    }
  }
  closeList();
  return out.join("\n");
}

// ---------------------------------------------------------------- icons
// The line icons, from the design's set plus the ones the app needs. icon("pin") draws one; cls adds a class ("filled"
// paints its inside).
const ICONS = {
  home: '<path d="M3 11.5 12 4l9 7.5"/><path d="M5.5 10v10h13V10"/><path d="M10 20v-5.5h4V20"/>',
  briefcase: '<rect x="3" y="7" width="18" height="14" rx="2"/><path d="M8 7V5a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2M3 12a22 22 0 0 0 18 0M12 12v3"/>',
  columns: '<rect x="3" y="4" width="5" height="16" rx="1.5"/><rect x="10" y="4" width="5" height="11" rx="1.5"/><rect x="17" y="4" width="4" height="14" rx="1.5"/>',
  chart: '<path d="M3 20h18"/><rect x="5" y="11" width="3" height="6" rx="1"/><rect x="10.5" y="5" width="3" height="12" rx="1"/><rect x="16" y="8" width="3" height="9" rx="1"/>',
  settings: '<path d="M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8z"/><path d="m9 3-1 3-3 1-2 3 2 2-1 3 2 3 3-1 2 3h3l1-3 3-1 2-3-2-2 1-3-2-3-3 1-2-3z"/>',
  file: '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><path d="M14 2v6h6M8 13h8M8 17h6"/>',
  book: '<path d="M12 5C8 2 3 3 3 3v16s5-1 9 2c4-3 9-2 9-2V3s-5-1-9 2zM12 5v16"/>',
  calendar: '<rect x="3" y="5" width="18" height="16" rx="2"/><path d="M16 3v4M8 3v4M3 11h18M8 15h2M14 15h2"/>',
  arrow: '<path d="M5 12h14M13 6l6 6-6 6"/>',
  back: '<path d="M15 6l-6 6 6 6"/>',
  search: '<circle cx="10.5" cy="10.5" r="7.5"/><path d="m16 16 5 5"/>',
  chevron: '<path d="m7 10 5 5 5-5"/>',
  up: '<path d="m7 14 5-5 5 5"/>',
  upload: '<path d="M12 16V3M7 8l5-5 5 5M4 16v5h16v-5"/>',
  download: '<path d="M12 4v11M7 10l5 5 5-5M5 20h14"/>',
  close: '<path d="m6 6 12 12M18 6 6 18"/>',
  pin: '<path d="M20 10c0 6-8 12-8 12S4 16 4 10a8 8 0 1 1 16 0z"/><circle cx="12" cy="10" r="2.5"/>',
  clock: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
  check: '<path d="m5 12.5 4.5 4.5L19 7"/>',
  plus: '<path d="M12 5v14M5 12h14"/>',
  trash: '<path d="M4 7h16M10 11v6M14 11v6M6 7l1 13h10l1-13M9 7V4h6v3"/>',
  refresh: '<path d="M20 12a8 8 0 1 1-2.3-5.6M20 4v5h-5"/>',
  undo: '<path d="M4 12a8 8 0 1 0 2.3-5.6M4 4v5h5"/>',
  external: '<path d="M14 4h6v6M20 4l-9 9M18 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5"/>',
  star: '<path d="M12 3.5l2.6 5.3 5.9.9-4.3 4.1 1 5.8L12 16.9l-5.2 2.7 1-5.8-4.3-4.1 5.9-.9z"/>',
  warning: '<path d="M12 3.8 2.8 20h18.4z"/><path d="M12 10v4.4M12 17.3v.2"/>',
  play: '<path d="M7 4.5v15l12-7.5z"/>',
  stop: '<rect x="6" y="6" width="12" height="12" rx="1.5"/>',
  sparkle: '<path d="M11 3l1.9 5.6 5.6 1.9-5.6 1.9L11 18l-1.9-5.6-5.6-1.9 5.6-1.9z"/><path d="M18.5 14.5l.9 2.6 2.6.9-2.6.9-.9 2.6-.9-2.6-2.6-.9 2.6-.9z"/>',
  question: '<circle cx="12" cy="12" r="9"/><path d="M9.5 9.3a2.6 2.6 0 0 1 5 .9c0 1.7-2.5 2.2-2.5 3.8M12 17.2v.2"/>',
  flag: '<path d="M5 21V4M5 4h11l-2 4 2 4H5"/>',
  user: '<circle cx="12" cy="8" r="4"/><path d="M4 21c1-4 4-6 8-6s7 2 8 6"/>',
  people: '<circle cx="9" cy="8" r="3.5"/><path d="M2.5 20c.8-3.6 3.4-5.5 6.5-5.5s5.7 1.9 6.5 5.5"/><path d="M16 4.5a3.5 3.5 0 0 1 0 7M18 14.6c1.8.8 3 2.6 3.5 5.4"/>',
  mail: '<rect x="3" y="5" width="18" height="14" rx="2"/><path d="m3 7 9 6 9-6"/>',
  copy: '<rect x="9" y="9" width="11" height="11" rx="2"/><path d="M5 15V5a1 1 0 0 1 1-1h10"/>',
  folder: '<path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>',
  signal: '<path d="M5 19a10 10 0 0 1 0-14M19 5a10 10 0 0 1 0 14M8.5 15.5a5 5 0 0 1 0-7M15.5 8.5a5 5 0 0 1 0 7"/><circle cx="12" cy="12" r="1.6"/>',
  bell: '<path d="M18 8a6 6 0 0 0-12 0c0 7-3 7-3 9h18c0-2-3-2-3-9M10 21h4"/>',
  sun: '<circle cx="12" cy="12" r="4"/><path d="M12 2v2m0 16v2M2 12h2m16 0h2M5 5l1.5 1.5m11 11L19 19M5 19l1.5-1.5m11-11L19 5"/>',
  moon: '<path d="M20.9 13a9 9 0 0 1-9.9-9.9A9 9 0 1 0 20.9 13Z"/>',
  tool: '<path d="M14.5 6.5a4 4 0 0 0-5.3 5.3L4 17l3 3 5.2-5.2a4 4 0 0 0 5.3-5.3l-2.5 2.5-2.5-.5-.5-2.5z"/>',
  cert: '<path d="M3 9l9-4.5L21 9l-9 4.5z"/><path d="M7 11.2V15c0 1.5 2.2 2.8 5 2.8s5-1.3 5-2.8v-3.8M21 9v5"/>',
};
const icon = (name, cls = "") => `<svg viewBox="0 0 24 24" aria-hidden="true"${cls ? ` class="${cls}"` : ""}>${ICONS[name] || ""}</svg>`;

// ---------------------------------------------------------------- app state
// S is the one object every page shares. Each field says who fills it. "Event" means a Server-Sent Event (see live.js).
const S = {
  // Loaded at startup (main.js) and kept up to date by events
  meta: null,             // GET /api/meta: version, os, data_dir, statuses, status_labels, efforts, collectors, pdf_ready
  state: { running: false, counts: {} },  // the live run state from the server: running, run_id, mode, phase, counts,
                                          // started_at, tokens, run_tokens_start, ai (the ChatGPT sign-in), active_agents
  stats: null,            // GET /api/stats: the sidebar badges and the Home stats
  logs: [],               // live feed lines {ts, source, level, msg}: the last run's log, then "log" events (600 at most)
  profileStatus: null,    // GET /api/profile/status and "profile_status" events: has_resume, answers_saved, built, busy,
                          // phase, error, unsynced (answers not yet in the profile), open_questions, last_built
  buildDone: false,       // a profile build finished while you watched: Home says so until you move on
  onboarding: null,       // GET /api/onboarding: the standard questions, your answers, what's missing, the main resume
  documents: [],          // the extra documents (GET /api/onboarding, then "documents" events)
  questions: null,        // GET /api/questions and "questions" events: the questions JobPortal asks along the way
  searchArea: null,       // the search area from Settings (locations.allowed): states, cities, "Remote", "Anywhere in the US"
  industries: null,       // the industry list from Settings, for the lead details' industry menu
  profileCache: null,     // GET /api/profile, kept for the Application kit and Settings, Profile (reset on "profile")
  route: [],              // the current hash split into parts: #/leads/12/emails is ["leads", "12", "emails"]
  dirty: false,           // unsaved edits on screen: an editor, a form, a lead's notes, an answer typed on Home
  quit: false,            // you quit JobPortal from Settings: don't reconnect the live stream
  notify: store.get("notify") === "1",  // system notifications for toasts while JobPortal is in the background
  // Leads page (leads.js). The filter and the feed's open state are remembered.
  leadsTab: store.get("leadsTab", "ready"),  // ready, queue, filtered, closed, trashed or all
  q: "",                  // the search box in the top bar
  sort: "score",          // score, new, deadline, posted or industry
  industry: "",           // "" (all) or one industry
  kind: "",               // "" (all), posting, program, event or intel (a company worth contacting, with no posting yet)
  dreamOnly: false,       // only dream companies and dream jobs
  feedOpen: store.get("feedOpen") !== "0",  // the live search feed is expanded
  expanded: null,         // the id of the lead card that's open
  openSources: false,     // an old #/sources link: Leads opens the Sources dialog once it's drawn
  // Lead details (lead.js), on Leads or in the Tracker's dialog
  lead: null,             // GET /api/leads/{id}: the lead on screen, with its package (documents, contacts, emails...)
  leadView: null,         // where it's shown: { box, id, tab, hashBase, header } (hashBase: tabs change the address, as on Leads)
  editor: null,           // the open resume editor's options, so the layout menu and Re-check can reach it
  // Settings (settings.js, sources.js and the tabs)
  cfg: null,              // GET /api/settings, edited in place by the form until you save
  cfgDirty: false,        // S.cfg has edits that aren't saved yet
  cfgEdits: new Set(),    // the settings paths edited since the last save: saving writes only those
  profileSection: null,   // the open part of Settings, Profile (profile.js)
  skills: null,           // the skills inventory rows being edited (profile.js)
  dreams: null,           // GET /api/dreams (dreams.js)
  libTag: "",             // the tag filter on Settings, Resumes (resumes.js)
  libQ: "",               // its search box
  analysis: null,         // the latest analysis' search steering, for its "Add to search plan" buttons (analysis.js)
};

// Display names for where a lead came from (lead.source and lead.sources).
const LABEL_SRC = { github: "GitHub lists", ats: "Company board", linkedin: "LinkedIn", ai_hunt: "AI hunt", hackernews: "Hacker News",
  themuse: "The Muse", usajobs: "USAJobs", reddit: "Reddit", mastodon: "Mastodon", bluesky: "Bluesky", remote: "Remote board",
  rss: "RSS", adzuna: "Adzuna", google: "Google Jobs", manual: "Added by you" };
// The resume layouts, as named in RESUME_THEMES in documents/render.py on the server.
const RESUME_THEMES = ["classic", "modern", "compact", "academic"];

// ---------------------------------------------------------------- toasts
// Shows a short message at the bottom of the window. level "error" makes it red and keeps it longer. With a leadId,
// clicking it opens that lead. action ({ label, run }) adds a button, like Undo. When alerts are on (S.notify) and
// JobPortal is in the background, it also shows a system notification.
function toast(title, body = "", level = "", leadId = null, action = null) {
  const el = document.createElement("div");
  el.className = `toast ${level}`;
  el.innerHTML = `<div class="toast-text"><b>${esc(title)}</b>${body ? `<span>${esc(body)}</span>` : ""}</div>`
    + (action ? `<button class="toast-action" type="button">${esc(action.label)}</button>` : "")
    + `<button class="toast-close" type="button" aria-label="Dismiss">${icon("close")}</button>`;
  el.addEventListener("click", (e) => {
    if (e.target.closest(".toast-action")) {
      Promise.resolve().then(action.run).catch((err) => toast("Something went wrong", err.message, "error"));
    } else if (leadId && !e.target.closest(".toast-close")) {
      location.hash = `#/leads/${leadId}`;
    }
    el.remove();
  });
  const box = $("#toasts");
  box.prepend(el);
  $$(".toast", box).slice(4).forEach((old) => old.remove());  // four at most
  setTimeout(() => el.remove(), level === "error" ? 12000 : action ? 10000 : 6500);
  if (!S.notify) return;
  if (desktop() && !document.hasFocus()) {
    window.pywebview.api.notify(title, body);
  } else if (document.hidden && "Notification" in window && Notification.permission === "granted") {
    const notification = new Notification(title, { body });
    notification.onclick = () => {
      window.focus();
      if (leadId) location.hash = `#/leads/${leadId}`;
    };
  }
}

// ---------------------------------------------------------------- dialogs
// Opens a dialog with the given HTML under a top row (a small heading and a close button) and returns it. Dialogs stack:
// one opened from another sits on top of it. Clicks inside run data-act actions like anywhere else.
// opts: eyebrow (the small heading), wide (a large dialog, for a lead's details), guard (it edits: closing it with
// unsaved edits asks first, and closing it drops them), onClose (runs once it has closed, whatever closed it).
// When it closes, the focus goes back to what opened it. The browser does that while the opener is still on the page;
// when a live update redrew it meanwhile (a Tracker card, the search area card), its twin in the new HTML gets the focus.
function openDialog(html, opts = {}) {
  const openerKey = focusKey(document.body), page = main.dataset.page;
  const dialog = document.createElement("dialog");
  dialog.className = opts.wide ? "wide" : "";
  dialog.innerHTML = `<div class="dialog-body"><div class="dialog-top"><span class="eyebrow">${esc(opts.eyebrow || "")}</span>`
    + `<button class="icon-button" type="button" data-act="close-dialog" aria-label="Close">${icon("close")}</button></div>${html}</div>`;
  dialog.jp = { guard: !!opts.guard, onClose: opts.onClose };
  dialog.addEventListener("cancel", (e) => {  // Esc
    e.preventDefault();
    closeDialog(dialog);
  });
  dialog.addEventListener("mousedown", (e) => {  // a press on the dim backdrop around the dialog
    if (e.target === dialog) closeDialog(dialog);
  });
  dialog.addEventListener("close", () => {
    if (dialog.jp.guard) {
      S.dirty = false;
      S.cfgDirty = false;
    }
    dialog.remove();
    if (dialog.jp.onClose) dialog.jp.onClose();
    if (main.dataset.page === page) refocus(document.body, openerKey);  // not after a move to another page
  });
  document.body.appendChild(dialog);
  dialog.showModal();
  return dialog;
}

// Closes a dialog (the top one when none is given). A dialog with unsaved edits asks first; returns false when you keep it.
function closeDialog(dialog = $$("dialog[open]").at(-1)) {
  if (!dialog) return true;
  if (dialog.jp.guard && (S.dirty || S.cfgDirty) && !confirm("Discard your unsaved edits?")) return false;
  dialog.close();
  return true;
}

// ---------------------------------------------------------------- pop-up menus
// A button with data-act="menu" opens the .menu right after it (both inside a .menu-wrap), and the focus moves to its
// first item. The arrow keys, Home and End move between the items. Picking one, a click anywhere else, or the focus
// moving out (Tab past the last item) closes it; Esc closes it too and puts the focus back on the button.
function closeMenus(focusButton = false) {
  $$(".menu:not([hidden])").forEach((menu) => {
    const button = menu.previousElementSibling, hadFocus = menu.contains(document.activeElement);
    menu.hidden = true;
    button?.setAttribute("aria-expanded", "false");
    if (focusButton && hadFocus) button?.focus();
  });
}
document.addEventListener("click", (e) => {
  if (!e.target.closest(".menu-wrap") || e.target.closest(".menu [data-act]")) closeMenus();
});
document.addEventListener("focusin", (e) => {
  if (!e.target.closest?.(".menu-wrap")) closeMenus();
});
const MENU_KEYS = ["ArrowDown", "ArrowUp", "Home", "End"];
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") closeMenus(true);
  const menu = MENU_KEYS.includes(e.key) && e.target.closest?.(".menu:not([hidden])");
  if (!menu) return;
  e.preventDefault();  // the arrows would scroll the page
  const items = $$("[role=menuitem]", menu), at = items.indexOf(e.target);
  const step = e.key === "ArrowDown" ? 1 : -1;
  items[e.key === "Home" ? 0 : e.key === "End" ? items.length - 1 : (at + step + items.length) % items.length]?.focus();
});

// ---------------------------------------------------------------- own window
// JobPortal shows the dashboard in a window of its own when it can:
// - desktop(): the desktop app. pywebview gives the page window.pywebview.api (app/desktop.py) to save downloads with the
//   system's Save dialog, open links in the default browser and show notifications.
// - appWindow: a browser opened in app mode (no tabs or address bar), marked by ?shell=app in the address. Web and mail
//   links leave it through POST /api/open-external, so they open in the default browser instead.
// In a normal browser tab neither is true: links open in new tabs, and Settings offers a Quit button.
const desktop = () => !!(window.pywebview && window.pywebview.api);
const appWindow = new URLSearchParams(location.search).get("shell") === "app";
const ownWindow = () => desktop() || appWindow;
const isExternal = (url) => /^(https?:|mailto:)/i.test(url);

// Opens a link or a download the right way for the window JobPortal is in.
async function openUrl(url) {
  if (appWindow && isExternal(url)) {
    api("/api/open-external", { method: "POST", body: { url } });
    return;
  }
  if (!desktop()) {
    window.open(url, "_blank", "noopener");
    return;
  }
  if (url.startsWith("/api/")) {  // a file download: save it where you choose
    const result = await window.pywebview.api.save_file(url);
    if (result.ok) toast("Saved", result.path);
    else if (!result.canceled) toast("Couldn't save the file", result.error || "", "error");
  } else {
    window.pywebview.api.open_external(url);
  }
}

// Plain <a href> links get the same treatment in the own window. This listener runs in the capture phase, before any other
// click handler, and stops the click there.
document.addEventListener("click", (e) => {
  const link = e.target.closest("a[href]");
  if (!link || !ownWindow()) return;
  const href = link.getAttribute("href");
  if (isExternal(href) || (desktop() && href.startsWith("/api/"))) {
    e.preventDefault();
    e.stopPropagation();
    openUrl(href);
  }
}, true);

// Closing the app window quits JobPortal, so warn first when that would stop a search.
if (appWindow) {
  window.addEventListener("beforeunload", (e) => {
    if (S.state.running) {
      e.preventDefault();
      e.returnValue = "";
    }
  });
}

// ---------------------------------------------------------------- the action registry
// Clicks: an element with data-act="name" runs ACTIONS[name](el, event), where el is that element. Only the nearest
// data-act element runs, so a button inside a clickable card runs its own action and not the card's.
const ACTIONS = {};
const onAction = (name, fn) => {
  ACTIONS[name] = fn;
};
// Changes to selects, checkboxes and file pickers. main.js offers each change to every handler in turn. A handler returns
// true when the change was its own, and the search stops there.
const CHANGE_HANDLERS = [];
const onChange = (fn) => {
  CHANGE_HANDLERS.push(fn);
};

// ---------------------------------------------------------------- actions
// A link inside a clickable card (where a lead was found) has data-act="ext", so the click only follows the link.
onAction("ext", () => {});
// Copies the element's data-text (contact emails, standard answers).
onAction("copytext", (el) => copy(el.dataset.text));
onAction("close-dialog", (el) => closeDialog(el.closest("dialog")));
onAction("menu", (el) => {
  const menu = el.nextElementSibling;
  const opening = menu.hidden;
  closeMenus();
  menu.hidden = !opening;
  el.setAttribute("aria-expanded", String(opening));
  if (opening) $("[role=menuitem]", menu)?.focus();
});
