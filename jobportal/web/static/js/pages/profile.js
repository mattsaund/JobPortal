/* profile.js: Settings, Profile (#/settings/profile/<part>). The profile is built only from your resume, your documents,
   your standard answers and your answers to the questions asked along the way; every search, score and application is
   made from it. Here you can change all of it: the standard answers (the full form), the overview and its history, and
   the parts of the profile you can correct by hand (facts, skills, experience and projects, stories, targeting, your
   writing voice), plus your answers along the way and something new to tell JobPortal.
   APIs: GET /api/profile, GET /api/profile/overview, GET /api/onboarding, GET /api/questions, PUT /api/profile/{part},
   GET /api/profile/{part}/history, POST /api/profile/build, /sync-answers and /voice, PUT /api/onboarding/answers and
   POST /api/questions/answer. "profile" and "profile_status" events redraw it unless you have unsaved edits (live.js). */
"use strict";

// The parts, in order: [key, label, function that fills it]. Each function gets the part's box, the profile
// (GET /api/profile) and the key.
const PROFILE_PARTS = [
  ["answers", "Standard answers", renderAnswersPart],
  ["overview", "Overview and history", renderOverviewPart],
  ["facts", "Facts", renderFactsPart],
  ["skills", "Skills", renderSkillsPart],
  ["project_bank", "Experience and projects", renderTextPart],
  ["story_bank", "Stories", renderTextPart],
  ["targeting", "Targeting", renderTextPart],
  ["voice", "Writing voice", renderTextPart],
  ["questions", "Answers along the way", renderQuestionsPart],
];

// Draws the profile tab: the status line, the parts, and the open part. A "profile" event draws it again (live.js) only
// without unsaved edits; edits you start while it loads win too, and the tab stays as it is.
async function renderProfileSettings(box, part) {
  S.profileSection = PROFILE_PARTS.some(([key]) => key === part) ? part : "answers";
  const profile = (S.profileCache = await api("/api/profile"));
  if (S.route[1] !== "profile" || S.dirty) return;
  box.innerHTML = `<div class="profile-status" id="profile-status"></div>
    <div class="filters" role="group" aria-label="Parts of your profile">${PROFILE_PARTS.map(([key, label]) =>
      `<a class="chip${S.profileSection === key ? " active" : ""}" href="#/settings/profile/${key}"${S.profileSection === key ? ' aria-current="page"' : ""}>${label}</a>`).join("")}</div>
    <div id="profile-part"></div>`;
  renderProfileStatusLine();
  const current = PROFILE_PARTS.find(([key]) => key === S.profileSection);
  await current[2]($("#profile-part"), profile, S.profileSection);
}

// The line at the top: whether the profile is up to date, when it was built, and the buttons to add answers now or
// build it again. Also redrawn by "profile_status" events.
function renderProfileStatusLine() {
  const el = $("#profile-status");
  if (!el) return;
  const st = S.profileStatus || {};
  let state;
  if (st.busy) state = `${spinner()}<b>${esc(humanize(st.phase || "Updating"))}</b>`;
  else if (st.error) state = `<span class="status-dot bad"></span><b>The last update failed</b><small>${esc(st.error)}</small>`;
  else if (!st.built) state = `<span class="status-dot off"></span><b>Not built yet</b>`;
  else if (st.unsynced) state = `<span class="status-dot warn"></span><b>${plural(st.unsynced, "new answer")} to add</b>`;
  else state = `<span class="status-dot"></span><b>Up to date</b>`;
  el.innerHTML = `<div class="profile-state">${state}<small>Last built ${esc(fmtTs(st.last_built))}</small></div>
    ${st.unsynced ? `<button class="button light" type="button" data-act="sync-answers">${icon("sparkle")}Add answers now</button>` : ""}
    <button class="button outline" type="button" data-act="profile-build"${st.busy || !st.has_resume ? " disabled" : ""}>${icon("refresh")}Build again</button>`;
}

// Marks the part's edits as unsaved, so live updates leave it alone until you save or leave.
const trackEdits = (box) => box.addEventListener("input", () => (S.dirty = true));

// ---------------------------------------------------------------- standard answers
// The full standard questions form. Saving rebuilds the profile so the search follows.
async function renderAnswersPart(box) {
  const d = (S.onboarding = await api("/api/onboarding"));  // missingRequired() reads the question list from here
  box.innerHTML = `<p class="panel-note">These answers fill in every application kit and set your search: experience levels, the search area,
      dream companies and the title filters. Saving them rebuilds your profile so the search follows.</p>
    <div class="stack" id="answers-form">${answersForm(d.questions, d.answers, d.from_resume || [])}</div>
    <div class="save-bar"><span class="muted-note" id="answers-state"></span><button class="button primary" type="button" data-act="save-std-answers">Save answers</button></div>`;
  $("#answers-form").addEventListener("input", () => {
    S.dirty = true;
    $("#answers-state").textContent = "Not saved yet";
  });
}

// ---------------------------------------------------------------- overview and history
// Who you are, what the profile knows, what it has made, ways to improve it, and how it changed over time.
async function renderOverviewPart(box) {
  const d = await api("/api/profile/overview"), knows = d.knows, made = d.produced, id = d.identity;
  const tile = (n, label) => `<div class="mini-stat"><strong>${(n ?? 0).toLocaleString()}</strong><span>${label}</span></div>`;
  const facts = [id.location, id.authorization, id.clearance, id.gpa ? `GPA ${id.gpa}` : ""].filter(Boolean).map((x) => `<span class="tag">${esc(x)}</span>`).join("");
  const lookingFor = id.target_roles.length
    ? `<p><b>Looking for:</b> ${id.target_roles.map(esc).join(", ")}${id.levels ? ` (${esc(id.levels)})` : ""}</p>` : "";
  const plan = id.roles.length ? `<p class="panel-note">The search plan covers ${plural(id.roles.length, "kind")} of role: ${id.roles.slice(0, 8).map(esc).join(", ")}${id.roles.length > 8 ? ", and more" : ""}.</p>` : "";
  box.innerHTML = `<div class="stack">
    <section class="panel"><div class="profile-progress"><span class="avatar large">${esc(initials(id.name)) || icon("user")}</span>
      <div><strong>${esc(id.name || "Your profile")}</strong><p>${esc(id.headline || "")}${id.graduation ? `${id.headline ? ", " : ""}graduating ${esc(id.graduation)}` : ""}</p></div></div>
      ${facts ? `<div class="tags">${facts}</div>` : ""}${lookingFor}${plan}</section>
    <section class="panel"><h2>What your profile knows</h2><div class="mini-stats">
      ${tile(knows.jobs, "Jobs")}${tile(knows.projects, "Projects")}${tile(knows.skills_total, `Skills (${knows.skills.strong || 0} strong)`)}
      ${tile(knows.stories, "Interview stories")}${tile(knows.answers, "Standard answers")}${tile(knows.answered_questions, "Questions answered")}</div></section>
    <section class="panel"><h2>What it has made for you</h2><div class="mini-stats">
      ${tile(made.leads_scored, "Jobs read and scored")}${tile(made.resumes, "Tailored resumes")}${tile(made.cover_letters, "Cover letters")}
      ${tile(made.emails, "Emails written")}${tile(made.contacts, "People found")}${tile(made.answers + made.interview_preps + made.company_briefs, "Answers, preps and briefs")}</div></section>
    <section class="panel"><h2>History</h2>${(d.changelog || []).map(historyEntry).join("") || `<p class="muted-note">Nothing yet.</p>`}</section></div>`;
}

// One change to the profile: how (a build, an edit, added answers), when, why, and the first six things that changed.
function historyEntry(c) {
  const changes = (c.changes || []).slice(0, 6).map((x) => `<li>${esc(x)}</li>`).join("") || "<li>No real changes</li>";
  return `<div class="history-entry"><div class="history-head"><span class="tag ${c.mode === "build" ? "purple" : "blue"}">${esc(humanize(c.mode))}</span>
      <small>${esc(fmtTs(c.ts))}</small><span>${esc(c.reason || "")}</span><span class="spacer"></span>${c.tokens ? `<small>${fmtTokens(c.tokens)} tokens</small>` : ""}</div>
    <ul class="bullets">${changes}</ul></div>`;
}

// ---------------------------------------------------------------- the parts you can correct
// Facts: your contact details, education and eligibility, plus where each fact came from.
function renderFactsPart(box, profile) {
  const facts = profile.facts || {};
  const field = (path, label, wide) => `<label class="field${wide ? " wide" : ""}"><span class="field-label">${label}</span><input type="text" data-fact="${path}" value="${esc(getPath(facts, path) ?? "")}"></label>`;
  const source = (x) => `<tr><td>${esc(humanize(x.field))}</td><td>${esc(x.value)}</td><td>${esc(x.source)}</td><td class="nowrap">${esc(x.date)}</td></tr>`;
  box.innerHTML = `<div class="stack"><section class="panel"><div class="form-grid three">${field("name", "Name")}${field("email", "Email")}${field("phone", "Phone")}
      ${field("city", "City")}${field("state", "State")}${field("gpa", "GPA")}
      ${field("links.site", "Website")}${field("links.github", "GitHub")}${field("links.linkedin", "LinkedIn")}${field("school", "School")}${field("degree", "Degree")}${field("graduation", "Graduation")}
      ${field("work_authorization", "Work authorization", true)}${field("clearance", "Clearance", true)}</div>
      <label class="field"><span class="field-label">Skills (for matching)</span><textarea data-fact="skills" rows="3">${esc(facts.skills)}</textarea></label>
      <div class="block-actions end"><button class="button primary" type="button" data-act="save-facts">Save facts</button></div></section>
    ${settingsPanel("Where each fact came from", "Your standard answers win over what the resume says. Fixes you make here are kept when the profile is rebuilt, unless your resume or answers say otherwise.",
      `<div class="table-wrap"><table class="table"><thead><tr><th>Fact</th><th>Value</th><th>Source</th><th>Date</th></tr></thead><tbody>
      ${(profile.provenance || []).map(source).join("") || `<tr><td colspan="4" class="muted-note">Recorded when your profile is built.</td></tr>`}</tbody></table></div>`)}</div>`;
  trackEdits(box);
}

// Skills: every skill with its category, level and evidence. Edited in S.skills and redrawn from it.
function renderSkillsPart(box, profile) {
  S.skills = profile.skills_inventory || [];
  drawSkills(box);
  trackEdits(box);
}
function drawSkills(box = $("#profile-part")) {
  const row = (x, i) => `<tr><td><input type="text" data-sk="${i}" data-sf="skill" value="${esc(x.skill)}" aria-label="Skill"></td>
      <td><input type="text" data-sk="${i}" data-sf="category" value="${esc(x.category)}" aria-label="Category"></td>
      <td><select data-sk="${i}" data-sf="level" aria-label="Level">${selectOptions(["strong", "working", "listed"].map((l) => [l, humanize(l)]), x.level)}</select></td>
      <td><input type="text" data-sk="${i}" data-sf="evidence" value="${esc((x.evidence || []).join("; "))}" aria-label="Evidence"></td>
      <td><button class="icon-button" type="button" data-act="rm-skill" data-i="${i}" aria-label="Remove ${esc(x.skill)}">${icon("trash")}</button></td></tr>`;
  box.innerHTML = settingsPanel(`Skills (${S.skills.length})`, `Every skill from your resume, documents and answers. Tailored resumes may only claim skills
      listed here. <b>Strong</b>: used a lot in a job or project. <b>Working</b>: from courses or smaller use. <b>Listed</b>: only named somewhere (used
      only when a job asks for it). Your edits are kept when the profile is rebuilt.`,
    `<div class="table-wrap"><table class="table"><thead><tr><th>Skill</th><th>Category</th><th>Level</th><th>Evidence (separated by semicolons)</th>
      <th><span class="sr-only">Remove</span></th></tr></thead><tbody>${S.skills.map(row).join("")}</tbody></table></div>
    <div class="block-actions"><button class="button outline" type="button" data-act="add-skill">${icon("plus")}Add a skill</button><span class="spacer"></span>
      <button class="button primary" type="button" data-act="save-skills">Save skills</button></div>`);
}

// Reads the skills table back into S.skills. Evidence is a semicolon-separated list.
function readSkills() {
  $$("[data-sk]").forEach((el) => {
    const skill = S.skills[+el.dataset.sk];
    if (skill) skill[el.dataset.sf] = el.dataset.sf === "evidence" ? el.value.split(";").map((v) => v.trim()).filter(Boolean) : el.value;
  });
}

// What each written part of the profile is for.
const PROFILE_TEXT_HELP = {
  project_bank: "The record every resume is written from: education, every job (titles, dates, results), certifications and projects.",
  story_bank: "Stories about your work, told as situation, task, action and result. Used for interview prep and application answers.",
  targeting: "What you're looking for, plus the facts about whether you can take a job, and your dealbreakers. Every search reads it.",
  voice: "How you write, learned from the writing sample in your standard answers (Help it sound like you). Cover letters, emails and answers are written this way.",
};

// Experience and projects, Stories, Targeting and Writing voice: Markdown with a preview, and a menu that brings back an
// earlier version (GET /api/profile/{part}/history).
async function renderTextPart(box, profile, key) {
  const history = await api(`/api/profile/${key}/history`);
  const versions = history.length
    ? `<label class="control"><span>Earlier versions</span><select id="part-history">${selectOptions([["", "Pick one to bring back"], ...history.map((h) => [h.id, localStamp(h.saved_at)])])}</select></label>` : "";
  box.innerHTML = `<p class="panel-note">${PROFILE_TEXT_HELP[key]}</p>
    <div class="toolbar"><button class="button primary" type="button" data-act="save-part" data-k="${key}">Save</button>${versions}
      ${key === "voice" ? `<button class="button light" type="button" data-act="learn-voice">${icon("sparkle")}Learn it from my writing sample</button>` : ""}</div>
    <div class="editor"><textarea class="editor-text" id="part-text" aria-label="${esc(humanize(key))}">${esc(profile[key])}</textarea><div class="block prose editor-preview" id="part-preview"></div></div>`;
  const preview = () => ($("#part-preview").innerHTML = md($("#part-text").value));
  $("#part-text").addEventListener("input", debounce(preview, 200));
  preview();
  trackEdits(box);
  if (history.length) {
    $("#part-history").addEventListener("change", (e) => {
      const old = history.find((h) => h.id === +e.target.value);
      if (!old) return;
      $("#part-text").value = old.value;
      S.dirty = true;
      preview();
      toast("An earlier version is loaded", "Save to keep it.");
    });
  }
}

// ---------------------------------------------------------------- answers along the way
// Every answer to the questions asked along the way (with whether it's in the profile yet), and a box to tell JobPortal
// something new. The open questions are on Home.
async function renderQuestionsPart(box) {
  const questions = (S.questions = await api("/api/questions"));
  const open = questions.filter((q) => q.status === "open").length;
  const answered = questions.filter((q) => ["answered", "applied"].includes(q.status));
  const pending = answered.filter((q) => !q.synced).length;
  const answer = (q) => `<div class="copy-row"><span class="copy-q">${esc(q.question)}</span><span class="copy-a">${esc(q.answer || "")}</span>
      <span class="tag ${q.synced ? "green" : "warn"}" title="${q.synced ? "Part of your profile" : "Waiting to be added to your profile"}">${q.synced ? "In profile" : "Waiting"}</span></div>`;
  box.innerHTML = `<div class="stack">
    ${open ? `<div class="banner info">${icon("question")}<div>${plural(open, "question")} waiting on Home.</div><a class="button outline" href="#/home">Answer them</a></div>` : ""}
    ${settingsPanel("Tell JobPortal something new", "A project, a certificate, a skill or a result that isn't on your resume. It goes into your profile like any other answer.",
      `<div class="stack"><label class="field"><span class="field-label">What is it about?</span><input type="text" id="own-q" placeholder="A volunteer project, a new license, an award"></label>
        <label class="field"><span class="field-label">The details, in a sentence or two</span><textarea id="own-a" rows="3"></textarea></label>
        <div class="block-actions end"><button class="button primary" type="button" data-act="add-own-answer">Save</button></div></div>`)}
    ${settingsPanel(`Your answers (${answered.length})`, "Answers go into your profile by themselves, about a minute after you stop answering.",
      `${pending ? `<div class="block-actions"><button class="button light" type="button" data-act="sync-answers">${icon("sparkle")}Add ${pending} to my profile now</button></div>` : ""}
      ${answered.slice().reverse().map(answer).join("") || `<p class="muted-note">Nothing answered yet.</p>`}`)}</div>`;
  trackEdits(box);
}

// ---------------------------------------------------------------- actions
onAction("save-std-answers", async () => {
  const answers = readAnswersForm($("#answers-form"));
  const missing = missingRequired(answers);
  if (missing.length) {
    toast("A few answers are required", missing.join(", "), "error");
    return;
  }
  const r = await api("/api/onboarding/answers", { method: "PUT", body: { answers, build: true } });
  S.dirty = false;
  $("#answers-state").textContent = "Saved";
  onProfileStatus(r.status);
  toast("Answers saved", r.building ? "Your search follows them, and your profile is being rebuilt." : "Your search follows them.");
  reloadOnboarding();
  refreshSearchArea();
});
onAction("save-facts", async () => {
  // The facts the form doesn't show come from the profile as it is now. A "profile" event empties S.profileCache, and
  // while you have edits the tab isn't drawn again to fill it, so it's read again here.
  if (!S.profileCache) S.profileCache = await api("/api/profile");
  const facts = clone(S.profileCache.facts || {});
  $$("[data-fact]").forEach((input) => setPath(facts, input.dataset.fact, input.value));
  await api("/api/profile/facts", { method: "PUT", body: { value: facts } });
  S.dirty = false;
  toast("Saved", "Your facts are updated.");
});
onAction("save-part", async (el) => {
  await api(`/api/profile/${el.dataset.k}`, { method: "PUT", body: { value: $("#part-text").value } });
  S.dirty = false;
  toast("Saved", "The earlier version is kept in its history.");
});
onAction("add-skill", () => {
  readSkills();
  S.skills.push({ skill: "", category: "", level: "working", evidence: [] });
  drawSkills();
  S.dirty = true;
});
onAction("rm-skill", (el) => {
  readSkills();
  S.skills.splice(+el.dataset.i, 1);
  drawSkills();
  S.dirty = true;
});
onAction("save-skills", async () => {
  readSkills();
  await api("/api/profile/skills_inventory", { method: "PUT", body: { value: S.skills.filter((x) => x.skill.trim()) } });
  S.dirty = false;
  toast("Saved", "Your skills are updated.");
});
onAction("profile-build", async () => {  // Build again here, and Try again or Build it now on Home
  await api("/api/profile/build", { method: "POST" });
  toast("Building your profile", "Reading your resume, documents and answers again. A few minutes.");
});
onAction("sync-answers", async (el) => {  // add answers to the profile now instead of waiting
  await api("/api/profile/sync-answers", { method: "POST" });
  toast("Adding your answers", "Your profile updates in a minute or two.");
  el.disabled = true;
});
onAction("learn-voice", async (el) => {
  el.disabled = true;
  el.innerHTML = `${spinner()} Reading your writing`;
  try {
    const r = await api("/api/profile/voice", { method: "POST" });
    if (!r.ok) toast("Nothing to learn from yet", r.message, "error");
  } catch (err) {
    toast("Couldn't learn your voice", err.message, "error");
  }
  S.dirty = false;
  if (S.route[1] === "profile") renderSettings("profile", "voice");
});
onAction("add-own-answer", async () => {  // "Tell JobPortal something new" is saved like an answer to your own question
  const question = $("#own-q").value.trim(), answer = $("#own-a").value.trim();
  if (!question || !answer) {
    toast("Fill in both boxes", "What it's about, and the details.", "error");
    return;
  }
  await api("/api/questions/answer", { method: "POST", body: { question, answer } });
  S.dirty = false;
  toast("Saved", "It goes into your profile in about a minute.");
  renderSettings("profile", "questions");
});
