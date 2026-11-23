/* layout.js: the frame around every page, and the router.
   - The sidebar: the menu with its badges (leads ready, follow-ups due), what's running right now, the AI in use (a click
     opens the Connect popup, components/connect.js) and your name.
   - The top bar: the page's name and tabs (pageHead), the search box (it searches your leads; "/" jumps to it), and Run
     or Stop.
   - The hash router that picks the page (#/home, #/leads/12, #/settings/ai, ...) and sends old addresses where their
     content lives now, and what a page shows when its data can't load (loadError, with Try again).
   The frame is static HTML in index.html; these functions fill its parts.
   APIs: GET /api/stats, POST /api/run and /api/run/stop. */
"use strict";

// Puts html into el only when it changed. Live events redraw the frame (and parts of pages) often during a search; this
// way what you're pointing at (a menu, a hovered button) stays as it is. When it does change, a focused button or link
// inside gets the focus back in the new HTML (focusKey in core.js). Only use it on an element nothing else writes into:
// it compares with the last HTML it put there, not with what's on screen.
function setHtml(el, html) {
  if (!el || el.shownHtml === html) return;
  const focus = focusKey(el);
  el.innerHTML = html;
  el.shownHtml = html;
  refocus(el, focus);
}

// ---------------------------------------------------------------- the menu
// The pages in the menu: [route, label, icon]. Settings sits at the bottom of the sidebar.
const NAV = [["home", "Home", "home"], ["leads", "Leads", "briefcase"], ["tracker", "Tracker", "columns"], ["analysis", "Analysis", "chart"],
  ["settings", "Settings", "settings"]];

// The menu with its badges: leads ready to apply, and follow-ups due on the Tracker.
function renderNav() {
  const stats = S.stats || {};
  const badges = { leads: stats.ready ? `${plural(stats.ready, "lead")} ready` : "",
    tracker: stats.followups_due ? `${plural(stats.followups_due, "follow-up")} due` : "" };
  const counts = { leads: stats.ready, tracker: stats.followups_due };
  const page = S.route[0];
  const inside = (key, label, name) => icon(name) + label
    + (badges[key] ? `<span class="nav-badge" title="${badges[key]}">${counts[key]}<span class="sr-only"> ${badges[key]}</span></span>` : "");
  setHtml($("#navigation"), NAV.map(([key, label, name]) => `<a class="nav-item${page === key ? " active" : ""}" href="#/${key}"`
    + `${page === key ? ' aria-current="page"' : ""}>${inside(key, label, name)}</a>`).join(""));
}

// ---------------------------------------------------------------- the page's name and tabs
// The left of the top bar. Every page calls this as it draws. tabs is HTML made with pageTab().
function pageHead(title, tabs = "") {
  $("#page-title").textContent = title;
  setHtml($("#page-tabs"), tabs);
}

// One tab in the top bar. attrs says what it does: an href, or data-act with its data. count is an optional number.
function pageTab(attrs, label, on, count) {
  const tag = attrs.includes("href=") ? "a" : "button";
  return `<${tag} class="page-tab${on ? " active" : ""}"${tag === "button" ? ' type="button"' : ""} ${attrs}${on ? ' aria-current="true"' : ""}>`
    + `${esc(label)}${count == null ? "" : `<span>${esc(count)}</span>`}</${tag}>`;
}

// ---------------------------------------------------------------- what's running
// What a search is doing (the server's phases are collecting, triaging and packaging).
const RUN_PHASES = { collecting: "Searching", triaging: "Scoring", packaging: "Tailoring" };
const runPhase = (phase) => RUN_PHASES[phase] || humanize(phase || "Starting");

// A run's counts in words: "120 found, 40 new, 12 good fits". Each count shows once the run has it.
const RUN_COUNTS = [["found", "found"], ["candidates", "new"], ["triaged", "scored"], ["qualified", "good fits"], ["packaged", "ready"]];
const runCounts = (counts) => RUN_COUNTS.filter(([key]) => (counts || {})[key] != null).map(([key, label]) => `${counts[key]} ${label}`).join(", ");

// The block above the AI in the sidebar: a search running, AI work, or a profile build. Empty when nothing is running.
function renderSideRun() {
  const el = $("#side-run");
  if (!el) return;  // the frame is gone after Quit
  const run = S.state || {}, profile = S.profileStatus || {}, agents = Object.values(run.active_agents || {});
  const line = (title, text) => `<b><span class="pulse"></span>${esc(title)}</b>${text ? `<small>${esc(text)}</small>` : ""}`;
  if (run.running) setHtml(el, line(runPhase(run.phase), runCounts(run.counts)));
  else if (profile.busy) setHtml(el, line("Building profile", ""));
  else if (agents.length) setHtml(el, line(plural(agents.length, "AI task"), agents[0]));
  else setHtml(el, "");
  renderAIButton();
}

// ---------------------------------------------------------------- the AI
// True once the AI in use is connected. The AI features only work then.
const aiReady = () => !!(S.state.ai && (S.state.ai.ready ?? S.state.ai.signed_in));
// The name of the AI in use, like "Gemini" or "Claude".
const aiName = () => S.state.ai?.provider_name || "AI";
const aiConnected = () => (aiReady() ? aiName() : "Not connected");

// Your name for the sidebar: from your standard answers, else from your AI account's sign-in.
const yourName = () => String(S.onboarding?.answers?.name || "").trim() || String(S.state.ai?.name || "").trim();

// The AI in the sidebar. A click opens the Connect popup.
function renderAIButton() {
  const el = $("#ai-button");
  if (!el) return;
  if (!aiReady()) {
    setHtml(el, `<button class="side-link connect" type="button" data-act="ai-connect" aria-label="Connect AI"><span>Connect AI</span></button>`);
    return;
  }
  const u = S.state.usage || {};
  const [dot, state] = u.capped ? [" warn", "Paused"] : +u.running ? ["", "Working"] : ["", ""];
  setHtml(el, `<button class="side-link" type="button" data-act="ai-connect" aria-label="${esc(aiName())}, change AI" title="${esc(aiName())}">`
    + `<span class="status-dot${dot}"></span><span>${esc(aiName())}</span>${state ? `<small>${state}</small>` : ""}</button>`);
}

// Your name at the bottom of the sidebar. It opens your profile.
function renderUserButton() {
  const el = $("#user-button");
  if (!el) return;
  const name = yourName();
  setHtml(el, `<span class="avatar">${esc(initials(name)) || icon("user")}</span><span>${esc(name || "Profile")}</span>`);
  el.setAttribute("aria-label", name ? `${name}, profile` : "Profile");
}

// Handles an "ai" event (the AI, its sign-in or its key changed): redraw the frame, say so once it's connected, and swap
// Home's welcome for the dashboard (or back).
function onAIStatus(data) {
  if (connectBusy) return;  // a key being checked isn't connected yet: the popup calls this once it passes
  const wasReady = aiReady(), wasProvider = S.state.ai?.provider;
  S.state.ai = data;
  renderFrame();
  connectStatusChanged(data);
  if (wasReady === aiReady() && wasProvider === data.provider) return;
  if (aiReady()) toast(`${aiName()} connected`);
  if (S.route[0] === "home") renderHome();
  if (S.route[0] === "settings" && S.route[1] === "ai" && !S.cfgDirty) renderSettings("ai");
}

// ---------------------------------------------------------------- the profile and the counts
// Handles a "profile_status" event: a build starting, moving on, failing or finishing.
function onProfileStatus(data) {
  const was = S.profileStatus || {};
  S.profileStatus = data;
  if (was.busy && !data.busy && data.built && !data.error) toast("Profile ready");
  renderSideRun();
  if (S.route[0] === "home") homeStatusChanged();
  if (S.route[0] === "settings" && S.route[1] === "profile") renderProfileStatusLine();
}

// Fetches the counts behind the menu badges and Home's stats (GET /api/stats). A failure keeps the old numbers.
async function refreshStats() {
  try {
    S.stats = await api("/api/stats");
  } catch (_) {
    return;
  }
  renderNav();
  if (S.route[0] === "home") renderHomeStats();
}

// ---------------------------------------------------------------- the top bar
// The ways to run a search. The button runs everything; its menu offers the rest.
const RUN_MODES = [["full", "Everything"], ["boards", "Job boards"], ["hunt", "AI hunt"], ["backlog", "Queue"]];

// Run search (with its menu), or Stop while a search runs. Starting or stopping swaps the buttons; when one of them had
// the focus, the button that replaces it gets it, so a keyboard user can stop the search they just started.
function renderRunControl() {
  const el = $("#run-control");
  if (!el) return;
  const hadFocus = el.contains(document.activeElement);
  if (S.state.running) {
    setHtml(el, `<span class="run-status">${spinner()}<span>${esc(runPhase(S.state.phase))}</span></span>`
      + `<button class="button stop" type="button" data-act="stop">${icon("stop", "filled")}<span>Stop</span></button>`);
  } else {
    const modes = RUN_MODES.map(([mode, label]) => `<button type="button" role="menuitem" data-act="run" data-mode="${mode}">${label}</button>`).join("");
    setHtml(el, `<div class="split menu-wrap"><button class="button primary" type="button" data-act="run">${icon("play", "filled")}<span>Run</span></button>`
      + `<button class="button primary split-more" type="button" data-act="menu" aria-haspopup="menu" aria-expanded="false" aria-label="Run options">${icon("chevron")}</button>`
      + `<div class="menu" role="menu" hidden>${modes}</div></div>`);
  }
  if (hadFocus && !el.contains(document.activeElement)) $("button", el)?.focus();
}

// Everything in the frame that shows the sign-in, the run or the counts.
function renderFrame() {
  renderNav();
  renderSideRun();
  renderUserButton();
  renderRunControl();
}

// The search box searches your leads: typing shows the Leads page filtered to what you typed.
$("#search-box").innerHTML = `${icon("search")}<input id="search" type="search" placeholder="Search leads" aria-label="Search leads" autocomplete="off">`;
const searchLeads = () => {
  S.q = $("#search").value.trim();
  if (S.route[0] === "leads") loadLeads();
  else location.hash = "#/leads";
};
$("#search").addEventListener("input", debounce(searchLeads, 250));
$("#search").addEventListener("keydown", (e) => {
  if (e.key === "Enter") searchLeads();
  if (e.key === "Escape" && e.target.value) {
    e.target.value = "";
    searchLeads();
  }
});
// "/" anywhere (outside a text box and a dialog) jumps to the search box.
document.addEventListener("keydown", (e) => {
  if (e.key !== "/" || e.ctrlKey || e.metaKey || e.altKey || $("dialog[open]")) return;
  if (e.target.closest("input, textarea, select, [contenteditable]")) return;
  e.preventDefault();
  $("#search").focus();
});

// ---------------------------------------------------------------- theme
// Switches between the light and dark theme and remembers it. The script at the top of index.html restores it on load.
function applyTheme(theme) {
  const chosen = theme === "dark" ? "dark" : "light";
  document.documentElement.dataset.theme = chosen;
  store.set("jobportal-theme", chosen);
}

// ---------------------------------------------------------------- router
// The first part of the hash picks the page; the rest are its parameters (#/leads/12/emails opens lead 12 on its Emails
// tab). Every entry is an arrow function because the page files load after this one.
const ROUTES = {
  home: () => renderHome(),
  leads: (id, tab) => renderLeads(id, tab),
  tracker: (view) => renderTracker(view),
  analysis: () => renderAnalysis(),
  settings: (tab, item) => renderSettings(tab, item),
};

// Where the addresses of pages that moved land now: Set up and Equity mining on Home, a lead on Leads, the Profile,
// Resumes, Runs and Dream list pages in Settings, Contacts on the Tracker, and Sources in a dialog on Leads.
function movedRoute([page, a, b]) {
  const under = (base, ...parts) => [base, ...parts.filter(Boolean)].join("/");
  switch (page) {
    case "lead": return under("#/leads", a, b);
    case "profile":
      if (a === "questions" || a === "resume") return "#/home";  // open questions and documents are on Home
      return a === "search_plan" ? "#/settings/search" : under("#/settings/profile", a);
    case "resumes": return under("#/settings/resumes", a);
    case "runs": return under("#/settings/history", a);
    case "dreams": return "#/settings/search";
    case "contacts": return "#/tracker/contacts";
    case "sources":
      S.openSources = true;  // Leads opens the Sources dialog once it's drawn
      return "#/leads";
    default: return "#/home";  // #/setup, #/crm and anything unknown
  }
}

// Shows the page the hash names. A new page closes any dialog and starts at the top; a new address on the same page
// (another lead, another Settings tab) updates it in place. Unsaved edits ask before they're dropped.
let shownHash = null;
function route() {
  const parts = location.hash.replace(/^#\/?/, "").split("/").filter(Boolean);
  if (parts.length && !ROUTES[parts[0]]) {
    location.replace(movedRoute(parts));  // replace: the old address doesn't stay in the history
    return;
  }
  if (shownHash !== null && location.hash !== shownHash && (S.dirty || S.cfgDirty) && !confirm("Discard your unsaved edits?")) {
    S.openSources = false;  // an old #/sources link stays where you are too: the dialog mustn't pop up on a later visit
    history.replaceState(null, "", shownHash || "#/home");  // stay, with the address you were on
    return;
  }
  shownHash = location.hash;
  S.dirty = false;
  S.cfgDirty = false;
  const next = parts.length ? parts : ["home"];
  if (next[0] !== S.route[0]) {
    $$("dialog[open]").forEach((dialog) => dialog.close());
    if (S.leadView) closeLeadDetails();  // the lead that was open went with the page
    main.scrollTo(0, 0);
    pageHead(NAV.find(([key]) => key === next[0])?.[1] || "");  // the page adds its tabs when it draws
  }
  S.route = next;
  renderNav();
  Promise.resolve(ROUTES[next[0]](...next.slice(1))).catch((err) => toast("Couldn't show this page", err.message, "error"));
}
window.addEventListener("hashchange", route);

// What a page shows where its content would be when loading it failed: what went wrong, and Try again, which draws the
// page again. Without it, a failed request leaves a page half-drawn (no list, or "Loading" for good) until you leave it.
const loadError = (err) => `<div class="empty"><h3>Couldn't load</h3><p>${esc(err?.message || "")}</p>`
  + `<button class="button outline" type="button" data-act="reload-page">${icon("refresh")}Retry</button></div>`;

// ---------------------------------------------------------------- actions
onAction("ai-connect", () => openConnect());
onAction("run", async (el) => {
  // In a browser tab, the first run with alerts on asks for permission to notify.
  if (S.alerts && !desktop() && "Notification" in window && Notification.permission === "default") Notification.requestPermission();
  try {
    await api("/api/run", { method: "POST", body: { mode: el.dataset.mode || "full" } });
  } catch (err) {
    toast("Can't search", err.message, "error");
    return;
  }
  S.logs = [];
  clearLog();
  toast("Search started");
});
onAction("stop", async () => {
  await api("/api/run/stop", { method: "POST" });
  toast("Stopping");
});
onAction("reload-page", () => {  // Try again under a loadError: the same address, drawn from scratch
  if ((S.dirty || S.cfgDirty) && !confirm("Discard your unsaved edits?")) return;
  main.dataset.page = "";
  route();
});
