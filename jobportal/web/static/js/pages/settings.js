/* settings.js: Settings (#/settings/<section>), a full-screen menu like a desktop app's preferences. The sections run down
   a column on the left and the open one fills the rest and scrolls on its own. One Save bar sits under it while it has
   unsaved changes (setSaver in components/settings-form.js).
   - Profile (profile.js): your standard answers, the parts of your profile, your writing voice, and its history.
   - Search, in tabs: Filters (the search area, levels and the rules every job passes), Plan, the Dream list (dreams.js),
     Industries, and Runs (how much each search does, and the schedule).
   - Resumes (resumes.js): your saved resumes, the recruiter review and the resume playbook.
   - AI: the AI in use and its numbers (the Connect popup in components/connect.js changes it), the model and effort for
     each task, how many run at once, and the prompts.
   - Appearance: light or dark, and desktop alerts (with a test alert).
   - History (runs.js): every search and its log.
   - Data: your data folder, putting settings back to their defaults, and Quit (in a browser tab, or while the schedule
     keeps JobPortal running in the background).
   APIs: GET /api/settings and PUT /api/settings (through S.cfg and saveCfg, see components/settings-form.js),
   GET /api/ai/status, GET /api/ai/providers, GET /api/ai/models, GET /api/prompts/defaults, GET /api/profile,
   PUT /api/profile/search_plan, PATCH /api/onboarding/answers (the experience levels), POST /api/settings/reset,
   POST /api/open-data-folder, POST /api/quit, POST /api/leads/retag-industries, GET /api/schedule and
   POST /api/alerts/test. */
"use strict";

// The sections: [key, label, icon, function that fills it]. The functions get the section's box and the rest of the
// address (#/settings/resumes/12 opens saved resume 12).
const SETTINGS_TABS = [
  ["profile", "Profile", "user", (box, item) => renderProfileSettings(box, item)],
  ["search", "Search", "search", (box, item) => renderSearchSettings(box, item)],
  ["resumes", "Resumes", "file", (box, item) => renderLibrary(box, item)],
  ["ai", "AI", "sparkle", (box) => renderAISettings(box)],
  ["appearance", "Appearance", "sun", (box) => renderAppearance(box)],
  ["history", "History", "clock", (box, item) => renderRuns(box, item)],
  ["data", "Data", "folder", (box) => renderDataSettings(box)],
];

// Draws the frame once, then the section the address names. Opening a section shows "Loading" until its data is in; the
// same section drawn again (another part of it, a live update) keeps what's on screen until the new content replaces
// it, so it doesn't flash or jump to the top. A section whose data didn't load says so, with Retry.
async function renderSettings(tab, item) {
  const current = SETTINGS_TABS.find(([key]) => key === tab);
  if (!current) {
    location.replace("#/settings/profile");
    return;
  }
  pageHead("Settings");
  if (main.dataset.page !== "settings") {
    main.dataset.page = "settings";
    main.innerHTML = `<div class="set"><nav class="set-nav" aria-label="Settings">${SETTINGS_TABS.map(([key, label, name]) =>
        `<a class="set-link" href="#/settings/${key}" data-tab="${key}">${icon(name)}<span>${label}</span></a>`).join("")}</nav>
      <div class="set-main"><div class="set-body" id="settings-body"></div>
        <div class="set-save" id="set-save" hidden><span>Unsaved changes</span><span class="spacer"></span>
          <button class="button outline" type="button" data-act="set-discard">Discard</button>
          <button class="button primary" type="button" data-act="set-save">Save</button></div></div></div>`;
  }
  $$(".set-link").forEach((link) => {
    const on = link.dataset.tab === tab;
    link.classList.toggle("active", on);
    if (on) link.setAttribute("aria-current", "page");
    else link.removeAttribute("aria-current");
  });
  const box = $("#settings-body");
  if (box.dataset.tab !== tab) {
    box.dataset.tab = tab;
    setSaver();  // the new section says what its Save does
    box.scrollTop = 0;
    main.scrollTop = 0;  // on a narrow screen <main> is what scrolls
    box.innerHTML = `<p class="loading">${spinner()} Loading</p>`;
  }
  try {
    await current[3](box, item);
  } catch (err) {
    if (S.route[1] === tab) box.innerHTML = loadError(err);
  }
  syncSaveBar();
}

// A plain value in a setting row.
const optText = (text) => `<span class="opt-text">${text}</span>`;
// A section with a heading. end goes at the right of the heading.
const setSect = (title, html, end = "") => `<section class="sect"><div class="sect-head"><h2>${title}</h2>${end}</div>${html}</section>`;

// ---------------------------------------------------------------- Search
// The tabs of the Search section. They switch in the page, without changing the address, so edits in one tab are still
// there (and saved together) after you look at another.
const SEARCH_PARTS = [["filters", "Filters"], ["plan", "Plan"], ["dreams", "Dream list"], ["industries", "Industries"], ["runs", "Runs"]];
let searchPart = "filters";  // the open tab
let planEdited = false;   // the search plan saves through its own API

// Shows one Search tab.
function showSearchPart(part) {
  searchPart = part;
  if (S.route[1] === "search") S.route[2] = part;  // a redraw (Discard, a saved level) stays on this tab
  const box = $("#settings-body");
  $$("[data-search-part]", box).forEach((el) => (el.hidden = el.dataset.searchPart !== part));
  $$("[data-act=search-part]", box).forEach((tab) => {
    const on = tab.dataset.part === part;
    tab.classList.toggle("active", on);
    tab.setAttribute("aria-selected", String(on));
  });
  const pane = $(".set-scroll", box);
  if (pane) pane.scrollTop = 0;
}

// The whole Search form, one tab showing at a time.
async function renderSearchSettings(box, part) {
  if (SEARCH_PARTS.some(([key]) => key === part)) searchPart = part;
  const [, profile, schedule] = await Promise.all([loadCfg(), api("/api/profile").catch(() => ({})), api("/api/schedule").catch(() => null)]);
  S.schedule = schedule || S.schedule;
  if (S.route[1] !== "search") return;
  const c = S.cfg, plan = profile.search_plan || {};
  const levels = questionFields().levels;
  const number = (path, label, extra = "") => cfgOpt(path, label, "number", `step="1" min="0" ${extra}`);
  const planList = (id, label, items) => `<label class="field"><span class="field-label">${label}</span><textarea id="${id}">${esc((items || []).join("\n"))}</textarea></label>`;
  // The cheap check before AI scoring (textutil.TargetMatcher on the server). It passes everything until you have targets.
  const targetGate = c.filters.require_target_match === undefined ? ""
    : cfgOptSwitch("filters.require_target_match", "Match target roles", c.filters.require_target_match);
  planEdited = false;
  box.innerHTML = `<div class="set-page" data-cfg>
    <div class="set-head"><div class="tabs" role="tablist" aria-label="Search">${SEARCH_PARTS.map(([key, label]) =>
      `<button class="tab" type="button" role="tab" data-act="search-part" data-part="${key}">${label}</button>`).join("")}</div></div>
    <div class="set-scroll">
      <div class="set-columns" data-search-part="filters">
        <div><section class="sect" id="area-card"></section>
          ${levels ? setSect("Levels", `<div data-levels>${answerInput(levels, S.onboarding.answers.levels)}</div>`) : ""}
          ${setSect("Exclude", cfgOptLines("filters.exclude_companies", "Companies", 4) + cfgOptLines("filters.exclude_keywords", "Description words", 4))}</div>
        <div>${setSect("Titles", cfgOptLines("filters.title_include", "Must match", 9) + cfgOptLines("filters.title_exclude", "Must not match", 9) + targetGate)}</div></div>
      <div class="set-plan" data-search-part="plan" data-plan>
        <div class="set-plan-lists">${planList("plan-roles", "Roles", plan.role_families)}${planList("plan-queries", "Search terms", plan.queries)}
          ${planList("plan-companies", "Companies", plan.dream_companies)}</div>
        <label class="field"><span class="field-label">Notes</span><input type="text" id="plan-notes" value="${esc(plan.notes || "")}"></label></div>
      <div data-search-part="dreams" id="dream-card"></div>
      <div class="set-lines" data-search-part="industries">
        <div class="toolbar"><b>Industries</b><span class="spacer"></span>
          <button class="button outline small" type="button" data-act="retag-industries">${icon("sparkle")}Retag leads</button></div>
        <div class="set-lines-body"><textarea data-list="industries" aria-label="Industries">${esc((c.industries || []).join("\n"))}</textarea></div></div>
      <div class="set-columns" data-search-part="runs">
        <div>${setSect("Each run",
          number("run.min_score", "Good-fit score", 'max="100"') + number("run.max_triage", "Jobs scored") + number("run.triage_batch", "Jobs per AI request")
          + number("run.max_packages", "Applications tailored") + number("run.max_age_days", "Max job age (days)")
          + cfgOptSwitch("run.package_web_research", "Web research", c.run.package_web_research))}</div>
        <div id="schedule-card" data-schedule></div></div>
    </div></div>`;
  $("[data-plan]", box).addEventListener("input", () => {
    planEdited = true;
    S.dirty = true;
  });
  showSearchPart(searchPart);
  renderAreaCard();
  renderDreams($("#dream-card"));
  renderScheduleCard();
  setSaver(saveSearch);
}

// The Save bar on Search: the search plan when it changed, then the settings when they did.
async function saveSearch() {
  if (planEdited) {
    const lines = (id) => $(id).value.split("\n").map((x) => x.trim()).filter(Boolean);
    const plan = { role_families: lines("#plan-roles"), queries: lines("#plan-queries"), dream_companies: lines("#plan-companies"), notes: $("#plan-notes").value };
    await api("/api/profile/search_plan", { method: "PUT", body: { value: plan } });
    planEdited = false;
    S.dirty = false;
  }
  if (S.cfgDirty) await saveCfg();
  else toast("Saved");
}

// ---------------------------------------------------------------- the schedule
const DAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];  // the schedule's days; 0 is Monday, as on the server

// The schedule, on the Runs tab: on or off, the times and the days, searching in the background, and when the next search
// starts. Its fields are part of the Search form (onCfgEdit reads data-time and data-day), so the Save bar saves them with
// the rest. Adding or removing a time redraws it from S.cfg.
function renderScheduleCard() {
  const card = $("#schedule-card");
  if (!card || !S.cfg) return;
  const sc = S.cfg.schedule || {}, days = sc.days || [];
  const times = (sc.times || []).map((t, i) => `<span class="time-row"><input type="time" data-time="${i}" value="${esc(t)}" aria-label="Time ${i + 1}">`
    + `<button class="icon-button" type="button" data-act="rm-time" data-i="${i}" aria-label="Remove ${esc(t)}" title="Remove">${icon("close")}</button></span>`).join("");
  card.innerHTML = setSect("Schedule", `${cfgOptSwitch("schedule.enabled", "Scheduled runs", sc.enabled, "Each run uses AI credit")}
    ${optRow("Times", `<div class="time-list">${times}<button class="button outline small" type="button" data-act="add-time">${icon("plus")}Add</button></div>`)}
    ${optRow("Days", `<div class="choice-row">${DAY_NAMES.map((name, i) =>
      `<label class="choice${days.includes(i) ? " active" : ""}"><input type="checkbox" data-day="${i}"${days.includes(i) ? " checked" : ""}>${name}</label>`).join("")}</div>`)}
    ${cfgOptSwitch("schedule.background", "Run in background", sc.background, "Runs while closed")}
    ${optRow("Next run", `<span class="opt-text" id="schedule-note">${esc(scheduleNote())}</span>`)}`);
}

// The Next run row: off, when it is, or why the last scheduled one was skipped (from the server).
function scheduleNote() {
  const st = S.schedule || {};
  if (!st.enabled) return "Off";
  if (!st.next) return "No time or day set";
  const skipped = st.last?.skipped ? `. Last one skipped: ${st.last.skipped}` : "";
  return `${fmtNextSearch(st.next)}${skipped}`;
}

// When a scheduled search starts, like "Tue 5:00 PM".
const fmtNextSearch = (iso) => new Date(iso).toLocaleString([], { weekday: "short", hour: "numeric", minute: "2-digit" });

// The schedule changed on the server (saved, a search started or skipped): update the line that shows it.
function scheduleChanged() {
  const note = $("#schedule-note");
  if (note) note.textContent = scheduleNote();
}

// The search area on the Filters tab (redrawn when the editor saves; setHtml gives the focus back to its button, which the
// closing editor had just returned it to).
function renderAreaCard() {
  const card = $("#area-card");
  if (!card) return;
  const loc = S.cfg?.locations || {};
  setHtml(card, `<div class="sect-head"><h2>Search area</h2><button class="button outline small" type="button" data-act="edit-area">${icon("pin")}Edit</button></div>
    <div class="tags">${areaTags(loc.allowed || S.searchArea)}</div>
    <dl class="facts set-area-facts"><dt>Unclear location</dt><dd>${loc.unknown_policy === "drop" ? "Skip" : "AI decides"}</dd>
      <dt>Dream companies</dt><dd>${loc.dream_bypass ? "Anywhere in the US" : "In search area"}</dd></dl>`);
}

// ---------------------------------------------------------------- AI
// Each kind of AI task's name, by its stage name in settings.
const AI_STAGES = { prefill: "Resume reading", triage: "Job scoring", hunt: "AI hunt", package: "Tailoring", revise: "Revisions",
  profile: "Profile", documents: "Documents", analysis: "Analysis" };

// What's known about the AI in use besides its status: its entry in the provider list, and web search (true, false, or
// unknown until the first web task tries it).
let aiShown = { provider: null, webSearch: undefined };

// A model menu: the models your AI offers, plus the saved choice if it no longer lists it. "" uses the default.
function modelOptions(models, selected, emptyLabel) {
  const choices = [...new Set([...models, ...(selected ? [selected] : [])])];
  return selectOptions([["", emptyLabel], ...choices], selected);
}

// How the AI in use is connected: the account it's signed in with, its saved key, or its address.
function aiConnection(ai, provider) {
  if (ai.email || ai.name) return `Signed in, ${ai.email || ai.name}`;
  const key = ai.keys?.[ai.provider];
  if (key) return `API key ${key}`;
  const url = ai.endpoints?.[ai.provider]?.url;
  if (url) return url;
  return provider?.group === "signin" ? "Signed in" : "Connected";
}

// The AI in use and this session's numbers (S.state.usage, kept current by "usage" events), or that none is connected.
function renderAIStatus() {
  const el = $("#ai-status");
  if (!el) return;
  if (!aiReady()) {
    setHtml(el, `<div class="sect-head"><h2>AI in use</h2></div>
      <div class="set-ai-none"><span><span class="status-dot off"></span><b>Not connected</b></span>
        <button class="button primary" type="button" data-act="ai-connect">Connect AI</button></div>`);
    return;
  }
  const ai = S.state.ai, u = S.state.usage || {}, { provider, webSearch } = aiShown;
  const search = provider && !provider.search ? "Not offered" : webSearch === false ? "Not available" : webSearch ? "Available" : "Not checked yet";
  const tasks = u.capped ? `<span class="status-dot warn"></span>Paused at a limit` : +u.running ? `${u.running} of ${u.slots} running` : "Idle";
  setHtml(el, `<div class="sect-head"><h2>AI in use</h2><button class="button outline small" type="button" data-act="ai-connect">Change</button></div>
    ${optRow("Provider", optText(`<span class="status-dot"></span><b>${esc(aiName())}</b>`))}
    ${optRow("Connection", optText(esc(aiConnection(ai, provider))))}
    ${optRow("Model", optText(u.model ? `${esc(u.model)}${u.model_note ? ` <span class="muted">(${esc(u.model_note)})</span>` : ""}` : "Default"))}
    ${optRow("Tasks", optText(tasks))}
    ${optRow("This session", optText(`${fmtTokens(+u.tokens || 0)} tokens, ${plural(+u.requests || 0, "request")}`))}
    ${optRow("Web search", optText(search))}`);
}
// The session numbers change as tasks run, while this section is open.
setInterval(() => {
  if (S.route[0] === "settings" && S.route[1] === "ai") renderAIStatus();
}, 2000);

// The AI in use, the models and efforts, how many AI tasks run at once, and the prompts.
async function renderAISettings(box) {
  await loadCfg();
  let webSearch, listing = [];
  try {
    const [status, list] = await Promise.all([api("/api/ai/status"), api("/api/ai/providers")]);
    S.state.ai = status;
    webSearch = status.web_search;
    listing = list.providers;
  } catch (_) {}
  const [models, defaults] = await Promise.all([
    aiReady() ? api("/api/ai/models").then((r) => r.models).catch(() => []) : [],
    api("/api/prompts/defaults"),
  ]);
  if (S.route[1] !== "ai") return;
  const c = S.cfg;
  aiShown = { provider: listing.find((p) => p.id === S.state.ai?.provider) || null, webSearch };
  // The stage and prompt keys come from the settings and the server, so they're escaped in the attributes too.
  const stageRow = ([key, stage]) => {
    const label = AI_STAGES[key] || humanize(key);
    return optRow(esc(label), `<div class="set-model"><select data-path="ai.stages.${esc(key)}.model" aria-label="${esc(label)} model">${modelOptions(models, stage.model, "Default model")}</select>
      <select data-path="ai.stages.${esc(key)}.effort" aria-label="${esc(label)} effort">${selectOptions(S.meta.efforts.map((e) => [e, humanize(e)]), stage.effort)}</select></div>`);
  };
  const prompt = (key) => `<details class="set-prompt"><summary><span>${esc(humanize(key))}</span>${c.prompts?.[key] ? `<span class="tag green">Custom</span>` : ""}${icon("chevron")}</summary>
    <textarea rows="12" data-path="prompts.${esc(key)}" aria-label="${esc(humanize(key))} prompt" placeholder="${esc(defaults[key])}">${esc(c.prompts?.[key] || "")}</textarea></details>`;
  box.innerHTML = `<div class="set-columns" data-cfg>
    <div><section class="sect" id="ai-status"></section>
      ${setSect("Prompts", `<div class="set-prompts">${Object.keys(defaults).map(prompt).join("")}</div>`)}</div>
    <div>${setSect("Models", `${optRow("Default", `<select data-path="ai.model" aria-label="Default model">${modelOptions(models, c.ai.model, "Best available")}</select>`)}
      ${Object.entries(c.ai.stages).map(stageRow).join("")}
      ${cfgOpt("ai.max_parallel", "Parallel tasks", "number", 'min="1"')}`)}</div></div>`;
  renderAIStatus();
  setSaver(() => saveCfg());
}

// ---------------------------------------------------------------- Appearance
// The light or dark theme (saved on this computer), and desktop alerts with a button that sends a test one.
function renderAppearance(box) {
  const theme = document.documentElement.dataset.theme;
  const choice = (key, label, name) => `<button class="choice${theme === key ? " active" : ""}" type="button" role="radio" aria-checked="${theme === key}"
      data-act="set-theme" data-choice="${key}">${icon(name)}${label}</button>`;
  const focus = focusKey(box);
  box.innerHTML = `<section class="sect">
    ${optRow("Theme", `<div class="choice-row" role="radiogroup" aria-label="Theme">${choice("light", "Light", "sun")}${choice("dark", "Dark", "moon")}</div>`)}
    ${optRow("Desktop alerts", `<div class="set-inline">${toggle('id="notify-switch" aria-label="Desktop alerts"', S.alerts)}
      <button class="button outline small" type="button" data-act="test-alert">${icon("bell")}Test</button></div>`)}</section>`;
  refocus(box, focus);
  setSaver();
}

// Turns desktop alerts on or off on the server, on top of the settings as they are there now.
async function saveAlerts(on) {
  const fresh = await api("/api/settings");
  fresh.alerts = { ...(fresh.alerts || {}), desktop: on };
  await api("/api/settings", { method: "PUT", body: fresh });
  S.alerts = on;
}

// ---------------------------------------------------------------- Data
// The parts of the settings that can go back to their defaults: [settings path, name, what it also removes].
const RESETTABLE = [
  ["ai", "Models", ""],
  ["run", "Search limits", ""],
  ["filters", "Filters", ""],
  ["industries", "Industries", ""],
  ["sources", "Sources", "Removes company boards you added"],
  ["prompts", "Prompts", ""],
  ["resume_playbook", "Resume playbook", ""],
];

// Your data folder, the version, putting settings back to their defaults, and Quit (only in a browser tab: JobPortal's own
// window quits when you close it).
function renderDataSettings(box) {
  const m = S.meta;
  // A server started for the schedule goes on after its window closes, so it gets a Quit button even in its own window.
  const background = !!S.schedule?.background_server;
  const quit = ownWindow() && !background ? "" : setSect("Quit",
    optRow(`JobPortal<small>${background ? "Keeps searching in the background" : "Keeps running when this tab closes"}</small>`,
      `<button class="button outline" type="button" data-act="quit">Quit</button>`));
  box.innerHTML = `<div class="set-columns">
    <div>${setSect("Storage", optRow("Folder<small>Stored only on this computer</small>", `<div class="set-path"><code>${esc(m.data_dir || "")}</code>
        <button class="button outline small" type="button" data-act="open-data">${icon("folder")}Open</button></div>`))}
      ${setSect("About", `${optRow("Version", optText(esc(m.version || "")))}
        ${optRow("System", optText(esc(humanize(m.os || ""))))}
        ${optRow("PDF downloads", optText(m.pdf_ready ? "Ready" : "Needs Chrome, Edge or Chromium"))}
        ${optRow("AI", optText(esc(aiConnected())))}`)}${quit}</div>
    <div>${setSect("Reset", RESETTABLE.map(([path, label, note]) => optRow(`${label}${note ? `<small>${note}</small>` : ""}`,
      `<button class="button outline small" type="button" data-act="reset-section" data-path="${path}" data-label="${esc(label)}">${icon("undo")}Reset</button>`)).join(""))}</div></div>`;
  setSaver();
}

// ---------------------------------------------------------------- actions
onAction("search-part", (el) => showSearchPart(el.dataset.part));
onAction("retag-industries", async () => {
  if (!confirm("Retag every lead with AI?")) return;
  await api("/api/leads/retag-industries", { method: "POST" });
  toast("Retagging leads");
});
onAction("set-theme", (el) => {
  applyTheme(el.dataset.choice);
  renderAppearance($("#settings-body"));
});
onAction("open-data", async () => {
  const r = await api("/api/open-data-folder", { method: "POST" });
  if (!r.ok) toast("Couldn't open folder", r.path, "error");
});
onAction("reset-section", async (el) => {
  if (!confirm(`Reset ${el.dataset.label.toLowerCase()}?`)) return;
  const fresh = await api("/api/settings/reset", { method: "POST", body: { path: el.dataset.path } });
  S.searchArea = fresh.locations.allowed;
  S.industries = fresh.industries;
  toast("Reset", el.dataset.label);
});
onAction("add-time", () => {
  const times = S.cfg.schedule.times || (S.cfg.schedule.times = []);
  const last = times.length ? +times[times.length - 1].split(":")[0] : 6;
  times.push(`${String((last + 3) % 24).padStart(2, "0")}:00`);  // three hours after the last time, so it's new
  markCfgEdit("schedule.times");
  renderScheduleCard();
});
onAction("rm-time", (el) => {
  S.cfg.schedule.times.splice(+el.dataset.i, 1);
  markCfgEdit("schedule.times");
  renderScheduleCard();
});
onAction("test-alert", async () => {
  const r = await api("/api/alerts/test", { method: "POST" });
  if (r.ok) toast("Test alert sent");
  else toast("Alerts unavailable", "", "error");
});
onAction("quit", async () => {
  if (S.state.running && !confirm("Quit and stop the running search?")) return;
  await api("/api/quit", { method: "POST" });
  S.quit = true;
  document.body.innerHTML = `<div class="empty quit"><h3>JobPortal has quit</h3></div>`;
});
onChange(async (el) => {
  if (el.id === "notify-switch") {
    await saveAlerts(el.checked).catch((err) => {
      el.checked = !el.checked;
      throw err;
    });
    if (S.alerts && !desktop() && "Notification" in window) Notification.requestPermission();
    toast(S.alerts ? "Alerts on" : "Alerts off");
    return true;
  }
  if (el.matches("[data-levels] [data-qm]")) {  // the experience levels are one of your standard answers
    const picked = $$("[data-levels] [data-qm]").filter((box) => box.checked).map((box) => box.value);
    const undo = () => {  // the level goes back to how it's saved
      el.checked = !el.checked;
      el.closest(".choice").classList.toggle("active", el.checked);
    };
    if (!picked.length) {
      undo();
      toast("Keep one level", "", "error");
      return true;
    }
    const r = await api("/api/onboarding/answers", { method: "PATCH", body: { answers: { levels: picked } } }).catch((err) => {
      undo();
      throw err;
    });
    S.onboarding.answers = r.answers;
    toast("Levels saved");
    if (!S.cfgDirty && !S.dirty) renderSettings("search");  // show the title filters made from them
    return true;
  }
  return false;
});
