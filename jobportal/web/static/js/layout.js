/* layout.js: the frame around every page, and the router.
   - The sidebar: the menu with its badges (leads ready, follow-ups due), a card that says what's happening (a search,
     the AI agents at work) or the next useful step, Settings, and a line with your ChatGPT sign-in and the version.
   - The top bar: the search box (it searches your leads; "/" jumps to it), Run search or Stop, and your account button.
   - The hash router that picks the page (#/home, #/leads/12, #/settings/ai, ...) and sends old addresses where their
     content lives now.
   The frame is static HTML in index.html; these functions fill its parts.
   APIs: GET /api/stats, POST /api/run and /api/run/stop, POST /api/ai/signin and /api/ai/signout. */
"use strict";

// ---------------------------------------------------------------- the menu
// The pages in the menu: [route, label, icon]. Settings sits at the bottom of the sidebar.
const NAV = [["home", "Home", "home"], ["leads", "Leads", "briefcase"], ["tracker", "Tracker", "columns"], ["analysis", "Analysis", "chart"]];

// The menu with its badges: leads ready to apply, and follow-ups due on the Tracker.
function renderNav() {
  const stats = S.stats || {};
  const badges = { leads: stats.ready ? `${plural(stats.ready, "lead")} ready` : "",
    tracker: stats.followups_due ? `${plural(stats.followups_due, "follow-up")} due` : "" };
  const counts = { leads: stats.ready, tracker: stats.followups_due };
  const page = S.route[0];
  const item = (key, label, name) => {
    const on = page === key;
    const badge = badges[key] ? `<span class="nav-badge" title="${badges[key]}">${counts[key]}<span class="sr-only"> ${badges[key]}</span></span>` : "";
    return `<a class="nav-item${on ? " active" : ""}" href="#/${key}"${on ? ' aria-current="page"' : ""}>${icon(name)}${label}${badge}</a>`;
  };
  $("#navigation").innerHTML = NAV.map(([key, label, name]) => item(key, label, name)).join("");
  $("#nav-settings").outerHTML = item("settings", "Settings", "settings").replace("<a ", '<a id="nav-settings" ');
}

// ---------------------------------------------------------------- the sidebar card
// What a search is doing, in plain words (the server's phases are collecting, triaging and packaging).
const RUN_PHASES = { collecting: "Looking for jobs", triaging: "Scoring what it found", packaging: "Tailoring applications" };
const runPhase = (phase) => RUN_PHASES[phase] || humanize(phase || "Starting");

// A run's counts in words: "120 found, 40 new, 12 good fits". Each count shows once the run has it.
const RUN_COUNTS = [["found", "found"], ["candidates", "new"], ["triaged", "scored"], ["qualified", "good fits"], ["packaged", "ready"]];
const runCounts = (counts) => RUN_COUNTS.filter(([key]) => (counts || {})[key] != null).map(([key, label]) => `${counts[key]} ${label}`).join(", ");

// The card above Settings: a search running (its phase, its counts and the AI agents at work), else the next useful step.
function renderNextStep() {
  const el = $("#next-step");
  if (!el) return;  // the frame is gone after Quit
  const run = S.state || {}, profile = S.profileStatus || {};
  const agents = Object.values(run.active_agents || {});
  const waiting = homeWaiting();
  const go = (href, label) => `<a class="button mint" href="${href}">${label} ${icon("arrow")}</a>`;
  const act = (name, label) => `<button class="button mint" type="button" data-act="${name}">${label} ${icon("arrow")}</button>`;
  let card;  // [eyebrow, title, text, button]
  if (run.running) card = ["SEARCH RUNNING", runPhase(run.phase), runCounts(run.counts), go("#/leads", "Watch it live")];
  else if (agents.length) card = ["AI AT WORK", `${plural(agents.length, "agent")} working`, "", ""];
  else if (!aiReady()) card = ["START HERE", "Sign in with ChatGPT", "JobPortal's AI runs on your own ChatGPT plan.", act("ai-signin", "Continue with ChatGPT")];
  else if (!profile.has_resume) card = ["NEXT STEP", "Drop your resume", "Add it with any certificates, awards or transcripts.", go("#/home", "Add documents")];
  else if (profile.busy) card = ["BUILDING YOUR PROFILE", humanize(profile.phase || "Working"), "Usually 1 to 4 minutes.", ""];
  else if (profile.error) card = ["NEEDS A LOOK", "The profile build stopped", "Try it again from Home.", go("#/home", "See what happened")];
  else if (waiting) card = ["NEXT STEP", `Answer ${plural(waiting, "question")}`, "Each answer sharpens your matches.", go("#/home", "Answer now")];
  else if (profile.built) card = ["READY WHEN YOU ARE", "Run a search", "JobPortal looks everywhere and ranks what it finds.", act("run", "Run search")];
  else card = ["NEXT STEP", "Build your profile", "It's what every search and application is made from.", go("#/home", "Go to Home")];
  const [eyebrow, title, text, button] = card;
  const more = agents.length > 5 ? `<li>and ${agents.length - 5} more</li>` : "";
  const working = agents.length ? `<ul class="agent-list">${agents.slice(0, 5).map((label) => `<li><span class="pulse"></span>${esc(label)}</li>`).join("")}${more}</ul>` : "";
  el.innerHTML = `<span class="eyebrow">${eyebrow}</span><h3>${esc(title)}</h3>${text ? `<p>${esc(text)}</p>` : ""}${working}${button}`;
}

// ---------------------------------------------------------------- ChatGPT
// True once you're signed in with ChatGPT. The AI features only work then.
const aiReady = () => !!(S.state.ai && S.state.ai.signed_in);

// Your name for the avatar: from your standard answers, else from your ChatGPT account.
const yourName = () => String(S.onboarding?.answers?.name || "").trim() || String(S.state.ai?.name || "").trim();

// The line at the bottom of the sidebar: the sign-in (with the AI tokens used this session) and the version.
function renderSidebarFoot() {
  const el = $("#sidebar-foot");
  if (!el) return;
  const tokens = +S.state.tokens || 0;
  const tip = tokens ? ` title="${fmtTokens(tokens)} AI tokens used this session"` : "";
  el.innerHTML = `<span class="status-dot${aiReady() ? "" : " off"}"></span><span${tip}>${aiReady() ? "ChatGPT connected" : "Not signed in"}</span>`
    + `<span>v${esc(S.meta?.version || "")}</span>`;
}

// The account button at the right of the top bar. It opens Settings.
function renderUserButton() {
  const el = $("#user-button");
  if (!el) return;
  const name = yourName();
  el.innerHTML = `<span class="avatar">${esc(initials(name)) || icon("user")}</span>`
    + `<span class="user-name"><strong>${esc(name || "Your account")}</strong><small>${aiReady() ? "ChatGPT connected" : "Not signed in"}</small></span>${icon("chevron")}`;
  el.setAttribute("aria-label", `${name || "Your account"}, settings`);
}

// Handles an "ai" event (the sign-in changed): redraw the frame, say hello after signing in, and swap Home's welcome for
// the dashboard (or back).
function onAIStatus(data) {
  const wasReady = aiReady();
  S.state.ai = data;
  renderFrame();
  if (wasReady === aiReady()) return;
  if (aiReady()) toast("Signed in with ChatGPT", data.email || data.name || "JobPortal can use your plan now.");
  if (S.route[0] === "home") renderHome();
  if (S.route[0] === "settings" && S.route[1] === "ai" && !S.cfgDirty) renderSettings("ai");
}

// Starts Sign in with ChatGPT. It happens in the system browser: POST /api/ai/signin returns OpenAI's sign-in page, OpenAI
// sends the browser back to this app's server when you're done, and the server publishes an "ai" event.
async function aiSignIn() {
  // In a normal tab, open the new tab now, during the click, so popup blockers allow it. Its address comes later.
  const tab = ownWindow() ? null : window.open("", "_blank");
  try {
    const r = await api("/api/ai/signin", { method: "POST" });
    if (ownWindow()) await openUrl(r.url);
    else if (tab) tab.location = r.url;
    else location.href = r.url;
    toast("Finish signing in", "Sign in with ChatGPT in your browser. JobPortal updates when you're done.");
  } catch (e) {
    if (tab) tab.close();
    toast("Couldn't start sign-in", e.message, "error");
  }
}

// ---------------------------------------------------------------- the profile and the counts
// Handles a "profile_status" event: a build starting, moving on, failing or finishing.
function onProfileStatus(data) {
  const was = S.profileStatus || {};
  S.profileStatus = data;
  if (was.busy && !data.busy && data.built && !data.error) S.buildDone = true;  // Home says "Your profile is ready"
  renderNextStep();
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
const RUN_MODES = [["full", "Run everything"], ["boards", "Job boards only"], ["hunt", "AI hunt only"], ["backlog", "Only the waiting queue"]];

// Run search (with its menu), or Stop while a search runs.
function renderRunControl() {
  const el = $("#run-control");
  if (!el) return;
  if (S.state.running) {
    el.innerHTML = `<span class="run-status" title="${esc(runCounts(S.state.counts))}">${spinner()}<span>${esc(runPhase(S.state.phase))}</span></span>`
      + `<button class="button stop" type="button" data-act="stop">${icon("stop", "filled")}<span>Stop</span></button>`;
    return;
  }
  const modes = RUN_MODES.map(([mode, label]) => `<button type="button" role="menuitem" data-act="run" data-mode="${mode}">${label}</button>`).join("");
  el.innerHTML = `<div class="split menu-wrap"><button class="button primary" type="button" data-act="run">${icon("play", "filled")}<span>Run search</span></button>`
    + `<button class="button primary split-more" type="button" data-act="menu" aria-haspopup="menu" aria-expanded="false" aria-label="Other ways to run">${icon("chevron")}</button>`
    + `<div class="menu" role="menu" hidden>${modes}</div></div>`;
}

// Everything in the frame that shows the sign-in, the run or the counts.
function renderFrame() {
  renderNav();
  renderNextStep();
  renderSidebarFoot();
  renderUserButton();
  renderRunControl();
}

// The search box searches your leads: typing shows the Leads page filtered to what you typed.
$("#search-box").innerHTML = `${icon("search")}<input id="search" type="search" placeholder="Search your leads" aria-label="Search your leads" autocomplete="off"><kbd>/</kbd>`;
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
    history.replaceState(null, "", shownHash || "#/home");  // stay, with the address you were on
    return;
  }
  shownHash = location.hash;
  S.dirty = false;
  S.cfgDirty = false;
  const next = parts.length ? parts : ["home"];
  if (next[0] !== S.route[0]) {
    $$("dialog[open]").forEach((dialog) => dialog.close());
    window.scrollTo(0, 0);
  }
  S.route = next;
  renderNav();
  ROUTES[next[0]](...next.slice(1));
}
window.addEventListener("hashchange", route);

// ---------------------------------------------------------------- actions
onAction("ai-signin", () => aiSignIn());
onAction("ai-signout", async () => {
  const r = await api("/api/ai/signout", { method: "POST" });
  toast("Signed out of ChatGPT", r.note || "JobPortal no longer uses your plan.");
});
onAction("run", async (el) => {
  // In a browser tab, the first run with alerts on asks for permission to notify.
  if (S.notify && !desktop() && "Notification" in window && Notification.permission === "default") Notification.requestPermission();
  try {
    await api("/api/run", { method: "POST", body: { mode: el.dataset.mode || "full" } });
  } catch (err) {
    toast("Can't search yet", err.message, "error");
    return;
  }
  S.logs = [];
  S.buildDone = false;
  clearLog();
  toast("Searching", "New leads show up on Leads as they're ready.");
});
onAction("stop", async () => {
  await api("/api/run/stop", { method: "POST" });
  toast("Stopping", "Finishing up and saving what it found.");
});
