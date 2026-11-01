/* settings.js: Settings (#/settings/<tab>), one page with a tab for each area:
   - Profile (profile.js): your standard answers, the parts of your profile, your writing voice, and its history.
   - Search: where to look, experience levels, what to search for (the search plan), the Dream list (dreams.js),
     filters, industries, and how much each search does.
   - Resumes (resumes.js): your saved resumes, the recruiter review and the resume playbook.
   - AI: your ChatGPT account, the model and effort for each kind of AI task, and the prompts.
   - Appearance: light or dark, and desktop alerts.
   - History (runs.js): every search and its log.
   - Data: your data folder, putting settings back to their defaults, and Quit (in a browser tab).
   APIs: GET /api/settings and PUT /api/settings (through S.cfg and saveCfg, see components/settings-form.js),
   GET /api/ai/status, GET /api/ai/models, GET /api/prompts/defaults, GET /api/profile, PUT /api/profile/search_plan,
   PATCH /api/onboarding/answers (the experience levels), POST /api/settings/reset, POST /api/open-data-folder,
   POST /api/quit and POST /api/leads/retag-industries. */
"use strict";

// The tabs: [key, label, icon, function that fills the tab]. The functions get the tab's box and the rest of the address
// (#/settings/resumes/12 opens saved resume 12).
const SETTINGS_TABS = [
  ["profile", "Profile", "user", (box, item) => renderProfileSettings(box, item)],
  ["search", "Search", "search", (box) => renderSearchSettings(box)],
  ["resumes", "Resumes", "file", (box, item) => renderLibrary(box, item)],
  ["ai", "AI", "sparkle", (box) => renderAISettings(box)],
  ["appearance", "Appearance", "sun", (box) => renderAppearance(box)],
  ["history", "History", "clock", (box, item) => renderRuns(box, item)],
  ["data", "Data", "folder", (box) => renderDataSettings(box)],
];

// Draws the page frame once, then the tab the address names.
async function renderSettings(tab, item) {
  const current = SETTINGS_TABS.find(([key]) => key === tab);
  if (!current) {
    location.replace("#/settings/profile");
    return;
  }
  if (main.dataset.page !== "settings") {
    main.dataset.page = "settings";
    main.innerHTML = `<div class="page-heading"><div><p class="eyebrow">SETTINGS</p><h1>Settings</h1>
        <p>Your profile, your search, and how JobPortal works for you.</p></div></div>
      <div class="settings-layout"><nav class="side-tabs" aria-label="Settings">${SETTINGS_TABS.map(([key, label, name]) =>
        `<a class="side-tab" href="#/settings/${key}" data-tab="${key}">${icon(name)}${label}</a>`).join("")}</nav>
        <div class="settings-body" id="settings-body"></div></div>`;
  }
  $$(".side-tab").forEach((link) => {
    const on = link.dataset.tab === tab;
    link.classList.toggle("active", on);
    if (on) link.setAttribute("aria-current", "page");
    else link.removeAttribute("aria-current");
  });
  const box = $("#settings-body");
  box.innerHTML = `<p class="loading">${spinner()} Loading</p>`;
  await current[3](box, item);
}

// A panel with a heading and a short note under it.
const settingsPanel = (title, note, html, attrs = "") => `<section class="panel"${attrs}><h2>${title}</h2>${note ? `<p class="panel-note">${note}</p>` : ""}${html}</section>`;

// ---------------------------------------------------------------- Search
// Where to look, levels, the search plan, the Dream list, filters, industries and how much each search does.
async function renderSearchSettings(box) {
  const [, profile] = await Promise.all([loadCfg(), api("/api/profile").catch(() => ({}))]);
  if (S.route[1] !== "search") return;
  const c = S.cfg, plan = profile.search_plan || {};
  const levels = questionFields().levels;
  const number = (path, label, step = 1) => cfgInput(path, label, "number", `step="${step}" min="0"`);
  const planList = (id, label, items) => `<label class="field"><span class="field-label">${label}</span><textarea id="${id}" rows="10">${esc((items || []).join("\n"))}</textarea></label>`;
  // The cheap check before AI scoring (textutil.TargetMatcher on the server). It passes everything until you have targets.
  const targetGate = c.filters.require_target_match === undefined ? ""
    : cfgSwitch("filters.require_target_match", "Only keep jobs that match the roles you're targeting (lenient: related titles count)", c.filters.require_target_match);
  box.innerHTML = `<div class="stack" data-cfg>
    <section class="panel" id="area-card"></section>
    ${levels ? settingsPanel("Experience levels", "The levels to search at. They also decide which job titles get through the filters.",
      `<div class="levels" data-levels>${answerInput(levels, S.onboarding.answers.levels)}</div>`) : ""}
    ${settingsPanel("What to search for", "Your search plan: the kinds of roles, the search terms and the companies to look at. It's written from your profile and rewritten when the profile is rebuilt; your edits are kept unless your answers say otherwise.",
      `<div class="form-grid three" data-plan>${planList("plan-roles", "Kinds of roles, best first", plan.role_families)}
        ${planList("plan-queries", "Search terms", plan.queries)}${planList("plan-companies", "Companies to look at", plan.dream_companies)}</div>
      <label class="field"><span class="field-label">A note on the strategy</span><input type="text" id="plan-notes" value="${esc(plan.notes || "")}"></label>
      <div class="block-actions end"><button class="button outline" type="button" data-act="save-plan">Save the search plan</button></div>`)}
    <section class="panel" id="dream-card"></section>
    ${settingsPanel("Filters", "Rules every job passes before any AI reads it. The title rules are made from your experience levels and the jobs you want each time you save your answers; change them here if you need to.",
      `<div class="form-grid">${cfgLines("filters.title_include", "A title must match one of these (patterns; leave empty for any title)", 7)}
        ${cfgLines("filters.title_exclude", "A title must not match these (patterns)", 7)}
        ${cfgLines("filters.exclude_companies", "Never show these companies", 4)}${cfgLines("filters.exclude_keywords", "Skip a job when its description has", 4)}</div>${targetGate}`)}
    ${settingsPanel("Industries", "Every lead is tagged with one of these, so you can filter and sort by it. One per line. Save, then tag your leads again.",
      `${cfgLines("industries", "Industries", 8)}<div class="block-actions"><button class="button light" type="button" data-act="retag-industries">${icon("sparkle")}Tag all leads again with AI</button></div>`)}
    ${settingsPanel("How much each search does", "",
      `<div class="form-grid three">${number("run.min_score", "Good-fit score (0 to 100)")}${number("run.max_triage", "Jobs scored per search")}
        ${number("run.triage_batch", "Jobs per AI scoring request")}${number("run.max_packages", "Applications tailored per search")}
        ${number("run.max_age_days", "Skip jobs older than (days)")}${number("run.auto_run_hours", "Search by itself every (hours, 0 is off)", 0.5)}</div>
      ${cfgSwitch("run.package_web_research", "Research each job on the web while tailoring: check the posting, company news and people to contact", c.run.package_web_research)}`)}
    ${saveBar()}</div>`;
  $("[data-plan]", box).closest(".panel").addEventListener("input", () => (S.dirty = true));
  renderAreaCard();
  renderDreams($("#dream-card"));
}

// The search area's card (redrawn when the editor saves).
function renderAreaCard() {
  const card = $("#area-card");
  if (!card) return;
  const loc = S.cfg?.locations || {};
  card.innerHTML = `<div class="panel-heading"><h2>Where to look</h2><button class="button primary" type="button" data-act="edit-area">${icon("pin")}Change the search area</button></div>
    <div class="tags area-tags">${areaTags(loc.allowed || S.searchArea)}</div>
    <p class="panel-note">${loc.dream_bypass ? "Dream companies can be anywhere in the US. " : ""}When a job's location is unclear,
      ${loc.unknown_policy === "drop" ? "it's skipped" : "the AI decides"}.</p>`;
}

// ---------------------------------------------------------------- AI
// What each kind of AI task does, by its stage name in settings.
const AI_STAGES = {
  prefill: ["Reading your resume", "Fills in your answers from your resume. A fast model is fine."],
  triage: ["Scoring jobs", "Scores every job a search finds, in batches. It runs hundreds of times, so a fast model is fine."],
  hunt: ["AI hunt", "The missions that search the web, social posts and forums for jobs."],
  package: ["Tailoring applications", "Researches each job and writes its resume, cover letter, emails and interview prep."],
  revise: ["Revise with AI", "Your edits by instruction in the editors, and the recruiter review."],
  profile: ["Your profile", "Builds and updates your profile from your resume, documents and answers, and learns your writing voice."],
  documents: ["Reading your documents", "Reads the title, issuer, dates and skills off each certificate, license or award you add. A fast model is fine."],
  analysis: ["Analysis", "The fit and interest scores on the Analysis page."],
};

// A model menu: the models your plan offers, plus the saved choice if your plan no longer lists it. "" uses the default.
function modelOptions(models, selected, emptyLabel) {
  const choices = [...new Set([...models, ...(selected ? [selected] : [])])];
  return selectOptions([["", emptyLabel], ...choices], selected);
}

// Your ChatGPT account, the models and efforts, how many AI tasks run at once, and the prompts.
async function renderAISettings(box) {
  await loadCfg();
  let webSearch;  // true, false, or unknown until the first web task tries it
  try {
    const status = await api("/api/ai/status");
    S.state.ai = status;
    webSearch = status.web_search;
  } catch (_) {}
  const [models, defaults] = await Promise.all([
    aiReady() ? api("/api/ai/models").then((r) => r.models).catch(() => []) : [],
    api("/api/prompts/defaults"),
  ]);
  if (S.route[1] !== "ai") return;
  const c = S.cfg, ai = S.state.ai || {};
  const account = aiReady()
    ? `<div class="account-row"><span class="avatar">${esc(initials(ai.name)) || icon("user")}</span><div><b>${esc(ai.name || "Signed in")}</b><small>${esc(ai.email || "")}</small></div>
        <span class="spacer"></span><button class="button outline" type="button" data-act="ai-signout">Sign out</button></div>`
    : `<div class="account-row"><div><b>Not signed in</b><small>JobPortal's AI needs your ChatGPT account.</small></div><span class="spacer"></span>
        <button class="button primary" type="button" data-act="ai-signin">Continue with ChatGPT</button></div>`;
  const webSearchText = webSearch === false ? "isn't available on your account, so the AI reads pages directly"
    : webSearch ? "is available" : "is checked the first time the AI needs it";
  const stageRow = ([key, stage]) => {
    const [label, help] = AI_STAGES[key] || [humanize(key), ""];
    return `<tr><td><b>${esc(label)}</b><small class="cell-note">${esc(help)}</small></td>
      <td><select data-path="ai.stages.${key}.model" aria-label="${esc(label)} model">${modelOptions(models, stage.model, "Default model")}</select></td>
      <td><select data-path="ai.stages.${key}.effort" aria-label="${esc(label)} effort">${selectOptions(S.meta.efforts.map((e) => [e, humanize(e)]), stage.effort)}</select></td></tr>`;
  };
  const prompt = (key) => `<label class="field"><span class="field-label">${esc(humanize(key))}</span>
    <textarea rows="5" data-path="prompts.${key}" placeholder="${esc(defaults[key])}">${esc(c.prompts?.[key] || "")}</textarea></label>`;
  box.innerHTML = `<div class="stack" data-cfg>
    ${settingsPanel("Your ChatGPT account", `JobPortal's AI runs on your ChatGPT plan (Go, Plus or Pro), and what it uses counts against your plan. You can set a
      limit for JobPortal in ChatGPT's settings. Web search ${webSearchText}.`, account)}
    ${settingsPanel("Models", "Which model does each kind of task, and how hard it thinks. A higher effort is slower and uses more of your plan.",
      `<label class="field narrow"><span class="field-label">Default model</span><select data-path="ai.model">${modelOptions(models, c.ai.model, "The first model your plan lists")}</select></label>
      <div class="table-wrap"><table class="table"><thead><tr><th>Task</th><th>Model</th><th>Effort</th></tr></thead>
        <tbody>${Object.entries(c.ai.stages).map(stageRow).join("")}</tbody></table></div>
      <div class="form-grid three">${cfgInput("ai.max_parallel", "AI tasks at the same time", "number", 'min="1"')}</div>`)}
    <section class="panel"><details class="disclosure"><summary>Prompts (advanced)</summary>
      <p class="panel-note">Replace the instructions the AI follows. Leave one empty to use the built-in one, shown in gray.</p>
      ${Object.keys(defaults).map(prompt).join("")}</details></section>
    ${saveBar()}</div>`;
}

// ---------------------------------------------------------------- Appearance
// The light or dark theme (saved on this computer), and desktop alerts.
function renderAppearance(box) {
  const theme = document.documentElement.dataset.theme;
  const choice = (key, label, name) => `<button class="theme-choice${theme === key ? " active" : ""}" type="button" role="radio" aria-checked="${theme === key}"
      data-act="set-theme" data-choice="${key}"><span class="theme-preview ${key}" aria-hidden="true"><i></i><i></i><i></i></span><span>${icon(name)}${label}</span></button>`;
  box.innerHTML = `<div class="stack">
    ${settingsPanel("Theme", "Light or dark. JobPortal remembers your choice on this computer.",
      `<div class="theme-choices" role="radiogroup" aria-label="Theme">${choice("light", "Light", "sun")}${choice("dark", "Dark", "moon")}</div>`)}
    ${settingsPanel("Desktop alerts", "",
      `<label class="switch-row">${toggle('id="notify-switch"', S.notify)}<span>Show a desktop alert when new leads are ready while JobPortal is in the background</span></label>`)}</div>`;
}

// ---------------------------------------------------------------- Data
// The parts of the settings that can go back to their defaults: [settings path, name, what else to know].
const RESETTABLE = [
  ["ai", "Models and efforts", ""],
  ["run", "How much each search does", ""],
  ["filters", "Filters", "The title rules come back the next time you save your answers."],
  ["industries", "Industries", ""],
  ["sources", "Job sources and AI hunt missions", "Company boards you added are removed."],
  ["prompts", "Prompts", ""],
  ["resume_playbook", "Resume playbook", ""],
];

// Your data folder, the version, putting settings back to their defaults, and Quit (only in a browser tab: JobPortal's own
// window quits when you close it).
function renderDataSettings(box) {
  const m = S.meta;
  const quit = ownWindow() ? "" : settingsPanel("Quit JobPortal", "Closing this tab leaves JobPortal running, so a search can finish. Quit stops it.",
    `<button class="button outline" type="button" data-act="quit">Quit JobPortal</button>`);
  box.innerHTML = `<div class="stack">
    ${settingsPanel("Your data", "Everything JobPortal keeps (your profile, leads, documents and tailored files) is in one folder on this computer. Delete the folder to start over from nothing.",
      `<div class="path-row"><code>${esc(m.data_dir || "")}</code><button class="button outline" type="button" data-act="open-data">${icon("folder")}Open the folder</button></div>
      <dl class="facts"><dt>Version</dt><dd>JobPortal ${esc(m.version || "")}</dd><dt>System</dt><dd>${esc(humanize(m.os || ""))}</dd>
        <dt>PDF downloads</dt><dd>${m.pdf_ready ? "Ready" : "Need Chrome, Edge or Chromium installed"}</dd><dt>ChatGPT</dt><dd>${aiReady() ? "Signed in" : "Not signed in"}</dd></dl>`)}
    ${settingsPanel("Back to the defaults", "Put one part of your settings back the way it came. Your profile, leads and documents stay as they are.",
      `<ul class="reset-list">${RESETTABLE.map(([path, label, note]) => `<li><div><b>${label}</b>${note ? `<small>${note}</small>` : ""}</div>
        <button class="button outline small" type="button" data-act="reset-section" data-path="${path}" data-label="${esc(label)}">${icon("undo")}Reset</button></li>`).join("")}</ul>`)}
    ${quit}</div>`;
}

// ---------------------------------------------------------------- actions
onAction("save-plan", async () => {
  const lines = (id) => $(id).value.split("\n").map((x) => x.trim()).filter(Boolean);
  const plan = { role_families: lines("#plan-roles"), queries: lines("#plan-queries"), dream_companies: lines("#plan-companies"), notes: $("#plan-notes").value };
  await api("/api/profile/search_plan", { method: "PUT", body: { value: plan } });
  S.dirty = false;
  toast("Search plan saved", "The next search uses it.");
});
onAction("retag-industries", async () => {
  if (!confirm("Tag the industry of every lead again with AI? It uses a fast model.")) return;
  await api("/api/leads/retag-industries", { method: "POST" });
  toast("Tagging your leads", "Their industries update in a minute or two.");
});
onAction("set-theme", (el) => {
  applyTheme(el.dataset.choice);
  renderAppearance($("#settings-body"));
});
onAction("open-data", async () => {
  const r = await api("/api/open-data-folder", { method: "POST" });
  if (!r.ok) toast("Couldn't open the folder", r.path, "error");
});
onAction("reset-section", async (el) => {
  if (!confirm(`Put ${el.dataset.label.toLowerCase()} back to the defaults?`)) return;
  const fresh = await api("/api/settings/reset", { method: "POST", body: { path: el.dataset.path } });
  S.searchArea = fresh.locations.allowed;
  S.industries = fresh.industries;
  toast("Back to the defaults", el.dataset.label);
});
onAction("quit", async () => {
  if (S.state.running && !confirm("A search is running. Quitting stops it; what it found so far is kept.")) return;
  await api("/api/quit", { method: "POST" });
  S.quit = true;
  document.body.innerHTML = `<div class="empty-state quit"><h3>JobPortal has quit</h3><p>You can close this tab. Open JobPortal again to pick up where you left off.</p></div>`;
});
onChange(async (el) => {
  if (el.id === "notify-switch") {
    S.notify = el.checked;
    store.set("notify", S.notify ? "1" : "0");
    if (S.notify && !desktop() && "Notification" in window) Notification.requestPermission();
    toast(S.notify ? "Desktop alerts on" : "Desktop alerts off");
    return true;
  }
  if (el.matches("[data-levels] [data-qm]")) {  // the experience levels are one of your standard answers
    const picked = $$("[data-levels] [data-qm]").filter((box) => box.checked).map((box) => box.value);
    if (!picked.length) {
      el.checked = true;
      el.closest(".choice").classList.add("active");
      toast("Keep at least one level", "The search needs one to know what to look for.", "error");
      return true;
    }
    const r = await api("/api/onboarding/answers", { method: "PATCH", body: { answers: { levels: picked } } });
    S.onboarding.answers = r.answers;
    toast("Levels saved", "The title filters follow them.");
    if (!S.cfgDirty && !S.dirty) renderSettings("search");  // show the title filters made from them
    return true;
  }
  return false;
});
