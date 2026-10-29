/* The Settings page: ChatGPT and AI models, search and filter settings, the resume playbook, prompts, your data and Quit. */
"use strict";

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

// ---------------------------------------------------------------- actions
onAction("save-cfg", async (el, e) => { await saveCfg(); });
onAction("add-chip", async (el, e) => { const inp = $(`[data-chipadd="${el.dataset.path}"]`); if (!inp.value.trim()) return; getPath(S.cfg, el.dataset.path).push(inp.value.trim()); await saveCfg(); renderSettings(); });
onAction("rm-chip", async (el, e) => { getPath(S.cfg, el.dataset.path).splice(+el.dataset.i, 1); await saveCfg(); renderSettings(); });
onAction("quit", async (el, e) => {
  if (S.state.running && !confirm("A search is running. Quitting stops it; progress so far is saved.")) return;
  await api("/api/quit", { method: "POST" });
  S.quit = true;
  document.body.innerHTML = `<div class="empty" style="padding:64px"><b>JobPortal has quit</b>You can close this tab. Open JobPortal again to pick up where you left off.</div>`;
});
onAction("open-data", async (el, e) => { const r = await api("/api/open-data-folder", { method: "POST" }); if (!r.ok) toast("Couldn't open the folder", r.path, "error"); });
onAction("playbook-save", async (el, e) => { const cfg = await api("/api/settings"); cfg.resume_playbook = $("#playbook").value; await api("/api/settings", { method: "PUT", body: cfg }); $("#pb-state").textContent = "saved (custom)"; });
onAction("playbook-reset", async (el, e) => { if (!confirm("Replace your playbook with the researched default?")) return; const cfg = await api("/api/settings"); cfg.resume_playbook = ""; await api("/api/settings", { method: "PUT", body: cfg }); const pb = await api("/api/resume-playbook"); $("#playbook").value = pb.text; $("#pb-state").textContent = "researched default"; });
onAction("retag-industries", async (el, e) => { if (confirm("Re-tag the industry of every lead with AI (cheap model)?")) { await api("/api/leads/retag-industries", { method: "POST" }); toast("Re-tagging", "Industries update in a minute or two."); } });
