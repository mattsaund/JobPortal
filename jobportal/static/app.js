/* JobPortal dashboard. Vanilla JS, no build step. Everything from the web is escaped before rendering. */
"use strict";

// ================================================================ utils
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

// ================================================================ live events
function connect() {
  const es = new EventSource("/api/events");
  es.onmessage = (e) => { try { onEvent(JSON.parse(e.data)); } catch (err) { console.error(err); } };
  es.onerror = () => { es.close(); if (!S.quit) setTimeout(connect, 2500); };
}
const refreshSoon = debounce(() => { refreshStats(); if (S.route[0] === "leads") loadLeads(true); }, 2500);
function onEvent({ kind, data }) {
  if (kind === "state") {
    const wasRunning = S.state.running;
    S.state = data;
    if (data.running && !wasRunning) S.runStart = Date.now();
    renderAgents(); renderAI();
    if (S.route[0] === "leads") renderMission();
    if (wasRunning && !data.running) refreshSoon();
  } else if (kind === "log") {
    S.logs.push(data); if (S.logs.length > 600) S.logs.splice(0, S.logs.length - 600);
    appendLog(data);
  } else if (kind === "lead") {
    if (data && S.route[0] === "leads") upsertLead(data);
    if (data && S.route[0] === "lead" && +S.route[1] === data.id) renderLead(data.id, true);
    refreshSoon();
  } else if (kind === "toast") {
    toast(data.title, data.body, data.level || "", data.lead_id);
  } else if (kind === "ai") { onAIStatus(data); }
  else if (kind === "tokens") { S.state.tokens = data; renderAI(); if (S.route[0] === "leads") renderMission(); }
  else if (kind === "agents") { S.state.active_agents = data; renderAgents(); }
  else if (kind === "run_done") { toast(`Run #${data.run_id} ${data.status}`, `${data.stats.qualified || 0} qualified, ${data.stats.packaged || 0} packaged`); refreshSoon(); }
  else if (kind === "profile") { S.profileCache = null; if (S.route[0] === "profile" && !S.dirty && !["answers", "questions"].includes(S.ptab)) renderProfile(); }
  else if (kind === "profile_status") { onProfileStatus(data); }
  else if (kind === "questions") { S.questions = data; renderNav(); if (S.route[0] === "profile" && S.ptab === "questions" && !questionDraft()) renderProfile("questions"); }
  else if (kind === "analysis") { if (S.route[0] === "analysis") renderAnalysis(); }
}

// ================================================================ sidebar
function renderNav() {
  const st = S.stats || {};
  const openQ = (S.questions || []).filter((q) => q.status === "open").length;
  const items = [...(onboarded() && aiReady() ? [] : [["setup", "Set up", "!"]]), ["leads", "Leads", st.ready], ["crm", "Equity mining"], ["tracker", "Tracker", st.followups_due], ["resumes", "Resumes"], ["analysis", "Analysis"], ["dreams", "Dream list"], ["contacts", "Contacts"],
    ["sources", "Sources"], ["profile", "Profile", openQ], ["settings", "Settings"], ["runs", "Runs"]];
  $("#nav").innerHTML = items.map(([k, l, b]) =>
    `<a href="#/${k}" class="${S.route[0] === k || (k === "leads" && S.route[0] === "lead") ? "on" : ""}">${I[k]}${l}${b ? `<span class="badge">${b}</span>` : ""}</a>`).join("");
}
const fmtTokens = (n) => (n >= 1e6 ? `${(n / 1e6).toFixed(1)}M` : n >= 1e4 ? `${Math.round(n / 1e3)}k` : (n || 0).toLocaleString());
const aiReady = () => !!(S.state.ai && S.state.ai.signed_in);
function renderAI() {
  const el = $("#usage"); if (!el) return;
  const a = S.state.ai || {};
  el.innerHTML = a.signed_in
    ? `<div>ChatGPT</div><div class="small" style="overflow:hidden;text-overflow:ellipsis" title="${esc(a.email || "")}">${esc(a.name || a.email || "signed in")}</div><div class="small">${fmtTokens(+S.state.tokens || 0)} tokens this session</div>`
    : `<div>ChatGPT</div><div class="small">not signed in</div><button class="btn sm primary" data-act="ai-signin" style="margin-top:6px">Continue with ChatGPT</button>`;
}
function onAIStatus(data) {
  const was = aiReady();
  S.state.ai = data; renderAI(); renderNav();
  if (!was && aiReady()) toast("Signed in with ChatGPT", data.email || data.name || "JobPortal can use your plan now.");
  if (S.route[0] === "setup" && S.setupStep === "chatgpt" && aiReady()) renderSetup("resume");
  if (S.route[0] === "settings" && !S.cfgDirty) renderSettings();
}
// Sign in with ChatGPT happens in the system browser; OpenAI sends it back to this app's server, which then publishes "ai".
async function aiSignIn() {
  const w = ownWindow() ? null : window.open("", "_blank");  // opened during the click so popup blockers allow it
  try {
    const r = await api("/api/ai/signin", { method: "POST" });
    if (ownWindow()) await openUrl(r.url); else if (w) w.location = r.url; else location.href = r.url;
    toast("Finish signing in", "Sign in with ChatGPT in your browser. JobPortal updates when you're done.");
  } catch (e) { if (w) w.close(); toast("Couldn't start sign-in", e.message, "error"); }
}
async function aiSignOut() {
  const r = await api("/api/ai/signout", { method: "POST" });
  toast("Signed out of ChatGPT", r.note || "JobPortal no longer uses your plan.");
}
$("#usage").addEventListener("click", (e) => { if (e.target.closest("[data-act=ai-signin]")) aiSignIn(); });

// ---------- profile status (setup progress, builds, answers waiting to be added)
const onboarded = () => { const st = S.pstatus || {}; return !!(st.has_resume && st.answers_saved && st.built); };
function onProfileStatus(data) {
  const was = onboarded();
  S.pstatus = data;
  renderProfilePill();
  if (was !== onboarded()) renderNav();
  if (S.route[0] === "setup") setupStatusChanged();
  if (S.route[0] === "profile" && S.ptab === "overview" && !S.dirty) renderProfile("overview");
}
function renderProfilePill() {
  const el = $("#profile-pill"); if (!el) return;
  const st = S.pstatus || {};
  let cls = "ok", html = `<i class=i-check></i> profile up to date`, href = "#/profile", tip = "Your profile has everything you've told JobPortal.";
  if (st.busy) { cls = "busy"; html = `<span class="spin"></span> ${esc(st.phase || "updating your profile")}`; tip = "JobPortal is updating your profile."; }
  else if (st.error) { cls = "err"; html = `<i class=i-warn></i> profile update failed`; tip = st.error; }
  else if (!onboarded()) { cls = "dirty"; html = `<i class=i-dot></i> finish setting up`; href = "#/setup"; tip = "Import your resume and answer the standard questions to start searching."; }
  else if (st.unsynced) { cls = "dirty"; html = `<i class=i-dot></i> ${st.unsynced} answer${st.unsynced > 1 ? "s" : ""} to add`; href = "#/profile/questions"; tip = "New answers are added to your profile automatically after a short pause."; }
  el.className = `status-pill ${cls}`; el.href = href; el.innerHTML = html; el.title = tip;
}

function renderAgents() {
  const a = Object.values(S.state.active_agents || {});
  $("#agents").innerHTML = a.length ? `<div class="small" style="margin-bottom:4px">${a.length} agent${a.length > 1 ? "s" : ""} working</div>` +
    a.slice(0, 6).map((x) => `<div class="a"><span class="dot"></span>${esc(x)}</div>`).join("") : "";
}
async function refreshStats() {
  try { S.stats = await api("/api/stats"); renderNav(); if (S.route[0] === "leads") renderTiles(); } catch (_) {}
}

// ================================================================ router
const ROUTES = { setup: () => renderSetup(), resumes: (id) => renderLibrary(id), crm: () => renderCRM(), dreams: () => renderDreams(), analysis: () => renderAnalysis(), leads: renderLeads, lead: (id, tab) => { if (tab) S.leadTab = tab; renderLead(+id); }, tracker: renderTracker, contacts: renderContacts,
  sources: renderSources, profile: renderProfile, settings: renderSettings, runs: renderRuns };
function route() {
  const parts = location.hash.replace(/^#\/?/, "").split("/").filter(Boolean);
  S.route = parts.length ? parts : [onboarded() ? "leads" : "setup"];
  renderNav();
  (ROUTES[S.route[0]] || renderLeads)(...S.route.slice(1));
  main.scrollTop = 0;
}
window.addEventListener("hashchange", route);

// ================================================================ LEADS (mission control)
async function renderLeads() {
  main.innerHTML = `<div class="page">
    <div class="page-h"><h1>Mission control</h1><span class="sub">Every lead, tailored and ready to fire.</span><span class="spacer"></span>
      <button class="btn" data-act="add-lead">+ Add a lead</button></div>
    ${onboarded() ? "" : `<div class="banner accent"><div><b>Finish setting up first.</b> Import your resume and answer the standard job questions, and JobPortal builds the profile it searches with.</div><span class="spacer"></span><a class="btn primary sm" href="#/setup">Set up</a></div>`}
    <div id="mission"></div>
    <div class="tiles" id="tiles"></div>
    <div class="console ${S.consoleOpen ? "" : "closed"}" id="console">
      <div class="ch" data-act="toggle-console"><span><i class=i-chev></i> Live feed</span><span class="spacer"></span><span id="console-n"></span><span>${S.consoleOpen ? "hide" : "show"}</span></div>
      <div class="body" id="console-body"></div></div>
    <div class="tabs" id="ltabs"></div>
    <div class="filters">
      <input type="text" id="lq" placeholder="Search title, company, location, source…" value="${esc(S.q)}">
      <select id="lsort"><option value="score">Best match</option><option value="new">Newest found</option><option value="deadline">Deadline soonest</option><option value="posted">Recently posted</option><option value="industry">Industry</option></select>
      <select id="lind"><option value="">All industries</option></select>
      <button class="btn sm ${S.dreamOnly ? "toggled" : "ghost"}" data-act="dream-only" title="Only dream companies / dream jobs. Edit them on the Dream list page"><i class=i-star></i> Dream</button>
      <select id="lkind"><option value="">All kinds</option><option value="posting">Postings</option><option value="program">Programs</option><option value="event">Events</option><option value="intel">Intel (no posting yet)</option></select>
      <span class="spacer"></span><span class="muted small mono" id="lcount"></span>
    </div>
    <div class="leads" id="leadlist"></div></div>`;
  $("#lsort").value = S.sort; $("#lkind").value = S.kind;
  $("#lq").addEventListener("input", debounce((e) => { S.q = e.target.value; loadLeads(); }, 250));
  $("#lsort").onchange = (e) => { S.sort = e.target.value; loadLeads(); };
  $("#lkind").onchange = (e) => { S.kind = e.target.value; loadLeads(); };
  $("#lind").onchange = (e) => { S.industry = e.target.value; loadLeads(); };
  renderMission(); renderTiles();
  $("#console-body").innerHTML = S.logs.map(logLine).join("");
  $("#console-body").scrollTop = 1e9;
  await loadLeads();
}

function renderMission() {
  const el = $("#mission"); if (!el) return;
  const st = S.state, c = st.counts || {};
  const chips = [["found", c.found], ["candidates", c.candidates], ["triaged", c.triaged], ["qualified", c.qualified], ["packaged", c.packaged]]
    .filter(([, v]) => v != null).map(([k, v]) => `<span class="chip"><b>${v}</b> ${k}</span>`).join("");
  const used = (+st.tokens || 0) - (+st.run_tokens_start || 0);
  const cost = st.running && used > 0 ? `<span class="chip" title="AI tokens this run has used on your ChatGPT plan">${fmtTokens(used)} tokens</span>` : "";
  const t0 = st.started_at ? Date.parse(st.started_at) : S.runStart;
  const el2 = st.running && t0 ? Math.max(0, Math.floor((Date.now() - t0) / 1000)) : 0;
  el.innerHTML = `<div class="mission ${st.running ? "running" : ""}">
    <div class="runbtn">${st.running
      ? `<button class="btn stop" data-act="stop"><i class=i-stop></i> Stop</button>`
      : `<button class="btn primary go" data-act="run"><i class=i-play></i> Run search</button><select class="mode" id="runmode" title="What to run">
          <option value="full">Everything</option><option value="boards">Job boards only</option><option value="hunt">AI hunt only</option><option value="backlog">Package queue only</option></select>`}</div>
    <div class="phase">${st.running
      ? `<div class="p"><span class="spin"></span><b>${esc(st.phase)}</b><span class="muted">run #${st.run_id}, ${esc(st.mode)}, ${Math.floor(el2 / 60)}m ${el2 % 60}s</span></div><div class="counters">${chips}${cost}</div>`
      : `<div class="p muted">Idle. A run sweeps LinkedIn, company boards, job lists, HN, Reddit, Mastodon and feeds, while AI agents hunt social media, recruiters, labs, contracts and events.</div>${chips ? `<div class="counters">${chips}${cost}<span class="chip">last run</span></div>` : ""}`}</div>
    <div class="right"><button class="chip area-chip" data-act="edit-area" title="Where the search looks. Click to broaden or shrink it."><i class=i-pin></i> ${esc(areaSummary(S.locAllowed || []))} <i class=i-edit></i></button>
      <button class="btn ghost sm" data-act="notify" title="Desktop notifications when leads are ready">${S.notify ? '<i class=i-bell></i> Alerts on' : '<i class=i-bell-off></i> Alerts off'}</button></div></div>`;
  if (!st.running) { const m = localStorage.getItem("runmode"); if (m && $("#runmode")) $("#runmode").value = m; }
}
setInterval(() => { if (S.state.running && S.route[0] === "leads") renderMission(); }, 1000);

function renderTiles() {
  const el = $("#tiles"); if (!el) return;
  const s = S.stats || {};
  const t = [["ready", "Ready to apply", s.ready, "hot"], ["queue", "In the queue", s.queue], ["tracker", "Applied (last 7 days)", `${s.applied ?? 0} (${s.applied_week ?? 0})`],
    ["tracker", "Interviewing", s.interviewing], ["tracker", "Follow-ups due", s.followups_due, s.followups_due ? "hot" : ""]];
  el.innerHTML = t.map(([go, l, n, cls]) => `<div class="tile ${cls || ""}" data-act="tile" data-go="${go}"><div class="n">${n ?? 0}</div><div class="l">${l}</div></div>`).join("");
}

const cleanMsg = (m) => String(m || "").replace(/^\u2713 (\d+) /, "qualified $1: ").replace(/^\u2605 (\d+) /, "ready $1: ").replace(/^[\u25A0\u25B6\u23F8] ?/, "")
  .replace(/^\uD83D\uDD0E ?/, "search: ").replace(/^\uD83C\uDF10 ?/, "read: ");
const logLine = (l) => `<div class="ln ${esc(l.level)}"><span class="t">${esc((l.ts || new Date().toISOString()).slice(11, 19))}</span><span class="s">${esc(l.source || "")}</span>  ${esc(cleanMsg(l.msg))}</div>`;
function appendLog(l) {
  const b = $("#console-body"); if (!b) return;
  const atBottom = b.scrollHeight - b.scrollTop - b.clientHeight < 40;
  b.insertAdjacentHTML("beforeend", logLine(l));
  while (b.childElementCount > 600) b.firstElementChild.remove();
  if (atBottom) b.scrollTop = 1e9;
  const n = $("#console-n"); if (n) n.textContent = `${S.logs.length} lines`;
}

const TAB_LABELS = { ready: "Ready", queue: "In queue", filtered: "Below threshold", closed: "Closed", trashed: "Trashed", all: "All" };
function inTab(l, tab) {
  if (tab === "trashed") return l.app_status === "trashed";
  if (l.app_status === "trashed") return false;
  return { ready: l.stage === "ready" && ["new", "saved"].includes(l.app_status), queue: ["qualified", "packaging", "error"].includes(l.stage),
    filtered: l.stage === "filtered", closed: l.stage === "closed", all: true }[tab];
}
async function loadLeads(silent) {
  const p = new URLSearchParams({ tab: S.leadsTab, q: S.q, sort: S.sort, kind: S.kind, industry: S.industry || "", dream: S.dreamOnly ? 1 : 0 });
  const d = await api(`/api/leads?${p}`);
  const tabs = $("#ltabs"); if (!tabs) return;
  tabs.innerHTML = Object.entries(TAB_LABELS).map(([k, l]) => `<a class="${S.leadsTab === k ? "on" : ""}" data-act="ltab" data-tab="${k}">${l}<span class="n">${d.counts[k] ?? 0}</span></a>`).join("");
  $("#lcount").innerHTML = `${d.leads.length} shown` + (["filtered", "queue"].includes(S.leadsTab) ? ` <button class="btn sm" data-act="retriage" title="Re-score these against your current profile (new answers can change the verdict)"><i class=i-refresh></i> Re-evaluate</button>` : "");
  const li = $("#lind");
  if (li) li.innerHTML = `<option value="">All industries</option>` + Object.entries(d.industries || {}).map(([k, n]) => `<option value="${esc(k)}" ${S.industry === k ? "selected" : ""}>${esc(k)} (${n})</option>`).join("")
    + (S.industry && !(d.industries || {})[S.industry] ? `<option selected value="${esc(S.industry)}">${esc(S.industry)} (0)</option>` : "");
  const list = $("#leadlist");
  if (!d.leads.length) {
    list.innerHTML = `<div class="empty"><b>${S.leadsTab === "ready" ? "No packaged leads yet" : "Nothing here"}</b>${S.leadsTab === "ready" ? "Hit Run search. Leads pop in here as each application package finishes." : ""}</div>`;
    return;
  }
  if (silent) {
    const have = new Set($$(".lead", list).map((e) => +e.dataset.id));
    list.innerHTML = d.leads.map((l) => leadCard(l, !have.has(l.id) && have.size > 0)).join("");
  } else list.innerHTML = d.leads.map((l) => leadCard(l)).join("");
}
function upsertLead(l) {
  const list = $("#leadlist"); if (!list) return;
  const el = $(`.lead[data-id="${l.id}"]`, list);
  if (!inTab(l, S.leadsTab)) { el?.remove(); return; }
  const html = leadCard(l, !el);
  if (el) el.outerHTML = html;
  else { $(".empty", list)?.remove(); list.insertAdjacentHTML("afterbegin", html); }
}
function stageBadge(l) {
  if (l.stage === "packaging") return `<span class="stage stage-packaging row" style="gap:6px"><span class="spin"></span>building package</span>`;
  if (l.stage === "qualified") return `<span class="stage stage-qualified">queued</span>`;
  if (l.stage === "error") return `<span class="stage stage-error" title="${esc(l.stage_error)}">error</span>`;
  if (l.stage === "filtered") return `<span class="stage stage-filtered">below threshold</span>`;
  if (l.stage === "closed") return `<span class="stage stage-closed">closed</span>`;
  if (l.app_status && l.app_status !== "new") return `<span class="chip ${l.app_status === "offer" ? "good" : l.app_status === "rejected" ? "bad" : "blue"}">${STATUS_LABEL[l.app_status]}</span>`;
  return `<span class="stage stage-ready"><i class=i-dot></i> ready</span>`;
}
function leadChips(l) {
  const c = [];
  if (l.industry) c.push(`<span class="chip ind">${esc(l.industry)}</span>`);
  if (l.dream) c.push(`<span class="chip accent"><i class=i-star></i> dream</span>`);
  if (l.kind && l.kind !== "posting") c.push(`<span class="chip violet">${esc(l.kind)}</span>`);
  if (l.category) c.push(`<span class="chip">${esc(l.category)}</span>`);
  (l.sources || [l.source]).forEach((s) => c.push(`<span class="chip blue">${esc(LABEL_SRC[s] || s)}</span>`));
  if (l.posted_at) c.push(`<span class="chip">posted ${ago(l.posted_at)}</span>`);
  const du = daysUntil(l.deadline);
  if (du != null) c.push(`<span class="chip ${du < 0 ? "" : du <= 5 ? "bad" : du <= 14 ? "warn" : ""}">${du < 0 ? "deadline passed" : `due in ${du}d`}</span>`);
  if (l.ats_coverage != null) c.push(`<span class="chip ${l.ats_coverage >= 0.75 ? "good" : "warn"}" title="Job keywords present in the tailored resume">ATS ${Math.round(l.ats_coverage * 100)}%</span>`);
  if (l.open_q) c.push(`<span class="chip warn" title="Questions that could strengthen this application. Open the lead to answer them."><i class=i-question></i> ${l.open_q} question${l.open_q > 1 ? "s" : ""}</span>`);
  const rf = (l.triage && l.triage.red_flags) || [];
  if (rf.length) c.push(`<span class="chip warn" title="${esc(rf.join("; "))}"><i class=i-flag></i> ${rf.length} flag${rf.length > 1 ? "s" : ""}</span>`);
  return c.join("");
}
// ---------- where a lead was found
const FOUND_NAME = { github: "GitHub list", ats: "company board", linkedin: "LinkedIn", hackernews: "Hacker News", reddit: "Reddit",
  mastodon: "Mastodon", bluesky: "Bluesky", themuse: "The Muse", usajobs: "USAJobs", remote: "remote board", rss: "RSS feed",
  adzuna: "Adzuna", google: "Google Jobs", manual: "your link" };
const foundList = (l) => (l.found || []).filter((f) => safeUrl(f.url));
function foundShort(f) {
  let host = ""; try { host = new URL(f.url).hostname.replace(/^www\./, ""); } catch (_) {}
  if (f.source === "ai_hunt") {
    const m = (f.label || "").match(/\):\s*(.+)$/) || (f.label || "").match(/\u00b7\s*([^\u00b7]+)$/);
    if (/reddit\.com/.test(host)) return "Reddit thread";
    if (/linkedin\.com/.test(host)) return "LinkedIn post";
    if (/(x|twitter)\.com/.test(host)) return "X post";
    if (/news\.ycombinator/.test(host)) return "HN comment";
    return host || (m ? m[1].trim().slice(0, 30) : "AI find");
  }
  return FOUND_NAME[f.source] || host || f.source;
}
function foundBtn(l) {
  const fs = foundList(l);
  if (!fs.length) return "";
  if (fs.length === 1) return `<a class="btn sm ghost" data-act="ext" href="${esc(fs[0].url)}" target="_blank" rel="noopener" title="Where this was found: ${esc(fs[0].label)}"><i class=i-ext></i> ${esc(foundShort(fs[0]))}</a>`;
  return `<button class="btn sm ghost" data-act="found-menu" data-id="${l.id}" title="Found in ${fs.length} places"><i class=i-ext></i> ${fs.length} places</button>`;
}
function foundMenu(l) {
  modal(`<h2>Where this lead was found</h2><p class="muted small">${esc(l.title)}, ${esc(l.company || "")}</p><div class="stack">
    ${foundList(l).map((f) => `<a class="card" href="${esc(f.url)}" target="_blank" rel="noopener" style="display:block;text-decoration:none;color:var(--text)">
      <div class="row"><span class="chip blue">${esc(foundShort(f))}</span><span class="small muted mono" style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap;flex:1">${esc(f.url)}</span>${I.ext}</div>
      <div class="small" style="margin-top:6px">${esc(f.label)}</div></a>`).join("")}</div>
    <div class="row" style="justify-content:flex-end;margin-top:14px"><button class="btn" onclick="closeModal()">Close</button></div>`);
}

function leadCard(l, fresh) {
  return `<div class="lead ${fresh ? "fresh" : ""}" data-id="${l.id}" data-act="open-lead">
    ${ring(l.score)}
    <div style="min-width:0"><div class="t">${esc(l.title)}</div>
      <div class="c"><b>${esc(l.company || "Unknown company")}</b>, ${esc(l.location || "location n/a")}${l.triage?.summary ? ` <span class="muted">(${esc(l.triage.summary)})</span>` : ""}</div>
      <div class="meta">${leadChips(l)}</div></div>
    <div class="acts">${foundBtn(l)}${stageBadge(l)}
      ${l.app_status === "new" ? `<button class="btn sm ghost" data-act="quick-status" data-st="saved" title="Save for later"><i class=i-star-o></i></button>` : ""}
      ${l.app_status !== "trashed" ? `<button class="btn sm ghost danger" data-act="quick-status" data-st="trashed" title="Trash this lead"><i class=i-x></i></button>` : `<button class="btn sm ghost" data-act="quick-status" data-st="new">restore</button>`}
    </div></div>`;
}

function addLeadModal() {
  modal(`<h2>Add a lead</h2><p class="muted small">Paste any job link (LinkedIn, Workday, a post, a Reddit comment) or paste the job text. JobPortal builds the full package.</p>
    <div class="stack"><label class="f"><span>URL</span><input type="url" id="al-url" placeholder="https://…"></label>
    <label class="f"><span>…or paste the posting text</span><textarea id="al-text" rows="7"></textarea></label>
    <div class="grid3"><label class="f"><span>Title (optional)</span><input type="text" id="al-title"></label>
    <label class="f"><span>Company (optional)</span><input type="text" id="al-co"></label>
    <label class="f"><span>Kind</span><select id="al-kind"><option value="posting">Posting</option><option value="program">Program</option><option value="event">Event</option><option value="intel">Intel / cold outreach</option></select></label></div>
    <div class="row" style="justify-content:flex-end"><button class="btn ghost" onclick="closeModal()">Cancel</button><button class="btn primary" id="al-go">Build package</button></div></div>`);
  $("#al-go").onclick = async () => {
    try {
      const l = await api("/api/leads/manual", { method: "POST", body: { url: $("#al-url").value, text: $("#al-text").value, title: $("#al-title").value, company: $("#al-co").value, kind: $("#al-kind").value } });
      closeModal(); toast("Building package", "JobPortal is researching and tailoring. It pops up here when it's ready.", "", l.id); location.hash = `#/lead/${l.id}`;
    } catch (e) { toast("Couldn't add lead", e.message, "error"); }
  };
}

// ================================================================ LEAD DETAIL
const LEAD_TABS = [["overview", "Overview"], ["resume", "Resume"], ["cover", "Cover letter"], ["emails", "Emails"], ["contacts", "Contacts"],
  ["intel", "Company intel"], ["prep", "Interview prep"], ["kit", "Application kit"], ["activity", "Activity"], ["posting", "Posting"]];

async function renderLead(id, fromEvent) {
  if (fromEvent && S.dirty) return; // don't clobber unsaved edits
  let l;
  try { l = await api(`/api/leads/${id}`); } catch (e) { main.innerHTML = `<div class="page"><div class="empty"><b>Lead not found</b></div></div>`; return; }
  if (fromEvent && S.lead && S.lead.stage === l.stage && S.lead.updated_at === l.updated_at) return;
  S.lead = l; S.dirty = false;
  const pkg = l.package || {}, fit = pkg.fit || {}, packaged = !!l.resume_md;
  const apply = safeUrl(l.apply_url) || safeUrl(l.url);
  let banner = "";
  if (l.stage === "packaging") banner = `<div class="banner accent"><span class="spin"></span><div><b>JobPortal is building this package:</b> reading the posting, researching the team, finding contacts, tailoring your resume and cover letter. Usually 2 to 6 minutes.</div></div>`;
  else if (l.stage === "error") banner = `<div class="banner bad"><div><b>Package failed:</b> ${esc(l.stage_error)}</div><span class="spacer"></span><button class="btn sm" data-act="regen">Retry</button></div>`;
  else if (!packaged) banner = `<div class="banner"><div>${l.stage === "filtered" ? "Triage scored this below your threshold." : "Queued for packaging."} Want the full package now?</div><span class="spacer"></span><button class="btn primary sm" data-act="regen">Build package</button></div>`;
  else if (l.stage === "closed") banner = `<div class="banner bad"><div><b>JobPortal couldn't find this posting open anymore.</b> Double-check the link before spending time on it.</div></div>`;
  if (packaged && ["applied", "assessment", "interviewing"].includes(l.app_status) && l.follow_up_at && daysUntil(l.follow_up_at) <= 0)
    banner += `<div class="banner accent"><div><b>Follow-up due.</b> A ready-to-send follow-up email is in the Emails tab.</div><span class="spacer"></span><button class="btn sm" data-act="ltabgo" data-tab="emails">Open emails</button></div>`;

  main.innerHTML = `<div class="page">
    <div class="row" style="margin-bottom:12px"><a href="#/leads" class="mono small"><i class=i-back></i> All leads</a></div>
    <div class="lh">${ring(l.score, true)}
      <div><h1>${esc(l.title)}</h1><div class="co"><b>${esc(l.company)}</b>, ${esc(l.location || "location n/a")}</div>
        <div class="row" style="margin-top:8px;gap:6px">${leadChips(l)}</div>
        ${foundList(l).length ? `<div class="row small" style="margin-top:8px;gap:6px"><span class="muted mono">FOUND AT</span>${foundList(l).map((f) => `<a class="chip blue" href="${esc(f.url)}" target="_blank" rel="noopener" title="${esc(f.label)}"><i class=i-ext></i> ${esc(foundShort(f))}</a>`).join("")}</div>` : ""}</div>
      <div class="acts">
        <button class="btn ${l.dream ? "toggled" : "ghost"}" data-act="toggle-dream" title="Mark as a dream job">${l.dream ? "<i class=i-star></i> Dream" : "<i class=i-star-o></i> Dream"}</button>
        <select id="industry" title="Industry (edit if it's wrong)">${(S.industries || []).concat(l.industry && !(S.industries || []).includes(l.industry) ? [l.industry] : []).map((x) => `<option ${x === l.industry ? "selected" : ""}>${esc(x)}</option>`).join("")}</select>
        <select id="appstatus" title="Application status">${S.meta.statuses.map((s) => `<option value="${s}" ${s === l.app_status ? "selected" : ""}>${STATUS_LABEL[s]}</option>`).join("")}</select>
        ${apply ? `<button class="btn primary" data-act="apply" data-url="${esc(apply)}">Apply ${I.ext}</button>` : ""}
        ${packaged ? `<a class="btn" href="/api/leads/${l.id}/export/package.zip" title="Resume, cover letter, emails (.eml), answers, prep, intel, contacts">${I.dl} All files</a>` : ""}
        <button class="btn" data-act="regen" title="Re-run research + tailoring">${packaged ? "<i class=i-refresh></i> Regenerate" : "Build package"}</button>
      </div></div>
    ${banner}
    ${leadQuestionsPanel(l)}
    <div class="tabs" id="dtabs">${LEAD_TABS.map(([k, t]) => `<a class="${S.leadTab === k ? "on" : ""}" data-act="ltabgo" data-tab="${k}">${t}</a>`).join("")}</div>
    <div id="dbody"></div></div>`;
  $("#appstatus").onchange = (e) => setStatus(l.id, e.target.value);
  $("#industry").onchange = async (e) => { await api(`/api/leads/${l.id}`, { method: "PATCH", body: { industry: e.target.value } }); toast("Industry updated", e.target.value); };
  renderLeadTab();
}

function renderLeadTab() {
  const old = $("#dbody"), b = old.cloneNode(false);
  old.replaceWith(b);
  const l = S.lead, pkg = l.package || {};
  $$("#dtabs a").forEach((a) => a.classList.toggle("on", a.dataset.tab === S.leadTab));
  const none = (what) => `<div class="empty"><b>No ${what} yet</b>Build the package to generate it.</div>`;
  const t = S.leadTab;
  if (t === "overview") {
    const fit = pkg.fit || {}, tri = l.triage || {}, cov = pkg.coverage || {};
    const plan = pkg.action_plan || [], done = pkg.plan_done || [];
    b.innerHTML = `<div class="cols"><div class="stack">
      ${fit.summary || tri.summary ? `<div class="card"><h3>Fit</h3><p style="margin:0 0 10px">${esc(fit.summary || tri.summary)}</p>
        ${fit.strengths?.length ? `<b class="small mono">STRENGTHS</b><ul class="clean good">${fit.strengths.map((x) => `<li>${esc(x)}</li>`).join("")}</ul>` : ""}
        ${fit.gaps?.length ? `<div style="margin-top:10px"><b class="small mono">GAPS & HOW TO HANDLE THEM</b><ul class="clean warn">${fit.gaps.map((x) => `<li>${esc(x)}</li>`).join("")}</ul></div>` : ""}
        ${fit.eligibility_notes ? `<p class="small" style="margin:10px 0 0"><b class="mono">ELIGIBILITY:</b> ${esc(fit.eligibility_notes)}</p>` : ""}</div>` : ""}
      ${plan.length ? `<div class="card"><h3>Action plan</h3><div class="checklist">${plan.map((p, i) => `<label><input type="checkbox" data-act="plan" data-i="${i}" ${done.includes(i) ? "checked" : ""}><span class="${done.includes(i) ? "done" : ""}">${esc(p)}</span></label>`).join("")}</div></div>` : ""}
      ${pkg.job_summary ? `<div class="card"><h3>The role in brief</h3><div class="md">${md(pkg.job_summary)}</div></div>` : ""}
    </div><div class="stack">
      <div class="card"><h3>At a glance</h3><dl class="kv">
        <dt>Status</dt><dd>${esc(STATUS_LABEL[l.app_status])}${l.applied_at ? `, applied ${esc(l.applied_at)}` : ""}</dd>
        <dt>Deadline</dt><dd>${esc(l.deadline || "unknown")}</dd>
        <dt>Posted</dt><dd>${esc(l.posted_at || "unknown")}</dd>
        <dt>Found via</dt><dd>${esc(l.source_detail || l.source)}</dd>
        <dt>Posting</dt><dd>${safeUrl(l.url) ? `<a href="${esc(l.url)}" target="_blank" rel="noopener">${esc(l.url.slice(0, 70))}</a>` : "none"}</dd>
        <dt>Triage</dt><dd>${tri.score ?? "-"}, ${esc(tri.eligibility || "")}${tri.reasons?.length ? `: ${esc(tri.reasons.join("; "))}` : ""}</dd>
        <dt>AI usage</dt><dd>${(+l.tokens || 0).toLocaleString()} tokens</dd></dl></div>
      ${tri.red_flags?.length ? `<div class="card"><h3>Red flags</h3><ul class="clean warn">${tri.red_flags.map((x) => `<li>${esc(x)}</li>`).join("")}</ul></div>` : ""}
      ${(cov.hit || cov.miss) ? `<div class="card"><h3>ATS keywords in your resume: ${Math.round((l.ats_coverage || 0) * 100)}%</h3><div class="cov">${(cov.hit || []).map((k) => `<span class="chip good">${esc(k)}</span>`).join("")}${(cov.miss || []).map((k) => `<span class="chip" title="Not in the resume. Add it only if it's true.">${esc(k)}</span>`).join("")}</div></div>` : ""}
    </div></div>`;
  } else if (t === "resume" || t === "cover") {
    const text = t === "resume" ? l.resume_md : l.cover_md;
    if (!text) {
      b.innerHTML = t === "resume" ? `<div class="empty"><b>No tailored resume yet</b>Build the package to generate one, or start from a resume in your collection.
        <div style="margin-top:12px"><button class="btn" data-act="lead-lib-use">Use a saved resume</button></div></div>` : none("cover letter");
      return;
    }
    let host = b;
    if (t === "resume") {
      b.innerHTML = `<div class="cols" style="margin-bottom:14px">${resumeStrategyCard(pkg)}${resumeCheckCard(pkg.resume_check, pkg.resume_review)}</div><div id="ed-host"></div>`;
      host = $("#ed-host", b);
    }
    mountEditor(host, {
      doc: t, text, leadId: l.id, theme: t === "resume" ? (pkg.resume_style || {}).theme : undefined, maxPages: t === "resume" ? (pkg.resume_style || {}).max_pages || 1 : 1,
      original: t === "resume" ? pkg.original_resume_md : pkg.original_cover_md,
      save: async (v) => { await api(`/api/leads/${l.id}`, { method: "PATCH", body: t === "resume" ? { resume_md: v } : { cover_md: v } }); l[t === "resume" ? "resume_md" : "cover_md"] = v; },
      files: t === "resume" ? ["resume.pdf", "resume.docx", "resume.md"] : ["cover_letter.pdf", "cover_letter.docx", "cover_letter.md"],
      tools: t === "resume" ? `<button class="btn" data-act="lead-lib-save" title="Keep a copy of this resume in your collection"><i class=i-star></i> Save to collection</button><button class="btn" data-act="lead-lib-use">Use a saved resume</button>` : "",
      coverage: t === "resume" ? pkg.coverage : null,
    });
  } else if (t === "emails") {
    const emails = pkg.emails || [];
    if (!emails.length && !pkg.linkedin_note) { b.innerHTML = none("emails"); return; }
    const contacts = (pkg.contacts || []).filter((c) => c.email);
    b.innerHTML = `<datalist id="cemails">${contacts.map((c) => `<option value="${esc(c.email)}">${esc(c.name)}, ${esc(c.title)}</option>`).join("")}</datalist>
      <div class="stack">${emails.map((e, i) => `<div class="card email" data-i="${i}">
        <div class="hd"><span class="chip accent">${esc(e.kind.replace(/_/g, " "))}</span><span class="muted small">${esc(e.to)}</span><span class="spacer"></span>
          <button class="btn sm" data-act="mail" data-how="gmail" data-i="${i}">Open in Gmail ${I.ext}</button>
          <button class="btn sm" data-act="mail" data-how="mailto" data-i="${i}">Mail app</button>
          <button class="btn sm" data-act="mail" data-how="copy" data-i="${i}">Copy</button>
          <button class="btn sm" data-act="mail" data-how="eml" data-i="${i}" title="Download as an unsent draft (.eml) for Thunderbird / Outlook / Apple Mail">.eml</button>
          <button class="btn sm" data-act="mail" data-how="sent" data-i="${i}">Mark sent</button></div>
        <div class="grid2"><label class="f"><span>To</span><input type="email" list="cemails" data-ef="to_addr" value="${esc(pickTo(e))}" placeholder="pick a contact or type an address"></label>
          <label class="f"><span>Subject</span><input type="text" data-ef="subject" value="${esc(e.subject)}"></label></div>
        <textarea data-ef="body">${esc(e.body)}</textarea>
        <div class="revise" style="margin:0"><input type="text" data-erev="${i}" placeholder="Say how to change this email"><button class="btn sm" data-act="revise-email" data-i="${i}">Revise</button></div></div>`).join("")}
        ${pkg.linkedin_note ? `<div class="card"><h3>LinkedIn connection note <span id="lncount" class="muted">${pkg.linkedin_note.length}/300</span></h3>
          <textarea id="lnote" rows="3" style="font-family:var(--sans)">${esc(pkg.linkedin_note)}</textarea>
          <div class="row" style="margin-top:8px"><button class="btn sm" data-act="copy-lnote">Copy</button></div></div>` : ""}
        <div class="row" style="justify-content:flex-end"><span class="muted small">Export all emails:</span>${exportBtns(l.id, "emails", ["md", "docx", "pdf"])}<button class="btn primary" data-act="save-emails">Save edits</button></div></div>`;
    b.addEventListener("input", (e) => { S.dirty = true; if (e.target.id === "lnote") $("#lncount").textContent = `${e.target.value.length}/300`; });
  } else if (t === "contacts") {
    const cs = pkg.contacts || [];
    const inp = (i, k, v, ph) => `<input type="text" data-cf="${k}" data-i="${i}" value="${esc(v || "")}" placeholder="${ph}">`;
    b.innerHTML = `<div class="card"><div class="row" style="margin-bottom:6px"><h3 style="margin:0">People to reach (${cs.length})</h3><span class="spacer"></span>${exportBtns(l.id, "contacts", ["csv"])}</div>
      <p class="muted small" style="margin-top:0">Found by the AI on the public web. Every field is editable and saves when you leave it. <b>found</b> means the email was seen publicly; <b>pattern</b> means it was inferred from the company's email format (verify it).</p>
      ${cs.length ? `<table class="t"><thead><tr><th>Name / title / org</th><th>Email</th><th>LinkedIn and notes</th><th>Why them</th><th>Status</th><th></th></tr></thead><tbody>
      ${cs.map((c, i) => `<tr><td style="min-width:200px">${inp(i, "name", c.name, "Name")}<div style="height:4px"></div>${inp(i, "title", c.title, "Title")}<div style="height:4px"></div>${inp(i, "org", c.org, "Organization")}</td>
        <td style="min-width:220px">${inp(i, "email", c.email, "email@example.com")}<div class="row" style="margin-top:5px;gap:5px"><span class="chip ${c.email_confidence === "found" ? "good" : c.email_confidence === "pattern" ? "warn" : ""}">${esc(c.email_confidence || "unknown")}</span>${c.email ? `<button class="btn sm ghost" data-act="copytext" data-text="${esc(c.email)}">copy</button>` : ""}</div></td>
        <td style="min-width:200px">${inp(i, "linkedin", c.linkedin, "LinkedIn URL")}<div style="height:4px"></div>${inp(i, "notes", c.notes, "Notes")}
          <div class="small row" style="margin-top:4px;gap:8px">${safeUrl(c.linkedin) ? `<a href="${esc(c.linkedin)}" target="_blank" rel="noopener">open LinkedIn</a>` : ""}${safeUrl(c.source_url) ? `<a href="${esc(c.source_url)}" target="_blank" rel="noopener">source</a>` : ""}</div></td>
        <td class="small" style="max-width:300px"><textarea data-cf="why" data-i="${i}" rows="3" style="font-family:var(--sans);font-size:12.5px">${esc(c.why || "")}</textarea></td>
        <td><select data-act="cstatus" data-i="${i}">${["", "to contact", "contacted", "replied", "no response", "referred me"].map((s) => `<option ${c.status === s ? "selected" : ""} value="${s}">${s || "not set"}</option>`).join("")}</select></td>
        <td><button class="btn sm ghost danger" data-act="rm-contact" data-i="${i}" title="Remove"><i class=i-x></i></button></td></tr>`).join("")}
      </tbody></table>` : `<div class="muted">No contacts found yet.</div>`}
      <div class="hr"></div><div class="grid3" id="newc">
        <input type="text" placeholder="Name" data-nc="name"><input type="text" placeholder="Title" data-nc="title"><input type="email" placeholder="Email" data-nc="email">
        <input type="url" placeholder="LinkedIn URL" data-nc="linkedin"><input type="text" placeholder="Why / notes" data-nc="why"><button class="btn" data-act="add-contact">+ Add contact</button></div></div>`;
    b.addEventListener("change", async (e) => {
      const el = e.target; if (!el.dataset.cf) return;
      await api(`/api/leads/${l.id}/contacts/${el.dataset.i}`, { method: "POST", body: { [el.dataset.cf]: el.value } });
      pkg.contacts[+el.dataset.i][el.dataset.cf] = el.value;
    });
  } else if (t === "intel" || t === "prep") {
    const key = t === "intel" ? "company_brief_md" : "interview_prep_md";
    if (!pkg[key]) { b.innerHTML = none(t === "intel" ? "company intel" : "interview prep"); return; }
    mountDocEditor(b, { text: pkg[key], leadId: l.id, stem: t === "intel" ? "company_intel" : "interview_prep", doc: t === "intel" ? "company brief" : "interview prep",
      save: async (v) => { await api(`/api/leads/${l.id}`, { method: "PATCH", body: { package: { [key]: v } } }); pkg[key] = v; } });
  } else if (t === "kit") {
    renderKit(b, l, pkg);
  } else if (t === "activity") {
    b.innerHTML = `<div class="cols"><div class="stack"><div class="card"><h3>Notes</h3><textarea id="notes" rows="8" style="font-family:var(--sans)">${esc(l.notes || "")}</textarea>
        <div class="row" style="margin-top:8px"><button class="btn sm" data-act="save-notes">Save notes</button></div></div>
      <div class="card"><h3>Timeline</h3><div class="timeline">${(l.events || []).map((e) => `<div class="ev"><span class="ts">${esc(e.ts.replace("T", " ").slice(0, 16))}</span><span class="chip">${esc(e.type)}</span><span>${esc(e.text)}</span></div>`).join("") || `<div class="muted">No activity yet.</div>`}</div></div></div>
      <div class="stack"><div class="card"><h3>Follow-up</h3><label class="f"><span>Follow up on</span><input type="date" id="fu" value="${esc(l.follow_up_at || "")}"></label>
        <div class="row" style="margin-top:8px"><button class="btn sm" data-act="save-fu">Save date</button></div></div>
        <div class="card"><h3>Log an event</h3><div class="row">${["Got online assessment", "Recruiter reached out", "Interview scheduled", "Referral submitted", "Offer!", "Rejected"].map((x) => `<button class="btn sm" data-act="logev" data-text="${esc(x)}">${esc(x)}</button>`).join("")}</div>
          <div class="row" style="margin-top:10px"><input type="text" id="evtext" placeholder="Custom event" style="flex:1"><button class="btn sm" data-act="logev">Log</button></div></div></div></div>`;
  } else if (t === "posting") {
    b.innerHTML = `<div class="card"><div class="row" style="margin-bottom:12px">${safeUrl(l.url) ? `<a class="btn sm" href="${esc(l.url)}" target="_blank" rel="noopener">Open posting ${I.ext}</a>` : ""}
      ${safeUrl(l.apply_url) && l.apply_url !== l.url ? `<a class="btn sm" href="${esc(l.apply_url)}" target="_blank" rel="noopener">Apply page ${I.ext}</a>` : ""}
      <span class="muted small">${esc(l.source_detail || "")}</span></div><pre class="jd">${esc(l.description || "No description captured.")}</pre></div>`;
  }
}

// Only pre-fill a recipient when the AI wrote a concrete address for this email, never a guessed pattern placeholder.
function pickTo(e) {
  if (e.to_addr != null) return e.to_addr;
  const m = (e.to || "").match(/[\w.+-]+@[\w-]+\.[\w.-]+/);
  return m && !/^(first|firstname|name|flast|f\.?last|last|jdoe|john|email)\b|[\[\]]/i.test(m[0]) ? m[0] : "";
}

async function renderKit(b, l, pkg) {
  if (!S.profileCache) S.profileCache = await api("/api/profile");
  const qa = S.profileCache.qa || [], f = S.profileCache.facts || {};
  const row = (q, a) => `<div class="copyrow"><div class="q">${esc(q)}</div><div class="a">${esc(a)}</div><button class="btn sm" data-act="copytext" data-text="${esc(a)}">copy</button></div>`;
  const apply = safeUrl(l.apply_url) || safeUrl(l.url);
  const answers = pkg.application_answers || [];
  b.innerHTML = `<div class="cols"><div class="stack">
    <div class="card"><h3>Files</h3><div class="row">${l.resume_md ? exportBtns(l.id, "resume", ["pdf", "docx", "md"], "Resume") : ""}</div>
      <div class="row" style="margin-top:8px">${l.cover_md ? exportBtns(l.id, "cover_letter", ["pdf", "docx", "md"], "Cover") : ""}</div>
      <div class="row" style="margin-top:12px"><a class="btn" href="/api/leads/${l.id}/export/package.zip">${I.dl} Everything (.zip)</a>
      ${apply ? `<button class="btn primary" data-act="apply" data-url="${esc(apply)}">Open application ${I.ext}</button>` : ""}</div></div>
    <div class="card"><div class="row" style="margin-bottom:10px"><h3 style="margin:0">Tailored answers</h3><span class="spacer"></span>${exportBtns(l.id, "answers", ["docx", "pdf", "md"])}</div>
      <div class="stack" id="answers">${answers.map((x, i) => `<div class="stack" style="gap:6px;padding-bottom:12px;border-bottom:1px solid var(--line)">
        <div class="row"><input type="text" data-aq="${i}" value="${esc(x.question)}" style="flex:1;font-weight:600"><button class="btn sm" data-act="copy-answer" data-i="${i}">copy</button><button class="btn sm ghost danger" data-act="rm-answer" data-i="${i}" title="Remove"><i class=i-x></i></button></div>
        <textarea data-aa="${i}" rows="5" style="font-family:var(--sans);font-size:13px">${esc(x.answer)}</textarea></div>`).join("") || `<div class="muted">Build the package to generate tailored answers.</div>`}</div>
      <div class="row" style="margin-top:12px"><button class="btn sm" data-act="add-answer">+ Add question</button><span class="spacer"></span><span class="muted small" id="ans-state"></span><button class="btn primary sm" data-act="save-answers">Save answers</button></div></div>
  </div><div class="stack"><div class="card"><h3>Standard answers</h3><p class="muted small" style="margin-top:-4px">From your answers in <a href="#/profile/answers">Profile, Standard answers</a>. Edit them there.</p>${qa.filter((x) => !x.eeo).map((x) => row(x.q, x.a)).join("") || `<div class="muted small">Answer the standard questions to fill these in.</div>`}</div>
    ${qa.some((x) => x.eeo) ? `<div class="card"><h3>Voluntary self-identification</h3><p class="muted small" style="margin-top:-4px">Only shown here for copying. Never sent to the AI.</p>${qa.filter((x) => x.eeo).map((x) => row(x.q, x.a)).join("")}</div>` : ""}</div></div>`;
  b.addEventListener("input", (e) => { if (e.target.dataset.aq != null || e.target.dataset.aa != null) { S.dirty = true; $("#ans-state").textContent = "unsaved"; } });
}

function readAnswers() {
  const pkg = S.lead.package;
  pkg.application_answers = (pkg.application_answers || []).map((x, i) => ({
    question: $(`[data-aq="${i}"]`)?.value ?? x.question, answer: $(`[data-aa="${i}"]`)?.value ?? x.answer }));
  return pkg.application_answers;
}

function exportBtns(id, stem, fmts, label = "") {
  return fmts.map((f) => `<button class="btn sm" data-act="export" data-url="/api/leads/${id}/export/${stem}.${f}">${I.dl} ${label ? label + " " : ""}${f.toUpperCase()}</button>`).join("");
}

// ---------- generic markdown document editor (company intel, interview prep)
function mountDocEditor(container, o) {
  container.innerHTML = `<div class="toolbar"><button class="btn primary" data-de="save">Save</button>
      ${["pdf", "docx", "md"].map((f) => `<button class="btn" data-de="exp" data-fmt="${f}">${I.dl} ${f.toUpperCase()}</button>`).join("")}
      <span class="muted small mono" id="destate"></span></div>
    <div class="revise"><input type="text" id="de-rev" placeholder="Say how to change it, e.g. “add 3 questions about system design, shorten the company history”"><button class="btn ai" data-de="revise"><i class=i-ai></i> Revise with AI</button></div>
    <div class="editor"><textarea id="de-ed" spellcheck="true">${esc(o.text)}</textarea><div class="card md" id="de-pv" style="max-height:76vh;overflow:auto"></div></div>`;
  const ed = $("#de-ed", container), pv = $("#de-pv", container), st = $("#destate", container);
  const draw = () => (pv.innerHTML = md(ed.value));
  ed.addEventListener("input", debounce(() => { S.dirty = true; st.textContent = "unsaved"; draw(); }, 150));
  const save = async () => { await o.save(ed.value); S.dirty = false; st.textContent = "saved"; };
  ed.addEventListener("keydown", (e) => { if ((e.ctrlKey || e.metaKey) && e.key === "s") { e.preventDefault(); save(); } });
  container.onclick = async (e) => {
    const btn = e.target.closest("[data-de]"); if (!btn) return;
    if (btn.dataset.de === "save") save();
    if (btn.dataset.de === "exp") { if (S.dirty) await save(); openUrl(`/api/leads/${o.leadId}/export/${o.stem}.${btn.dataset.fmt}`); }
    if (btn.dataset.de === "revise") {
      const ins = $("#de-rev", container).value.trim(); if (!ins) return;
      btn.disabled = true; btn.innerHTML = `<span class="spin"></span> Revising…`;
      try {
        const r = await api(`/api/leads/${o.leadId}/revise`, { method: "POST", body: { doc: o.doc, instruction: ins, text: ed.value } });
        ed.value = r.text; S.dirty = true; st.textContent = "revised: review it, then Save"; draw(); toast("Revised", r.change_summary);
      } catch (err) { toast("Revision failed", err.message, "error"); }
      btn.disabled = false; btn.innerHTML = "<i class=i-ai></i> Revise with AI";
    }
  };
  draw();
}

// ---------- document editor (tailored resume / cover letter)
function mountEditor(container, o) {
  const covHtml = (c) => c ? `<div class="cov">${(c.hit || []).map((k) => `<span class="chip good">${esc(k)}</span>`).join("")}${(c.miss || []).map((k) => `<span class="chip" title="Not in this resume">${esc(k)}</span>`).join("")}</div>` : "";
  container.innerHTML = `<div class="toolbar">
      <button class="btn primary" data-ed="save">Save</button>
      ${(o.files || []).map((f) => `<button class="btn" data-ed="file" data-file="${f}">${I.dl} ${f.split(".").pop().toUpperCase()}</button>`).join("")}
      ${o.original ? `<button class="btn ghost" data-ed="revert">Revert to AI version</button>` : ""}${o.tools || ""}
      <span class="muted small mono" id="edstate"></span><span class="spacer"></span><span class="chip warn" id="overflow" style="display:none"><i class=i-warn></i> spills past one page</span></div>
    ${o.leadId || o.reviseUrl ? `<div class="revise"><input type="text" id="revise-in" placeholder="Say how to change it, e.g. “lead with the data pipeline project, emphasize SQL, cut the retail job to one bullet”"><button class="btn ai" data-ed="revise"><i class=i-ai></i> Revise with AI</button></div>` : ""}
    ${o.coverage ? `<div style="margin-bottom:12px">${covHtml(o.coverage)}</div>` : ""}
    <div class="editor"><textarea id="ed" spellcheck="true">${esc(o.text)}</textarea>
      <div class="preview-wrap" id="pvw"><div class="preview-box" id="pvb"><iframe id="pv" sandbox="allow-same-origin" title="preview"></iframe></div></div></div>`;
  const ed = $("#ed", container), pv = $("#pv", container), state = $("#edstate", container);
  const pages = Math.max(1, +o.maxPages || 1);
  pv.style.height = `${1056 * pages}px`;
  const scale = () => {
    const w = $("#pvw", container).clientWidth - 28, s = Math.min(1, w / 816);
    pv.style.transform = `scale(${s})`; $("#pvb", container).style.width = `${816 * s}px`; $("#pvb", container).style.height = `${1056 * pages * s}px`;
  };
  const refresh = async () => {
    const html = await api("/api/preview", { method: "POST", body: { doc: o.doc, md: ed.value, lead_id: o.leadId, theme: o.theme } });
    pv.srcdoc = html;
    pv.onload = () => { // mirror the server's one-page auto-fit (shrinks to 86% max) so the preview matches the PDF
      try {
        const d = pv.contentDocument, page = d.querySelector(".page"), warn = $("#overflow", container);
        d.documentElement.style.overflow = "hidden";
        let fit = 1;
        if (o.doc === "resume" && page) {
          for (const sc of [1, 0.97, 0.94, 0.91, 0.88, 0.86]) {
            page.style.setProperty("--s", sc);
            if (sc < 0.95) { page.style.setProperty("--mt", "0.35in"); page.style.setProperty("--mx", "0.42in"); }
            fit = sc;
            if (d.documentElement.scrollHeight <= 1060 * pages) break;
          }
        }
        const over = d.documentElement.scrollHeight > 1060 * pages;
        warn.style.display = over || fit < 1 ? "" : "none";
        warn.className = `chip ${over ? "bad" : "blue"}`;
        warn.textContent = over ? `Longer than ${pages === 1 ? "one page" : `${pages} pages`}, trim it` : `auto-fit to ${pages === 1 ? "one page" : `${pages} pages`} at ${Math.round(fit * 100)}%`;
      } catch (_) {}
    };
  };
  const later = debounce(refresh, 350);
  ed.addEventListener("input", () => { S.dirty = true; state.textContent = "unsaved"; later(); });
  const save = async () => { await o.save(ed.value); S.dirty = false; state.textContent = "saved"; if (o.doc === "resume" && o.leadId) recheckResume(o.leadId); };
  o.refresh = refresh;
  S.editorOpts = o;
  ed.addEventListener("keydown", (e) => { if ((e.ctrlKey || e.metaKey) && e.key === "s") { e.preventDefault(); save(); } });
  container.onclick = async (e) => {
    const btn = e.target.closest("[data-ed]"); if (!btn) return;
    const a = btn.dataset.ed;
    if (a === "save") save();
    if (a === "file") { if (S.dirty) await save(); openUrl(o.fileHref ? o.fileHref(btn.dataset.file) : `/api/leads/${o.leadId}/files/${btn.dataset.file}`); }
    if (a === "revert" && confirm("Replace the editor contents with the original AI version?")) { ed.value = o.original; S.dirty = true; state.textContent = "unsaved"; refresh(); }
    if (a === "revise") {
      const ins = $("#revise-in", container).value.trim(); if (!ins) return;
      btn.disabled = true; btn.innerHTML = `<span class="spin"></span> Revising…`;
      try {
        const r = await api(o.reviseUrl || `/api/leads/${o.leadId}/revise`, { method: "POST", body: { doc: o.doc, instruction: ins, text: ed.value } });
        ed.value = r.text; S.dirty = true; state.textContent = "revised: review it, then Save"; refresh(); toast("Revised", r.change_summary);
      } catch (err) { toast("Revision failed", err.message, "error"); }
      btn.disabled = false; btn.innerHTML = "<i class=i-ai></i> Revise with AI";
    }
  };
  new ResizeObserver(scale).observe($("#pvw", container));
  scale(); refresh();
}

const ARCHETYPE_LABEL = { big_tech_swe: "Big-tech SWE", startup_product: "Startup / product", defense_contractor: "Defense contractor",
  aerospace_space: "Aerospace / space", research_lab: "Research lab", federal_usajobs: "Federal (USAJobs)", data_ml: "Data / ML",
  it_support_infra: "IT / infrastructure", solutions_sales_eng: "Solutions / sales engineering", experienced_professional: "Experienced professional",
  general: "General", general_tech: "General tech" };
function resumeStrategyCard(pkg) {
  const st = pkg.resume_strategy || {}, style = pkg.resume_style || { theme: "classic", max_pages: 1 }, rv = pkg.resume_review || {};
  return `<div class="card"><div class="row" style="margin-bottom:8px"><h3 style="margin:0">Strategy</h3>
      ${st.archetype ? `<span class="chip violet">${esc(ARCHETYPE_LABEL[st.archetype] || st.archetype)}</span>` : ""}<span class="spacer"></span>
      <label class="row small" style="gap:6px">Layout <select id="rs-theme" style="width:auto">${["classic", "modern", "compact", "academic"].map((x) => `<option ${x === style.theme ? "selected" : ""}>${x}</option>`).join("")}</select></label>
      <span class="chip">${style.max_pages === 2 ? "2 pages max" : "1 page"}</span></div>
    ${st.rationale ? `<p class="small" style="margin:0 0 8px">${esc(st.rationale)}</p>` : `<p class="muted small" style="margin:0 0 8px">Regenerate this package to get a strategy-driven resume.</p>`}
    ${st.section_order?.length ? `<div class="small"><b class="mono">ORDER</b> ${st.section_order.map(esc).join(" → ")}</div>` : ""}
    ${st.projects?.length ? `<div class="small" style="margin-top:4px"><b class="mono">PROJECTS</b> ${st.projects.map(esc).join(", ")}</div>` : ""}
    ${st.summary ? `<div class="small" style="margin-top:4px"><b class="mono">SUMMARY</b> ${esc(st.summary)}</div>` : ""}
    ${st.skills_grouping ? `<div class="small" style="margin-top:4px"><b class="mono">SKILLS</b> ${esc(st.skills_grouping)}</div>` : ""}
    ${rv.changes?.length ? `<details style="margin-top:8px"><summary class="small mono" style="cursor:pointer">RECRUITER CRITIC: ${rv.changes.length} change${rv.changes.length > 1 ? "s" : ""} (score ${rv.before_score} → ${rv.after_score ?? rv.before_score})</summary><ul class="clean small">${rv.changes.map((c) => `<li>${esc(c)}</li>`).join("")}</ul></details>` : ""}</div>`;
}
function resumeCheckCard(chk, rv) {
  if (!chk) return `<div class="card"><h3>Resume check</h3><p class="muted small">Not checked yet.</p><button class="btn sm" data-act="resume-recheck">Run check</button></div>`;
  const col = chk.score >= 85 ? "good" : chk.score >= 65 ? "warn" : "bad";
  return `<div class="card" id="rcheck"><div class="row" style="margin-bottom:8px"><h3 style="margin:0">Resume check</h3><span class="chip ${col}">${chk.score}/100</span>
      <span class="chip">${chk.pages ?? "?"} page${chk.pages === 1 ? "" : "s"}</span><span class="chip ${chk.coverage >= 0.75 ? "good" : "warn"}">keywords ${Math.round((chk.coverage || 0) * 100)}%</span>
      <span class="spacer"></span><button class="btn sm" data-act="resume-recheck">Re-check</button></div>
    ${chk.issues.length ? `<ul class="clean small">${chk.issues.map((i) => `<li style="color:${i.level === "error" ? "var(--bad)" : "var(--text2)"}">${i.level === "error" ? '<i class=i-x></i>' : '<i class=i-warn></i>'} ${esc(i.text)}</li>`).join("")}</ul>`
      : `<div class="small" style="color:var(--good)"><i class=i-check></i> ATS-safe, fits the page limit, and every skill is backed by your inventory.</div>`}</div>`;
}
async function recheckResume(id) {
  const box = $("#rcheck"); if (box) box.style.opacity = 0.5;
  try { const chk = await api(`/api/leads/${id}/resume-check`, { method: "POST" }); if (S.lead?.package) S.lead.package.resume_check = chk;
    const host = $("#rcheck") || $(".cols .card:last-child"); if (host) host.outerHTML = resumeCheckCard(chk); } catch (e) { toast("Check failed", e.message, "error"); }
}

function leadQuestionsPanel(l) {
  const qs = l.questions || [], open = qs.filter((q) => q.status === "open"), answered = qs.filter((q) => q.status === "answered");
  if (!l.resume_md) return "";
  if (!qs.length) return `<div class="banner"><div class="small">No open questions for this application.</div><span class="spacer"></span>
    <button class="btn sm" data-act="lead-gapq" title="Ask the AI what you could tell it that would make this resume stronger"><i class=i-question></i> Find gaps to ask me about</button></div>`;
  return `<div class="card lq" style="margin-bottom:14px"><div class="row" style="margin-bottom:6px"><h3 style="margin:0"><i class=i-question></i> Questions that could strengthen this resume</h3>
      <span class="muted small">Answers are saved to your profile, so every future application benefits.</span><span class="spacer"></span>
      ${answered.length ? `<button class="btn primary sm ai" data-act="lead-apply" title="Add your answers to your profile, then rework this resume with them"><i class=i-ai></i> Update this resume with my answers</button>` : ""}</div>
    ${open.map((q) => `<div class="lq-item"><div><b>${esc(q.question)}</b></div><div class="small muted">${esc(q.why)}</div>
      <div class="row" style="margin-top:6px"><input type="text" data-lqa="${esc(q.question)}" placeholder="Your answer" style="flex:1">
      <button class="btn sm" data-act="lead-answer">Save answer</button><button class="btn sm ghost" data-act="lead-dismiss" data-q="${esc(q.question)}" title="Not relevant"><i class=i-x></i></button></div></div>`).join("")}
    ${answered.map((q) => `<div class="lq-item done"><div class="small"><b>${esc(q.question)}</b></div><div class="small" style="color:var(--good)"><i class=i-check></i> ${esc(q.answer || "")}</div></div>`).join("")}</div>`;
}

async function setStatus(id, st) {
  try {
    await api(`/api/leads/${id}`, { method: "PATCH", body: { app_status: st } });
    toast("Status updated", STATUS_LABEL[st]);
    refreshStats();
    if (S.route[0] === "lead") renderLead(id);
  } catch (e) { toast("Couldn't update", e.message, "error"); }
}
function mailAction(how, i) {
  const card = $(`.email[data-i="${i}"]`), get = (k) => $(`[data-ef="${k}"]`, card).value;
  const to = get("to_addr"), su = get("subject"), body = get("body");
  if (how === "gmail") openUrl(`https://mail.google.com/mail/?view=cm&fs=1&to=${encodeURIComponent(to)}&su=${encodeURIComponent(su)}&body=${encodeURIComponent(body)}`);
  if (how === "mailto") { const u = `mailto:${encodeURIComponent(to)}?subject=${encodeURIComponent(su)}&body=${encodeURIComponent(body)}`; if (ownWindow()) openUrl(u); else location.href = u; }
  if (how === "copy") copy(`Subject: ${su}\n\n${body}`, "Email copied");
  if (how === "eml") saveEmails().then(() => openUrl(`/api/leads/${S.lead.id}/export/email-${i}.eml`));
  if (how === "sent") api(`/api/leads/${S.lead.id}/events`, { method: "POST", body: { type: "email", text: `Sent ${S.lead.package.emails[i].kind.replace(/_/g, " ")} to ${to || "?"}: ${su}` } }).then(() => toast("Logged", "Email marked as sent"));
}

// ================================================================ TRACKER
const TRACK = ["saved", "applied", "assessment", "interviewing", "offer", "rejected", "ghosted", "withdrawn"];
async function renderTracker() {
  const d = await api("/api/tracker"), s = d.stats;
  const maxW = Math.max(1, ...d.weekly.map((w) => w.n));
  main.innerHTML = `<div class="page"><div class="page-h"><h1>Application tracker</h1><span class="sub">Drag cards between columns. Applying sets a 7-day follow-up automatically.</span></div>
    <div class="tiles"><div class="tile"><div class="n">${s.applied}</div><div class="l">Applied</div></div>
      <div class="tile"><div class="n">${Math.round(s.response_rate * 100)}%</div><div class="l">Response rate</div></div>
      <div class="tile"><div class="n">${s.interviewing}</div><div class="l">OA / interviewing</div></div>
      <div class="tile ${s.offers ? "hot" : ""}"><div class="n">${s.offers}</div><div class="l">Offers</div></div>
      <div class="tile"><div class="weekly" title="Applications per week">${d.weekly.slice().reverse().map((w) => `<i style="height:${(w.n / maxW) * 100}%" title="week ${esc(w.wk)}: ${w.n}"></i>`).join("") || `<span class="muted small">no applications yet</span>`}</div><div class="l">Per week</div></div></div>
    ${d.due.length ? `<div class="card" style="margin-bottom:16px"><h3>Follow-ups due</h3>${d.due.map((l) => `<div class="row" style="padding:5px 0"><span class="chip warn">${esc(l.follow_up_at)}</span><b>${esc(l.company)}</b><span class="muted">${esc(l.title)}</span><span class="spacer"></span><a class="btn sm" href="#/lead/${l.id}" data-act="goemails">Send follow-up</a></div>`).join("")}</div>` : ""}
    <div class="kanban">${TRACK.map((st) => `<div class="kcol" data-st="${st}"><h4><span>${STATUS_LABEL[st]}</span><span>${d.columns[st].length}</span></h4>
      ${d.columns[st].map((l) => `<div class="kcard" draggable="true" data-id="${l.id}"><div class="t">${esc(l.title)}</div><div class="c">${esc(l.company)}${l.location ? `, ${esc(l.location)}` : ""}</div>
        <div class="row" style="gap:5px;margin-top:6px">${l.applied_at ? `<span class="chip">applied ${esc(l.applied_at)}</span>` : ""}${l.follow_up_at && ["applied", "assessment", "interviewing"].includes(st) ? `<span class="chip ${daysUntil(l.follow_up_at) <= 0 ? "warn" : ""}">f/u ${esc(l.follow_up_at)}</span>` : ""}</div></div>`).join("")}</div>`).join("")}</div>
    <p class="muted small">Leads you haven't acted on live in <a href="#/leads">Leads</a>. Set a lead to “Saved” there to put it on this board.</p></div>`;
  $$(".kcard").forEach((c) => {
    c.addEventListener("dragstart", (e) => { e.dataTransfer.setData("text/plain", c.dataset.id); c.classList.add("dragging"); });
    c.addEventListener("dragend", () => c.classList.remove("dragging"));
    c.addEventListener("click", () => (location.hash = `#/lead/${c.dataset.id}`));
  });
  $$(".kcol").forEach((col) => {
    col.addEventListener("dragover", (e) => { e.preventDefault(); col.classList.add("over"); });
    col.addEventListener("dragleave", () => col.classList.remove("over"));
    col.addEventListener("drop", async (e) => { e.preventDefault(); col.classList.remove("over");
      const id = e.dataTransfer.getData("text/plain");
      await api(`/api/leads/${id}`, { method: "PATCH", body: { app_status: col.dataset.st } }); refreshStats(); renderTracker(); });
  });
}

// ================================================================ CONTACTS
async function renderContacts() {
  const cs = await api("/api/contacts");
  main.innerHTML = `<div class="page"><div class="page-h"><h1>Contacts</h1><span class="sub">${cs.length} people across your leads: recruiters, hiring managers, people on the team, alumni.</span><span class="spacer"></span>
    <input type="text" id="cq" placeholder="Filter" style="max-width:260px"><select id="cst" style="width:auto"><option value="">Any status</option><option>to contact</option><option>contacted</option><option>replied</option><option>no response</option><option>referred me</option></select></div>
    <div class="card"><table class="t"><thead><tr><th>Person</th><th>Lead</th><th>Email</th><th>Links</th><th>Status</th></tr></thead><tbody id="ctb"></tbody></table></div></div>`;
  const draw = () => {
    const q = $("#cq").value.toLowerCase(), st = $("#cst").value;
    $("#ctb").innerHTML = cs.filter((c) => (!q || JSON.stringify(c).toLowerCase().includes(q)) && (!st || c.status === st)).map((c) => `<tr>
      <td><b>${esc(c.name)}</b><div class="muted small">${esc(c.title)}${c.org ? `, ${esc(c.org)}` : ""}</div></td>
      <td><a href="#/lead/${c.lead_id}">${esc(c.lead_company)}</a><div class="muted small">${esc(c.lead_title)}</div></td>
      <td>${c.email ? `<span class="mono small">${esc(c.email)}</span> <span class="chip ${c.email_confidence === "found" ? "good" : "warn"}">${esc(c.email_confidence)}</span>` : `<span class="muted">none</span>`}</td>
      <td class="small">${safeUrl(c.linkedin) ? `<a href="${esc(c.linkedin)}" target="_blank" rel="noopener">LinkedIn</a> ` : ""}${safeUrl(c.source_url) ? `<a href="${esc(c.source_url)}" target="_blank" rel="noopener">source</a>` : ""}</td>
      <td><select data-act="cstatus2" data-lead="${c.lead_id}" data-i="${c.idx}">${["", "to contact", "contacted", "replied", "no response", "referred me"].map((s) => `<option ${c.status === s ? "selected" : ""} value="${s}">${s || "not set"}</option>`).join("")}</select></td></tr>`).join("")
      || `<tr><td colspan="5" class="muted">No contacts yet. They're found while application packages are built.</td></tr>`;
  };
  $("#cq").oninput = draw; $("#cst").onchange = draw; draw();
}

// ================================================================ SOURCES
const SRC_HELP = {
  github_lists: "Community-tracked internship and new-grad lists (SimplifyJobs, vanshb03), thousands of roles updated daily. Used only when internships or entry level are among your levels.",
  ats_boards: "Company job boards through their public APIs: tech, fintech, health, aerospace, defense and more. Add any company by pasting its careers URL.",
  linkedin: "LinkedIn's public job search (no login): your search queries in your locations, filtered to your experience levels.",
  usajobs: "U.S. federal jobs, including Pathways and student roles. Needs a free API key from developer.usajobs.gov/apirequest.",
  hackernews: "The monthly 'Who is hiring?' threads plus a search of recent HN comments that mention roles at your level.",
  bluesky: "Searches Bluesky posts for hiring announcements. Needs your handle and a free app password (Bluesky settings, Privacy and security, App passwords).",
  themuse: "The Muse listings at your levels in your locations.",
  reddit: "Reddit search feeds across the hiring and career subreddits below. Reddit rate-limits hard; the AI social mission covers more.",
  mastodon: "Hiring hashtags on Mastodon instances.",
  remote_boards: "Remotive and RemoteOK (only when Remote is one of your locations).",
  rss: "Any RSS or Atom feed. Tip: create Google Alerts (e.g. “data analyst jobs Austin”) delivered as an RSS feed and paste the feed URLs here.",
  adzuna: "Adzuna aggregator (indexes many boards). Free key at developer.adzuna.com.",
  serpapi: "Google Jobs results through SerpAPI (100 free searches a month at serpapi.com).",
};
async function renderSources(cfgOverride) {
  S.cfg = cfgOverride && typeof cfgOverride === "object" ? cfgOverride : await api("/api/settings");
  const plan = (await api("/api/profile")).search_plan || {};
  const c = S.cfg, src = c.sources;
  const field = (path, label, type = "text", extra = "") => `<label class="f"><span>${label}</span><input type="${type}" data-path="${path}" value="${esc(getPath(c, path) ?? "")}" ${extra}></label>`;
  const list = (path, label, rows = 4) => `<label class="f"><span>${label}</span><textarea data-list="${path}" rows="${rows}">${esc((getPath(c, path) || []).map((x) => (typeof x === "object" ? `${x.name || ""} | ${x.url}` : x)).join("\n"))}</textarea></label>`;
  const cfgFor = {
    github_lists: list("sources.github_lists.urls", "listings.json URLs (one per line)", 3),
    ats_boards: `<div class="row"><input type="url" id="det-url" placeholder="Paste any careers page or job URL to add that company…" style="flex:1"><input type="text" id="det-name" placeholder="Company name" style="width:200px"><button class="btn" data-act="detect">Detect & add</button></div><div id="det-res" class="small muted"></div>
      <div class="boards"><table class="t"><thead><tr><th></th><th>Company</th><th>ATS</th><th>Slug / URL</th><th title="Dream company"><i class=i-star></i></th><th></th></tr></thead><tbody>
      ${src.ats_boards.boards.map((b, i) => `<tr><td>${toggle(`data-board="${i}" data-bf="enabled"`, b.enabled !== false)}</td><td><input type="text" data-board="${i}" data-bf="name" value="${esc(b.name)}"></td>
        <td class="mono small">${esc(b.ats)}</td><td><input type="text" data-board="${i}" data-bf="${b.slug ? "slug" : "url"}" value="${esc(b.slug || b.url)}"></td>
        <td>${toggle(`data-board="${i}" data-bf="dream"`, !!b.dream)}</td><td><button class="btn sm ghost danger" data-act="rm-board" data-i="${i}"><i class=i-x></i></button></td></tr>`).join("")}</tbody></table></div>`,
    linkedin: `<div class="grid3">${field("sources.linkedin.max_requests", "Max searches per run", "number")}
      <label class="f"><span>Posted within</span><select data-path="sources.linkedin.time_window">${[["r86400", "24 hours"], ["r604800", "1 week"], ["r2592000", "1 month"]].map(([v, l]) => `<option value="${v}" ${src.linkedin.time_window === v ? "selected" : ""}>${l}</option>`).join("")}</select></label>
      ${field("sources.linkedin.experience", "Experience filter (blank = your levels)", "text", 'placeholder="1 intern, 2 entry, 3 associate, 4 mid-senior"')}</div>`,
    usajobs: `<div class="grid2">${field("sources.usajobs.api_key", "API key", "password")}${field("sources.usajobs.email", "Email used to register", "email")}</div>`,
    hackernews: field("sources.hackernews.threads", "Monthly threads to scan", "number"),
    themuse: field("sources.themuse.pages", "Pages per run", "number"),
    mastodon: `<div class="grid2">${list("sources.mastodon.instances", "Instances", 3)}${list("sources.mastodon.tags", "Hashtags", 3)}</div>`,
    reddit: list("sources.reddit.subreddits", "Subreddits (one per line, without r/)", 4),
    rss: `<label class="f"><span>Feeds: one per line, “name | url” or just the url</span><textarea data-feeds="1" rows="4">${esc((src.rss.feeds || []).map((f) => (typeof f === "object" ? `${f.name} | ${f.url}` : f)).join("\n"))}</textarea></label>`,
    adzuna: `<div class="grid2">${field("sources.adzuna.app_id", "App ID")}${field("sources.adzuna.app_key", "App key", "password")}</div>`,
    serpapi: field("sources.serpapi.api_key", "API key", "password"),
    bluesky: `<div class="grid2">${field("sources.bluesky.handle", "Handle (you.bsky.social)")}${field("sources.bluesky.app_password", "App password", "password")}</div>`,
  };
  main.innerHTML = `<div class="page"><div class="page-h"><h1>Sources</h1><span class="sub">Where the search looks. Locations and filters live in Settings.</span></div>
    <div class="card" style="margin-bottom:16px"><h3>Search queries <span class="muted">(LinkedIn, The Muse, aggregators)</span></h3>
      <div class="row" style="margin-bottom:8px">${toggle(`data-path="search.use_profile_plan" data-bool="1"`, c.search.use_profile_plan !== false)}<span class="small">Use the ${(plan.queries || []).length} queries from your profile's search plan</span><a class="small" href="#/profile/search_plan">edit search plan →</a></div>
      <div class="row" style="gap:5px;margin-bottom:12px">${(plan.queries || []).map((q) => `<span class="chip">${esc(q)}</span>`).join("")}</div>
      ${list("search.queries", "Your extra queries (one per line)", 4)}</div>
    <div class="card" style="margin-bottom:16px"><h3>Job sources</h3>
      ${S.meta.collectors.map(({ key, label }) => `<div class="src">${toggle(`data-path="sources.${key}.enabled" data-bool="1"`, src[key]?.enabled)}
        <div><div class="name">${esc(label)}</div><div class="desc">${esc(SRC_HELP[key] || "")}</div>${cfgFor[key] ? `<div class="cfg">${cfgFor[key]}</div>` : ""}<div id="tr-${key}"></div></div>
        <button class="btn sm" data-act="test-src" data-key="${key}">Test</button></div>`).join("")}</div>
    <div class="card"><h3>AI hunt missions</h3><p class="muted small" style="margin-top:-4px">Each mission is an AI agent with web tools that digs where no API reaches: social posts, comment threads, insiders' LinkedIn posts, forums, niche boards, recruiters, labs, campus pipelines, local news, contract awards and events. Every mission reads your profile, so it searches for your roles in your locations. “AI hunt only” runs every mission; “Everything” rotates through them so each run fits your usage window. Edit freely or add your own.</p>
      <div class="row" style="margin-bottom:12px">${toggle(`data-path="sources.ai_hunt.enabled" data-bool="1"`, src.ai_hunt.enabled)}<span class="small">AI hunting enabled</span>
        <label class="row small" style="gap:6px;margin-left:14px">Per “Everything” run <select data-path="sources.ai_hunt.missions_per_run" data-num="1" style="width:auto">${[[0, "all missions"], [4, "4 (rotate)"], [7, "7 (rotate)"], [10, "10 (rotate)"]].map(([v, l]) => `<option value="${v}" ${(+src.ai_hunt.missions_per_run || 0) === v ? "selected" : ""}>${l}</option>`).join("")}</select></label>
        <label class="row small" style="gap:6px;margin-left:14px">Depth <select data-path="sources.ai_hunt.depth" style="width:auto">${[["deep", "Deep (30+ searches each)"], ["standard", "Standard (~15)"], ["quick", "Quick (~8)"]].map(([v, l]) => `<option value="${v}" ${(src.ai_hunt.depth || "standard") === v ? "selected" : ""}>${l}</option>`).join("")}</select></label><span class="spacer"></span>
        <button class="btn sm" data-act="add-mission">+ New mission</button><button class="btn sm ghost" data-act="reset-missions">Reset to defaults</button></div>
      <div class="stack" id="missions">${src.ai_hunt.missions.map((m, i) => `<div class="mission-ed"><div class="row">${toggle(`data-mission="${i}" data-mf="enabled"`, m.enabled !== false)}
        <input type="text" data-mission="${i}" data-mf="name" value="${esc(m.name)}" style="flex:1;font-weight:600">${m.only_levels ? `<span class="chip" title="Runs only when you search at these levels">${esc(m.only_levels.join(" and "))} only</span>` : ""}<button class="btn sm ghost danger" data-act="rm-mission" data-i="${i}"><i class=i-x></i></button></div>
        <textarea data-mission="${i}" data-mf="prompt" rows="4" style="font-family:var(--sans);font-size:13px">${esc(m.prompt)}</textarea></div>`).join("")}</div></div>
    <div class="sticky-save"><button class="btn primary" data-act="save-cfg">Save sources</button></div></div>`;
  bindCfgInputs();
}
function bindCfgInputs() {
  main.oninput = main.onchange = (e) => {
    const t = e.target, c = S.cfg;
    if (t.dataset.path) setPath(c, t.dataset.path, t.dataset.bool || t.type === "checkbox" ? t.checked : t.type === "number" || t.dataset.num ? +t.value : t.value);
    else if (t.dataset.list) setPath(c, t.dataset.list, t.value.split("\n").map((x) => x.trim()).filter(Boolean));
    else if (t.dataset.feeds) c.sources.rss.feeds = t.value.split("\n").map((x) => x.trim()).filter(Boolean).map((x) => { const [a, b] = x.includes("|") ? x.split("|").map((s) => s.trim()) : [x, x]; return { name: a, url: b }; });
    else if (t.dataset.board != null) c.sources.ats_boards.boards[+t.dataset.board][t.dataset.bf] = t.type === "checkbox" ? t.checked : t.value;
    else if (t.dataset.mission != null) c.sources.ai_hunt.missions[+t.dataset.mission][t.dataset.mf] = t.type === "checkbox" ? t.checked : t.value;
    else if (t.dataset.chips) return;
    else return;
    S.cfgDirty = true;
  };
}
async function saveCfg() {
  S.cfg = await api("/api/settings", { method: "PUT", body: S.cfg });
  S.cfgDirty = false; S.locAllowed = S.cfg.locations.allowed; S.industries = S.cfg.industries; toast("Saved", "Settings updated");
}

// ================================================================ PROFILE
const PTABS = [["overview", "Overview"], ["resume", "Resume"], ["answers", "Standard answers"], ["questions", "Questions"], ["facts", "Facts"],
  ["skills", "Skills inventory"], ["project_bank", "Experience & projects"], ["story_bank", "Story bank"], ["targeting", "Targeting"],
  ["search_plan", "Search plan"], ["voice", "Voice"]];
const fmtTs = (ts) => (ts ? new Date(ts).toLocaleString([], { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" }) : "never");
const questionDraft = () => $$("[data-qans], #own-q, #own-a").some((el) => el.value.trim());
async function renderProfile(tab) {
  S.ptab = tab || S.ptab || "overview";
  const p = (S.profileCache = await api("/api/profile"));
  const openQ = (S.questions || []).filter((q) => q.status === "open").length;
  main.innerHTML = `<div class="page"><div class="page-h"><h1>Profile</h1><span class="sub">Built from your resume, your standard answers and your answers to questions along the way. Every search, score and document comes from here.</span></div>
    <div class="tabs">${PTABS.map(([k, t]) => `<a class="${S.ptab === k ? "on" : ""}" href="#/profile/${k}">${t}${k === "questions" && openQ ? `<span class="n">${openQ}</span>` : ""}</a>`).join("")}</div><div id="pbody"></div></div>`;
  const b = $("#pbody"), k = S.ptab;
  if (k === "overview") await renderProfileOverview(b);
  else if (k === "resume") await renderResumeTab(b);
  else if (k === "answers") await renderAnswersTab(b);
  else if (k === "questions") await renderQuestionsTab(b);
  else if (k === "facts") {
    const f = p.facts, fld = (path, label, w) => `<label class="f" ${w ? `style="grid-column:span ${w}"` : ""}><span>${label}</span><input type="text" data-fp="${path}" value="${esc(getPath(f, path) ?? "")}"></label>`;
    b.innerHTML = `<div class="stack"><div class="card"><div class="grid3">${fld("name", "Name")}${fld("email", "Email")}${fld("phone", "Phone")}${fld("city", "City")}${fld("state", "State")}${fld("gpa", "GPA")}
      ${fld("links.site", "Website")}${fld("links.github", "GitHub")}${fld("links.linkedin", "LinkedIn")}${fld("school", "School")}${fld("degree", "Degree")}${fld("graduation", "Graduation")}
      ${fld("work_authorization", "Work authorization", 3)}${fld("clearance", "Clearance", 3)}</div>
      <label class="f" style="margin-top:14px"><span>Skills (for matching)</span><textarea data-fp="skills" rows="3">${esc(f.skills)}</textarea></label>
      <div class="row" style="justify-content:flex-end;margin-top:12px"><button class="btn primary" data-act="save-facts">Save facts</button></div></div>
      <div class="card"><h3>Where each fact came from</h3><p class="muted small" style="margin-top:-4px">Your standard answers override what the resume says. Quick fixes here are kept when the profile is rebuilt, unless your resume or answers say otherwise.</p>
      <table class="t"><thead><tr><th>Field</th><th>Value</th><th>Source</th><th>Source date</th></tr></thead><tbody>
      ${(p.provenance || []).map((x) => `<tr><td class="mono small">${esc(x.field)}</td><td>${esc(x.value)}</td><td class="small">${esc(x.source)}</td><td class="mono small">${esc(x.date)}</td></tr>`).join("") || `<tr><td colspan="4" class="muted">Recorded when your profile is built.</td></tr>`}</tbody></table></div></div>`;
  } else if (k === "skills") {
    const inv = p.skills_inventory || [];
    const draw = () => (b.innerHTML = `<div class="card"><p class="muted small" style="margin-top:0">Every skill from your resume and your answers. Tailored resumes may only list skills from here.
      <b>strong</b>: used substantially in a documented job or project. <b>working</b>: coursework or smaller use. <b>listed</b>: only appears in a list (used only when a posting asks for it). Rebuilt with your profile; your edits are kept.</p>
      <table class="t"><thead><tr><th>Skill</th><th>Category</th><th>Level</th><th>Evidence (semicolon-separated)</th><th></th></tr></thead><tbody>
      ${inv.map((x, i) => `<tr><td><input type="text" data-sk="${i}" data-sf="skill" value="${esc(x.skill)}"></td><td><input type="text" data-sk="${i}" data-sf="category" value="${esc(x.category)}"></td>
        <td><select data-sk="${i}" data-sf="level">${["strong", "working", "listed"].map((lv) => `<option ${lv === x.level ? "selected" : ""}>${lv}</option>`).join("")}</select></td>
        <td><input type="text" data-sk="${i}" data-sf="evidence" value="${esc((x.evidence || []).join("; "))}"></td><td><button class="btn sm ghost danger" data-act="rm-skill" data-i="${i}"><i class=i-x></i></button></td></tr>`).join("")}</tbody></table>
      <div class="row" style="margin-top:12px"><button class="btn" data-act="add-skill">+ Add skill</button><span class="spacer"></span><span class="muted small">${inv.length} skills</span><button class="btn primary" data-act="save-skills">Save inventory</button></div></div>`);
    draw(); S.skDraw = draw; S.skInv = inv;
  } else if (k === "search_plan") {
    const sp = p.search_plan || {};
    b.innerHTML = `<div class="card"><p class="muted small" style="margin-top:0">What the search goes after, derived from your resume and answers and regenerated on each rebuild (your edits are kept unless your answers say otherwise). It's combined with your extra queries in Sources and your dream companies.</p>
      <div class="grid3"><label class="f"><span>Role families (ranked)</span><textarea id="sp-roles" rows="14">${esc((sp.role_families || []).join("\n"))}</textarea></label>
      <label class="f"><span>Search queries</span><textarea id="sp-queries" rows="14">${esc((sp.queries || []).join("\n"))}</textarea></label>
      <label class="f"><span>Target companies</span><textarea id="sp-cos" rows="14">${esc((sp.dream_companies || []).join("\n"))}</textarea></label></div>
      <label class="f" style="margin-top:12px"><span>Strategy note</span><input type="text" id="sp-notes" value="${esc(sp.notes || "")}"></label>
      <div class="row" style="justify-content:flex-end;margin-top:12px"><button class="btn primary" data-act="save-plan">Save search plan</button></div></div>`;
  } else if (["project_bank", "story_bank", "targeting", "voice"].includes(k)) {
    const hist = await api(`/api/profile/${k}/history`);
    b.innerHTML = `<div class="toolbar"><button class="btn primary" data-act="save-ptext" data-k="${k}">Save</button>
      ${hist.length ? `<select id="phist" style="width:auto"><option value="">Restore a previous version</option>${hist.map((h) => `<option value="${h.id}">${esc(h.saved_at.replace("T", " ").slice(0, 16))}</option>`).join("")}</select>` : ""}
      ${k === "voice" ? `<button class="btn" data-act="learn-voice"><i class=i-ai></i> Learn from my writing sample</button>` : ""}
      <span class="muted small">${{ project_bank: "The record every resume is composed from: education, every job (titles, dates, metrics), certifications and projects. Built from your resume and answers.", story_bank: "Interview stories in STAR form, used for interview prep and application answers.", targeting: "What you're looking for, plus eligibility facts and dealbreakers. Triage reads this on every run.", voice: "How you write, learned from the writing sample in your standard answers. Cover letters, emails, LinkedIn notes and application answers are written in this voice." }[k]}</span></div>
      <div class="editor"><textarea id="ptext">${esc(p[k])}</textarea><div class="card md" id="pprev" style="max-height:78vh;overflow:auto"></div></div>`;
    const upd = () => ($("#pprev").innerHTML = md($("#ptext").value));
    $("#ptext").oninput = debounce(upd, 200); upd();
    if ($("#phist")) $("#phist").onchange = (e) => { const h = hist.find((x) => x.id === +e.target.value); if (h) { $("#ptext").value = h.value; upd(); toast("Loaded old version", "Save to keep it."); } };
  }
}

async function renderResumeTab(b) {
  const d = await api("/api/onboarding");
  const r = d.resume;
  b.innerHTML = `<div class="cols"><div class="stack">
      <div class="card"><h3>Your resume</h3>${r ? `<div class="row"><i class=i-doc></i><b>${esc(r.filename)}</b><span class="muted small">imported ${esc(fmtTs(r.imported_at))}, ${(r.chars || 0).toLocaleString()} characters</span></div>
        <p class="muted small">JobPortal reads this resume as a source of facts. It never uses it as a template: every tailored resume is written fresh from your profile.</p>`
        : `<p class="muted">No resume imported yet.</p>`}
        ${resumeDropzone(d.accept, r ? "Import a newer resume" : "Import your resume")}</div>
      <div class="card"><h3>Rebuild</h3><p class="muted small" style="margin-top:-4px">Reads your resume, standard answers and every answer again. Edits you made by hand are kept unless something newer contradicts them.</p>
        <button class="btn" data-act="profile-build" ${r ? "" : "disabled"}><i class=i-refresh></i> Rebuild profile</button></div></div>
    <div class="card"><h3>Text JobPortal read from it</h3><pre class="jd" style="max-height:70vh">${esc(d.resume_preview || "Nothing yet.")}${(r?.chars || 0) > 4000 ? "\n\n(first 4,000 characters shown)" : ""}</pre></div></div>`;
  wireResumeDropzone(b, async () => {
    toast("Resume imported", "Rebuilding your profile with it now.");
    await api("/api/profile/build", { method: "POST" });
    renderProfile("resume");
  }, { prefill: false });
}

async function renderAnswersTab(b) {
  const d = await api("/api/onboarding");
  b.innerHTML = `<div class="card" style="margin-bottom:14px"><p class="muted small" style="margin:0">These answers fill in every Application kit and set your search: experience levels, locations, dream companies and the title filters. Saving rebuilds your profile so the search plan follows.</p></div>
    <div id="qform">${answersForm(d.questions, d.answers, {})}</div>
    <div class="sticky-save"><span class="muted small" id="ans-tab-state"></span><button class="btn primary" data-act="save-std-answers">Save answers</button></div>`;
  $("#qform").addEventListener("input", () => { S.dirty = true; $("#ans-tab-state").textContent = "unsaved"; });
}

async function renderQuestionsTab(b) {
  const qs = (S.questions = await api("/api/questions"));
  const open = qs.filter((q) => q.status === "open"), answered = qs.filter((q) => ["answered", "applied"].includes(q.status));
  const pending = answered.filter((q) => !q.synced).length;
  S.openQs = open;
  const from = (q) => q.source === "profile" ? "" : q.lead_id ? `<a class="chip blue" style="margin-left:4px" href="#/lead/${q.lead_id}">for ${esc(String(q.source || "").replace(/ application$/, ""))} <i class=i-ext></i></a>` : q.source ? `<span class="chip blue" style="margin-left:4px">from ${esc(q.source)}</span>` : "";
  b.innerHTML = `<div class="cols"><div class="stack">
      <div class="card"><h3>Open questions (${open.length})</h3><p class="muted small" style="margin-top:-4px">Gaps JobPortal found while building your profile and your applications. Answers are added to your profile automatically about a minute after you stop answering.</p>
        <div class="stack">${open.map((q, i) => `<div class="mission-ed"><div><b>${esc(q.question)}</b></div><div class="small muted">${esc(q.why)} ${q.field ? `<span class="chip" style="margin-left:4px">${esc(q.field)}</span>` : ""}${from(q)}</div>
          <textarea rows="2" data-qans="${i}" placeholder="Your answer" style="font-family:var(--sans);font-size:13px"></textarea>
          <div class="row"><button class="btn sm primary" data-act="answer-q" data-i="${i}">Save answer</button><button class="btn sm ghost" data-act="dismiss-q" data-i="${i}">Not relevant</button></div></div>`).join("") || `<div class="muted">No open questions right now.</div>`}</div></div>
      <div class="card"><h3>Tell JobPortal something new</h3><p class="muted small" style="margin-top:-4px">A project, a certification, a skill or a result that isn't on your resume. It goes into your profile like any other answer.</p>
        <input type="text" id="own-q" placeholder="What is it about? (e.g. Kubernetes experience, a hackathon win)" style="width:100%;margin-bottom:8px">
        <textarea id="own-a" rows="3" placeholder="The details, in a sentence or two" style="font-family:var(--sans);font-size:13px;width:100%"></textarea>
        <div class="row" style="margin-top:8px"><span class="spacer"></span><button class="btn primary sm" data-act="add-own-answer">Save</button></div></div></div>
    <div class="card"><div class="row" style="margin-bottom:8px"><h3 style="margin:0">Your answers (${answered.length})</h3><span class="spacer"></span>
        ${pending ? `<button class="btn sm ai" data-act="sync-answers"><i class=i-ai></i> Add ${pending} to my profile now</button>` : ""}</div>
      ${answered.slice().reverse().map((q) => `<div class="copyrow" style="grid-template-columns:1fr 1fr auto"><div class="q">${esc(q.question)}</div><div class="a">${esc(q.answer || "")}</div>
        <span class="chip ${q.synced ? "good" : "warn"}" title="${q.synced ? "Part of your profile" : "Waiting to be added to your profile"}">${q.synced ? "in profile" : "pending"}</span></div>`).join("") || `<div class="muted small">Nothing answered yet.</div>`}</div></div>`;
}

// ================================================================ SETTINGS
const STAGE_HELP = { prefill: "Reads your resume during setup to pre-fill the standard questions. Cheap and fast is fine.",
  triage: "Scores every candidate in batches. Runs hundreds of times, so cheap and fast is fine.",
  hunt: "AI hunt missions: agents that search the web, social media and threads.", package: "Builds each application package: research, contacts, resume, cover letter, emails, prep.",
  revise: "‘Revise with AI’ edits in the editor.", profile: "Builds your profile from your resume and answers, adds new answers, and learns your writing voice.",
  analysis: "The Analysis tab: fit and interest per work genre, and what to build next." };
function modelOptions(selected, emptyLabel) {
  const list = [...new Set([...(S.models || []), ...(selected ? [selected] : [])])];
  return `<option value="">${esc(emptyLabel)}</option>` + list.map((m) => `<option ${m === selected ? "selected" : ""}>${esc(m)}</option>`).join("");
}
async function renderSettings() {
  S.cfg = await api("/api/settings");
  try { const st = await api("/api/ai/status"); S.state.ai = st; S.aiWeb = st.web_search; } catch (_) {}
  S.models = aiReady() ? ((await api("/api/ai/models").catch(() => null)) || { models: [] }).models : [];
  const defaults = await api("/api/prompts/defaults");
  const c = S.cfg;
  const num = (path, label, step = 1) => `<label class="f"><span>${label}</span><input type="number" step="${step}" data-path="${path}" value="${esc(getPath(c, path))}"></label>`;
  const chips = (path, label) => `<div class="f"><label class="f"><span>${label}</span></label><div class="row" style="gap:6px;margin:6px 0">${(getPath(c, path) || []).map((x, i) => `<span class="chip">${esc(x)}<span class="x" data-act="rm-chip" data-path="${path}" data-i="${i}"><i class=i-x></i></span></span>`).join("")}</div>
    <div class="row"><input type="text" placeholder="Add…" data-chipadd="${path}" style="max-width:320px"><button class="btn sm" data-act="add-chip" data-path="${path}">Add</button></div></div>`;
  const lines = (path, label, rows = 5) => `<label class="f"><span>${label}</span><textarea data-list="${path}" rows="${rows}">${esc((getPath(c, path) || []).join("\n"))}</textarea></label>`;
  main.innerHTML = `<div class="page"><div class="page-h"><h1>Settings</h1></div><div class="stack">
    <div class="card"><h3>AI: ChatGPT</h3>
      <div class="row" style="margin-bottom:8px">${aiReady() ? `<span>Signed in as <b>${esc(S.state.ai.email || S.state.ai.name || "your account")}</b></span><span class="spacer"></span><button class="btn sm" data-act="ai-signout">Sign out</button>`
        : `<span class="muted">Not signed in.</span><span class="spacer"></span><button class="btn sm primary" data-act="ai-signin">Continue with ChatGPT</button>`}</div>
      <p class="muted small" style="margin-top:0">JobPortal's AI runs on your ChatGPT plan (Go, Plus or Pro). Usage counts against your plan. Set a weekly cap for JobPortal in ChatGPT settings.
        Web search ${S.aiWeb === false ? "isn't available on your account, so agents read pages directly" : S.aiWeb ? "is available" : "is checked on the first web task"}.</p>
      <label class="f" style="max-width:420px"><span>Default model</span><select data-path="ai.model">${modelOptions(c.ai.model, "First model your plan lists")}</select></label>
      <table class="t" style="margin-top:10px"><tbody>${Object.entries(c.ai.stages).map(([k, v]) => `<tr><td style="width:110px" class="mono"><b>${k}</b></td>
        <td style="width:220px"><select data-path="ai.stages.${k}.model">${modelOptions(v.model, "Default model")}</select></td>
        <td style="width:130px"><select data-path="ai.stages.${k}.effort">${S.meta.efforts.map((m) => `<option ${m === v.effort ? "selected" : ""}>${m}</option>`).join("")}</select></td>
        <td class="muted small">${STAGE_HELP[k] || ""}</td></tr>`).join("")}</tbody></table>
      <div class="grid3" style="margin-top:14px">${num("ai.max_parallel", "Parallel agents")}</div></div>
    <div class="card"><h3>Runs</h3><div class="grid3">${num("run.min_score", "Min score to qualify (0 to 100)")}${num("run.max_triage", "Max candidates triaged per run")}${num("run.triage_batch", "Triage batch size")}
      ${num("run.max_packages", "Max packages per run")}${num("run.max_age_days", "Ignore postings older than (days)")}${num("run.auto_run_hours", "Auto-run every N hours (0 = off)", 0.5)}</div>
      <div class="row" style="margin-top:12px">${toggle(`data-path="run.package_web_research" data-bool="1"`, c.run.package_web_research)}<span class="small">Packages do live web research (verify posting, company news, find contacts)</span></div></div>
    <div class="card"><h3>Resumes</h3><div class="row" style="margin-bottom:10px">${toggle(`data-path="run.resume_review" data-bool="1"`, c.run.resume_review !== false)}<span class="small">Recruiter-critic pass on every tailored resume (fixes check issues, sharpens bullets; ~+$0.10 each)</span></div>
      <label class="f"><span>Resume playbook (researched practices the generator follows: universal rules, layouts, industry archetypes)</span><textarea id="playbook" rows="14"></textarea></label>
      <div class="row" style="margin-top:8px"><span class="muted small" id="pb-state"></span><span class="spacer"></span><button class="btn sm ghost" data-act="playbook-reset">Reset to researched default</button><button class="btn sm primary" data-act="playbook-save">Save playbook</button></div></div>
    <div class="card"><h3>Search area</h3><div class="row"><span class="chip" style="font-size:13px"><i class=i-pin></i> ${esc(areaSummary(c.locations.allowed))}</span>
      <span class="muted small">${c.locations.dream_bypass ? "Dream companies can be anywhere in the US. " : ""}Unknown locations: ${c.locations.unknown_policy === "ai" ? "AI decides" : "dropped"}.</span>
      <span class="spacer"></span><button class="btn primary" data-act="edit-area">Edit states, cities & remote</button></div></div>
    <div class="card"><h3>Industries</h3><p class="muted small" style="margin-top:-4px">Every lead is tagged with one of these so you can filter and sort. Edit the list (one per line), save, then re-tag.</p>
      ${lines("industries", "Industries", 8)}<div class="row" style="margin-top:8px"><button class="btn sm ai" data-act="retag-industries"><i class=i-ai></i> Re-tag all leads with AI</button></div></div>
    <div class="card"><h3>Dream companies & jobs</h3><div class="row"><span class="small muted">Edit your dream companies, dream roles and their location rules on one page.</span><span class="spacer"></span><a class="btn primary" href="#/dreams"><i class=i-star></i> Open Dream list</a></div></div>
    <div class="card"><h3>Filters</h3><p class="muted small" style="margin-top:-4px">The title filters are generated from your experience levels and target roles each time you save your standard answers. Edit them here if you need to.</p>
      <div class="grid2">${lines("filters.title_include", "Title must match one of (regex, blank = any title)", 8)}${lines("filters.title_exclude", "Title must NOT match (regex)", 8)}
      ${lines("filters.exclude_companies", "Never show these companies", 4)}${lines("filters.exclude_keywords", "Drop if description contains", 4)}</div>
      <div class="row" style="margin-top:12px">${toggle(`data-path="filters.require_tech_title" data-bool="1"`, c.filters.require_tech_title)}<span class="small">Require a tech/science word in the title for job-board sources</span></div></div>
    <div class="card"><h3>Your data</h3><p class="muted small" style="margin-top:-4px">Everything JobPortal stores (database, imported resume, generated files) lives in one folder on this computer, never in the code folder. Delete the folder to start over from zero.</p>
      <div class="row"><span class="mono small" style="flex:1;min-width:0;overflow-wrap:anywhere">${esc(S.meta.data_dir || "")}</span><button class="btn sm" data-act="open-data">Open folder</button></div>
      ${ownWindow() ? "" : `<div class="row" style="margin-top:8px"><span class="muted small" style="flex:1">Closing this tab leaves JobPortal running so searches can finish. Quit stops it.</span><button class="btn sm" data-act="quit">Quit JobPortal</button></div>`}
      <div class="muted small" style="margin-top:8px">JobPortal ${esc(S.meta.version || "")} on ${esc(S.meta.os || "")}. PDF export: ${S.meta.pdf_ready ? "ready" : "needs Chrome, Edge or Chromium"}. ChatGPT: ${aiReady() ? "signed in" : "not signed in"}.</div></div>
    <div class="card"><h3>Prompts (advanced)</h3><p class="muted small" style="margin-top:-4px">Override the system prompts. Leave blank to use the built-in default (shown greyed).</p>
      ${Object.keys(defaults).map((k) => `<label class="f" style="margin-bottom:12px"><span>${k}</span><textarea rows="5" data-path="prompts.${k}" placeholder="${esc(defaults[k])}">${esc(c.prompts?.[k] || "")}</textarea></label>`).join("")}</div>
    <div class="sticky-save"><button class="btn primary" data-act="save-cfg">Save settings</button></div></div></div>`;
  bindCfgInputs();
  api("/api/resume-playbook").then((pb) => { $("#playbook").value = pb.text; $("#pb-state").textContent = pb.custom ? "custom playbook" : "researched default (Oct 2026)"; });
}

// ================================================================ RUNS
async function renderRuns(id) {
  const runs = await api("/api/runs");
  const dur = (r) => r.finished_at ? Math.round((new Date(r.finished_at) - new Date(r.started_at)) / 60000) + " min" : "…";
  main.innerHTML = `<div class="page"><div class="page-h"><h1>Runs</h1><span class="sub">History of every mega search.</span></div>
    <div class="card" style="margin-bottom:16px"><table class="t"><thead><tr><th>#</th><th>Started</th><th>Mode</th><th>Status</th><th>Duration</th><th>Found</th><th>Candidates</th><th>Triaged</th><th>Qualified</th><th>Packaged</th><th>Tokens</th></tr></thead><tbody>
    ${runs.map((r) => `<tr style="cursor:pointer" data-act="runlog" data-id="${r.id}"><td class="mono">${r.id}</td><td>${esc(new Date(r.started_at).toLocaleString())}</td><td>${esc(r.mode)}</td>
      <td><span class="chip ${r.status === "done" ? "good" : r.status === "running" ? "accent" : "warn"}">${esc(r.status)}</span></td><td>${dur(r)}</td>
      <td>${r.stats.found ?? ""}</td><td>${r.stats.candidates ?? ""}</td><td>${r.stats.triaged ?? ""}</td><td>${r.stats.qualified ?? ""}</td><td>${r.stats.packaged ?? ""}</td><td>${fmtTokens(+r.tokens || 0)}</td></tr>`).join("") || `<tr><td colspan="11" class="muted">No runs yet.</td></tr>`}</tbody></table></div>
    <div id="runlog"></div></div>`;
  if (id || runs[0]) showRunLog(id || runs[0].id, runs.find((r) => r.id === +(id || runs[0].id)));
}
async function showRunLog(id, run) {
  const lines = await api(`/api/runs/${id}/log`);
  const st = run?.stats || {};
  const filt = Object.entries(st).filter(([k]) => k.startsWith("filtered") || ["already known", "duplicate", "deferred to next run", "below threshold"].includes(k));
  $("#runlog").innerHTML = `<div class="cols"><div class="console" style="margin:0"><div class="ch">run #${id} log, ${lines.length} lines</div><div class="body" style="height:60vh">${lines.map(logLine).join("")}</div></div>
    <div class="card"><h3>Where candidates went</h3><table class="t"><tbody>${filt.sort((a, b) => b[1] - a[1]).map(([k, v]) => `<tr><td>${esc(k)}</td><td class="mono">${v}</td></tr>`).join("") || `<tr><td class="muted">none</td></tr>`}</tbody></table></div></div>`;
}

// ================================================================ actions (event delegation)
main.addEventListener("click", async (e) => {
  const el = e.target.closest("[data-act]"); if (!el) return;
  const a = el.dataset.act;
  try {
    if (a === "ext") { e.stopPropagation(); return; }
    else if (a === "open-lead") { location.hash = `#/lead/${el.dataset.id}`; }
    else if (a === "found-menu") { e.stopPropagation(); const d = await api(`/api/leads/${el.dataset.id}`); foundMenu(d); }
    else if (a === "quick-status") { e.stopPropagation(); const id = el.closest(".lead").dataset.id; await api(`/api/leads/${id}`, { method: "PATCH", body: { app_status: el.dataset.st } }); if (el.dataset.st === "trashed") toast("Trashed", "Find it under the Trashed tab."); }
    else if (a === "run") {
      const mode = $("#runmode")?.value || "full"; localStorage.setItem("runmode", mode);
      if (S.notify && !desktop() && "Notification" in window && Notification.permission === "default") Notification.requestPermission();
      await api("/api/run", { method: "POST", body: { mode } }); S.logs = []; const b = $("#console-body"); if (b) b.innerHTML = "";
    }
    else if (a === "stop") { await api("/api/run/stop", { method: "POST" }); toast("Stopping", "Finishing up and saving progress…"); }
    else if (a === "notify") { S.notify = !S.notify; localStorage.setItem("notify", S.notify ? "1" : "0"); if (S.notify && !desktop() && "Notification" in window) Notification.requestPermission(); renderMission(); }
    else if (a === "toggle-console") { S.consoleOpen = !S.consoleOpen; localStorage.setItem("consoleOpen", S.consoleOpen ? "1" : "0"); $("#console").classList.toggle("closed", !S.consoleOpen); }
    else if (a === "tile") { const go = el.dataset.go; if (go === "tracker") location.hash = "#/tracker"; else { S.leadsTab = go; localStorage.setItem("leadsTab", go); loadLeads(); } }
    else if (a === "ltab") { S.leadsTab = el.dataset.tab; localStorage.setItem("leadsTab", S.leadsTab); loadLeads(); }
    else if (a === "add-lead") addLeadModal();
    // lead detail
    else if (a === "ltabgo") { if (S.dirty && !confirm("Discard unsaved edits?")) return; S.dirty = false; S.leadTab = el.dataset.tab; renderLeadTab(); }
    else if (a === "apply") {
      openUrl(el.dataset.url);
      if (S.lead && !["applied", "assessment", "interviewing", "offer"].includes(S.lead.app_status))
        setTimeout(() => { if (confirm("Did you submit the application? Mark it as Applied (sets a 7-day follow-up)?")) setStatus(S.lead.id, "applied"); }, 800);
    }
    else if (a === "regen") { if (S.lead.resume_md && !confirm("Regenerate the whole package? Your edits to the resume/cover letter will be replaced.")) return; await api(`/api/leads/${S.lead.id}/package`, { method: "POST" }); toast("Building package", "It'll update here when ready."); setTimeout(() => renderLead(S.lead.id), 800); }
    else if (a === "plan") { const pkg = S.lead.package; const done = new Set(pkg.plan_done || []); el.checked ? done.add(+el.dataset.i) : done.delete(+el.dataset.i); pkg.plan_done = [...done]; el.nextElementSibling.classList.toggle("done", el.checked); await api(`/api/leads/${S.lead.id}`, { method: "PATCH", body: { package: { plan_done: pkg.plan_done } } }); }
    else if (a === "mail") mailAction(el.dataset.how, +el.dataset.i);
    else if (a === "save-emails") { await saveEmails(); toast("Saved", "Emails updated"); }
    else if (a === "revise-email") {
      const i = +el.dataset.i, ins = $(`[data-erev="${i}"]`).value.trim(); if (!ins) return;
      const card = $(`.email[data-i="${i}"]`), bodyEl = $('[data-ef="body"]', card);
      el.disabled = true; el.innerHTML = `<span class="spin"></span>`;
      try { const r = await api(`/api/leads/${S.lead.id}/revise`, { method: "POST", body: { doc: `email (${S.lead.package.emails[i].kind})`, instruction: ins, text: bodyEl.value } });
        bodyEl.value = r.text; S.dirty = true; toast("Email revised", "Review it, then Save edits."); } catch (err) { toast("Revision failed", err.message, "error"); }
      el.disabled = false; el.textContent = "Revise";
    }
    else if (a === "export") {
      if (S.dirty && S.leadTab === "emails") await saveEmails();
      if (S.dirty && S.leadTab === "kit") { await api(`/api/leads/${S.lead.id}`, { method: "PATCH", body: { package: { application_answers: readAnswers() } } }); S.dirty = false; }
      openUrl(el.dataset.url);
    }
    else if (a === "save-answers") { await api(`/api/leads/${S.lead.id}`, { method: "PATCH", body: { package: { application_answers: readAnswers() } } }); S.dirty = false; $("#ans-state").textContent = "saved"; }
    else if (a === "add-answer") { readAnswers(); S.lead.package.application_answers.push({ question: "New question", answer: "" }); renderLeadTab(); S.dirty = true; }
    else if (a === "rm-answer") { readAnswers(); S.lead.package.application_answers.splice(+el.dataset.i, 1); renderLeadTab(); S.dirty = true; }
    else if (a === "copy-answer") copy($(`[data-aa="${el.dataset.i}"]`).value);
    else if (a === "rm-contact") { if (!confirm("Remove this contact?")) return; const r = await api(`/api/leads/${S.lead.id}/contacts/${el.dataset.i}`, { method: "POST", body: { delete: true } }); S.lead.package.contacts = r.contacts; renderLeadTab(); }
    else if (a === "copy-lnote") copy($("#lnote").value, "LinkedIn note copied");
    else if (a === "copytext") copy(el.dataset.text);
    else if (a === "add-contact") {
      const body = {}; $$("[data-nc]").forEach((i) => (body[i.dataset.nc] = i.value)); if (!body.name) return;
      const r = await api(`/api/leads/${S.lead.id}/contacts/-1`, { method: "POST", body }); S.lead.package.contacts = r.contacts; renderLeadTab();
    }
    else if (a === "save-notes") { await api(`/api/leads/${S.lead.id}`, { method: "PATCH", body: { notes: $("#notes").value } }); toast("Saved", "Notes updated"); }
    else if (a === "save-fu") { await api(`/api/leads/${S.lead.id}`, { method: "PATCH", body: { follow_up_at: $("#fu").value || null } }); toast("Saved", "Follow-up date set"); refreshStats(); }
    else if (a === "logev") { const text = el.dataset.text || $("#evtext").value; if (!text) return; await api(`/api/leads/${S.lead.id}/events`, { method: "POST", body: { type: "update", text } }); renderLead(S.lead.id); }
    else if (a === "goemails") { S.leadTab = "emails"; }
    // sources / settings
    else if (a === "save-cfg") await saveCfg();
    else if (a === "test-src") {
      const key = el.dataset.key, box = $(`#tr-${key}`);
      if (S.cfgDirty) await saveCfg();
      box.innerHTML = `<div class="testres"><span class="spin"></span> testing…</div>`;
      const r = await api(`/api/sources/test/${key}`, { method: "POST" });
      box.innerHTML = `<div class="testres">${r.ok ? `<b>${r.found}</b> found, <b>${r.pass_filters}</b> pass your filters<br>${r.sample.map((s) => `• ${esc(s.title)}, ${esc(s.company)} (${esc(s.location)})`).join("<br>")}` : `<span style="color:var(--bad)">${esc(r.error)}</span>`}${r.logs?.length ? `<br><span class="muted">${r.logs.map(esc).join("<br>")}</span>` : ""}</div>`;
    }
    else if (a === "detect") {
      const res = $("#det-res"); res.textContent = "detecting…";
      const r = await api("/api/sources/detect", { method: "POST", body: { url: $("#det-url").value, name: $("#det-name").value } });
      if (r.ok) { S.cfg.sources.ats_boards.boards.unshift({ ...r.board, name: r.board.name || $("#det-name").value || r.board.slug || "New company" }); await saveCfg(); toast("Company added", `${r.count} postings, ${r.board.ats}`); renderSources(); }
      else res.textContent = r.message;
    }
    else if (a === "rm-board") { S.cfg.sources.ats_boards.boards.splice(+el.dataset.i, 1); S.cfgDirty = true; renderSourcesKeep(); }
    else if (a === "add-mission") { S.cfg.sources.ai_hunt.missions.push({ id: "m" + Date.now(), name: "New mission", enabled: true, prompt: "Describe where to look and what to find…" }); renderSourcesKeep(); }
    else if (a === "rm-mission") { if (confirm("Delete this mission?")) { S.cfg.sources.ai_hunt.missions.splice(+el.dataset.i, 1); renderSourcesKeep(); } }
    else if (a === "reset-missions") { if (confirm("Reset all missions to the built-in defaults?")) { await api("/api/settings/reset", { method: "POST", body: { path: "sources.ai_hunt.missions" } }); renderSources(); } }
    else if (a === "add-chip") { const inp = $(`[data-chipadd="${el.dataset.path}"]`); if (!inp.value.trim()) return; getPath(S.cfg, el.dataset.path).push(inp.value.trim()); await saveCfg(); renderSettings(); }
    else if (a === "rm-chip") { getPath(S.cfg, el.dataset.path).splice(+el.dataset.i, 1); await saveCfg(); renderSettings(); }
    // profile
    else if (a === "save-facts") { const f = clone(S.profileCache.facts); $$("[data-fp]").forEach((i) => setPath(f, i.dataset.fp, i.value)); await api("/api/profile/facts", { method: "PUT", body: { value: f } }); toast("Saved", "Facts updated"); }
    else if (a === "save-ptext") { await api(`/api/profile/${el.dataset.k}`, { method: "PUT", body: { value: $("#ptext").value } }); toast("Saved", "Previous version kept in history"); }
    else if (a === "profile-build") { await api("/api/profile/build", { method: "POST" }); toast("Rebuilding your profile", "Reading your resume and answers again. A few minutes."); }
    else if (a === "sync-answers") { await api("/api/profile/sync-answers", { method: "POST" }); toast("Adding your answers", "Your profile updates in a minute or two."); el.disabled = true; }
    else if (a === "learn-voice") {
      el.disabled = true; el.innerHTML = `<span class="spin"></span> Reading your writing`;
      try { const r = await api("/api/profile/voice", { method: "POST" }); if (!r.ok) toast("Nothing to learn from yet", r.message, "error"); }
      catch (err) { toast("Couldn't learn your voice", err.message, "error"); }
      if (S.route[0] === "profile") renderProfile(S.ptab);
    }
    else if (a === "ai-signin") aiSignIn();
    else if (a === "ai-signout") { await aiSignOut(); if (S.route[0] === "settings") renderSettings(); }
    else if (a === "quit") {
      if (S.state.running && !confirm("A search is running. Quitting stops it; progress so far is saved.")) return;
      await api("/api/quit", { method: "POST" });
      S.quit = true;
      document.body.innerHTML = `<div class="empty" style="padding:64px"><b>JobPortal has quit</b>You can close this tab. Open JobPortal again to pick up where you left off.</div>`;
    }
    else if (a === "open-data") { const r = await api("/api/open-data-folder", { method: "POST" }); if (!r.ok) toast("Couldn't open the folder", r.path, "error"); }
    else if (a === "save-std-answers") {
      const answers = readAnswersForm($("#qform"));
      const miss = missingRequired(answers); if (miss.length) { toast("A few answers are required", miss.join(", "), "error"); return; }
      const r = await api("/api/onboarding/answers", { method: "PUT", body: { answers, build: true } });
      S.dirty = false; $("#ans-tab-state").textContent = "saved"; S.pstatus = r.status; renderProfilePill();
      toast("Answers saved", r.building ? "Your search settings are updated and your profile is rebuilding." : "Your search settings are updated.");
    }
    else if (a === "answer-q") {
      const q = S.openQs[+el.dataset.i], ans = $(`[data-qans="${el.dataset.i}"]`).value.trim(); if (!ans) return;
      await api("/api/questions/answer", { method: "POST", body: { question: q.question, answer: ans } }); toast("Answer saved", "It's added to your profile about a minute after you stop answering."); renderProfile("questions"); }
    else if (a === "add-own-answer") {
      const q = $("#own-q").value.trim(), ans = $("#own-a").value.trim(); if (!q || !ans) { toast("Fill in both boxes", "What it's about, and the details.", "error"); return; }
      await api("/api/questions/answer", { method: "POST", body: { question: q, answer: ans } }); toast("Saved", "It's added to your profile in about a minute."); renderProfile("questions"); }
    else if (a === "dismiss-q") { await api("/api/questions/dismiss", { method: "POST", body: { question: S.openQs[+el.dataset.i].question } }); S.questions = await api("/api/questions"); renderNav(); renderProfile("questions"); }
    else if (a === "save-plan") {
      const lines = (id) => $(id).value.split("\n").map((x) => x.trim()).filter(Boolean);
      await api("/api/profile/search_plan", { method: "PUT", body: { value: { role_families: lines("#sp-roles"), queries: lines("#sp-queries"), dream_companies: lines("#sp-cos"), notes: $("#sp-notes").value } } });
      toast("Saved", "Search plan updated, used on the next run"); }
    else if (a === "edit-area") openAreaEditor();
    else if (a === "crm-snooze") { await api("/api/crm/snooze", { method: "POST", body: { key: el.dataset.key, days: +el.dataset.days } }); el.closest(".crm-act").remove(); }
    else if (a === "crm-package") { await api(`/api/leads/${el.dataset.id}/package`, { method: "POST" }); toast("Building package", "It'll show up as ready in a few minutes."); el.disabled = true; el.textContent = "building…"; }
    else if (a === "crm-search") { S.q = el.dataset.q; S.leadsTab = "all"; localStorage.setItem("leadsTab", "all"); location.hash = "#/leads"; }
    else if (a === "tile-q") location.hash = "#/profile/questions";
    else if (a === "setup-step") renderSetup(el.dataset.step);
    // resume collection
    else if (a === "lib-open") location.hash = `#/resumes/${el.dataset.id}`;
    else if (a === "lib-use") { e.stopPropagation(); libUseModal(+el.dataset.id); }
    else if (a === "lib-dl") { e.stopPropagation(); openUrl(el.dataset.url); }
    else if (a === "lib-tag") { S.libTag = S.libTag === el.dataset.tag ? "" : el.dataset.tag; renderLibrary(); }
    else if (a === "lib-paste") libPasteModal();
    else if (a === "lib-dup") {
      const it = await api(`/api/library/${el.dataset.id}`);
      const c = await api("/api/library", { method: "POST", body: { name: `${it.name} (copy)`, md: $("#ed")?.value || it.md, style: it.style, tags: it.tags, notes: it.notes, source: it.source } });
      toast("Duplicated", c.name); location.hash = `#/resumes/${c.id}`;
    }
    else if (a === "lib-del") {
      if (!confirm("Delete this resume from your collection?")) return;
      await api(`/api/library/${el.dataset.id}`, { method: "DELETE" }); S.dirty = false; toast("Deleted"); location.hash = "#/resumes";
    }
    else if (a === "lead-lib-save") {
      const name = prompt("Name this resume in your collection:", `${S.lead.company}: ${S.lead.title}`.slice(0, 90)); if (name === null) return;
      const it = await api("/api/library", { method: "POST", body: { lead_id: S.lead.id, name, md: $("#ed")?.value || S.lead.resume_md, style: S.lead.package?.resume_style } });
      toast("Saved to your collection", it.name);
    }
    else if (a === "lead-lib-use") leadPickSavedModal(S.lead);
    else if (a === "lead-gapq") { el.disabled = true; el.innerHTML = `<span class="spin"></span> Thinking…`; try { const r = await api(`/api/leads/${S.lead.id}/questions/generate`, { method: "POST" }); toast("Questions added", `${r.added} question(s) for this application`); } catch (err) { toast("Couldn't generate questions", err.message, "error"); } S.questions = await api("/api/questions"); renderNav(); renderLead(S.lead.id); }
    else if (a === "lead-answer") { const inp = el.parentElement.querySelector("[data-lqa]"); if (!inp.value.trim()) return; await api("/api/questions/answer", { method: "POST", body: { question: inp.dataset.lqa, answer: inp.value.trim() } }); toast("Answer saved", "Saved to your profile."); S.questions = await api("/api/questions"); renderNav(); renderLead(S.lead.id); }
    else if (a === "lead-dismiss") { await api("/api/questions/dismiss", { method: "POST", body: { question: el.dataset.q } }); S.questions = await api("/api/questions"); renderNav(); renderLead(S.lead.id); }
    else if (a === "lead-apply") { await api(`/api/leads/${S.lead.id}/apply-answers`, { method: "POST" }); el.disabled = true; el.innerHTML = `<span class="spin"></span> Adding your answers and reworking the resume`; toast("Updating resume", "Adding your answers to your profile, then rewriting this resume with them (a minute or two)."); }
    else if (a === "add-skill") { readSkills(); S.skInv.push({ skill: "", category: "Languages", level: "working", evidence: [] }); S.skDraw(); }
    else if (a === "rm-skill") { readSkills(); S.skInv.splice(+el.dataset.i, 1); S.skDraw(); }
    else if (a === "save-skills") { readSkills(); await api("/api/profile/skills_inventory", { method: "PUT", body: { value: S.skInv.filter((x) => x.skill.trim()) } }); toast("Saved", "Skills inventory updated"); }
    else if (a === "playbook-save") { const cfg = await api("/api/settings"); cfg.resume_playbook = $("#playbook").value; await api("/api/settings", { method: "PUT", body: cfg }); $("#pb-state").textContent = "saved (custom)"; }
    else if (a === "playbook-reset") { if (!confirm("Replace your playbook with the researched default?")) return; const cfg = await api("/api/settings"); cfg.resume_playbook = ""; await api("/api/settings", { method: "PUT", body: cfg }); const pb = await api("/api/resume-playbook"); $("#playbook").value = pb.text; $("#pb-state").textContent = "researched default"; }
    else if (a === "resume-recheck") { if (S.dirty && S.editorOpts) await S.editorOpts.save($("#ed").value); recheckResume(S.lead.id); }
    else if (a === "retriage") { await api("/api/leads/retriage", { method: "POST" }); toast("Re-evaluating", "Below-threshold and queued leads are being re-scored against your current profile."); }
    else if (a === "dream-add") {
      const kind = el.dataset.kind, inp = $(kind === "companies" ? "#dc-add" : "#dj-add");
      const add = inp.value.split(",").map((x) => x.trim()).filter(Boolean); if (!add.length) return;
      await saveDreams({ [kind]: [...S.dreams[kind], ...add.filter((x) => !S.dreams[kind].some((y) => y.toLowerCase() === x.toLowerCase()))] }, `Added ${add.join(", ")}`); }
    else if (a === "dream-rm") { const kind = el.dataset.kind, list = [...S.dreams[kind]]; const [gone] = list.splice(+el.dataset.i, 1); await saveDreams({ [kind]: list }, `Removed ${gone}`); }
    else if (a === "dream-exclude") await saveDreams({ excluded: [...S.dreams.excluded, el.dataset.name] }, `Removed ${el.dataset.name} from the profile-derived list`);
    else if (a === "dream-restore") await saveDreams({ excluded: S.dreams.excluded.filter((x) => x !== el.dataset.name) }, `Restored ${el.dataset.name}`);
    else if (a === "dream-recheck") { const r = await api("/api/dreams/recheck", { method: "POST" }); toast("Leads re-checked", `${r.changed} lead${r.changed === 1 ? "" : "s"} changed, ${r.flagged} flagged as dream`); refreshStats(); renderDreams(); }
    else if (a === "dream-view") { S.dreamOnly = true; S.leadsTab = "all"; localStorage.setItem("leadsTab", "all"); location.hash = "#/leads"; }
    else if (a === "dream-only") { S.dreamOnly = !S.dreamOnly; el.classList.toggle("primary", S.dreamOnly); el.classList.toggle("ghost", !S.dreamOnly); loadLeads(); }
    else if (a === "toggle-dream") { await api(`/api/leads/${S.lead.id}`, { method: "PATCH", body: { dream: S.lead.dream ? 0 : 1 } }); renderLead(S.lead.id); }
    else if (a === "retag-industries") { if (confirm("Re-tag the industry of every lead with AI (cheap model)?")) { await api("/api/leads/retag-industries", { method: "POST" }); toast("Re-tagging", "Industries update in a minute or two."); } }
    else if (a === "run-analysis") { await api("/api/analysis/run", { method: "POST" }); toast("Analyzing", "Scoring your fit across every work genre. About a minute."); renderAnalysis(); }
    else if (a === "radar-toggle") { const k = el.dataset.k; radarOff.has(k) ? radarOff.delete(k) : radarOff.add(k); localStorage.setItem("radarOff", JSON.stringify([...radarOff])); renderAnalysis(); }
    else if (a === "genre-row") { const r = $(`#gd-${el.dataset.id}`); r.style.display = r.style.display === "none" ? "" : "none"; }
    else if (a === "plan-add") {
      const kind = el.dataset.kind, add = S.analysis.steer[kind === "queries" ? "add_queries" : "add_companies"] || [];
      const prof = await api("/api/profile"), plan = prof.search_plan || {};
      plan[kind] = [...new Set([...(plan[kind] || []), ...add])];
      await api("/api/profile/search_plan", { method: "PUT", body: { value: plan } }); toast("Search plan updated", `${add.length} added, used on the next run`); el.disabled = true; el.textContent = "Added"; }
    else if (a === "runlog") showRunLog(el.dataset.id, (await api("/api/runs")).find((r) => r.id === +el.dataset.id));
  } catch (err) { toast("Something went wrong", err.message, "error"); }
});
main.addEventListener("change", async (e) => {
  const el = e.target;
  if (el.id === "rs-theme") {
    const style = { ...(S.lead.package.resume_style || { max_pages: 1 }), theme: el.value };
    await api(`/api/leads/${S.lead.id}`, { method: "PATCH", body: { package: { resume_style: style } } });
    S.lead.package.resume_style = style;
    if (S.editorOpts) { S.editorOpts.theme = el.value; S.editorOpts.refresh(); }
    toast("Layout changed", `${el.value}: PDF and DOCX exports updated`); recheckResume(S.lead.id); return;
  }
  if (el.dataset.dbyp) { await saveDreams({ [el.dataset.dbyp]: el.checked }, el.checked ? "Location bypass on" : "Location bypass off"); return; }
  if (el.dataset.act === "cstatus") { await api(`/api/leads/${S.lead.id}/contacts/${el.dataset.i}`, { method: "POST", body: { status: el.value } }); toast("Updated", "Contact status saved"); }
  if (el.dataset.act === "cstatus2") { await api(`/api/leads/${el.dataset.lead}/contacts/${el.dataset.i}`, { method: "POST", body: { status: el.value } }); toast("Updated", "Contact status saved"); }
});
async function saveEmails() {
  if (!$(".email")) return;
  const emails = S.lead.package.emails.map((em, i) => { const card = $(`.email[data-i="${i}"]`); return { ...em, to_addr: $('[data-ef="to_addr"]', card).value, subject: $('[data-ef="subject"]', card).value, body: $('[data-ef="body"]', card).value }; });
  const body = { emails }; if ($("#lnote")) body.linkedin_note = $("#lnote").value;
  await api(`/api/leads/${S.lead.id}`, { method: "PATCH", body: { package: body } }); Object.assign(S.lead.package, body); S.dirty = false;
}
function readSkills() {
  $$("[data-sk]").forEach((el) => { const x = S.skInv[+el.dataset.sk]; if (!x) return; x[el.dataset.sf] = el.dataset.sf === "evidence" ? el.value.split(";").map((v) => v.trim()).filter(Boolean) : el.value; });
}
function renderSourcesKeep() { S.cfgDirty = true; renderSources(S.cfg); }
window.addEventListener("beforeunload", (e) => { if (S.dirty || S.cfgDirty) { e.preventDefault(); e.returnValue = ""; } });

// ================================================================ boot
(async function boot() {
  S.meta = await api("/api/meta");
  await refreshStats();
  S.state = S.stats.state;
  if (S.state.running) S.runStart = Date.now();
  renderAI(); renderAgents();
  try { S.pstatus = await api("/api/profile/status"); } catch (_) { S.pstatus = {}; }
  renderProfilePill();
  try { S.questions = await api("/api/questions"); } catch (_) {}
  try { const cfg = await api("/api/settings"); S.locAllowed = cfg.locations.allowed; S.industries = cfg.industries; } catch (_) {}
  try { // show the most recent run's log in the live feed after a reload
    const last = (await api("/api/runs"))[0];
    if (last) S.logs = (await api(`/api/runs/${last.id}/log`)).slice(-250);
  } catch (_) {}
  if (!/[?&]snapshot/.test(location.search)) connect(); // ?snapshot = no live stream (headless screenshots)
  route();
})();

// ================================================================ ANALYSIS
// Palette validated with the dataviz checker on the panel surface #111317 (dark, all-pairs): CVD ΔE ≥ 9.4, normal ΔE ≥ 20.9, contrast ≥ 3:1.
const VIZ = { fit: "#3987e5", demand: "#d95926", interest: "#199e70", prev: "#6b7280", surface: "#111317", grid: "#262b34" };
const RADAR_SERIES = [["demand", "Market demand"], ["interest", "Your interest"], ["prev", "Previous fit"], ["fit", "Your fit"]];
const MOVE_ICON = { project: '<i class=i-tool></i>', cert: '<i class=i-cert></i>', course: '<i class=i-book></i>', profile: '<i class=i-doc></i>', document: '<i class=i-doc></i>', search: '<i class=i-search></i>' };
let radarOff = new Set(JSON.parse(localStorage.getItem("radarOff") || "[]"));

function vizTip(html, e) {
  let t = $("#viz-tip");
  if (!t) { t = document.createElement("div"); t.id = "viz-tip"; t.className = "viz-tip"; document.body.appendChild(t); }
  if (!html) { t.style.display = "none"; return; }
  t.innerHTML = html; t.style.display = "block";
  const x = Math.min(e.clientX + 16, innerWidth - t.offsetWidth - 10), y = Math.min(e.clientY + 14, innerHeight - t.offsetHeight - 10);
  t.style.left = `${x}px`; t.style.top = `${y}px`;
}
const sw = (c) => `<i class="sw" style="background:${c}"></i>`;

function radarSVG(rows, present) {
  const W = 660, H = 540, cx = W / 2, cy = H / 2 + 6, R = 190, N = rows.length;
  const ang = (i) => -Math.PI / 2 + (i * 2 * Math.PI) / N;
  const pt = (i, v) => [cx + R * (v / 100) * Math.cos(ang(i)), cy + R * (v / 100) * Math.sin(ang(i))];
  let g = "";
  for (const lv of [25, 50, 75, 100]) {
    g += `<polygon points="${rows.map((_, i) => pt(i, lv).join(",")).join(" ")}" fill="none" stroke="${VIZ.grid}" stroke-width="1"/>`;
    g += `<text x="${cx + 4}" y="${cy - (R * lv) / 100 - 3}" class="rt">${lv}</text>`;
  }
  rows.forEach((r, i) => {
    const [x, y] = pt(i, 100);
    g += `<line x1="${cx}" y1="${cy}" x2="${x}" y2="${y}" stroke="${VIZ.grid}" stroke-width="1" class="spoke" data-i="${i}"/>`;
    const c = Math.cos(ang(i)), s = Math.sin(ang(i)), lx = cx + (R + 20) * c, ly = cy + (R + 20) * s;
    const anchor = c > 0.25 ? "start" : c < -0.25 ? "end" : "middle";
    const words = r.label.split(" "), lines = [];
    for (const w of words) { if (lines.length && (lines.at(-1) + " " + w).length <= 16) lines[lines.length - 1] += " " + w; else lines.push(w); }
    const dy0 = s < -0.5 ? -(lines.length - 1) * 14 : s > 0.5 ? 6 : -((lines.length - 1) * 14) / 2 + 4;
    g += `<text x="${lx}" y="${ly + dy0}" text-anchor="${anchor}" class="rl">${lines.map((l, k) => `<tspan x="${lx}" dy="${k ? 14 : 0}">${esc(l)}</tspan>`).join("")}</text>`;
  });
  for (const [key] of RADAR_SERIES) {
    if (!present.has(key) || radarOff.has(key)) continue;
    const col = VIZ[key], pts = rows.map((r, i) => pt(i, r[key] ?? 0));
    g += `<polygon points="${pts.map((p) => p.join(",")).join(" ")}" fill="${col}" fill-opacity="${key === "prev" ? 0 : 0.1}" stroke="${col}" stroke-width="2" stroke-linejoin="round"/>`;
    g += pts.map(([x, y]) => `<circle cx="${x}" cy="${y}" r="4" fill="${col}" stroke="${VIZ.surface}" stroke-width="2"/>`).join("");
  }
  // selective direct labels: each visible series' peak only
  const used = new Set();
  for (const [key, label] of RADAR_SERIES) {
    if (!present.has(key) || radarOff.has(key) || key === "prev") continue;
    let bi = 0; rows.forEach((r, i) => { if ((r[key] ?? -1) > (rows[bi][key] ?? -1)) bi = i; });
    if (used.has(bi)) continue; used.add(bi);
    // place the label just inside the vertex (toward the center) so it never collides with the axis labels at the rim
    const v = rows[bi][key] ?? 0, [x, y] = pt(bi, Math.max(0, v - 13)), c = Math.cos(ang(bi));
    g += `<text x="${x}" y="${y + 4}" text-anchor="${Math.abs(c) < 0.25 ? "middle" : c > 0 ? "end" : "start"}" class="dl">${esc(label.replace("Your ", "").replace("Market ", ""))} ${rows[bi][key]}</text>`;
  }
  // hit wedges (bigger than the marks) for the per-genre tooltip
  rows.forEach((_, i) => {
    const a0 = ang(i) - Math.PI / N, a1 = ang(i) + Math.PI / N, rr = R + 34;
    g += `<path class="hit" data-i="${i}" d="M${cx},${cy} L${cx + rr * Math.cos(a0)},${cy + rr * Math.sin(a0)} A${rr},${rr} 0 0 1 ${cx + rr * Math.cos(a1)},${cy + rr * Math.sin(a1)} Z" fill="transparent"/>`;
  });
  return `<svg viewBox="0 0 ${W} ${H}" class="radar" role="img" aria-label="Radar chart of fit, interest and market demand per work genre; the table below lists every value">${g}</svg>`;
}

async function renderAnalysis() {
  const d = await api("/api/analysis");
  const m = d.market, latest = d.latest, res = latest?.result || null;
  const ai = Object.fromEntries((res?.genres || []).map((g) => [g.id, g]));
  const prev = d.history.length >= 2 ? d.history[d.history.length - 2].fit : null;
  const rows = m.genres.map((g) => ({ ...g, fit: ai[g.id]?.fit ?? null, interest: ai[g.id]?.interest ?? null, demand: m.demand_total ? g.demand_index : null,
    prev: prev?.[g.id] ?? null, ai: ai[g.id] }));
  const present = new Set(["fit", "interest", "demand", "prev"].filter((k) => rows.some((r) => r[k] != null)));
  const payoff = (r) => ((r.demand ?? 50) / 100) * ((r.interest ?? 50) / 100) * (1 - (r.fit ?? 50) / 100);
  const sorted = [...rows].sort((a, b) => payoff(b) - payoff(a));
  const labelOf = Object.fromEntries(rows.map((r) => [r.id, r.label]));
  const legend = RADAR_SERIES.filter(([k]) => present.has(k)).map(([k, l]) => `<button class="lg ${radarOff.has(k) ? "off" : ""}" data-act="radar-toggle" data-k="${k}">${sw(VIZ[k])}${l}</button>`).join("");
  const maxGap = Math.max(1, ...m.gaps.map((x) => x.missing_in)), maxSrc = Math.max(1, ...m.sources.map((x) => x.qualified));
  const steer = res?.search_steering || {};
  main.innerHTML = `<div class="page">
    <div class="page-h"><h1>Analysis</h1><span class="sub">Where you fit, where the market is, and what to build next.</span><span class="spacer"></span>
      <span class="muted small mono">${latest ? `analyzed ${esc(fmtTs(latest.ts))}, ${fmtTokens(+latest.tokens || 0)} tokens` : "not analyzed yet"}</span>
      <button class="btn ${res ? "" : "primary"}" data-act="run-analysis" ${d.running ? "disabled" : ""}>${d.running ? `<span class="spin"></span> Analyzing` : res ? "<i class=i-refresh></i> Re-analyze" : "Run analysis"}</button></div>
    ${!res ? `<div class="banner accent"><div><b>Run the analysis</b> to score your fit and interest across ${rows.length} work genres against real market demand and get concrete moves. It re-runs automatically whenever your profile changes.</div></div>` : ""}
    <div class="cols" style="grid-template-columns:minmax(0,1.25fr) minmax(0,1fr)">
      <div class="card"><div class="row" style="margin-bottom:4px"><h3 style="margin:0">Work-genre radar</h3><span class="spacer"></span><div class="legend">${legend}</div></div>
        <div class="muted small">Fit and interest: AI assessment of your profile (0 to 100). Demand: share of postings that passed your filters, indexed so the busiest genre is 100 (${esc(m.demand_source)}).</div>
        <div id="radar">${radarSVG(rows, present)}</div></div>
      <div class="stack">
        <div class="card"><h3>The read</h3>${res ? `<p style="margin:0">${esc(res.summary)}</p>` : `<p class="muted" style="margin:0">No assessment yet.</p>`}</div>
        <div class="card"><h3>Top moves, ranked by payoff</h3>${(res?.top_priorities || []).map((t, i) => `<div style="padding:8px 0;border-bottom:1px solid var(--line)">
          <div class="row" style="gap:6px"><span class="mono muted">${i + 1}.</span><b>${esc(t.title)}</b></div>
          <div class="row" style="gap:5px;margin:4px 0"><span class="chip violet">${MOVE_ICON[t.type] || ""} ${esc(t.type)}</span><span class="chip">${esc(labelOf[t.genre] || t.genre)}</span></div>
          <div class="small">${esc(t.detail)}</div><div class="small muted" style="margin-top:3px">Why: ${esc(t.why)}</div></div>`).join("") || `<div class="muted small">Appears after the analysis runs.</div>`}</div></div></div>

    <div class="card" style="margin-top:14px"><h3>Every genre, sorted by payoff (high demand x high interest x room to grow)</h3>
      <table class="t gt"><thead><tr><th>Genre</th><th>${sw(VIZ.fit)}Fit</th><th>${sw(VIZ.interest)}Interest</th><th>${sw(VIZ.demand)}Demand</th><th>Qualified leads</th><th>Avg lead score</th><th>Δ fit</th><th>Skills your resumes lacked</th></tr></thead>
      <tbody>${sorted.map((r) => `<tr class="gr" data-act="genre-row" data-id="${r.id}" style="cursor:pointer"><td><b>${esc(r.label)}</b> <span class="muted small"><i class=i-chev></i></span></td>
        <td class="num">${r.fit ?? "-"}</td><td class="num">${r.interest ?? "-"}</td>
        <td class="num">${r.demand ?? "-"} <span class="muted small">(${(r.demand_share * 100).toFixed(1)}%)</span></td>
        <td class="num">${r.qualified}</td><td class="num">${r.avg_score ?? "-"}</td>
        <td class="num">${r.fit != null && r.prev != null ? `${r.fit - r.prev > 0 ? "<i class=i-up></i>" : r.fit - r.prev < 0 ? "<i class=i-down></i>" : ""} ${Math.abs(r.fit - r.prev)}` : "-"}</td>
        <td class="small">${esc(r.top_missing.join(", ")) || `<span class="muted">none</span>`}</td></tr>
        <tr class="gd" id="gd-${r.id}" style="display:none"><td colspan="8">${r.ai ? `<div class="grid3">
          <div><b class="small mono">EVIDENCE</b> <span class="chip">${esc(r.ai.confidence)} confidence</span><ul class="clean good small">${r.ai.evidence.map((x) => `<li>${esc(x)}</li>`).join("")}</ul></div>
          <div><b class="small mono">GAPS</b><ul class="clean warn small">${r.ai.gaps.map((x) => `<li>${esc(x)}</li>`).join("")}</ul></div>
          <div><b class="small mono">MOVES</b>${r.ai.moves.map((mv) => `<div class="small" style="margin:6px 0"><b>${MOVE_ICON[mv.type] || ""} ${esc(mv.title)}</b> <span class="muted">(${esc(mv.effort)}, ${esc(mv.impact)} impact)</span><div>${esc(mv.detail)}</div></div>`).join("")}</div></div>` : `<span class="muted small">Run the analysis for evidence, gaps and moves.</span>`}</td></tr>`).join("")}</tbody></table></div>

    <div class="cols" style="margin-top:14px">
      <div class="card"><h3>Skills employers asked for that your tailored resumes couldn't show</h3>
        <div class="muted small" style="margin-bottom:10px">Across ${m.packaged_leads} packaged lead${m.packaged_leads === 1 ? "" : "s"}. Build or document these and every future resume can claim them.</div>
        ${m.gaps.length ? `<div class="bars">${m.gaps.map((x) => `<div class="br" data-tip="${esc(`${x.skill}: missing in ${x.missing_in} of ${x.requested_in} postings that asked for it`)}">
          <span class="bl">${esc(x.skill)}</span><span class="bt"><i style="width:${(x.missing_in / maxGap) * 100}%;background:${VIZ.fit}"></i></span><span class="bv">${x.missing_in}/${x.requested_in}</span></div>`).join("")}</div>`
          : `<div class="empty" style="padding:24px"><b>No gaps measured yet</b>They appear as application packages are built.</div>`}</div>
      <div class="stack">
        <div class="card"><h3>Requested skills you already show</h3><div class="cov">${m.strengths.map((x) => `<span class="chip good" title="requested in ${x.requested_in}">${esc(x.skill)}</span>`).join("") || `<span class="muted small">Appears as packages are built.</span>`}</div></div>
        <div class="card"><h3>Steer the search</h3>${res ? `
          <div class="small"><b class="mono">EMPHASIZE</b> ${(steer.emphasize || []).map((g) => `<span class="chip blue">${esc(labelOf[g] || g)}</span>`).join(" ") || "none"}</div>
          <div class="small" style="margin-top:6px"><b class="mono">DE-EMPHASIZE</b> ${(steer.deemphasize || []).map((g) => `<span class="chip">${esc(labelOf[g] || g)}</span>`).join(" ") || "none"}</div>
          ${steer.notes ? `<p class="small" style="margin:8px 0 0">${esc(steer.notes)}</p>` : ""}
          ${(steer.add_queries || []).length ? `<div style="margin-top:10px"><b class="small mono">QUERIES TO ADD</b><div class="cov" style="margin:6px 0">${steer.add_queries.map((q) => `<span class="chip">${esc(q)}</span>`).join("")}</div><button class="btn sm" data-act="plan-add" data-kind="queries">+ Add to search plan</button></div>` : ""}
          ${(steer.add_companies || []).length ? `<div style="margin-top:10px"><b class="small mono">COMPANIES TO ADD</b><div class="cov" style="margin:6px 0">${steer.add_companies.map((q) => `<span class="chip">${esc(q)}</span>`).join("")}</div><button class="btn sm" data-act="plan-add" data-kind="dream_companies">+ Add to target companies</button></div>` : ""}` : `<span class="muted small">Appears after the analysis runs.</span>`}</div>
        <div class="card"><h3>Add these to your profile</h3>${(res?.profile_suggestions || []).map((x) => `<div style="padding:6px 0;border-bottom:1px solid var(--line)"><b class="small"><i class=i-doc></i> ${esc(x.title)}</b><div class="small muted">${esc(x.detail)}</div></div>`).join("") || `<span class="muted small">Appears after the analysis runs.</span>`}
          <div class="row" style="margin-top:10px"><a class="btn sm" href="#/profile/questions">Tell JobPortal about it</a><a class="btn sm ghost" href="#/profile/questions">Answer open questions →</a></div></div></div></div>

    <div class="card" style="margin-top:14px"><h3>Pipeline</h3><div class="funnel">${m.funnel.map((f, i) => `<div class="fs"><div class="n">${f.n.toLocaleString()}</div><div class="l">${esc(f.stage)}</div>
      ${i ? `<div class="cv">${m.funnel[i - 1].n ? `${((f.n / m.funnel[i - 1].n) * 100).toFixed(f.n / m.funnel[i - 1].n < 0.1 ? 1 : 0)}%` : "-"} of previous</div>` : `<div class="cv">&nbsp;</div>`}</div>`).join(`<div class="fa">→</div>`)}</div></div>

    <div class="card" style="margin-top:14px"><h3>Qualified leads by industry</h3>
      ${(m.industries || []).length ? `<div class="bars">${m.industries.map((x) => `<div class="br" data-tip="${esc(`${x.industry}: ${x.qualified} qualified of ${x.triaged} triaged, avg score ${x.avg_score ?? "-"}`)}">
        <span class="bl">${esc(x.industry)}</span><span class="bt"><i style="width:${(x.qualified / Math.max(1, ...m.industries.map((y) => y.qualified))) * 100}%;background:${VIZ.fit}"></i></span><span class="bv">${x.qualified} (avg ${x.avg_score ?? "-"})</span></div>`).join("")}</div>` : `<span class="muted small">Run a search first.</span>`}</div>
    <div class="card" style="margin-top:14px"><h3>Which sources produce qualified leads</h3>
      ${m.sources.length ? `<div class="bars">${m.sources.map((x) => `<div class="br" data-tip="${esc(`${LABEL_SRC[x.source] || x.source}: ${x.qualified} qualified of ${x.triaged} triaged, avg score ${x.avg_score ?? "-"}`)}">
        <span class="bl">${esc(LABEL_SRC[x.source] || x.source)}</span><span class="bt"><i style="width:${(x.qualified / maxSrc) * 100}%;background:${VIZ.fit}"></i></span><span class="bv">${x.qualified} (avg ${x.avg_score ?? "-"})</span></div>`).join("")}</div>` : `<span class="muted small">Run a search first.</span>`}</div>
  </div>`;
  const svg = $("#radar svg");
  svg.addEventListener("mousemove", (e) => {
    const hit = e.target.closest(".hit"); $$(".spoke", svg).forEach((s) => s.classList.remove("on"));
    if (!hit) return vizTip(null);
    const r = rows[+hit.dataset.i]; $(`.spoke[data-i="${hit.dataset.i}"]`, svg).classList.add("on");
    vizTip(`<b>${esc(r.label)}</b>${[["fit", "Your fit"], ["interest", "Your interest"], ["demand", "Market demand"], ["prev", "Previous fit"]].filter(([k]) => r[k] != null)
      .map(([k, l]) => `<div class="tr">${sw(VIZ[k])}<span>${l}</span><b>${r[k]}</b></div>`).join("")}<div class="muted" style="margin-top:4px">${r.qualified} qualified leads, ${(r.demand_share * 100).toFixed(1)}% of postings</div>`, e);
  });
  svg.addEventListener("mouseleave", () => { vizTip(null); $$(".spoke", svg).forEach((s) => s.classList.remove("on")); });
  $$(".br", main).forEach((b) => { b.addEventListener("mousemove", (e) => vizTip(esc(b.dataset.tip), e)); b.addEventListener("mouseleave", () => vizTip(null)); });
  S.analysis = { steer };
}

// ================================================================ SEARCH AREA (states, cities, remote, nationwide)
const US_STATES = [["AL","Alabama"],["AK","Alaska"],["AZ","Arizona"],["AR","Arkansas"],["CA","California"],["CO","Colorado"],["CT","Connecticut"],
  ["DE","Delaware"],["DC","Washington, DC"],["FL","Florida"],["GA","Georgia"],["HI","Hawaii"],["ID","Idaho"],["IL","Illinois"],["IN","Indiana"],
  ["IA","Iowa"],["KS","Kansas"],["KY","Kentucky"],["LA","Louisiana"],["ME","Maine"],["MD","Maryland"],["MA","Massachusetts"],["MI","Michigan"],
  ["MN","Minnesota"],["MS","Mississippi"],["MO","Missouri"],["MT","Montana"],["NE","Nebraska"],["NV","Nevada"],["NH","New Hampshire"],
  ["NJ","New Jersey"],["NM","New Mexico"],["NY","New York"],["NC","North Carolina"],["ND","North Dakota"],["OH","Ohio"],["OK","Oklahoma"],
  ["OR","Oregon"],["PA","Pennsylvania"],["RI","Rhode Island"],["SC","South Carolina"],["SD","South Dakota"],["TN","Tennessee"],["TX","Texas"],
  ["UT","Utah"],["VT","Vermont"],["VA","Virginia"],["WA","Washington"],["WV","West Virginia"],["WI","Wisconsin"],["WY","Wyoming"]];
const AREA_PRESETS = { "Northeast": ["ME", "NH", "VT", "MA", "RI", "CT", "NY", "NJ", "PA"], "Mid-Atlantic": ["NY", "NJ", "PA", "DE", "MD", "DC", "VA", "WV"],
  "Southeast": ["VA", "NC", "SC", "GA", "FL", "AL", "TN", "KY", "MS", "LA", "AR"], "Midwest": ["OH", "MI", "IN", "IL", "WI", "MN", "IA", "MO", "KS", "NE", "SD", "ND"],
  "Southwest": ["TX", "OK", "NM", "AZ", "NV", "UT", "CO"], "West Coast": ["CA", "OR", "WA", "AK", "HI"] };
// "My state" preset: the state from your standard answers, when it's a US state.
function homeStateAbbr() {
  const st = String((S.profileCache?.facts || {}).state || "").trim(), low = st.toLowerCase();
  const hit = US_STATES.find(([ab, n]) => ab.toLowerCase() === low || n.toLowerCase() === low);
  return hit ? hit[0] : "";
}
const NATIONWIDE_RE = /^(anywhere( in the)?( us| usa| united states)?|nationwide|united states|usa|us)$/i;

function parseArea(allowed) {
  const byName = Object.fromEntries(US_STATES.map(([ab, n]) => [n.toLowerCase(), ab]));
  const a = { states: new Set(), cities: [], remote: false, nationwide: false };
  for (const raw of allowed || []) {
    const x = String(raw).trim(), low = x.toLowerCase();
    if (NATIONWIDE_RE.test(low)) a.nationwide = true;
    else if (/remote/.test(low)) a.remote = true;
    else if (/^(dc|d\.c\.|washington,? d\.?c\.?|district of columbia)$/i.test(x)) a.states.add("DC");
    else if (byName[low]) a.states.add(byName[low]);
    else if (US_STATES.some(([ab]) => ab === x.toUpperCase()) && x.length === 2) a.states.add(x.toUpperCase());
    else if (x) a.cities.push(x);
  }
  return a;
}
function areaToAllowed(a) {
  const name = Object.fromEntries(US_STATES);
  return [...(a.nationwide ? ["Anywhere in the US"] : []), ...[...a.states].map((ab) => name[ab]), ...a.cities, ...(a.remote ? ["Remote"] : [])];
}
function areaSummary(allowed) {
  const a = parseArea(allowed);
  if (a.nationwide) return `Anywhere in the US${a.remote ? " + Remote" : ""}`;
  const parts = [...a.states].sort(), more = parts.length > 9 ? ` +${parts.length - 9}` : "";
  return [...parts.slice(0, 9), ...(more ? [more.trim()] : []), ...a.cities, ...(a.remote ? ["Remote"] : [])].join(", ") || "nowhere yet: pick an area";
}

async function openAreaEditor() {
  const cfg = await api("/api/settings"), L = cfg.locations;
  if (!S.profileCache) { try { S.profileCache = await api("/api/profile"); } catch (_) {} }
  const a = parseArea(L.allowed), home = homeStateAbbr();
  const draw = () => {
    modal(`<h2>Search area</h2><p class="muted small" style="margin-top:-6px">Where jobs can be. Everything outside this area is filtered out before AI triage, except dream companies when the bypass is on.</p>
      <div class="row" style="margin-bottom:10px">${home ? `<button class="btn sm" data-preset="__home">My state (${home})</button>` : ""}${Object.keys(AREA_PRESETS).map((p) => `<button class="btn sm" data-preset="${esc(p)}">${esc(p)}</button>`).join("")}
        <button class="btn sm" data-preset="__clear">Clear states</button></div>
      <div class="row" style="gap:18px;margin-bottom:12px">
        <label class="row small">${toggle(`id="ar-remote"`, a.remote)} Remote jobs (US)</label>
        <label class="row small">${toggle(`id="ar-nation"`, a.nationwide)} <b>Anywhere in the US</b> (ignores the state list)</label></div>
      <div class="stategrid ${a.nationwide ? "dim" : ""}">${US_STATES.map(([ab, n]) => `<label class="st ${a.states.has(ab) ? "on" : ""}" title="${esc(n)}"><input type="checkbox" data-st="${ab}" ${a.states.has(ab) ? "checked" : ""}><b>${ab}</b><span>${esc(n)}</span></label>`).join("")}</div>
      <div style="margin-top:14px"><label class="f"><span>Specific cities or metros (matched by name, e.g. “Houston, TX”, “Denver”, “Raleigh, NC”)</span></label>
        <div class="row" style="gap:6px;margin:6px 0">${a.cities.map((c, i) => `<span class="chip">${esc(c)}<span class="x" data-rmcity="${i}"><i class=i-x></i></span></span>`).join("") || `<span class="muted small">none</span>`}</div>
        <div class="row"><input type="text" id="ar-city" placeholder="Add a city" style="max-width:300px"><button class="btn sm" id="ar-addcity">Add city</button></div></div>
      <div class="hr"></div>
      <div class="row" style="gap:18px"><label class="row small">${toggle(`id="ar-dream"`, L.dream_bypass)} Dream companies can be anywhere in the US</label>
        <label class="row small">Unknown location: <select id="ar-unknown" style="width:auto"><option value="ai" ${L.unknown_policy === "ai" ? "selected" : ""}>let AI decide</option><option value="drop" ${L.unknown_policy === "drop" ? "selected" : ""}>drop</option></select></label></div>
      <div class="row" style="justify-content:space-between;margin-top:16px"><span class="muted small" id="ar-sum"></span>
        <div class="row"><button class="btn ghost" onclick="closeModal()">Cancel</button><button class="btn primary" id="ar-save">Save search area</button></div></div>`);
    $("#ar-sum").textContent = areaSummary(areaToAllowed(a));
    const m = $("#modal");
    m.onchange = (e) => {
      const t = e.target;
      if (t.dataset.st) { t.checked ? a.states.add(t.dataset.st) : a.states.delete(t.dataset.st); t.parentElement.classList.toggle("on", t.checked); }
      if (t.id === "ar-remote") a.remote = t.checked;
      if (t.id === "ar-nation") { a.nationwide = t.checked; $(".stategrid").classList.toggle("dim", t.checked); }
      $("#ar-sum").textContent = areaSummary(areaToAllowed(a));
    };
    m.onclick = async (e) => {
      const t = e.target;
      if (t.dataset.preset) { a.states = new Set(t.dataset.preset === "__clear" ? [] : t.dataset.preset === "__home" ? [home] : AREA_PRESETS[t.dataset.preset]); a.nationwide = false; draw(); }
      if (t.dataset.rmcity != null) { a.cities.splice(+t.dataset.rmcity, 1); draw(); }
      if (t.id === "ar-addcity") { const v = $("#ar-city").value.trim(); if (v) { a.cities.push(v); draw(); } }
      if (t.id === "ar-save") {
        const fresh = await api("/api/settings");
        fresh.locations = { ...fresh.locations, allowed: areaToAllowed(a), dream_bypass: $("#ar-dream").checked, unknown_policy: $("#ar-unknown").value };
        if (!fresh.locations.allowed.length) { toast("Pick an area", "Choose at least one state, city, Remote or Anywhere.", "error"); return; }
        await api("/api/settings", { method: "PUT", body: fresh }); S.locAllowed = fresh.locations.allowed;
        closeModal(); toast("Search area saved", areaSummary(fresh.locations.allowed));
        if (S.route[0] === "leads") renderMission(); if (S.route[0] === "settings") renderSettings();
      }
    };
  };
  draw();
}


// ================================================================ DREAM LIST
async function renderDreams() {
  const d = (S.dreams = await api("/api/dreams"));
  const chip = (x, i, kind) => `<span class="chip">${esc(x)}<span class="x" data-act="dream-rm" data-kind="${kind}" data-i="${i}" title="Remove"><i class=i-x></i></span></span>`;
  main.innerHTML = `<div class="page"><div class="page-h"><h1>Dream list</h1><span class="sub">Leads that match get the dream flag (it never changes their score) and can skip your search-area limits.</span></div>
    <div class="card" style="margin-bottom:14px"><div class="row"><span class="mono" style="font-size:15px;font-weight:700">${d.flagged}</span><span class="muted">leads flagged as dream right now</span>
      <span class="spacer"></span><button class="btn" data-act="dream-view">View them</button><button class="btn primary" data-act="dream-recheck" title="Re-flag every lead against this list (stars you set by hand are kept)"><i class=i-refresh></i> Re-check all leads</button></div></div>
    <div class="cols" style="grid-template-columns:1fr 1fr">
      <div class="card"><h3>Dream companies</h3>
        <div class="row" style="gap:6px;margin-bottom:10px">${d.companies.map((x, i) => chip(x, i, "companies")).join("") || `<span class="muted small">none yet</span>`}</div>
        <div class="row"><input type="text" id="dc-add" placeholder="Add companies, comma-separated (e.g. Apple, Capital One, Mayo Clinic)" style="flex:1"><button class="btn" data-act="dream-add" data-kind="companies">Add</button></div>
        <div class="hr"></div>
        <b class="small mono">FROM YOUR PROFILE (derived from your resume and answers; removing one drops it for good)</b>
        <div class="row" style="gap:6px;margin:8px 0">${d.profile_companies.map((x) => `<span class="chip blue">${esc(x)}<span class="x" data-act="dream-exclude" data-name="${esc(x)}" title="Remove from dream list"><i class=i-x></i></span></span>`).join("") || `<span class="muted small">none</span>`}</div>
        ${d.excluded.length ? `<b class="small mono">REMOVED</b><div class="row" style="gap:6px;margin:8px 0">${d.excluded.map((x) => `<span class="chip">${esc(x)}<span class="x" data-act="dream-restore" data-name="${esc(x)}" title="Restore"><i class=i-undo></i></span></span>`).join("")}</div>` : ""}
        <div class="row" style="margin-top:10px">${toggle(`data-dbyp="bypass"`, d.bypass)}<span class="small">Dream companies can be anywhere in the US (ignore my search area)</span></div></div>
      <div class="card"><h3>Dream jobs (roles)</h3><p class="muted small" style="margin-top:-4px">Any lead whose title contains one of these phrases is a dream job, at any company.</p>
        <div class="row" style="gap:6px;margin-bottom:10px">${d.jobs.map((x, i) => chip(x, i, "jobs")).join("") || `<span class="muted small">none yet</span>`}</div>
        <div class="row"><input type="text" id="dj-add" placeholder="Add roles, comma-separated (e.g. iOS developer, data engineer, product designer)" style="flex:1"><button class="btn" data-act="dream-add" data-kind="jobs">Add</button></div>
        <div class="row" style="margin-top:14px">${toggle(`data-dbyp="jobs_bypass"`, d.jobs_bypass)}<span class="small">Dream jobs can be anywhere in the US too</span></div></div></div></div>`;
  $$("#dc-add, #dj-add").forEach((inp) => inp.addEventListener("keydown", (e) => { if (e.key === "Enter") inp.nextElementSibling.click(); }));
}
async function saveDreams(patch, msg) {
  S.dreams = await api("/api/dreams", { method: "PUT", body: patch });
  toast("Dream list saved", msg || "Click Re-check all leads to apply it to leads you already have.");
  renderDreams();
}

// ================================================================ EQUITY MINING (CRM)
const KIND_CHIP = { "Closing soon": "bad", "Follow up": "warn", "Re-engage": "info", "Multi-opening account": "info", "Ready to apply": "act",
  "Build package": "ai", "Strengthen": "warn", "Reach out": "info", "Stale application": "", "Near miss": "" };
async function renderCRM() {
  const d = await api("/api/crm"), k = d.kpis;
  const maxEq = Math.max(1, ...d.accounts.map((a) => a.equity));
  const kinds = [...new Set(d.actions.map((a) => a.kind))];
  S.crmKind = S.crmKind && kinds.includes(S.crmKind) ? S.crmKind : "";
  const acts = d.actions.filter((a) => !S.crmKind || a.kind === S.crmKind);
  main.innerHTML = `<div class="page"><div class="page-h"><h1>Equity mining</h1><span class="sub">Your leads are a book of business. Work the highest-value moves first.</span></div>
    <div class="tiles" style="grid-template-columns:repeat(6,minmax(0,1fr))">
      <div class="tile"><div class="n">${k.book}</div><div class="l">Active book</div></div>
      <div class="tile hot"><div class="n">${k.ready_unworked}</div><div class="l">Ready, not applied</div></div>
      <div class="tile"><div class="n">${k.pipeline_value.toLocaleString()}</div><div class="l">Pipeline value</div></div>
      <div class="tile"><div class="n">${k.applied_week}</div><div class="l">Applied (7 days)</div></div>
      <div class="tile ${k.followups_due ? "hot" : ""}"><div class="n">${k.followups_due}</div><div class="l">Follow-ups due</div></div>
      <div class="tile" data-act="tile-q" style="cursor:pointer"><div class="n">${k.open_questions}</div><div class="l">Open questions</div></div></div>
    <div class="cols" style="grid-template-columns:minmax(0,1.35fr) minmax(0,1fr)">
      <div class="card"><div class="row" style="margin-bottom:8px"><h3 style="margin:0">Work the book today (${acts.length})</h3><span class="spacer"></span>
        <select id="crm-kind" style="width:auto"><option value="">All moves</option>${kinds.map((x) => `<option ${x === S.crmKind ? "selected" : ""}>${esc(x)}</option>`).join("")}</select></div>
        <p class="muted small" style="margin-top:0">Ranked by value: fit x how close to applying x urgency. Done hides a move for 30 days, Snooze for 3.${d.snoozed ? ` ${d.snoozed} hidden.` : ""}</p>
        <div class="stack" style="gap:0">${acts.map((a) => `<div class="crm-act">
          <div class="row" style="gap:6px"><span class="chip ${KIND_CHIP[a.kind] || ""}">${esc(a.kind)}</span><b class="small" style="flex:1;min-width:0">${esc(a.text)}</b></div>
          <div class="small muted" style="margin:3px 0 6px">${esc(a.why)}</div>
          <div class="row" style="gap:6px">${a.cta.href ? `<a class="btn sm primary" href="${esc(a.cta.href)}">${esc(a.cta.label)}</a>` : a.cta.act ? `<button class="btn sm primary" data-act="${a.cta.act}" data-id="${a.lead_id}">${esc(a.cta.label)}</button>` : `<button class="btn sm primary" data-act="crm-search" data-q="${esc(a.cta.search)}">${esc(a.cta.label)}</button>`}
            <button class="btn sm ghost" data-act="crm-snooze" data-key="${esc(a.key)}" data-days="30"><i class=i-check></i> Done</button><button class="btn sm ghost" data-act="crm-snooze" data-key="${esc(a.key)}" data-days="3">Snooze 3d</button>
            <span class="spacer"></span><span class="mono small muted" title="priority">${a.priority}</span></div></div>`).join("") || `<div class="empty" style="padding:24px"><b>Book is worked</b>Nothing urgent. Run a search or answer questions to create new equity.</div>`}</div></div>
      <div class="card"><h3>Accounts (${d.accounts.length})</h3><p class="muted small" style="margin-top:0">Companies by equity: the value of their best open opportunities plus the contacts you have there.</p>
        <div class="stack" style="gap:0">${d.accounts.map((a) => `<div class="crm-acc"><div class="row" style="gap:6px"><b style="flex:1;min-width:0">${esc(a.company)}</b>${a.dream ? `<span class="chip accent"><i class=i-star></i></span>` : ""}
            <span class="mono small">${a.equity}</span></div>
          <div class="bt" style="height:6px;margin:4px 0"><i style="display:block;height:100%;width:${(a.equity / maxEq) * 100}%;background:${VIZ.fit};border-radius:0 4px 4px 0"></i></div>
          <div class="small muted">${a.open} open, ${a.in_flight} in flight, best fit ${a.best}, ${a.contacted}/${a.contacts} contacts reached${a.last_touch ? `, last touch ${esc(a.last_touch)}` : ""}</div>
          <div class="small" style="margin-top:4px">${a.leads.map((l) => `<a href="#/lead/${l.id}" title="${esc(l.stage)}, ${esc(l.status)}">${esc(l.title.slice(0, 46))}</a> <span class="muted">${l.score ?? "-"}</span>`).join("; ")}</div></div>`).join("") || `<div class="muted small">No active accounts yet.</div>`}</div></div></div></div>`;
  $("#crm-kind").onchange = (e) => { S.crmKind = e.target.value; renderCRM(); };
}


// ================================================================ FILE DROPS (resume collection and setup)
const JUNK = /^(\._|\.DS_Store$|Thumbs\.db$|desktop\.ini$)/;
async function walkEntries(entries) {
  const out = [];
  const walk = async (entry, prefix) => {
    if (entry.isFile) {
      const f = await new Promise((res, rej) => entry.file(res, rej));
      out.push({ file: f, path: prefix + f.name });
    } else if (entry.isDirectory) {
      const reader = entry.createReader();
      let batch;
      do {
        batch = await new Promise((res, rej) => reader.readEntries(res, rej));
        for (const child of batch) await walk(child, prefix + entry.name + "/");
      } while (batch.length);
    }
  };
  for (const en of entries) await walk(en, "");
  return out;
}
// ================================================================ RESUME COLLECTION
const RESUME_THEMES = ["classic", "modern", "compact", "academic"];
const LIB_EXT = /\.(pdf|docx|doc|odt|rtf|md|markdown|txt)$/i;
const libSource = (it) => it.source === "imported" ? "Imported" : it.lead_id ? `Saved from <a href="#/lead/${it.lead_id}">lead #${it.lead_id}</a>` : "Saved";
async function renderLibrary(id) {
  if (id) return renderLibraryItem(+id);
  const items = (S.library = await api("/api/library"));
  const tags = [...new Set(items.flatMap((x) => x.tags || []))].sort();
  if (S.libTag && !tags.includes(S.libTag)) S.libTag = "";
  const ql = (S.libQ || "").toLowerCase();
  const shown = items.filter((x) => (!S.libTag || (x.tags || []).includes(S.libTag)) &&
    (!ql || `${x.name} ${(x.tags || []).join(" ")} ${x.notes} ${x.preview}`.toLowerCase().includes(ql)));
  main.innerHTML = `<div class="page"><div class="page-h"><h1>Resume collection</h1><span class="sub">Import resumes or save ones you like from a lead, then reuse them on any job.
      Tailored resumes are still written fresh from your profile; nothing here is used as a template.</span></div>
    <div class="dropzone" id="lib-drop" style="margin-bottom:14px"><div class="dz-big">Drop resumes here</div>
      <div class="muted small">PDF, DOCX, DOC, ODT, RTF, Markdown or text. Folders work too. Each one becomes an editable copy, wording kept exactly.</div>
      <div class="row" style="justify-content:center;margin-top:10px;gap:8px">
        <label class="btn">Choose files<input type="file" id="lib-pick" multiple accept=".pdf,.docx,.doc,.odt,.rtf,.md,.markdown,.txt" hidden></label>
        <button class="btn" data-act="lib-paste">Paste text</button></div>
      <div class="small mono muted" id="lib-log" style="margin-top:8px">${esc(S.libLog || "")}</div></div>
    <div class="row" style="margin-bottom:12px;gap:8px"><input type="text" id="lib-q" placeholder="Search names, tags, notes" value="${esc(S.libQ || "")}" style="width:280px">
      ${tags.map((t) => `<button class="chip ${t === S.libTag ? "accent" : ""}" data-act="lib-tag" data-tag="${esc(t)}">${esc(t)}</button>`).join("")}
      <span class="spacer"></span><span class="muted small">${shown.length} of ${items.length}</span></div>
    ${items.length ? `<div class="libgrid">${shown.map((it) => `<div class="libcard" data-act="lib-open" data-id="${it.id}">
        <div class="thumb"><iframe loading="lazy" src="/api/library/${it.id}/html?v=${encodeURIComponent(it.updated_at)}" sandbox tabindex="-1" title="${esc(it.name)}"></iframe></div>
        <div class="lib-body"><b class="lib-name">${esc(it.name)}</b>
          <div class="small muted">${libSource(it)}, ${esc(it.style?.theme || "classic")}, ${ago(it.updated_at)}</div>
          ${(it.tags || []).length ? `<div class="row" style="gap:4px;margin-top:6px">${it.tags.map((t) => `<span class="chip">${esc(t)}</span>`).join("")}</div>` : ""}
          <div class="row" style="gap:6px;margin-top:10px">
            <button class="btn sm primary" data-act="lib-use" data-id="${it.id}">Use on a lead</button>
            <button class="btn sm" data-act="lib-dl" data-url="/api/library/${it.id}/export/pdf">${I.dl} PDF</button>
            <button class="btn sm" data-act="lib-dl" data-url="/api/library/${it.id}/export/docx">${I.dl} DOCX</button></div></div></div>`).join("")}</div>`
      : `<div class="empty"><b>No saved resumes yet</b>Drop a resume above, or open any lead's Resume tab and click “Save to collection”.</div>`}</div>`;
  const z = $("#lib-drop");
  const over = (on) => (e) => { e.preventDefault(); z.classList.toggle("over", on); };
  ["dragenter", "dragover"].forEach((ev) => z.addEventListener(ev, over(true)));
  ["dragleave", "dragend"].forEach((ev) => z.addEventListener(ev, over(false)));
  z.addEventListener("drop", async (e) => {
    e.preventDefault(); z.classList.remove("over");
    const entries = [...(e.dataTransfer.items || [])].map((i) => i.webkitGetAsEntry && i.webkitGetAsEntry()).filter(Boolean);
    importResumes((entries.length ? await walkEntries(entries) : [...e.dataTransfer.files].map((f) => ({ file: f, path: f.name }))).map((x) => x.file));
  });
  $("#lib-pick").onchange = (e) => importResumes([...e.target.files]);
  $("#lib-q").addEventListener("input", debounce((e) => { S.libQ = e.target.value; renderLibrary().then(() => { const q = $("#lib-q"); q.focus(); q.setSelectionRange(q.value.length, q.value.length); }); }, 250));
}
async function importResumes(files, names = []) {
  files = files.filter((f) => !JUNK.test(f.name) && LIB_EXT.test(f.name));
  if (!files.length) { toast("Nothing to import", "Use PDF, DOCX, DOC, ODT, RTF, Markdown or text files.", "error"); return; }
  let ok = 0, last = null;
  for (const [i, f] of files.entries()) {
    S.libLog = `importing ${i + 1}/${files.length}: ${f.name} (reading and converting, usually under a minute)`;
    const log = $("#lib-log"); if (log) log.innerHTML = `<span class="spin"></span> ${esc(S.libLog)}`;
    try {
      const r = await fetch(`/api/library/import?filename=${encodeURIComponent(f.name)}&name=${encodeURIComponent(names[i] || "")}`, { method: "PUT", body: f });
      const j = await r.json();
      if (!r.ok) throw new Error(j.detail || r.statusText);
      ok++; last = j;
    } catch (err) { toast("Import failed", `${f.name}: ${err.message}`, "error"); }
  }
  S.libLog = `${ok} of ${files.length} imported`;
  if (ok) toast("Added to your collection", ok === 1 ? last.name : `${ok} resumes`);
  if (S.route[0] === "resumes" && !S.route[1]) renderLibrary();
  return last;
}
function libPasteModal() {
  modal(`<h2>Paste a resume</h2><p class="muted small">Paste the text of a resume. It's converted to the editable format with the wording kept exactly.</p>
    <input type="text" id="lp-name" placeholder="Name it (e.g. General, data roles)" style="width:100%;margin-bottom:8px">
    <textarea id="lp-text" rows="14" style="width:100%" placeholder="Paste here"></textarea>
    <div class="row" style="margin-top:12px;justify-content:flex-end;gap:8px"><button class="btn ghost" onclick="closeModal()">Cancel</button><button class="btn primary" id="lp-go">Import</button></div>`);
  $("#lp-go").onclick = async () => {
    const text = $("#lp-text").value.trim(), name = $("#lp-name").value.trim();
    if (text.length < 80) { toast("Too short", "Paste the whole resume.", "error"); return; }
    closeModal();
    const file = new File([text], `${(name || "Pasted resume").replace(/[\\/:*?"<>|]/g, "-")}.txt`, { type: "text/plain" });
    importResumes([file], [name]);
  };
}
async function renderLibraryItem(id) {
  let it;
  try { it = await api(`/api/library/${id}`); } catch (_) { main.innerHTML = `<div class="page"><div class="empty"><b>That resume is gone</b><a href="#/resumes">Back to the collection</a></div></div>`; return; }
  const style = { theme: "classic", max_pages: 1, ...(it.style || {}) };
  main.innerHTML = `<div class="page"><div class="page-h"><a href="#/resumes" class="btn ghost sm"><i class=i-back></i> Collection</a><h1 style="min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${esc(it.name)}</h1>
      <span class="sub">${libSource(it)}${it.original_file ? `, from ${esc(it.original_file)}` : ""}, created ${esc((it.created_at || "").slice(0, 10))}</span></div>
    <div class="card" style="margin-bottom:14px"><div class="row" style="gap:10px;align-items:flex-end">
      <label class="stack" style="gap:4px;flex:2;min-width:220px"><span class="small mono muted">NAME</span><input type="text" data-lib="name" value="${esc(it.name)}"></label>
      <label class="stack" style="gap:4px;flex:2;min-width:200px"><span class="small mono muted">TAGS (comma-separated)</span><input type="text" data-lib="tags" value="${esc((it.tags || []).join(", "))}" placeholder="e.g. software, finance, favorite"></label>
      <label class="stack" style="gap:4px"><span class="small mono muted">LAYOUT</span><select data-lib="theme" style="width:auto">${RESUME_THEMES.map((x) => `<option ${x === style.theme ? "selected" : ""}>${x}</option>`).join("")}</select></label>
      <label class="stack" style="gap:4px"><span class="small mono muted">PAGES</span><select data-lib="max_pages" style="width:auto">${[1, 2].map((x) => `<option value="${x}" ${x === +style.max_pages ? "selected" : ""}>${x}</option>`).join("")}</select></label>
      <span class="spacer"></span>
      <button class="btn primary" data-act="lib-use" data-id="${it.id}">Use on a lead</button>
      <button class="btn" data-act="lib-dup" data-id="${it.id}">Duplicate</button>
      <button class="btn ghost" data-act="lib-del" data-id="${it.id}">Delete</button></div>
      <label class="stack" style="gap:4px;margin-top:10px"><span class="small mono muted">NOTES</span><input type="text" data-lib="notes" value="${esc(it.notes || "")}" placeholder="When to use this one"></label>
      <div class="small mono muted" id="lib-meta-state" style="margin-top:6px"></div></div>
    <div id="lib-ed"></div></div>`;
  const metaState = $("#lib-meta-state");
  const o = {
    doc: "resume", text: it.md, theme: style.theme,
    files: ["resume.pdf", "resume.docx", "resume.md"], fileHref: (f) => `/api/library/${it.id}/export/${f.split(".").pop()}`,
    reviseUrl: `/api/library/${it.id}/revise`,
    save: async (v) => { await api(`/api/library/${it.id}`, { method: "PUT", body: { md: v } }); it.md = v; },
  };
  o.maxPages = style.max_pages;
  const saveMeta = debounce(async () => {
    const tags = $('[data-lib="tags"]').value.split(",").map((x) => x.trim()).filter(Boolean);
    style.theme = $('[data-lib="theme"]').value; style.max_pages = +$('[data-lib="max_pages"]').value;
    await api(`/api/library/${it.id}`, { method: "PUT", body: { name: $('[data-lib="name"]').value.trim() || it.name, tags, notes: $('[data-lib="notes"]').value, style } });
    metaState.textContent = "saved";
    if (o.theme !== style.theme) { o.theme = style.theme; o.refresh?.(); }
    if (o.maxPages !== style.max_pages) { o.maxPages = style.max_pages; renderLibraryItem(id); }
  }, 500);
  $$("[data-lib]").forEach((el) => el.addEventListener(el.tagName === "SELECT" ? "change" : "input", () => { metaState.textContent = "saving"; saveMeta(); }));
  mountEditor($("#lib-ed"), o);
}
async function libUseModal(itemId) {
  const it = await api(`/api/library/${itemId}`);
  modal(`<h2>Use “${esc(it.name)}” on a lead</h2>
    <input type="text" id="lu-q" placeholder="Search leads by company or title" style="width:100%;margin-bottom:8px">
    <div class="lu-list" id="lu-list"><div class="muted small">loading</div></div>
    <label class="row small" style="gap:8px;margin-top:10px">${toggle(`id="lu-backup"`, false)}Save the lead's current resume to the collection first</label>
    <p class="muted small" style="margin:8px 0 0">The lead's resume is replaced. “Revert to AI version” in its editor still brings back the generated one.</p>
    <div class="row" style="margin-top:12px;justify-content:flex-end;gap:8px"><button class="btn ghost" onclick="closeModal()">Cancel</button>
      <button class="btn" id="lu-asis" disabled>Use as-is</button><button class="btn primary ai" id="lu-tailor" disabled title="The AI re-angles it toward the job, then it gets the usual check and recruiter review"><i class=i-ai></i> Tailor to the job</button></div>`);
  let pick = null;
  const load = async (q) => {
    const d = await api(`/api/leads?tab=${q ? "all" : "ready"}&q=${encodeURIComponent(q || "")}&limit=60`);
    const rows = d.leads.filter((l) => l.app_status !== "trashed");
    $("#lu-list").innerHTML = rows.map((l) => `<label class="lu-row"><input type="radio" name="lu" value="${l.id}" ${pick === l.id ? "checked" : ""}>
        <span class="mono small" style="width:28px">${l.score ?? "-"}</span><span style="flex:1;min-width:0"><b>${esc(l.company)}</b>, ${esc(l.title)}</span>
        <span class="small muted">${l.has_resume ? "has a resume" : "no resume yet"}</span></label>`).join("") || `<div class="muted small">No matching leads${q ? "" : " in Ready. Search to find any lead"}.</div>`;
    $$('#lu-list input[name="lu"]').forEach((r) => (r.onchange = () => { pick = +r.value; $("#lu-asis").disabled = $("#lu-tailor").disabled = false; }));
  };
  $("#lu-q").addEventListener("input", debounce((e) => load(e.target.value.trim()), 250));
  const go = async (tailor, btn) => {
    if (!pick) return;
    btn.disabled = true; btn.innerHTML = `<span class="spin"></span> ${tailor ? "Tailoring" : "Applying"}`;
    try {
      const r = await api(`/api/library/${itemId}/apply/${pick}`, { method: "POST", body: { tailor, backup: $("#lu-backup").checked } });
      closeModal();
      toast(tailor ? "Tailored and applied" : "Resume applied", `Resume check ${r.check ?? "-"}${r.change_summary ? `. ${r.change_summary.slice(0, 140)}` : ""}`, "", pick);
      S.leadTab = "resume"; location.hash = `#/lead/${pick}/resume`;
    } catch (err) { toast("Couldn't apply it", err.message, "error"); btn.disabled = false; btn.innerHTML = tailor ? '<i class=i-ai></i> Tailor to the job' : "Use as-is"; }
  };
  $("#lu-asis").onclick = (e) => go(false, e.currentTarget);
  $("#lu-tailor").onclick = (e) => go(true, e.currentTarget);
  load("");
}
async function leadPickSavedModal(lead) {
  const items = await api("/api/library");
  if (!items.length) { toast("Your collection is empty", "Import resumes on the Resumes page, or save this one first."); return; }
  modal(`<h2>Use a saved resume for ${esc(lead.company)}</h2>
    <div class="lu-list">${items.map((it) => `<label class="lu-row"><input type="radio" name="lp" value="${it.id}"><span style="flex:1;min-width:0"><b>${esc(it.name)}</b>
      ${(it.tags || []).map((t) => `<span class="chip">${esc(t)}</span>`).join(" ")}</span><span class="small muted">${ago(it.updated_at)}</span></label>`).join("")}</div>
    ${lead.resume_md ? `<label class="row small" style="gap:8px;margin-top:10px">${toggle(`id="lp-backup"`, false)}Save this lead's current resume to the collection first</label>` : ""}
    <div class="row" style="margin-top:12px;justify-content:flex-end;gap:8px"><button class="btn ghost" onclick="closeModal()">Cancel</button>
      <button class="btn" id="lp-asis" disabled>Use as-is</button><button class="btn primary ai" id="lp-tailor" disabled><i class=i-ai></i> Tailor to this job</button></div>`);
  let pick = null;
  $$('input[name="lp"]').forEach((r) => (r.onchange = () => { pick = +r.value; $("#lp-asis").disabled = $("#lp-tailor").disabled = false; }));
  const go = async (tailor, btn) => {
    btn.disabled = true; btn.innerHTML = `<span class="spin"></span> ${tailor ? "Tailoring" : "Applying"}`;
    try {
      const r = await api(`/api/library/${pick}/apply/${lead.id}`, { method: "POST", body: { tailor, backup: !!$("#lp-backup")?.checked } });
      closeModal(); toast(tailor ? "Tailored and applied" : "Resume applied", `Resume check ${r.check ?? "-"}`);
      S.leadTab = "resume"; renderLead(lead.id);
    } catch (err) { toast("Couldn't apply it", err.message, "error"); btn.disabled = false; btn.innerHTML = tailor ? '<i class=i-ai></i> Tailor to this job' : "Use as-is"; }
  };
  $("#lp-asis").onclick = (e) => go(false, e.currentTarget);
  $("#lp-tailor").onclick = (e) => go(true, e.currentTarget);
}


// ================================================================ PROFILE OVERVIEW
async function renderProfileOverview(b) {
  const d = await api("/api/profile/overview"), id = d.identity, k = d.knows, o = d.produced, st = d.status || {};
  const initials = (id.name || "?").split(/\s+/).filter(Boolean).map((w) => w[0]).slice(0, 2).join("").toUpperCase() || "?";
  const stat = (n, l, href) => `<a class="tile" ${href ? `href="${href}"` : ""} style="text-decoration:none"><div class="n">${(n ?? 0).toLocaleString()}</div><div class="l">${l}</div></a>`;
  const state = st.busy ? `<span class="spin"></span> ${esc(st.phase || "Updating")}` : st.error ? `<i class=i-warn></i> Last update failed` : !st.built ? `<i class=i-dot></i> Not built yet`
    : st.unsynced ? `<i class=i-dot></i> ${st.unsynced} new answer${st.unsynced > 1 ? "s" : ""} to add` : "<i class=i-check></i> Up to date";
  if (!st.has_resume && !st.answers_saved) {
    b.innerHTML = `<div class="empty"><b>Your profile is empty</b>Import your resume and answer the standard job questions to build it.<div style="margin-top:12px"><a class="btn primary" href="#/setup">Set up</a></div></div>`;
    return;
  }
  b.innerHTML = `<div class="stack">
    <div class="card profile-hero"><div class="ph-id"><div class="monogram">${esc(initials)}</div>
        <div style="min-width:0"><h2>${esc(id.name || "Your profile")}</h2><div class="muted">${esc(id.headline || "")}${id.graduation ? `${id.headline ? ", " : ""}graduation ${esc(id.graduation)}` : ""}</div>
          <div class="row" style="gap:6px;margin-top:8px">${[id.location, id.authorization, id.clearance, id.gpa ? `GPA ${id.gpa}` : ""].filter(Boolean).map((x) => `<span class="chip">${esc(x)}</span>`).join("")}</div>
          ${id.target_roles.length ? `<div class="small" style="margin-top:8px"><span class="muted">Looking for:</span> ${id.target_roles.map(esc).join(", ")}${id.levels ? ` <span class="muted">(${esc(id.levels)})</span>` : ""} <a href="#/profile/answers">edit</a></div>` : ""}
          ${id.roles.length ? `<div class="small muted" style="margin-top:4px">Search plan covers ${id.roles.length} kinds of roles: ${id.roles.slice(0, 8).map(esc).join(", ")}${id.roles.length > 8 ? ", and more" : ""}. <a href="#/profile/search_plan">edit</a></div>` : ""}</div></div>
      <div class="ph-sync"><div class="mono" style="font-weight:700;color:${st.busy ? "var(--ai)" : st.error ? "var(--bad)" : !st.built || st.unsynced ? "var(--warn)" : "var(--good)"}">${state}</div>
        <div class="small muted" style="margin:4px 0 10px">last built ${esc(fmtTs(st.last_built))}</div>
        <div class="row" style="gap:6px;justify-content:flex-end">${st.unsynced ? `<button class="btn sm ai" data-act="sync-answers"><i class=i-ai></i> Add answers now</button>` : ""}
          <button class="btn sm" data-act="profile-build" ${st.busy || !st.has_resume ? "disabled" : ""}><i class=i-refresh></i> Rebuild</button></div></div></div>
    <div><h3 class="sect">What your profile knows</h3><div class="tiles" style="grid-template-columns:repeat(6,minmax(0,1fr))">
      ${stat(k.jobs, "Jobs", "#/profile/project_bank")}${stat(k.projects, "Projects", "#/profile/project_bank")}
      ${stat(k.skills_total, `Skills (${k.skills.strong || 0} strong)`, "#/profile/skills")}${stat(k.stories, "Interview stories", "#/profile/story_bank")}
      ${stat(k.answers, "Standard answers", "#/profile/answers")}${stat(k.answered_questions, "Questions answered", "#/profile/questions")}</div></div>
    <div><h3 class="sect">What it has made for you</h3><div class="tiles" style="grid-template-columns:repeat(6,minmax(0,1fr))">
      ${stat(o.leads_scored, "Jobs read and scored", "#/leads")}${stat(o.resumes, "Tailored resumes", "#/leads")}${stat(o.cover_letters, "Cover letters", "#/leads")}
      ${stat(o.emails, "Emails drafted", "#/leads")}${stat(o.contacts, "Contacts researched", "#/contacts")}${stat(o.answers + o.interview_preps + o.company_briefs, "Answers, preps and briefs", "#/leads")}</div></div>
    <div class="cols" style="grid-template-columns:minmax(0,1.2fr) minmax(0,1fr)">
      <div class="stack">
        <div class="card"><h3>Help it know you better</h3><div class="stack" style="gap:8px">
          <div class="row"><span style="flex:1">${k.open_questions ? `<b>${k.open_questions}</b> open question${k.open_questions > 1 ? "s" : ""} would strengthen your applications` : "No open questions right now"}</span><a class="btn sm" href="#/profile/questions">Answer</a></div>
          <div class="row"><span style="flex:1">Tell it about a project, skill or result that isn't on your resume</span><a class="btn sm" href="#/profile/questions">Add</a></div>
          <div class="row"><span style="flex:1">Import a newer resume when yours changes</span><a class="btn sm" href="#/profile/resume">Resume</a></div>
          <div class="row"><span style="flex:1">Change what you're looking for: roles, levels, locations</span><a class="btn sm" href="#/profile/answers">Answers</a></div></div></div>
        <div class="card"><h3>History</h3>${(d.changelog || []).map((c) => `<div style="padding:8px 0;border-bottom:1px solid var(--line)"><div class="row small"><span class="chip ${c.mode === "build" ? "violet" : "blue"}">${esc(c.mode)}</span><span class="mono muted">${esc(fmtTs(c.ts))}</span><span class="muted">${esc(c.reason || "")}</span><span class="spacer"></span>${c.tokens ? `<span class="muted mono">${fmtTokens(c.tokens)} tokens</span>` : ""}</div>
          <ul class="clean small" style="margin-top:6px">${(c.changes || []).slice(0, 6).map((x) => `<li>${esc(x)}</li>`).join("") || "<li class='muted'>no material changes</li>"}</ul></div>`).join("") || `<div class="muted small">Nothing yet.</div>`}</div></div>
      <div class="stack">
        <div class="card"><div class="row" style="margin-bottom:6px"><h3 style="margin:0">Voice</h3><span class="spacer"></span>
            ${d.voice_learned ? `<a class="btn sm ghost" href="#/profile/voice">Edit</a>` : ""}${d.has_sample ? `<button class="btn sm ${d.voice_learned ? "" : "primary"}" data-act="learn-voice">${d.voice_learned ? "<i class=i-refresh></i> Re-learn" : "<i class=i-ai></i> Learn my voice"}</button>` : ""}</div>
          ${d.voice_learned ? `<div class="md voice-md">${md(d.voice)}</div>` : `<p class="muted" style="margin:0">${d.has_sample ? "Click Learn my voice so cover letters and emails sound like you." : `Paste a writing sample (a past cover letter works well) in <a href="#/profile/answers">Standard answers</a> and cover letters, emails and answers will sound like you.`}</p>`}</div>
        <div class="card"><h3>Resume</h3>${d.resume ? `<div class="row"><i class=i-doc></i><b style="min-width:0;overflow-wrap:anywhere">${esc(d.resume.filename)}</b></div><div class="small muted" style="margin-top:4px">imported ${esc(fmtTs(d.resume.imported_at))}</div>` : `<span class="muted">none yet</span>`}
          <div class="row" style="margin-top:10px"><a class="btn sm" href="#/profile/resume">${d.resume ? "Replace or view" : "Import"}</a></div></div></div></div></div>`;
}

// ================================================================ SETUP (resume -> standard questions -> profile)
const SETUP_STEPS = [["chatgpt", "Continue with ChatGPT"], ["resume", "Import your resume"], ["answers", "Answer the standard questions"], ["build", "Build your profile"]];
function missingRequired(answers) {
  const req = (S.onb && S.onb.required) || [], labels = {};
  ((S.onb && S.onb.questions) || []).forEach((sec) => sec.fields.forEach((f) => (labels[f.id] = f.label)));
  return req.filter((k) => { const v = answers[k]; return Array.isArray(v) ? !v.length : !String(v ?? "").trim(); }).map((k) => labels[k] || k);
}
function resumeDropzone(accept, label) {
  return `<div class="dropzone" id="rz" style="margin-top:12px"><div class="dz-big"><i class=i-upload></i> ${esc(label)}</div>
    <div class="muted small">Drop a PDF, Word (DOCX), ODT, RTF, Markdown or text file here, or choose one. Scanned (image-only) PDFs can't be read.</div>
    <div class="row" style="justify-content:center;margin-top:10px;gap:8px"><label class="btn">Choose file<input type="file" id="rz-pick" accept="${esc(accept || "")}" hidden></label>
      <button class="btn ghost" data-rz="paste">Paste the text instead</button></div>
    <div id="rz-paste" style="display:none;margin-top:10px;text-align:left"><textarea id="rz-text" rows="10" style="width:100%" placeholder="Paste your whole resume here"></textarea>
      <div class="row" style="justify-content:flex-end;margin-top:8px"><button class="btn primary" data-rz="paste-go">Use this text</button></div></div>
    <label class="row small" style="justify-content:center;margin-top:10px;gap:8px">${toggle(`id="rz-lib"`, true)}Also keep an editable copy in my resume collection</label>
    <div class="small mono muted" id="rz-log" style="margin-top:8px"></div></div>`;
}
function wireResumeDropzone(root, onDone, opts = {}) {
  const z = $("#rz", root); if (!z) return;
  const log = (html) => ($("#rz-log", root).innerHTML = html);
  const send = async (fn) => {
    log(`<span class="spin"></span> Reading your resume. About 30 seconds.`);
    z.classList.add("busy");
    try { const r = await fn(); log(""); await onDone(r); }
    catch (err) { log(""); toast("Couldn't read that resume", err.message, "error"); }
    z.classList.remove("busy");
  };
  const lib = () => ($("#rz-lib", root).checked ? 1 : 0);
  const upload = (f) => send(async () => {
    const r = await fetch(`/api/onboarding/resume?filename=${encodeURIComponent(f.name)}&save_to_library=${lib()}&prefill=${opts.prefill === false ? 0 : 1}`, { method: "PUT", body: f });
    const j = await r.json(); if (!r.ok) throw new Error(j.detail || r.statusText); return j;
  });
  const over = (on) => (e) => { e.preventDefault(); z.classList.toggle("over", on); };
  ["dragenter", "dragover"].forEach((ev) => z.addEventListener(ev, over(true)));
  ["dragleave", "dragend"].forEach((ev) => z.addEventListener(ev, over(false)));
  z.addEventListener("drop", (e) => { e.preventDefault(); z.classList.remove("over"); const f = [...(e.dataTransfer.files || [])].find((x) => !JUNK.test(x.name)); if (f) upload(f); });
  $("#rz-pick", root).onchange = (e) => { const f = e.target.files[0]; if (f) upload(f); };
  z.addEventListener("click", (e) => {
    const t = e.target.closest("[data-rz]"); if (!t) return;
    if (t.dataset.rz === "paste") $("#rz-paste", root).style.display = "";
    if (t.dataset.rz === "paste-go") {
      const text = $("#rz-text", root).value.trim(); if (text.length < 80) { toast("That's too short", "Paste the whole resume.", "error"); return; }
      send(() => api("/api/onboarding/resume-text", { method: "POST", body: { text, save_to_library: !!lib(), prefill: opts.prefill !== false } }));
    }
  });
}

// One renderer for the standard questions, used by setup and by Profile, Standard answers.
function answersForm(sections, values, prefill) {
  const v = values || {}, pf = prefill || {};
  const fromResume = (id) => pf[id] != null && JSON.stringify(pf[id]) === JSON.stringify(v[id]) ? `<span class="chip violet pf" title="Filled in from your resume. Check it.">from resume</span>` : "";
  const field = (f) => {
    const val = v[f.id], req = f.required ? `<b class="req" title="required">*</b>` : "", help = f.help ? `<div class="small muted">${esc(f.help)}</div>` : "";
    const head = `<span>${esc(f.label)}${req}${fromResume(f.id)}</span>`;
    if (f.type === "select") return `<label class="f">${head}<select data-qf="${f.id}"><option value="">Choose one</option>${f.options.map(([k, l]) => `<option value="${esc(k)}" ${val === k ? "selected" : ""}>${esc(l)}</option>`).join("")}</select>${help}</label>`;
    if (f.type === "multi") return `<div class="f qmulti" style="grid-column:1/-1"><label class="f">${head}</label><div class="row" style="gap:6px;margin-top:4px">${f.options.map(([k, l]) => `<label class="chk ${(val || []).includes(k) ? "on" : ""}"><input type="checkbox" data-qm="${f.id}" value="${esc(k)}" ${(val || []).includes(k) ? "checked" : ""}>${esc(l)}</label>`).join("")}</div>${help}</div>`;
    if (f.type === "list") return `<label class="f">${head}<textarea data-ql="${f.id}" rows="4" placeholder="${esc(f.placeholder || "")}">${esc((val || []).join("\n"))}</textarea>${help}</label>`;
    if (f.type === "textarea") return `<label class="f" style="grid-column:1/-1">${head}<textarea data-qf="${f.id}" rows="${f.id === "writing_sample" ? 8 : 3}" placeholder="${esc(f.placeholder || "")}">${esc(val || "")}</textarea>${help}</label>`;
    return `<label class="f">${head}<input type="${f.type === "url" ? "url" : f.type === "email" ? "email" : f.type === "tel" ? "tel" : "text"}" data-qf="${f.id}" value="${esc(val || "")}" placeholder="${esc(f.placeholder || "")}">${help}</label>`;
  };
  return sections.map((sec) => `<div class="card qsec" style="margin-bottom:14px"><h3>${esc(sec.title)}</h3>${sec.help ? `<p class="muted small" style="margin-top:-4px">${esc(sec.help)}</p>` : ""}
    <div class="grid3">${sec.fields.map(field).join("")}</div></div>`).join("");
}
function readAnswersForm(root) {
  const out = {};
  $$("[data-qf]", root).forEach((el) => (out[el.dataset.qf] = el.value.trim()));
  $$("[data-ql]", root).forEach((el) => (out[el.dataset.ql] = el.value.split("\n").map((x) => x.trim()).filter(Boolean)));
  $$("[data-qm]", root).forEach((el) => { out[el.dataset.qm] = out[el.dataset.qm] || []; if (el.checked) out[el.dataset.qm].push(el.value); });
  return out;
}
document.addEventListener("change", (e) => { if (e.target.dataset && e.target.dataset.qm != null) e.target.closest(".chk")?.classList.toggle("on", e.target.checked); });

async function renderSetup(step) {
  const d = (S.onb = await api("/api/onboarding"));
  S.pstatus = d.status; renderProfilePill();
  if (step) S.setupStep = step;
  try { S.state.ai = await api("/api/ai/status"); renderAI(); } catch (_) {}
  if (!S.setupStep || !SETUP_STEPS.some(([k]) => k === S.setupStep)) S.setupStep = !aiReady() ? "chatgpt" : !d.resume ? "resume" : !d.answers_saved ? "answers" : "build";
  const cur = S.setupStep;
  const done = { chatgpt: aiReady(), resume: !!d.resume, answers: d.answers_saved, build: d.profile_built };
  main.innerHTML = `<div class="page setup"><div class="page-h"><h1>Set up JobPortal</h1><span class="sub">Four steps. Your data stays on this computer. Each AI task sends OpenAI only what it needs, through your ChatGPT sign-in.</span></div>
    <div class="stepper">${SETUP_STEPS.map(([k, l], i) => `<a class="step ${k === cur ? "on" : ""} ${done[k] ? "done" : ""}" data-step="${k}"><span class="num">${done[k] && k !== cur ? "<i class=i-check></i>" : i + 1}</span>${esc(l)}</a>`).join("")}</div>
    <div id="setup-body"></div></div>`;
  $$(".stepper .step").forEach((a) => (a.onclick = () => { if (["chatgpt", "resume"].includes(a.dataset.step) || d.resume) renderSetup(a.dataset.step); }));
  const body = $("#setup-body");
  if (cur === "chatgpt") {
    const a = S.state.ai || {};
    body.innerHTML = `<div class="card"><h3>Step 1: connect ChatGPT</h3>
      <p style="margin-top:0">JobPortal's AI runs on your own ChatGPT plan. Sign in once, and it reads your resume, scores jobs and writes your applications. It needs a ChatGPT Go, Plus or Pro plan.</p>
      <p class="muted small">ChatGPT shares only your name and email with JobPortal. Usage counts against your plan, and you can set a weekly cap for JobPortal in ChatGPT settings.</p>
      ${a.signed_in ? `<div class="banner"><div><i class=i-check></i> Signed in as <b>${esc(a.email || a.name || "your account")}</b>.</div><span class="spacer"></span><button class="btn primary sm" data-go="resume">Continue</button></div>`
        : `<button class="btn primary" data-act="ai-signin">Continue with ChatGPT</button>`}</div>`;
    body.querySelector("[data-go]")?.addEventListener("click", () => renderSetup("resume"));
  } else if (cur === "resume") {
    body.innerHTML = `<div class="card"><h3>Step 2: your resume</h3>
      <p style="margin-top:0">JobPortal reads your resume to learn your experience, projects and skills. It's a source of facts, not a template: every resume it makes for a job is written fresh.</p>
      ${d.resume ? `<div class="banner"><div><i class=i-doc></i> Using <b>${esc(d.resume.filename)}</b>, imported ${esc(fmtTs(d.resume.imported_at))}.</div><span class="spacer"></span><button class="btn primary sm" data-go="answers">Keep it and continue</button></div>` : ""}
      ${resumeDropzone(d.accept, d.resume ? "Or import a different resume" : "Drop your resume here")}</div>`;
    body.querySelector("[data-go]")?.addEventListener("click", () => renderSetup("answers"));
    wireResumeDropzone(body, async (r) => {
      S.prefill = r.prefill || {};
      toast("Resume read", r.prefill && r.prefill._error ? "Couldn't pre-fill the questions with AI, so fill them in yourself." : "The standard questions are pre-filled from it. Check them.");
      renderSetup("answers");
    });
  } else if (cur === "answers") {
    const pre = { ...(d.prefill || {}), ...(S.prefill || {}) };
    const vals = { ...d.answers };
    if (!d.answers_saved) for (const [k, v] of Object.entries(pre)) { if (k.startsWith("_")) continue; const have = vals[k]; if (have == null || (Array.isArray(have) ? !have.length : !String(have).trim())) vals[k] = v; }
    body.innerHTML = `<div class="card" style="margin-bottom:14px"><h3>Step 3: the standard questions</h3><p style="margin:0">These are the questions almost every application asks. Answer them once: JobPortal uses them to search (roles, levels, locations), to fill in every Application kit, and to keep your resumes truthful. Fields marked "from resume" were read from your resume, so check them.</p></div>
      <div id="qform">${answersForm(d.questions, vals, d.answers_saved ? {} : pre)}</div>
      <div class="sticky-save"><button class="btn ghost" data-go="resume">Back</button><span class="spacer"></span><span class="muted small" id="setup-state"></span><button class="btn primary" id="setup-save">Save and build my profile</button></div>`;
    body.querySelector("[data-go]").onclick = () => renderSetup("resume");
    $("#qform").addEventListener("input", () => (S.dirty = true));
    $("#setup-save").onclick = async (e) => {
      const answers = readAnswersForm($("#qform")), miss = missingRequired(answers);
      if (miss.length) { toast("A few answers are required", miss.join(", "), "error"); return; }
      e.currentTarget.disabled = true; $("#setup-state").innerHTML = `<span class="spin"></span> Saving`;
      try {
        const r = await api("/api/onboarding/answers", { method: "PUT", body: { answers, build: true } });
        S.dirty = false; S.pstatus = r.status; renderProfilePill(); renderSetup("build");
      } catch (err) { toast("Couldn't save your answers", err.message, "error"); e.currentTarget.disabled = false; $("#setup-state").textContent = ""; }
    };
  } else {
    body.innerHTML = `<div class="card" id="build-card"></div>`;
    setupStatusChanged();
  }
}
function setupStatusChanged() {
  const card = $("#build-card"); if (!card) return;
  const st = S.pstatus || {};
  if (st.busy || (!st.built && !st.error)) {
    card.innerHTML = `<h3>Step 4: building your profile</h3><div class="row" style="margin:10px 0"><span class="spin"></span><b>${esc(st.phase || "Starting")}</b></div>
      <p class="muted" style="margin:0">The AI is reading your resume and answers and writing your profile: your experience record, skills inventory, interview stories and search plan. This usually takes 1 to 4 minutes. You can leave this page; it keeps going.</p>`;
  } else if (st.error) {
    card.innerHTML = `<h3>Step 4: building your profile</h3><div class="banner bad"><div><b>The build failed:</b> ${esc(st.error)}</div></div>
      <p class="muted small">Check that you're signed in with ChatGPT on a Go, Plus or Pro plan, then try again.</p>
      <div class="row"><button class="btn primary" data-act="profile-build">Try again</button><button class="btn ghost" data-act="setup-step" data-step="answers">Back to the questions</button></div>`;
  } else {
    card.innerHTML = `<h3>Step 4: done</h3><div class="row" style="margin:6px 0 12px"><i class=i-check style="color:var(--good)"></i><b>Your profile is ready.</b></div>
      <p style="margin-top:0">Run your first search: JobPortal sweeps job boards, company career sites, social media and comment threads, scores every job against your profile, and writes a tailored application package for the best ones.</p>
      ${st.open_questions ? `<div class="banner accent"><div><b>${st.open_questions} question${st.open_questions > 1 ? "s" : ""}</b> would make your applications stronger. Answer them any time; your profile updates on its own.</div><span class="spacer"></span><a class="btn sm" href="#/profile/questions">Answer now</a></div>` : ""}
      <div class="row" style="margin-top:12px"><a class="btn primary" href="#/leads">Go to Leads and run a search</a><a class="btn" href="#/profile">Review my profile</a><a class="btn ghost" href="#/settings">Settings</a></div>`;
  }
}
