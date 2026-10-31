/* layout.js: the frame around every page. It draws the sidebar (the navigation with its badges, the profile status pill,
   the AI agents at work and the ChatGPT card) and runs the hash router that picks the page to show (#/leads, #/lead/12,
   #/profile/questions, ...). The sidebar is static HTML in index.html; these functions fill its parts. */
"use strict";

// ---------------------------------------------------------------- navigation
// The links on the left. Badges: leads ready to apply, follow-ups due and open questions. "Set up" shows until setup is
// done and ChatGPT is connected.
function renderNav() {
  const stats = S.stats || {};
  const openQuestions = (S.questions || []).filter((q) => q.status === "open").length;
  const items = [  // [route, label, badge]
    ...(onboarded() && aiReady() ? [] : [["setup", "Set up", "!"]]),
    ["leads", "Leads", stats.ready],
    ["crm", "Equity mining"],
    ["tracker", "Tracker", stats.followups_due],
    ["resumes", "Resumes"],
    ["analysis", "Analysis"],
    ["dreams", "Dream list"],
    ["contacts", "Contacts"],
    ["sources", "Sources"],
    ["profile", "Profile", openQuestions],
    ["settings", "Settings"],
    ["runs", "Runs"],
  ];
  const current = S.route[0] === "lead" ? "leads" : S.route[0];  // a lead's own page keeps Leads highlighted
  $("#nav").innerHTML = items.map(([key, label, badge]) => {
    const badgeHtml = badge ? `<span class="badge">${badge}</span>` : "";
    return `<a href="#/${key}" class="${current === key ? "on" : ""}">${I[key]}${label}${badgeHtml}</a>`;
  }).join("");
}

// ---------------------------------------------------------------- ChatGPT
// 950, 45k or 1.2M
const fmtTokens = (n) => (n >= 1e6 ? `${(n / 1e6).toFixed(1)}M` : n >= 1e4 ? `${Math.round(n / 1e3)}k` : (n || 0).toLocaleString());

// True once you're signed in with ChatGPT. The AI features only work then.
const aiReady = () => !!(S.state.ai && S.state.ai.signed_in);

// The ChatGPT card at the bottom of the sidebar: who is signed in and the tokens used this session, or a sign-in button.
function renderAI() {
  const el = $("#usage");
  if (!el) return;  // the sidebar is gone after Quit
  const ai = S.state.ai || {};
  if (ai.signed_in) {
    const tokens = fmtTokens(+S.state.tokens || 0);
    el.innerHTML = `<div>ChatGPT</div>`
      + `<div class="small" style="overflow:hidden;text-overflow:ellipsis" title="${esc(ai.email || "")}">${esc(ai.name || ai.email || "signed in")}</div>`
      + `<div class="small">${tokens} tokens this session</div>`;
  } else {
    el.innerHTML = `<div>ChatGPT</div><div class="small">not signed in</div>`
      + `<button class="btn sm primary" data-act="ai-signin" style="margin-top:6px">Continue with ChatGPT</button>`;
  }
}

// Handles an "ai" event (the sign-in status changed): redraw the card and the navigation, say hello after signing in, and
// move on from the ChatGPT step of setup.
function onAIStatus(data) {
  const wasReady = aiReady();
  S.state.ai = data;
  renderAI();
  renderNav();
  if (!wasReady && aiReady()) toast("Signed in with ChatGPT", data.email || data.name || "JobPortal can use your plan now.");
  if (S.route[0] === "setup" && S.setupStep === "chatgpt" && aiReady()) renderSetup("resume");
  if (S.route[0] === "settings" && !S.cfgDirty) renderSettings();
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

// The card's sign-in button is outside <main>, so it needs its own listener.
$("#usage").addEventListener("click", (e) => {
  if (e.target.closest("[data-act=ai-signin]")) aiSignIn();
});

// ---------------------------------------------------------------- profile status
// True once setup is done: a resume imported, the standard questions answered and the profile built.
const onboarded = () => {
  const st = S.profileStatus || {};
  return !!(st.has_resume && st.answers_saved && st.built);
};

// Handles a "profile_status" event: update the pill, show or hide "Set up", and refresh the pages that show progress.
function onProfileStatus(data) {
  const wasOnboarded = onboarded();
  S.profileStatus = data;
  renderProfilePill();
  if (wasOnboarded !== onboarded()) renderNav();
  if (S.route[0] === "setup") setupStatusChanged();
  if (S.route[0] === "profile" && S.profileTab === "overview" && !S.dirty) renderProfile("overview");
}

// The pill under the navigation. It says whether the profile is up to date, updating, failed, waiting for setup, or has
// answers waiting to be added, and links to the place that deals with it.
function renderProfilePill() {
  const el = $("#profile-pill");
  if (!el) return;  // the sidebar is gone after Quit
  const st = S.profileStatus || {};
  let cls = "ok";
  let html = `<i class=i-check></i> profile up to date`;
  let href = "#/profile";
  let tip = "Your profile has everything you've told JobPortal.";
  if (st.busy) {
    cls = "busy";
    html = `<span class="spin"></span> ${esc(st.phase || "updating your profile")}`;
    tip = "JobPortal is updating your profile.";
  } else if (st.error) {
    cls = "err";
    html = `<i class=i-warn></i> profile update failed`;
    tip = st.error;
  } else if (!onboarded()) {
    cls = "dirty";
    html = `<i class=i-dot></i> finish setting up`;
    href = "#/setup";
    tip = "Import your resume and answer the standard questions to start searching.";
  } else if (st.unsynced) {
    cls = "dirty";
    html = `<i class=i-dot></i> ${plural(st.unsynced, "answer")} to add`;
    href = "#/profile/questions";
    tip = "New answers are added to your profile automatically after a short pause.";
  }
  el.className = `status-pill ${cls}`;
  el.href = href;
  el.innerHTML = html;
  el.title = tip;
}

// ---------------------------------------------------------------- agents and counts
// The AI agents working right now, under the navigation (six at most).
function renderAgents() {
  const agents = Object.values(S.state.active_agents || {});
  if (!agents.length) {
    $("#agents").innerHTML = "";
    return;
  }
  $("#agents").innerHTML = `<div class="small" style="margin-bottom:4px">${plural(agents.length, "agent")} working</div>`
    + agents.slice(0, 6).map((label) => `<div class="a"><span class="dot"></span>${esc(label)}</div>`).join("");
}

// Fetches the counts behind the navigation badges and the Leads page tiles (GET /api/stats). A failure keeps the old
// numbers until the next refresh.
async function refreshStats() {
  try {
    S.stats = await api("/api/stats");
    renderNav();
    if (S.route[0] === "leads") renderTiles();
  } catch (_) {}
}

// ---------------------------------------------------------------- router
// The first part of the hash picks the page; the rest are its parameters (#/lead/12/emails opens lead 12 on its Emails
// tab). Every entry is an arrow function because the page files load after this one: their render functions don't exist
// yet when this object is built.
const ROUTES = {
  setup: () => renderSetup(),
  leads: () => renderLeads(),
  lead: (id, tab) => {
    if (tab) S.leadTab = tab;
    renderLead(+id);
  },
  tracker: () => renderTracker(),
  contacts: () => renderContacts(),
  resumes: (id) => renderLibrary(id),
  analysis: () => renderAnalysis(),
  dreams: () => renderDreams(),
  crm: () => renderCRM(),
  sources: () => renderSources(),
  profile: (tab) => renderProfile(tab),
  settings: () => renderSettings(),
  runs: (id) => renderRuns(id),
};

// Shows the page the hash names. An empty hash opens Leads once setup is done, and Set up before that.
function route() {
  const parts = location.hash.replace(/^#\/?/, "").split("/").filter(Boolean);
  S.route = parts.length ? parts : [onboarded() ? "leads" : "setup"];
  // Edits on the page you left are gone, so they no longer hold back live redraws or the leave warning.
  S.dirty = false;
  S.cfgDirty = false;
  renderNav();
  (ROUTES[S.route[0]] || ROUTES.leads)(...S.route.slice(1));
  main.scrollTop = 0;
}
window.addEventListener("hashchange", route);

// ---------------------------------------------------------------- actions
onAction("ai-signin", () => {
  aiSignIn();
});
onAction("ai-signout", async () => {
  const r = await api("/api/ai/signout", { method: "POST" });
  toast("Signed out of ChatGPT", r.note || "JobPortal no longer uses your plan.");
  if (S.route[0] === "settings") renderSettings();
});

// ---------------------------------------------------------------- theme
// Save only the display preference. Storage may be unavailable in some windows.
function setDisplayTheme(theme) {
  const selected = theme === "dark" ? "dark" : "light";
  document.documentElement.dataset.theme = selected;

  const button = $("#theme-toggle");
  if (button) {
    const dark = selected === "dark";
    button.textContent = dark ? "Switch to light theme" : "Switch to dark theme";
    button.setAttribute("aria-pressed", String(dark));
  }

  try {
    localStorage.setItem("jobportal-theme", selected);
  } catch (_) {}
}

onAction("theme-toggle", () => {
  const current = document.documentElement.dataset.theme;
  setDisplayTheme(current === "dark" ? "light" : "dark");
});

// The sidebar sits outside main, so its theme button needs a separate listener.
const displayThemeButton = $("#theme-toggle");
if (displayThemeButton) {
  displayThemeButton.addEventListener("click", () => {
    ACTIONS["theme-toggle"]();
  });
}

setDisplayTheme(document.documentElement.dataset.theme);
