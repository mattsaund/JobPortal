/* The frame around every page: the sidebar (navigation, profile status, running agents, the ChatGPT card) and the hash
   router that decides which page to show (#/leads, #/lead/12, #/profile/questions, ...). */
"use strict";

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
// The first part of the hash picks the page; the rest are its parameters (#/lead/12/emails opens lead 12 on its Emails tab).
// Every entry is an arrow function because the page files load after this one.
const ROUTES = {
  setup: () => renderSetup(),
  leads: (...args) => renderLeads(...args),
  lead: (id, tab) => { if (tab) S.leadTab = tab; renderLead(+id); },
  tracker: (...args) => renderTracker(...args),
  contacts: (...args) => renderContacts(...args),
  resumes: (id) => renderLibrary(id),
  analysis: () => renderAnalysis(),
  dreams: () => renderDreams(),
  crm: () => renderCRM(),
  sources: (...args) => renderSources(...args),
  profile: (...args) => renderProfile(...args),
  settings: (...args) => renderSettings(...args),
  runs: (...args) => renderRuns(...args),
};
function route() {
  const parts = location.hash.replace(/^#\/?/, "").split("/").filter(Boolean);
  S.route = parts.length ? parts : [onboarded() ? "leads" : "setup"];
  renderNav();
  (ROUTES[S.route[0]] || ROUTES.leads)(...S.route.slice(1));
  main.scrollTop = 0;
}
window.addEventListener("hashchange", route);

// ---------------------------------------------------------------- actions
onAction("ai-signin", async (el, e) => { aiSignIn(); });
onAction("ai-signout", async (el, e) => { await aiSignOut(); if (S.route[0] === "settings") renderSettings(); });
