/* settings.js: the Settings page. The ChatGPT sign-in and the model for each kind of AI task, run limits, the resume
   playbook, the search area, industries, filters, your data folder (plus Quit, in a normal browser tab) and prompt
   overrides. Job sources are on the Sources page and dream companies on the Dream list.
   APIs: GET /api/settings and PUT /api/settings (through S.cfg and saveCfg, see components/settings-form.js),
   GET /api/ai/status, GET /api/ai/models, GET /api/prompts/defaults, GET /api/resume-playbook,
   POST /api/open-data-folder, POST /api/quit and POST /api/leads/retag-industries. */
"use strict";

// What each AI stage does, shown next to its model menu.
const STAGE_HELP = {
  prefill: "Reads your resume during setup to pre-fill the standard questions. Cheap and fast is fine.",
  triage: "Scores every candidate in batches. Runs hundreds of times, so cheap and fast is fine.",
  hunt: "AI hunt missions: agents that search the web, social media and threads.",
  package: "Builds each application package: research, contacts, resume, cover letter, emails, prep.",
  revise: "‘Revise with AI’ edits in the editor.",
  profile: "Builds your profile from your resume and answers, adds new answers, and learns your writing voice.",
  analysis: "The Analysis tab: fit and interest per work genre, and what to build next.",
};

// A model menu: the models your plan offers, plus the saved choice if your plan no longer lists it. "" uses the default.
function modelOptions(models, selected, emptyLabel) {
  const choices = [...new Set([...models, ...(selected ? [selected] : [])])];
  return selectOptions([["", emptyLabel], ...choices], selected);
}

// Draws the page from the saved settings. The playbook text loads after the page shows.
async function renderSettings() {
  S.cfg = await api("/api/settings");
  S.cfgDirty = false;
  let webSearch;  // true, false, or unknown until the first web task tries it
  try {
    const status = await api("/api/ai/status");
    S.state.ai = status;
    webSearch = status.web_search;
  } catch (_) {}
  const models = aiReady() ? ((await api("/api/ai/models").catch(() => null)) || { models: [] }).models : [];
  const defaults = await api("/api/prompts/defaults");
  const c = S.cfg;
  const account = aiReady()
    ? `<span>Signed in as <b>${esc(S.state.ai.email || S.state.ai.name || "your account")}</b></span><span class="spacer"></span><button class="btn sm" data-act="ai-signout">Sign out</button>`
    : `<span class="muted">Not signed in.</span><span class="spacer"></span><button class="btn sm primary" data-act="ai-signin">Continue with ChatGPT</button>`;
  const webSearchText = webSearch === false ? "isn't available on your account, so agents read pages directly"
    : webSearch ? "is available" : "is checked on the first web task";
  const stageRow = ([key, stage]) => `<tr><td style="width:110px" class="mono"><b>${key}</b></td>
        <td style="width:220px"><select data-path="ai.stages.${key}.model">${modelOptions(models, stage.model, "Default model")}</select></td>
        <td style="width:130px"><select data-path="ai.stages.${key}.effort">${selectOptions(S.meta.efforts, stage.effort)}</select></td>
        <td class="muted small">${STAGE_HELP[key] || ""}</td></tr>`;
  const number = (path, label, step = 1) => cfgInput(path, label, "number", `step="${step}"`);
  // In a normal browser tab, closing the tab leaves JobPortal running, so it needs a Quit button. Its own window quits on close.
  const quit = ownWindow() ? "" : `<div class="row" style="margin-top:8px"><span class="muted small" style="flex:1">Closing this tab leaves JobPortal running so searches can finish. Quit stops it.</span>
    <button class="btn sm" data-act="quit">Quit JobPortal</button></div>`;
  const prompt = (key) => `<label class="f" style="margin-bottom:12px"><span>${key}</span>
    <textarea rows="5" data-path="prompts.${key}" placeholder="${esc(defaults[key])}">${esc(c.prompts?.[key] || "")}</textarea></label>`;
  main.innerHTML = `<div class="page"><div class="page-h"><h1>Settings</h1></div><div class="stack">
    <div class="card"><h3>AI: ChatGPT</h3>
      <div class="row" style="margin-bottom:8px">${account}</div>
      <p class="muted small" style="margin-top:0">JobPortal's AI runs on your ChatGPT plan (Go, Plus or Pro). Usage counts against your plan. Set a weekly cap for JobPortal in ChatGPT settings.
        Web search ${webSearchText}.</p>
      <label class="f" style="max-width:420px"><span>Default model</span><select data-path="ai.model">${modelOptions(models, c.ai.model, "First model your plan lists")}</select></label>
      <table class="t" style="margin-top:10px"><tbody>${Object.entries(c.ai.stages).map(stageRow).join("")}</tbody></table>
      <div class="grid3" style="margin-top:14px">${number("ai.max_parallel", "Parallel agents")}</div></div>
    <div class="card"><h3>Runs</h3>
      <div class="grid3">${number("run.min_score", "Min score to qualify (0 to 100)")}${number("run.max_triage", "Max candidates triaged per run")}
      ${number("run.triage_batch", "Triage batch size")}
      ${number("run.max_packages", "Max packages per run")}${number("run.max_age_days", "Ignore postings older than (days)")}${number("run.auto_run_hours", "Auto-run every N hours (0 = off)", 0.5)}</div>
      <div class="row" style="margin-top:12px">${toggle(`data-path="run.package_web_research" data-bool="1"`, c.run.package_web_research)}
        <span class="small">Packages do live web research (verify posting, company news, find contacts)</span></div></div>
    <div class="card"><h3>Resumes</h3>
      <div class="row" style="margin-bottom:10px">${toggle(`data-path="run.resume_review" data-bool="1"`, c.run.resume_review !== false)}
        <span class="small">Recruiter-critic pass on every tailored resume (fixes check issues, sharpens bullets; one more AI request each)</span></div>
      <label class="f"><span>Resume playbook (researched practices the generator follows: universal rules, layouts, industry archetypes)</span><textarea id="playbook" rows="14"></textarea></label>
      <div class="row" style="margin-top:8px"><span class="muted small" id="pb-state"></span><span class="spacer"></span>
        <button class="btn sm ghost" data-act="playbook-reset">Reset to researched default</button><button class="btn sm primary" data-act="playbook-save">Save playbook</button></div></div>
    <div class="card"><h3>Search area</h3><div class="row"><span class="chip" style="font-size:13px"><i class=i-pin></i> ${esc(areaSummary(c.locations.allowed))}</span>
      <span class="muted small">${c.locations.dream_bypass ? "Dream companies can be anywhere in the US. " : ""}Unknown locations:
        ${c.locations.unknown_policy === "ai" ? "AI decides" : "dropped"}.</span>
      <span class="spacer"></span><button class="btn primary" data-act="edit-area">Edit states, cities & remote</button></div></div>
    <div class="card"><h3>Industries</h3>
      <p class="muted small" style="margin-top:-4px">Every lead is tagged with one of these so you can filter and sort. Edit the list (one per line),
        save, then re-tag.</p>
      ${cfgLines("industries", "Industries", 8)}
      <div class="row" style="margin-top:8px"><button class="btn sm ai" data-act="retag-industries"><i class=i-ai></i> Re-tag all leads with AI</button></div></div>
    <div class="card"><h3>Dream companies & jobs</h3>
      <div class="row"><span class="small muted">Edit your dream companies, dream roles and their location rules on one page.</span><span class="spacer"></span>
        <a class="btn primary" href="#/dreams"><i class=i-star></i> Open Dream list</a></div></div>
    <div class="card"><h3>Filters</h3>
      <p class="muted small" style="margin-top:-4px">The title filters are generated from your experience levels and target roles each time you save your
        standard answers. Edit them here if you need to.</p>
      <div class="grid2">${cfgLines("filters.title_include", "Title must match one of (regex, blank = any title)", 8)}${cfgLines("filters.title_exclude", "Title must NOT match (regex)", 8)}
      ${cfgLines("filters.exclude_companies", "Never show these companies", 4)}${cfgLines("filters.exclude_keywords", "Drop if description contains", 4)}</div>
      <div class="row" style="margin-top:12px">${toggle(`data-path="filters.require_tech_title" data-bool="1"`, c.filters.require_tech_title)}
        <span class="small">Require a tech/science word in the title for job-board sources</span></div></div>
    <div class="card"><h3>Your data</h3>
      <p class="muted small" style="margin-top:-4px">Everything JobPortal stores (database, imported resume, generated files) lives in one folder on this
        computer, never in the code folder. Delete the folder to start over from zero.</p>
      <div class="row"><span class="mono small" style="flex:1;min-width:0;overflow-wrap:anywhere">${esc(S.meta.data_dir || "")}</span>
        <button class="btn sm" data-act="open-data">Open folder</button></div>
      ${quit}
      <div class="muted small" style="margin-top:8px">JobPortal ${esc(S.meta.version || "")} on ${esc(S.meta.os || "")}.
        PDF export: ${S.meta.pdf_ready ? "ready" : "needs Chrome, Edge or Chromium"}. ChatGPT: ${aiReady() ? "signed in" : "not signed in"}.</div></div>
    <div class="card"><h3>Prompts (advanced)</h3><p class="muted small" style="margin-top:-4px">Override the system prompts. Leave blank to use the built-in default (shown in gray).</p>
      ${Object.keys(defaults).map(prompt).join("")}</div>
    <div class="sticky-save"><button class="btn primary" data-act="save-cfg">Save settings</button></div></div></div>`;
  api("/api/resume-playbook").then((playbook) => showPlaybook(playbook, playbook.custom ? "custom playbook" : "researched default (Oct 2026)"));
}

// Fills the playbook box (a reply from GET /api/resume-playbook) with a note on which version it is.
function showPlaybook(playbook, note) {
  if (!$("#playbook")) return;  // you left Settings before it loaded
  $("#playbook").value = playbook.text;
  $("#pb-state").textContent = note;
}

// Saves only the playbook: the current settings from the server with the new playbook text. S.cfg gets the new text
// too, so "Save settings" afterwards doesn't put the old playbook back.
async function savePlaybook(text) {
  const cfg = await api("/api/settings");
  cfg.resume_playbook = text;
  await api("/api/settings", { method: "PUT", body: cfg });
  if (S.cfg) S.cfg.resume_playbook = text;
}

// ---------------------------------------------------------------- actions
onAction("quit", async () => {
  if (S.state.running && !confirm("A search is running. Quitting stops it; progress so far is saved.")) return;
  await api("/api/quit", { method: "POST" });
  S.quit = true;
  document.body.innerHTML = `<div class="empty" style="padding:64px"><b>JobPortal has quit</b>You can close this tab. Open JobPortal again to pick up where you left off.</div>`;
});
onAction("open-data", async () => {
  const r = await api("/api/open-data-folder", { method: "POST" });
  if (!r.ok) toast("Couldn't open the folder", r.path, "error");
});
onAction("playbook-save", async () => {
  await savePlaybook($("#playbook").value);
  $("#pb-state").textContent = "saved (custom)";
});
onAction("playbook-reset", async () => {
  if (!confirm("Replace your playbook with the researched default?")) return;
  await savePlaybook("");  // an empty playbook means "use the researched default"
  showPlaybook(await api("/api/resume-playbook"), "researched default");
});
onAction("retag-industries", async () => {
  if (!confirm("Re-tag the industry of every lead with AI (cheap model)?")) return;
  await api("/api/leads/retag-industries", { method: "POST" });
  toast("Re-tagging", "Industries update in a minute or two.");
});
