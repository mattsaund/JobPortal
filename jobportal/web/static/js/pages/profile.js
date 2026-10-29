/* The Profile page: overview, facts, the experience record, stories, skills, search plan, voice, standard answers and the
   questions JobPortal asks along the way. */
"use strict";

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
function readSkills() {
  $$("[data-sk]").forEach((el) => { const x = S.skInv[+el.dataset.sk]; if (!x) return; x[el.dataset.sf] = el.dataset.sf === "evidence" ? el.value.split(";").map((v) => v.trim()).filter(Boolean) : el.value; });
}

// ---------------------------------------------------------------- actions
onAction("save-facts", async (el, e) => { const f = clone(S.profileCache.facts); $$("[data-fp]").forEach((i) => setPath(f, i.dataset.fp, i.value)); await api("/api/profile/facts", { method: "PUT", body: { value: f } }); toast("Saved", "Facts updated"); });
onAction("save-ptext", async (el, e) => { await api(`/api/profile/${el.dataset.k}`, { method: "PUT", body: { value: $("#ptext").value } }); toast("Saved", "Previous version kept in history"); });
onAction("profile-build", async (el, e) => { await api("/api/profile/build", { method: "POST" }); toast("Rebuilding your profile", "Reading your resume and answers again. A few minutes."); });
onAction("sync-answers", async (el, e) => { await api("/api/profile/sync-answers", { method: "POST" }); toast("Adding your answers", "Your profile updates in a minute or two."); el.disabled = true; });
onAction("learn-voice", async (el, e) => {
  el.disabled = true; el.innerHTML = `<span class="spin"></span> Reading your writing`;
  try { const r = await api("/api/profile/voice", { method: "POST" }); if (!r.ok) toast("Nothing to learn from yet", r.message, "error"); }
  catch (err) { toast("Couldn't learn your voice", err.message, "error"); }
  if (S.route[0] === "profile") renderProfile(S.ptab);
});
onAction("save-std-answers", async (el, e) => {
  const answers = readAnswersForm($("#qform"));
  const miss = missingRequired(answers); if (miss.length) { toast("A few answers are required", miss.join(", "), "error"); return; }
  const r = await api("/api/onboarding/answers", { method: "PUT", body: { answers, build: true } });
  S.dirty = false; $("#ans-tab-state").textContent = "saved"; S.pstatus = r.status; renderProfilePill();
  toast("Answers saved", r.building ? "Your search settings are updated and your profile is rebuilding." : "Your search settings are updated.");
});
onAction("answer-q", async (el, e) => {
  const q = S.openQs[+el.dataset.i], ans = $(`[data-qans="${el.dataset.i}"]`).value.trim(); if (!ans) return;
  await api("/api/questions/answer", { method: "POST", body: { question: q.question, answer: ans } }); toast("Answer saved", "It's added to your profile about a minute after you stop answering."); renderProfile("questions"); });
onAction("add-own-answer", async (el, e) => {
  const q = $("#own-q").value.trim(), ans = $("#own-a").value.trim(); if (!q || !ans) { toast("Fill in both boxes", "What it's about, and the details.", "error"); return; }
  await api("/api/questions/answer", { method: "POST", body: { question: q, answer: ans } }); toast("Saved", "It's added to your profile in about a minute."); renderProfile("questions"); });
onAction("dismiss-q", async (el, e) => { await api("/api/questions/dismiss", { method: "POST", body: { question: S.openQs[+el.dataset.i].question } }); S.questions = await api("/api/questions"); renderNav(); renderProfile("questions"); });
onAction("save-plan", async (el, e) => {
  const lines = (id) => $(id).value.split("\n").map((x) => x.trim()).filter(Boolean);
  await api("/api/profile/search_plan", { method: "PUT", body: { value: { role_families: lines("#sp-roles"), queries: lines("#sp-queries"), dream_companies: lines("#sp-cos"), notes: $("#sp-notes").value } } });
  toast("Saved", "Search plan updated, used on the next run"); });
onAction("add-skill", async (el, e) => { readSkills(); S.skInv.push({ skill: "", category: "Languages", level: "working", evidence: [] }); S.skDraw(); });
onAction("rm-skill", async (el, e) => { readSkills(); S.skInv.splice(+el.dataset.i, 1); S.skDraw(); });
onAction("save-skills", async (el, e) => { readSkills(); await api("/api/profile/skills_inventory", { method: "PUT", body: { value: S.skInv.filter((x) => x.skill.trim()) } }); toast("Saved", "Skills inventory updated"); });
