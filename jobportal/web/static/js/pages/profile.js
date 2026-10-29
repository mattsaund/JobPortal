/* profile.js: the Profile page (#/profile, or #/profile/questions to open a tab). The profile is built from three
   things only: your imported resume, your standard answers, and your answers to the questions JobPortal asks along the
   way. Every search, score and document comes from it. Tabs: an overview, the resume, the standard answers, the
   questions, and the parts of the profile you can correct by hand (facts, skills, experience and projects, stories,
   targeting, the search plan and your writing voice).
   APIs: GET /api/profile, GET /api/profile/overview, GET /api/onboarding, GET /api/questions, PUT /api/profile/{part},
   GET /api/profile/{part}/history, POST /api/profile/build, /sync-answers and /voice, PUT /api/onboarding/answers,
   POST /api/questions/answer and /dismiss. "profile", "profile_status" and "questions" events redraw it (live.js). */
"use strict";

// The tabs in order: [key, label, function that fills the tab]. Each function gets the tab's box, the profile
// (GET /api/profile) and the tab key.
const PTABS = [
  ["overview", "Overview", renderProfileOverview],
  ["resume", "Resume", renderResumeTab],
  ["answers", "Standard answers", renderAnswersTab],
  ["questions", "Questions", renderQuestionsTab],
  ["facts", "Facts", renderFactsTab],
  ["skills", "Skills inventory", renderSkillsTab],
  ["project_bank", "Experience & projects", renderProfileTextTab],
  ["story_bank", "Story bank", renderProfileTextTab],
  ["targeting", "Targeting", renderProfileTextTab],
  ["search_plan", "Search plan", renderSearchPlanTab],
  ["voice", "Voice", renderProfileTextTab],
];

// True while you're typing an answer on the Questions tab, so a live update doesn't wipe it.
const questionDraft = () => $$("[data-qans], #own-q, #own-a").some((el) => el.value.trim());

// Draws the page and the open tab (the one named, else the last one you opened).
async function renderProfile(tab) {
  S.profileTab = tab || S.profileTab || "overview";
  S.dirty = false;  // whatever was on screen is redrawn
  const profile = (S.profileCache = await api("/api/profile"));
  const openQuestions = (S.questions || []).filter((q) => q.status === "open").length;
  const tabLink = ([key, label]) => `<a class="${S.profileTab === key ? "on" : ""}" href="#/profile/${key}">`
    + `${label}${key === "questions" && openQuestions ? `<span class="n">${openQuestions}</span>` : ""}</a>`;
  main.innerHTML = `<div class="page"><div class="page-h"><h1>Profile</h1>
    <span class="sub">Built from your resume, your standard answers and your answers to questions along the way. Every search, score
      and document comes from here.</span></div>
    <div class="tabs">${PTABS.map(tabLink).join("")}</div><div id="pbody"></div></div>`;
  const current = PTABS.find(([key]) => key === S.profileTab);
  if (current) await current[2]($("#pbody"), profile, S.profileTab);
}

// Marks the tab's edits as unsaved, so live updates leave it alone until you save or leave.
const trackEdits = (box) => box.addEventListener("input", () => (S.dirty = true));

// ---------------------------------------------------------------- overview
// Overview: who you are, whether the profile is up to date, what it knows, what it has made, ways to improve it, its
// history, your writing voice and your resume. Reads GET /api/profile/overview.
async function renderProfileOverview(box) {
  const d = await api("/api/profile/overview"), st = d.status || {};
  if (!st.has_resume && !st.answers_saved) {
    box.innerHTML = `<div class="empty"><b>Your profile is empty</b>Import your resume and answer the standard job questions to
      build it.<div style="margin-top:12px"><a class="btn primary" href="#/setup">Set up</a></div></div>`;
    return;
  }
  const knows = d.knows, made = d.produced;
  // A number tile that links to where you can see or change it.
  const tile = (n, label, href) => `<a class="tile" ${href ? `href="${href}"` : ""} style="text-decoration:none"><div class="n">${(n ?? 0).toLocaleString()}</div><div class="l">${label}</div></a>`;
  const tiles = (html) => `<div class="tiles" style="grid-template-columns:repeat(6,minmax(0,1fr))">${html}</div>`;
  const help = (text, label, href) => `<div class="row"><span style="flex:1">${text}</span><a class="btn sm" href="${href}">${label}</a></div>`;
  const openQuestions = knows.open_questions
    ? `<b>${knows.open_questions}</b> open question${knows.open_questions > 1 ? "s" : ""} would strengthen your applications` : "No open questions right now";
  box.innerHTML = `<div class="stack">
    ${profileHero(d.identity, st)}
    <div><h3 class="sect">What your profile knows</h3>${tiles(`
      ${tile(knows.jobs, "Jobs", "#/profile/project_bank")}${tile(knows.projects, "Projects", "#/profile/project_bank")}
      ${tile(knows.skills_total, `Skills (${knows.skills.strong || 0} strong)`, "#/profile/skills")}${tile(knows.stories, "Interview stories", "#/profile/story_bank")}
      ${tile(knows.answers, "Standard answers", "#/profile/answers")}${tile(knows.answered_questions, "Questions answered", "#/profile/questions")}`)}</div>
    <div><h3 class="sect">What it has made for you</h3>${tiles(`
      ${tile(made.leads_scored, "Jobs read and scored", "#/leads")}${tile(made.resumes, "Tailored resumes", "#/leads")}${tile(made.cover_letters, "Cover letters", "#/leads")}
      ${tile(made.emails, "Emails drafted", "#/leads")}${tile(made.contacts, "Contacts researched", "#/contacts")}
      ${tile(made.answers + made.interview_preps + made.company_briefs, "Answers, preps and briefs", "#/leads")}`)}</div>
    <div class="cols" style="grid-template-columns:minmax(0,1.2fr) minmax(0,1fr)">
      <div class="stack">
        <div class="card"><h3>Help it know you better</h3><div class="stack" style="gap:8px">
          ${help(openQuestions, "Answer", "#/profile/questions")}
          ${help("Tell it about a project, skill or result that isn't on your resume", "Add", "#/profile/questions")}
          ${help("Import a newer resume when yours changes", "Resume", "#/profile/resume")}
          ${help("Change what you're looking for: roles, levels, locations", "Answers", "#/profile/answers")}</div></div>
        <div class="card"><h3>History</h3>${(d.changelog || []).map(historyEntry).join("") || `<div class="muted small">Nothing yet.</div>`}</div></div>
      <div class="stack">
        ${voiceCard(d)}
        <div class="card"><h3>Resume</h3>
          ${d.resume ? `<div class="row"><i class=i-doc></i><b style="min-width:0;overflow-wrap:anywhere">${esc(d.resume.filename)}</b></div>
          <div class="small muted" style="margin-top:4px">imported ${esc(fmtTs(d.resume.imported_at))}</div>` : `<span class="muted">none yet</span>`}
          <div class="row" style="margin-top:10px"><a class="btn sm" href="#/profile/resume">${d.resume ? "Replace or view" : "Import"}</a></div></div></div></div></div>`;
}

// The top card: your initials, name, headline, key facts and what you're looking for, plus the build status with the
// "Add answers now" and "Rebuild" buttons.
function profileHero(id, st) {
  const initials = (id.name || "?").split(/\s+/).filter(Boolean).map((word) => word[0]).slice(0, 2).join("").toUpperCase() || "?";
  const facts = [id.location, id.authorization, id.clearance, id.gpa ? `GPA ${id.gpa}` : ""].filter(Boolean).map((x) => `<span class="chip">${esc(x)}</span>`).join("");
  const lookingFor = id.target_roles.length
    ? `<div class="small" style="margin-top:8px"><span class="muted">Looking for:</span>
      ${id.target_roles.map(esc).join(", ")}${id.levels ? ` <span class="muted">(${esc(id.levels)})</span>` : ""} <a href="#/profile/answers">edit</a></div>` : "";
  const plan = id.roles.length
    ? `<div class="small muted" style="margin-top:4px">Search plan covers ${id.roles.length} kinds of roles:
      ${id.roles.slice(0, 8).map(esc).join(", ")}${id.roles.length > 8 ? ", and more" : ""}. <a href="#/profile/search_plan">edit</a></div>` : "";
  let state, color;
  if (st.busy) [state, color] = [`<span class="spin"></span> ${esc(st.phase || "Updating")}`, "var(--ai)"];
  else if (st.error) [state, color] = [`<i class=i-warn></i> Last update failed`, "var(--bad)"];
  else if (!st.built) [state, color] = [`<i class=i-dot></i> Not built yet`, "var(--warn)"];
  else if (st.unsynced) [state, color] = [`<i class=i-dot></i> ${plural(st.unsynced, "new answer")} to add`, "var(--warn)"];
  else [state, color] = ["<i class=i-check></i> Up to date", "var(--good)"];
  return `<div class="card profile-hero"><div class="ph-id"><div class="monogram">${esc(initials)}</div>
        <div style="min-width:0"><h2>${esc(id.name || "Your profile")}</h2><div class="muted">${esc(id.headline || "")}${id.graduation ? `${id.headline ? ", " : ""}graduation ${esc(id.graduation)}` : ""}</div>
          <div class="row" style="gap:6px;margin-top:8px">${facts}</div>
          ${lookingFor}
          ${plan}</div></div>
      <div class="ph-sync"><div class="mono" style="font-weight:700;color:${color}">${state}</div>
        <div class="small muted" style="margin:4px 0 10px">last built ${esc(fmtTs(st.last_built))}</div>
        <div class="row" style="gap:6px;justify-content:flex-end">${st.unsynced ? `<button class="btn sm ai" data-act="sync-answers"><i class=i-ai></i> Add answers now</button>` : ""}
          <button class="btn sm" data-act="profile-build" ${st.busy || !st.has_resume ? "disabled" : ""}><i class=i-refresh></i> Rebuild</button></div></div></div>`;
}

// One profile history entry: how it changed (a build, an edit, added answers), when, why, and the first six changes.
function historyEntry(c) {
  const changes = (c.changes || []).slice(0, 6).map((x) => `<li>${esc(x)}</li>`).join("") || "<li class='muted'>no material changes</li>";
  return `<div style="padding:8px 0;border-bottom:1px solid var(--line)"><div class="row small"><span class="chip ${c.mode === "build" ? "violet" : "blue"}">${esc(c.mode)}</span><span class="mono muted">${esc(fmtTs(c.ts))}</span>
      <span class="muted">${esc(c.reason || "")}</span><span class="spacer"></span>${c.tokens ? `<span class="muted mono">${fmtTokens(c.tokens)} tokens</span>` : ""}</div>
          <ul class="clean small" style="margin-top:6px">${changes}</ul></div>`;
}

// The Voice card: your writing voice once it's learned, else how to get one (a writing sample in Standard answers).
function voiceCard(d) {
  const edit = d.voice_learned ? `<a class="btn sm ghost" href="#/profile/voice">Edit</a>` : "";
  const learn = d.has_sample
    ? `<button class="btn sm ${d.voice_learned ? "" : "primary"}" data-act="learn-voice">${d.voice_learned ? "<i class=i-refresh></i> Re-learn" : "<i class=i-ai></i> Learn my voice"}</button>` : "";
  const hint = d.has_sample ? "Click Learn my voice so cover letters and emails sound like you."
    : `Paste a writing sample (a past cover letter works well) in <a href="#/profile/answers">Standard answers</a> and cover letters, emails and answers will sound like you.`;
  return `<div class="card"><div class="row" style="margin-bottom:6px"><h3 style="margin:0">Voice</h3><span class="spacer"></span>
            ${edit}${learn}</div>
          ${d.voice_learned ? `<div class="md voice-md">${md(d.voice)}</div>` : `<p class="muted" style="margin:0">${hint}</p>`}</div>`;
}

// ---------------------------------------------------------------- resume, answers and questions
// Resume: the imported resume, a drop zone to import a newer one (which rebuilds the profile), and the text read from it.
async function renderResumeTab(box) {
  const d = await api("/api/onboarding");
  const r = d.resume;
  // The server sends the first 4,000 characters it read.
  const readText = esc(d.resume_preview || "Nothing yet.") + ((r?.chars || 0) > 4000 ? "\n\n(first 4,000 characters shown)" : "");
  const current = r ? `<div class="row"><i class=i-doc></i><b>${esc(r.filename)}</b><span class="muted small">imported ${esc(fmtTs(r.imported_at))}, ${(r.chars || 0).toLocaleString()} characters</span></div>
        <p class="muted small">JobPortal reads this resume as a source of facts. It never uses it as a template: every tailored resume is written fresh from your profile.</p>`
    : `<p class="muted">No resume imported yet.</p>`;
  box.innerHTML = `<div class="cols"><div class="stack">
      <div class="card"><h3>Your resume</h3>${current}
        ${resumeDropzone(d.accept, r ? "Import a newer resume" : "Import your resume")}</div>
      <div class="card"><h3>Rebuild</h3>
        <p class="muted small" style="margin-top:-4px">Reads your resume, standard answers and every answer again. Edits you made by hand are kept
          unless something newer contradicts them.</p>
        <button class="btn" data-act="profile-build" ${r ? "" : "disabled"}><i class=i-refresh></i> Rebuild profile</button></div></div>
    <div class="card"><h3>Text JobPortal read from it</h3><pre class="jd" style="max-height:70vh">${readText}</pre></div></div>`;
  wireResumeDropzone(box, async () => {
    toast("Resume imported", "Rebuilding your profile with it now.");
    await api("/api/profile/build", { method: "POST" });
    renderProfile("resume");
  }, { prefill: false });
}

// Standard answers: the same form as setup. Saving rebuilds the profile so the search plan follows.
async function renderAnswersTab(box) {
  const d = (S.onboarding = await api("/api/onboarding"));  // missingRequired() reads the question list from here
  box.innerHTML = `<div class="card" style="margin-bottom:14px"><p class="muted small" style="margin:0">These answers fill in every Application kit and set your search: experience
      levels, locations, dream companies and the title filters. Saving rebuilds your profile so the search plan follows.</p></div>
    <div id="qform">${answersForm(d.questions, d.answers, {})}</div>
    <div class="sticky-save"><span class="muted small" id="ans-tab-state"></span><button class="btn primary" data-act="save-std-answers">Save answers</button></div>`;
  $("#qform").addEventListener("input", () => {
    S.dirty = true;
    $("#ans-tab-state").textContent = "unsaved";
  });
}

// Questions: the open questions to answer or dismiss, a box to tell JobPortal something new, and every answer so far
// (with whether it's in the profile yet). Reads GET /api/questions.
async function renderQuestionsTab(box) {
  const questions = (S.questions = await api("/api/questions"));
  const open = questions.filter((q) => q.status === "open");
  const answered = questions.filter((q) => ["answered", "applied"].includes(q.status));
  const pending = answered.filter((q) => !q.synced).length;
  S.openQuestions = open;
  // Where a question came from: a lead's application (with a link) or another source. Profile questions get no chip.
  const origin = (q) => {
    if (q.source === "profile") return "";
    if (q.lead_id) return `<a class="chip blue" style="margin-left:4px" href="#/lead/${q.lead_id}">for ${esc(String(q.source || "").replace(/ application$/, ""))} <i class=i-ext></i></a>`;
    return q.source ? `<span class="chip blue" style="margin-left:4px">from ${esc(q.source)}</span>` : "";
  };
  const openItem = (q, i) => `<div class="mission-ed"><div><b>${esc(q.question)}</b></div>
          <div class="small muted">${esc(q.why)} ${q.field ? `<span class="chip" style="margin-left:4px">${esc(q.field)}</span>` : ""}${origin(q)}</div>
          <textarea rows="2" data-qans="${i}" placeholder="Your answer" style="font-size:13px"></textarea>
          <div class="row"><button class="btn sm primary" data-act="answer-q" data-i="${i}">Save answer</button><button class="btn sm ghost" data-act="dismiss-q" data-i="${i}">Not relevant</button></div></div>`;
  const answer = (q) => `<div class="copyrow" style="grid-template-columns:1fr 1fr auto"><div class="q">${esc(q.question)}</div><div class="a">${esc(q.answer || "")}</div>
        <span class="chip ${q.synced ? "good" : "warn"}" title="${q.synced ? "Part of your profile" : "Waiting to be added to your profile"}">${q.synced ? "in profile" : "pending"}</span></div>`;
  box.innerHTML = `<div class="cols"><div class="stack">
      <div class="card"><h3>Open questions (${open.length})</h3>
        <p class="muted small" style="margin-top:-4px">Gaps JobPortal found while building your profile and your applications. Answers are added
          to your profile automatically about a minute after you stop answering.</p>
        <div class="stack">${open.map(openItem).join("") || `<div class="muted">No open questions right now.</div>`}</div></div>
      <div class="card"><h3>Tell JobPortal something new</h3>
        <p class="muted small" style="margin-top:-4px">A project, a certification, a skill or a result that isn't on your resume. It goes into
          your profile like any other answer.</p>
        <input type="text" id="own-q" placeholder="What is it about? (e.g. Kubernetes experience, a hackathon win)" style="width:100%;margin-bottom:8px">
        <textarea id="own-a" rows="3" placeholder="The details, in a sentence or two" style="font-size:13px;width:100%"></textarea>
        <div class="row" style="margin-top:8px"><span class="spacer"></span><button class="btn primary sm" data-act="add-own-answer">Save</button></div></div></div>
    <div class="card"><div class="row" style="margin-bottom:8px"><h3 style="margin:0">Your answers (${answered.length})</h3><span class="spacer"></span>
        ${pending ? `<button class="btn sm ai" data-act="sync-answers"><i class=i-ai></i> Add ${pending} to my profile now</button>` : ""}</div>
      ${answered.slice().reverse().map(answer).join("") || `<div class="muted small">Nothing answered yet.</div>`}</div></div>`;
}

// ---------------------------------------------------------------- parts you can correct by hand
// Facts: your contact details, education and eligibility, plus where each fact came from.
function renderFactsTab(box, profile) {
  const facts = profile.facts || {};
  const field = (path, label, span) => `<label class="f" ${span ? `style="grid-column:span ${span}"` : ""}><span>${label}</span><input type="text" data-fp="${path}" value="${esc(getPath(facts, path) ?? "")}"></label>`;
  const source = (x) => `<tr><td class="mono small">${esc(x.field)}</td><td>${esc(x.value)}</td><td class="small">${esc(x.source)}</td><td class="mono small">${esc(x.date)}</td></tr>`;
  box.innerHTML = `<div class="stack"><div class="card"><div class="grid3">${field("name", "Name")}${field("email", "Email")}${field("phone", "Phone")}
      ${field("city", "City")}${field("state", "State")}${field("gpa", "GPA")}
      ${field("links.site", "Website")}${field("links.github", "GitHub")}${field("links.linkedin", "LinkedIn")}${field("school", "School")}${field("degree", "Degree")}${field("graduation", "Graduation")}
      ${field("work_authorization", "Work authorization", 3)}${field("clearance", "Clearance", 3)}</div>
      <label class="f" style="margin-top:14px"><span>Skills (for matching)</span><textarea data-fp="skills" rows="3">${esc(facts.skills)}</textarea></label>
      <div class="row" style="justify-content:flex-end;margin-top:12px"><button class="btn primary" data-act="save-facts">Save facts</button></div></div>
      <div class="card"><h3>Where each fact came from</h3>
      <p class="muted small" style="margin-top:-4px">Your standard answers override what the resume says. Quick fixes here are kept when the
        profile is rebuilt, unless your resume or answers say otherwise.</p>
      <table class="t"><thead><tr><th>Field</th><th>Value</th><th>Source</th><th>Source date</th></tr></thead><tbody>
      ${(profile.provenance || []).map(source).join("") || `<tr><td colspan="4" class="muted">Recorded when your profile is built.</td></tr>`}</tbody></table></div></div>`;
  trackEdits(box);
}

// Skills inventory: every skill with its category, level and evidence. Edited in S.skills, redrawn by S.drawSkills.
function renderSkillsTab(box, profile) {
  S.skills = profile.skills_inventory || [];
  const row = (x, i) => `<tr><td><input type="text" data-sk="${i}" data-sf="skill" value="${esc(x.skill)}"></td><td><input type="text" data-sk="${i}" data-sf="category" value="${esc(x.category)}"></td>
        <td><select data-sk="${i}" data-sf="level">${selectOptions(["strong", "working", "listed"], x.level)}</select></td>
        <td><input type="text" data-sk="${i}" data-sf="evidence" value="${esc((x.evidence || []).join("; "))}"></td>
        <td><button class="btn sm ghost danger" data-act="rm-skill" data-i="${i}"><i class=i-x></i></button></td></tr>`;
  S.drawSkills = () => (box.innerHTML = `<div class="card"><p class="muted small" style="margin-top:0">Every skill from your resume and your answers. Tailored resumes may only list skills from here.
      <b>strong</b>: used substantially in a documented job or project. <b>working</b>: coursework or smaller use. <b>listed</b>: only appears in a list (used only when a posting asks
      for it). Rebuilt with your profile; your edits are kept.</p>
      <table class="t"><thead><tr><th>Skill</th><th>Category</th><th>Level</th><th>Evidence (semicolon-separated)</th><th></th></tr></thead><tbody>
      ${S.skills.map(row).join("")}</tbody></table>
      <div class="row" style="margin-top:12px"><button class="btn" data-act="add-skill">+ Add skill</button><span class="spacer"></span>
        <span class="muted small">${S.skills.length} skills</span><button class="btn primary" data-act="save-skills">Save inventory</button></div></div>`);
  S.drawSkills();
  trackEdits(box);
}

// Reads the skills table back into S.skills. Evidence is a semicolon-separated list.
function readSkills() {
  $$("[data-sk]").forEach((el) => {
    const skill = S.skills[+el.dataset.sk];
    if (!skill) return;
    skill[el.dataset.sf] = el.dataset.sf === "evidence" ? el.value.split(";").map((v) => v.trim()).filter(Boolean) : el.value;
  });
}

// Search plan: the role families, search queries and target companies the search goes after.
function renderSearchPlanTab(box, profile) {
  const plan = profile.search_plan || {};
  const list = (id, label, items) => `<label class="f"><span>${label}</span><textarea id="${id}" rows="14">${esc((items || []).join("\n"))}</textarea></label>`;
  box.innerHTML = `<div class="card"><p class="muted small" style="margin-top:0">What the search goes after, derived from your resume and answers and regenerated on each rebuild (your edits are kept unless your answers say
      otherwise). It's combined with your extra queries in Sources and your dream companies.</p>
      <div class="grid3">${list("sp-roles", "Role families (ranked)", plan.role_families)}
      ${list("sp-queries", "Search queries", plan.queries)}
      ${list("sp-cos", "Target companies", plan.dream_companies)}</div>
      <label class="f" style="margin-top:12px"><span>Strategy note</span><input type="text" id="sp-notes" value="${esc(plan.notes || "")}"></label>
      <div class="row" style="justify-content:flex-end;margin-top:12px"><button class="btn primary" data-act="save-plan">Save search plan</button></div></div>`;
  trackEdits(box);
}

// What each Markdown part of the profile is for.
const PROFILE_TEXT_HELP = {
  project_bank: "The record every resume is composed from: education, every job (titles, dates, metrics), certifications and projects. Built from your resume and answers.",
  story_bank: "Interview stories in STAR form, used for interview prep and application answers.",
  targeting: "What you're looking for, plus eligibility facts and dealbreakers. Triage reads this on every run.",
  voice: "How you write, learned from the writing sample in your standard answers. Cover letters, emails, LinkedIn notes and application answers are written in this voice.",
};

// Experience & projects, Story bank, Targeting and Voice: Markdown with a preview, and a menu to bring back an earlier
// version (GET /api/profile/{part}/history).
async function renderProfileTextTab(box, profile, key) {
  const history = await api(`/api/profile/${key}/history`);
  const versions = history.length
    ? `<select id="phist" style="width:auto">${selectOptions([["", "Restore a previous version"], ...history.map((h) => [h.id, localStamp(h.saved_at)])])}</select>` : "";
  box.innerHTML = `<div class="toolbar"><button class="btn primary" data-act="save-ptext" data-k="${key}">Save</button>
      ${versions}
      ${key === "voice" ? `<button class="btn" data-act="learn-voice"><i class=i-ai></i> Learn from my writing sample</button>` : ""}
      <span class="muted small">${PROFILE_TEXT_HELP[key]}</span></div>
      <div class="editor"><textarea id="ptext">${esc(profile[key])}</textarea><div class="card md" id="pprev" style="max-height:78vh;overflow:auto"></div></div>`;
  const preview = () => ($("#pprev").innerHTML = md($("#ptext").value));
  $("#ptext").oninput = debounce(preview, 200);
  preview();
  trackEdits(box);
  if (history.length) {
    $("#phist").onchange = (e) => {
      const old = history.find((h) => h.id === +e.target.value);
      if (!old) return;
      $("#ptext").value = old.value;
      S.dirty = true;
      preview();
      toast("Loaded old version", "Save to keep it.");
    };
  }
}

// ---------------------------------------------------------------- actions
onAction("save-facts", async () => {
  const facts = clone(S.profileCache.facts);
  $$("[data-fp]").forEach((input) => setPath(facts, input.dataset.fp, input.value));
  await api("/api/profile/facts", { method: "PUT", body: { value: facts } });
  S.dirty = false;
  toast("Saved", "Facts updated");
});
onAction("save-ptext", async (el) => {
  await api(`/api/profile/${el.dataset.k}`, { method: "PUT", body: { value: $("#ptext").value } });
  S.dirty = false;
  toast("Saved", "Previous version kept in history");
});
onAction("save-plan", async () => {
  const lines = (id) => $(id).value.split("\n").map((x) => x.trim()).filter(Boolean);
  const plan = { role_families: lines("#sp-roles"), queries: lines("#sp-queries"), dream_companies: lines("#sp-cos"), notes: $("#sp-notes").value };
  await api("/api/profile/search_plan", { method: "PUT", body: { value: plan } });
  S.dirty = false;
  toast("Saved", "Search plan updated, used on the next run");
});
onAction("add-skill", () => {
  readSkills();
  S.skills.push({ skill: "", category: "Languages", level: "working", evidence: [] });
  S.drawSkills();
  S.dirty = true;
});
onAction("rm-skill", (el) => {
  readSkills();
  S.skills.splice(+el.dataset.i, 1);
  S.drawSkills();
  S.dirty = true;
});
onAction("save-skills", async () => {
  readSkills();
  await api("/api/profile/skills_inventory", { method: "PUT", body: { value: S.skills.filter((x) => x.skill.trim()) } });
  S.dirty = false;
  toast("Saved", "Skills inventory updated");
});
onAction("profile-build", async () => {  // Rebuild (also on setup's "Try again")
  await api("/api/profile/build", { method: "POST" });
  toast("Rebuilding your profile", "Reading your resume and answers again. A few minutes.");
});
onAction("sync-answers", async (el) => {  // add answered questions to the profile now instead of waiting
  await api("/api/profile/sync-answers", { method: "POST" });
  toast("Adding your answers", "Your profile updates in a minute or two.");
  el.disabled = true;
});
onAction("learn-voice", async (el) => {
  el.disabled = true;
  el.innerHTML = `<span class="spin"></span> Reading your writing`;
  try {
    const r = await api("/api/profile/voice", { method: "POST" });
    if (!r.ok) toast("Nothing to learn from yet", r.message, "error");
  } catch (err) {
    toast("Couldn't learn your voice", err.message, "error");
  }
  if (S.route[0] === "profile") renderProfile(S.profileTab);
});
onAction("save-std-answers", async () => {
  const answers = readAnswersForm($("#qform"));
  const missing = missingRequired(answers);
  if (missing.length) {
    toast("A few answers are required", missing.join(", "), "error");
    return;
  }
  const r = await api("/api/onboarding/answers", { method: "PUT", body: { answers, build: true } });
  S.dirty = false;
  $("#ans-tab-state").textContent = "saved";
  S.profileStatus = r.status;
  renderProfilePill();
  toast("Answers saved", r.building ? "Your search settings are updated and your profile is rebuilding." : "Your search settings are updated.");
});
onAction("answer-q", async (el) => {
  const question = S.openQuestions[+el.dataset.i];
  const answer = $(`[data-qans="${el.dataset.i}"]`).value.trim();
  if (!answer) return;
  await api("/api/questions/answer", { method: "POST", body: { question: question.question, answer } });
  toast("Answer saved", "It's added to your profile about a minute after you stop answering.");
  renderProfile("questions");
});
onAction("add-own-answer", async () => {  // "Tell JobPortal something new" is saved like an answer to your own question
  const question = $("#own-q").value.trim(), answer = $("#own-a").value.trim();
  if (!question || !answer) {
    toast("Fill in both boxes", "What it's about, and the details.", "error");
    return;
  }
  await api("/api/questions/answer", { method: "POST", body: { question, answer } });
  toast("Saved", "It's added to your profile in about a minute.");
  renderProfile("questions");
});
onAction("dismiss-q", async (el) => {
  await api("/api/questions/dismiss", { method: "POST", body: { question: S.openQuestions[+el.dataset.i].question } });
  S.questions = await api("/api/questions");
  renderNav();
  renderProfile("questions");
});
