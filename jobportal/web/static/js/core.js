/* core.js: the shared toolkit. It loads first, so every other file can use what's defined here.

   - Helpers: $ and $$ find elements, esc() makes text safe inside HTML, api() calls the server, plus small formatters.
   - md(): a small Markdown renderer for the text the AI writes.
   - S: the app state that every page reads and writes.
   - toast() for short messages in the corner, and modal() for dialogs.
   - The own window: the desktop app (desktop()) or a browser window in app mode (appWindow).
   - The action registry: onAction() for clicks and onChange() for selects and checkboxes.

   How clicks work: any element with data-act="name" inside <main> runs the handler registered with onAction("name", fn).
   Each page file registers its own handlers at the bottom, and main.js holds the one listener that calls them. */
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

// <main>: every page draws itself in here.
const main = $("#main");

// Calls the JobPortal server. An object body is sent as JSON. Returns the parsed JSON (or text). When the request fails it
// throws an Error carrying the server's message, so callers can show it in a toast.
async function api(path, opts = {}) {
  const request = { headers: {}, ...opts };
  if (request.body && typeof request.body !== "string") {
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
    throw new Error(message);
  }
  const type = response.headers.get("content-type") || "";
  return type.includes("json") ? response.json() : response.text();
}

// Sends a file as the raw body of a PUT and returns the JSON reply. (api() would turn the file into JSON.)
async function uploadFile(url, file) {
  const response = await fetch(url, { method: "PUT", body: file });
  const reply = await response.json();
  if (!response.ok) throw new Error(reply.detail || response.statusText);
  return reply;
}

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

// ---------------------------------------------------------------- formatting
// "today", "1d ago", "12d ago" or "3mo ago" for an ISO date or timestamp. A bare date (2026-10-29) counts from noon.
function ago(iso) {
  if (!iso) return "";
  const time = new Date(iso.length <= 10 ? iso + "T12:00:00" : iso).getTime();
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

// A bullet list of escaped text. cls adds classes such as "good" or "warn", which color the bullets.
const bulletList = (items, cls = "") => `<ul class="clean${cls ? " " + cls : ""}">${items.map((x) => `<li>${esc(x)}</li>`).join("")}</ul>`;

// The color of a fit score: green for great matches, fading to gray for weak ones.
function scoreColor(score) {
  if (score >= 85) return "var(--good)";
  if (score >= 70) return "color-mix(in srgb, var(--good) 60%, var(--text2))";
  return score >= 55 ? "var(--warn)" : "var(--muted)";
}

// The round score badge on lead cards and the lead page. big = the larger one in the lead page header.
const ring = (score, big) => `<div class="ring ${big ? "big" : ""}" style="--v:${score || 0};--c:${scoreColor(score || 0)}">`
  + `<span>${score ?? "-"}</span></div>`;

// An on/off switch. attrs go on the hidden checkbox (an id, or data-* attributes that say what it controls).
const toggle = (attrs, on) => `<label class="toggle"><input type="checkbox" ${attrs} ${on ? "checked" : ""}><i></i></label>`;

// <option> tags for a <select>. Each choice is a value, or a [value, label] pair. The choice equal to selected is chosen.
function selectOptions(choices, selected) {
  return choices.map((choice) => {
    const [value, label] = Array.isArray(choice) ? choice : [choice, choice];
    return `<option value="${esc(value)}"${value === selected ? " selected" : ""}>${esc(label)}</option>`;
  }).join("");
}

// ---------------------------------------------------------------- markdown
// A small Markdown renderer for text the AI writes (company intel, interview prep, the profile). It handles headings,
// bullet and numbered lists, paragraphs, **bold**, *italic*, `code` and links. The text is escaped first, so HTML inside
// it shows as plain text.
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
      const level = m[1].length + 1;  // "#" becomes <h2>: the page already has its own <h1>
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
// Inline SVG icons for the navigation (one per page, by route name) plus "ext" (opens elsewhere) and "dl" (download).
// The small icons in text and buttons are CSS classes instead: <i class=i-star></i> (see the end of style.css).
const I = {
  leads: '<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="5"/><path d="M12 12l6-6"/><circle cx="12" cy="12" r="1"/></svg>',
  tracker: '<svg viewBox="0 0 24 24"><rect x="3" y="4" width="5" height="16" rx="1"/><rect x="10" y="4" width="5" height="10" rx="1"/><rect x="17" y="4" width="4" height="13" rx="1"/></svg>',
  contacts: '<svg viewBox="0 0 24 24"><circle cx="9" cy="8" r="3.5"/><path d="M2.5 20c.8-3.6 3.4-5.5 6.5-5.5s5.7 1.9 6.5 5.5"/><path d="M16 4.5a3.5 3.5 0 010 7M18 14.6c1.8.8 3 2.6 3.5 5.4"/></svg>',
  sources: '<svg viewBox="0 0 24 24"><path d="M5 19a10 10 0 010-14M19 5a10 10 0 010 14M8.5 15.5a5 5 0 010-7M15.5 8.5a5 5 0 010 7"/><circle cx="12" cy="12" r="1.6"/></svg>',
  profile: '<svg viewBox="0 0 24 24"><circle cx="9" cy="8" r="3.5"/><path d="M2.5 20c.8-3.6 3.4-5.5 6.5-5.5s5.7 1.9 6.5 5.5"/><circle cx="15.5" cy="8" r="3.5" stroke-dasharray="2 2"/><path d="M17.5 14.7c2.1.6 3.5 2.4 4 5.3" stroke-dasharray="2 2"/></svg>',
  settings: '<svg viewBox="0 0 24 24"><path d="M4 6h10M18 6h2M4 12h4M12 12h8M4 18h12M20 18h0"/><circle cx="16" cy="6" r="2"/><circle cx="10" cy="12" r="2"/><circle cx="18" cy="18" r="2"/></svg>',
  crm: '<svg viewBox="0 0 24 24"><path d="M14 4l6 6M15.5 5.5L8 13M3 21l5-5"/><path d="M12 3l-3 3 9 9 3-3"/></svg>',
  dreams: '<svg viewBox="0 0 24 24"><path d="M12 3.5l2.6 5.3 5.9.9-4.3 4.1 1 5.8L12 16.9l-5.2 2.7 1-5.8-4.3-4.1 5.9-.9z"/></svg>',
  analysis: '<svg viewBox="0 0 24 24"><path d="M12 3l8 5.5-3 9.5H7L4 8.5z"/><path d="M12 8l3.5 2.5-1.3 4H9.8l-1.3-4z"/></svg>',
  resumes: '<svg viewBox="0 0 24 24"><path d="M6 3h8l4 4v14H6z"/><path d="M14 3v4h4M9 11h6M9 14.5h6M9 18h4"/></svg>',
  runs: '<svg viewBox="0 0 24 24"><rect x="3" y="4" width="18" height="16" rx="2"/><path d="M7 9l3 3-3 3M12 15h5"/></svg>',
  setup: '<svg viewBox="0 0 24 24"><path d="M9 11l3 3 8-8"/><path d="M20 12v6a2 2 0 01-2 2H6a2 2 0 01-2-2V6a2 2 0 012-2h9"/></svg>',
  ext: '<svg viewBox="0 0 24 24"><path d="M14 4h6v6M20 4l-9 9M18 14v5a1 1 0 01-1 1H5a1 1 0 01-1-1V7a1 1 0 011-1h5"/></svg>',
  dl: '<svg viewBox="0 0 24 24"><path d="M12 4v11M7 10l5 5 5-5M5 20h14"/></svg>',
};

// ---------------------------------------------------------------- app state
// S is the one object every page shares. Each field lists who fills it. "Event" means a Server-Sent Event (see live.js).
const S = {
  // Loaded at startup (main.js) and kept up to date by events
  meta: null,             // GET /api/meta: version, os, data_dir, statuses, efforts, collectors, pdf_ready
  state: { running: false, counts: {} },  // the live run state from the server: running, run_id, mode, phase, counts,
                                          // started_at, tokens, run_tokens_start, ai (sign-in status), active_agents
  stats: null,            // GET /api/stats: the numbers behind the navigation badges and the Leads page tiles
  logs: [],               // live feed lines {ts, source, level, msg}: the last run's log, then "log" events (600 at most)
  profileStatus: null,    // GET /api/profile/status and "profile_status" events: has_resume, answers_saved, built, busy,
                          // phase, error, unsynced (answers not yet in the profile), open_questions, last_built
  questions: null,        // GET /api/questions and "questions" events: the questions JobPortal asks along the way
  searchArea: null,       // the search area from Settings (locations.allowed): states, cities, "Remote", "Anywhere in the US"
  industries: null,       // the industry list from Settings, for the lead page's industry menu
  profileCache: null,     // GET /api/profile, kept for the Application kit and the search area editor (reset on "profile")
  route: [],              // the current hash split into parts: #/lead/12/emails is ["lead", "12", "emails"]
  dirty: false,           // the open page has unsaved edits (an editor or an answers form)
  quit: false,            // you quit JobPortal from Settings: don't reconnect the live stream
  // Leads page (leads.js). The tab and the two switches are remembered in localStorage.
  leadsTab: localStorage.getItem("leadsTab") || "ready",  // ready, queue, filtered, closed, trashed or all
  q: "",                  // the search box
  sort: "score",          // score, new, deadline, posted or industry
  kind: "",               // "" (all), posting, program, event or intel
  industry: "",           // "" (all) or one industry
  dreamOnly: false,       // only dream companies and dream jobs
  consoleOpen: localStorage.getItem("consoleOpen") !== "0",  // the live feed is expanded
  notify: localStorage.getItem("notify") === "1",            // system notifications for toasts while JobPortal is hidden
  // Lead page (lead.js)
  lead: null,             // GET /api/leads/{id}: the lead on screen, with its package (documents, contacts, emails...)
  leadTab: "overview",    // the lead page tab (LEAD_TABS)
  editor: null,           // the open resume editor's options, so the layout menu and Re-check can reach it
  // Profile page (profile.js)
  profileTab: null,       // the open tab (PTABS)
  openQuestions: null,    // the open questions in the order the Questions tab lists them
  skills: null,           // the skills inventory rows being edited on the Skills tab
  drawSkills: null,       // redraws the Skills tab table from S.skills
  // Settings and Sources pages (settings.js, sources.js)
  cfg: null,              // GET /api/settings, edited in place by the form until you save
  cfgDirty: false,        // S.cfg has edits that aren't saved yet
  // Set up page (setup.js)
  onboarding: null,       // GET /api/onboarding: the standard questions, your answers, the imported resume, the status
  setupStep: null,        // chatgpt, resume, answers or build
  prefill: null,          // answers the AI read from the resume you just imported, to pre-fill the questions
  // Resumes page (resumes.js)
  libTag: "",             // the tag filter
  libQ: "",               // the search box
  libLog: "",             // the last import progress line
  // Other pages
  dreams: null,           // GET /api/dreams (dreams.js)
  crmKind: "",            // the "kind of move" filter on Equity mining (crm.js)
  analysis: null,         // the latest analysis' search steering, for its "Add to search plan" buttons (analysis.js)
};

// Display names for where a lead came from (lead.source and lead.sources).
const LABEL_SRC = { github: "GitHub lists", ats: "Company board", linkedin: "LinkedIn", ai_hunt: "AI hunt", hackernews: "Hacker News",
  themuse: "The Muse", usajobs: "USAJobs", reddit: "Reddit", mastodon: "Mastodon", bluesky: "Bluesky", remote: "Remote board",
  rss: "RSS", adzuna: "Adzuna", google: "Google Jobs", manual: "Manual" };
// Display names for the application statuses (lead.app_status). The server sends the list in S.meta.statuses.
const STATUS_LABEL = { new: "New", saved: "Saved", applied: "Applied", assessment: "Assessment / OA", interviewing: "Interviewing",
  offer: "Offer", rejected: "Rejected", ghosted: "Ghosted", withdrawn: "Withdrawn", trashed: "Trashed" };
// The resume layouts, as named in RESUME_THEMES in documents/render.py on the server.
const RESUME_THEMES = ["classic", "modern", "compact", "academic"];

// ---------------------------------------------------------------- toasts and the modal
// Shows a short message in the corner. level "error" makes it red and keeps it longer. With a leadId, clicking it opens that
// lead. When alerts are on (S.notify) and JobPortal is in the background, it also shows a system notification.
function toast(title, body = "", level = "", leadId = null) {
  const el = document.createElement("div");
  el.className = `toast ${level}`;
  el.innerHTML = `<b>${esc(title)}</b><span>${esc(body)}</span>`;
  el.onclick = () => {
    if (leadId) location.hash = `#/lead/${leadId}`;
    el.remove();
  };
  $("#toasts").prepend(el);
  setTimeout(() => el.remove(), level === "error" ? 12000 : 6500);
  if (!S.notify) return;
  if (desktop() && !document.hasFocus()) {
    window.pywebview.api.notify(title, body);
  } else if (document.hidden && "Notification" in window && Notification.permission === "granted") {
    const notification = new Notification(title, { body });
    notification.onclick = () => {
      window.focus();
      if (leadId) location.hash = `#/lead/${leadId}`;
    };
  }
}

// Opens a dialog with the given HTML. Clicking the dark backdrop around it closes it. Dialogs live outside <main>, so their
// buttons use their own handlers instead of data-act.
function modal(html) {
  const host = $("#modal");
  host.onclick = host.onchange = null;  // drop the last dialog's handlers (a dialog that needs them sets them after this)
  host.innerHTML = `<div class="modal-bg"><div class="modal">${html}</div></div>`;
  $(".modal-bg", host).addEventListener("mousedown", (e) => {
    if (e.target.classList.contains("modal-bg")) closeModal();
  });
}
const closeModal = () => ($("#modal").innerHTML = "");

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
    else if (!result.cancelled) toast("Couldn't save the file", result.error || "", "error");
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
// Clicks: an element with data-act="name" inside <main> runs ACTIONS[name](el, event), where el is that element. Only the
// nearest data-act element runs, so a button inside a clickable card runs its own action and not the card's.
const ACTIONS = {};
const onAction = (name, fn) => {
  ACTIONS[name] = fn;
};
// Changes to selects and checkboxes inside <main>. main.js offers each change to every handler in turn. A handler returns
// true when the change was its own, and the search stops there.
const CHANGE_HANDLERS = [];
const onChange = (fn) => {
  CHANGE_HANDLERS.push(fn);
};

// ---------------------------------------------------------------- actions
// A link inside a clickable card (a lead's "found at" link) has data-act="ext", so the click only follows the link.
onAction("ext", () => {});
// Copies the element's data-text (contact emails, standard answers).
onAction("copytext", (el) => {
  copy(el.dataset.text);
});
