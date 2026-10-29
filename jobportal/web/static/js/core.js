/* Shared by every page: small helpers ($, esc, api, formatting), the app state S, toasts and the modal, the own-window
   helpers (desktop app or app-mode window), and the action registry.
   
   How clicks work: any element with data-act="name" inside <main> runs the handler registered with onAction("name", fn).
   Each page file registers its own handlers, and main.js holds the one listener that calls them. */
"use strict";

const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const safeUrl = (u) => (/^(https?:\/\/|mailto:)/i.test(String(u || "").trim()) ? String(u).trim() : "");
const clone = (o) => JSON.parse(JSON.stringify(o));
const main = $("#main");

async function api(path, opts = {}) {
  const o = { headers: {}, ...opts };
  if (o.body && typeof o.body !== "string") { o.body = JSON.stringify(o.body); o.headers["Content-Type"] = "application/json"; }
  const r = await fetch(path, o);
  if (!r.ok) {
    let msg = r.statusText;
    try { const j = await r.json(); msg = j.detail || JSON.stringify(j); } catch (_) {}
    throw new Error(msg);
  }
  const ct = r.headers.get("content-type") || "";
  return ct.includes("json") ? r.json() : r.text();
}
// ---------- own window: the desktop app (pywebview) or a browser in app mode (?shell=app)
// pywebview saves downloads and opens links through the native side. The app window sends links to the default browser.
const desktop = () => !!(window.pywebview && window.pywebview.api);
const appWindow = new URLSearchParams(location.search).get("shell") === "app";
const ownWindow = () => desktop() || appWindow;
const isExternal = (url) => /^(https?:|mailto:)/i.test(url);
const openExternal = (url) => api("/api/open-external", { method: "POST", body: { url } });
async function openUrl(url) {
  if (appWindow && isExternal(url)) { openExternal(url); return; }
  if (!desktop()) { window.open(url, "_blank", "noopener"); return; }
  if (url.startsWith("/api/")) {
    const r = await window.pywebview.api.save_file(url);
    if (r.ok) toast("Saved", r.path); else if (!r.cancelled) toast("Couldn't save the file", r.error || "", "error");
  } else window.pywebview.api.open_external(url);
}
document.addEventListener("click", (e) => {
  const a = e.target.closest("a[href]");
  if (!a || !ownWindow()) return;
  const href = a.getAttribute("href");
  if (isExternal(href) || (desktop() && href.startsWith("/api/"))) { e.preventDefault(); e.stopPropagation(); openUrl(href); }
}, true);
// Closing the app window quits JobPortal, so warn first when that would stop a search.
if (appWindow) window.addEventListener("beforeunload", (e) => { if (S.state.running) { e.preventDefault(); e.returnValue = ""; } });
const debounce = (fn, ms) => { let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); }; };
function ago(iso) {
  if (!iso) return "";
  const d = (Date.now() - new Date(iso.length <= 10 ? iso + "T12:00:00" : iso).getTime()) / 86400000;
  if (d < 1) return "today";
  if (d < 2) return "1d ago";
  return d < 60 ? `${Math.floor(d)}d ago` : `${Math.floor(d / 30)}mo ago`;
}
function daysUntil(iso) {
  if (!iso || !/^\d{4}-\d{2}-\d{2}/.test(iso)) return null;
  return Math.ceil((new Date(iso.slice(0, 10) + "T23:59:00").getTime() - Date.now()) / 86400000);
}
const scoreColor = (s) => (s >= 85 ? "var(--good)" : s >= 70 ? "color-mix(in srgb, var(--good) 60%, var(--text2))" : s >= 55 ? "var(--warn)" : "var(--muted)");
const ring = (s, big) => `<div class="ring ${big ? "big" : ""}" style="--v:${s || 0};--c:${scoreColor(s || 0)}"><span>${s ?? "-"}</span></div>`;
const toggle = (attrs, on) => `<label class="toggle"><input type="checkbox" ${attrs} ${on ? "checked" : ""}><i></i></label>`;
const getPath = (o, p) => p.split(".").reduce((a, k) => (a == null ? a : a[k]), o);
function setPath(o, p, v) { const ks = p.split("."); let a = o; ks.slice(0, -1).forEach((k) => (a = a[k] ??= {})); a[ks.at(-1)] = v; }
async function copy(text, label = "Copied") { await navigator.clipboard.writeText(text); toast(label, text.length > 90 ? text.slice(0, 90) + "…" : text); }

function md(src) {
  const inline = (s) => s
    .replace(/\[([^\]]+)\]\((https?:[^)\s]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>')
    .replace(/(^|[\s(])(https?:\/\/[^\s<)]+)/g, '$1<a href="$2" target="_blank" rel="noopener">$2</a>')
    .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
    .replace(/(^|[^*\w])\*([^*\s][^*]*?)\*(?!\*)/g, "$1<em>$2</em>")
    .replace(/`([^`]+)`/g, "<code>$1</code>");
  const out = []; let list = null;
  const close = () => { if (list) { out.push(`</${list}>`); list = null; } };
  for (const raw of esc(src || "").split("\n")) {
    const l = raw.trim();
    let m;
    if ((m = l.match(/^(#{1,4})\s+(.*)/))) { close(); out.push(`<h${m[1].length + 1}>${inline(m[2])}</h${m[1].length + 1}>`); }
    else if ((m = l.match(/^[-*•]\s+(.*)/))) { if (list !== "ul") { close(); out.push("<ul>"); list = "ul"; } out.push(`<li>${inline(m[1])}</li>`); }
    else if ((m = l.match(/^\d+[.)]\s+(.*)/))) { if (list !== "ol") { close(); out.push("<ol>"); list = "ol"; } out.push(`<li>${inline(m[1])}</li>`); }
    else if (!l) close();
    else { close(); out.push(`<p>${inline(l)}</p>`); }
  }
  close();
  return out.join("\n");
}

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
  ext: '<svg viewBox="0 0 24 24"><path d="M14 4h6v6M20 4l-9 9M18 14v5a1 1 0 01-1 1H5a1 1 0 01-1-1V7a1 1 0 011-1h5"/></svg>',
  dl: '<svg viewBox="0 0 24 24"><path d="M12 4v11M7 10l5 5 5-5M5 20h14"/></svg>',
  setup: '<svg viewBox="0 0 24 24"><path d="M9 11l3 3 8-8"/><path d="M20 12v6a2 2 0 01-2 2H6a2 2 0 01-2-2V6a2 2 0 012-2h9"/></svg>',
};

// ================================================================ state
const S = {
  meta: null, state: { running: false, counts: {} }, stats: null, logs: [], route: [], profileCache: null,
  leadsTab: localStorage.getItem("leadsTab") || "ready", q: "", sort: "score", kind: "",
  consoleOpen: localStorage.getItem("consoleOpen") !== "0", leadTab: "overview", runStart: null,
  notify: localStorage.getItem("notify") === "1",
};
const LABEL_SRC = { github: "GitHub lists", ats: "Company board", linkedin: "LinkedIn", ai_hunt: "AI hunt", hackernews: "Hacker News",
  themuse: "The Muse", usajobs: "USAJobs", reddit: "Reddit", mastodon: "Mastodon", remote: "Remote board", rss: "RSS",
  adzuna: "Adzuna", google: "Google Jobs", manual: "Manual" };
const STATUS_LABEL = { new: "New", saved: "Saved", applied: "Applied", assessment: "Assessment / OA", interviewing: "Interviewing",
  offer: "Offer", rejected: "Rejected", ghosted: "Ghosted", withdrawn: "Withdrawn", trashed: "Trashed" };

// ================================================================ toasts & modal
function toast(title, body = "", level = "", leadId = null) {
  const el = document.createElement("div");
  el.className = `toast ${level}`;
  el.innerHTML = `<b>${esc(title)}</b><span>${esc(body)}</span>`;
  el.onclick = () => { if (leadId) location.hash = `#/lead/${leadId}`; el.remove(); };
  $("#toasts").prepend(el);
  setTimeout(() => el.remove(), level === "error" ? 12000 : 6500);
  if (S.notify && desktop() && !document.hasFocus()) window.pywebview.api.notify(title, body);
  else if (S.notify && document.hidden && "Notification" in window && Notification.permission === "granted") {
    const n = new Notification(title, { body });
    n.onclick = () => { window.focus(); if (leadId) location.hash = `#/lead/${leadId}`; };
  }
}
function modal(html) {
  $("#modal").innerHTML = `<div class="modal-bg"><div class="modal">${html}</div></div>`;
  $("#modal .modal-bg").addEventListener("mousedown", (e) => { if (e.target.classList.contains("modal-bg")) closeModal(); });
}
const closeModal = () => ($("#modal").innerHTML = "");

// ================================================================ actions
// A click on an element with data-act="name" inside <main> runs ACTIONS[name](el, event). Pages add theirs with onAction().
const ACTIONS = {};
const onAction = (name, fn) => { ACTIONS[name] = fn; };
// Changes to selects and checkboxes inside <main>. Each handler returns true when the change was its own.
const CHANGE_HANDLERS = [];
const onChange = (fn) => { CHANGE_HANDLERS.push(fn); };

// ---------------------------------------------------------------- actions
onAction("ext", async (el, e) => { e.stopPropagation(); return; });
onAction("copytext", async (el, e) => { copy(el.dataset.text); });
