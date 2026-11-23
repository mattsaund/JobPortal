/* profile.js: Settings, Profile (#/settings/profile/<part>). The profile is built only from your resume, your documents,
   your standard answers and your answers to the questions asked along the way; every search, score and application is
   made from it. Each part has a tab and the whole screen: the standard answers, the overview and its history, the parts
   you can correct by hand (facts, skills, experience and projects, stories, targeting, your writing voice), and your
   extra answers, with a box to add something new. The Save bar saves the open part (setSaver in settings-form.js).
   APIs: GET /api/profile, GET /api/profile/overview, GET /api/onboarding, GET /api/questions, PUT /api/profile/{part},
   GET /api/profile/{part}/history, POST /api/profile/build, /sync-answers and /voice, PUT /api/onboarding/answers and
   POST /api/questions/answer. "profile" and "profile_status" events redraw it unless you have unsaved edits (live.js). */
"use strict";

// The parts, in order: [key, label, function that fills it]. Each function gets the part's box, the profile
// (GET /api/profile) and the key.
const PROFILE_PARTS = [
  ["answers", "Answers", renderAnswersPart],
  ["overview", "Overview", renderOverviewPart],
  ["facts", "Facts", renderFactsPart],
  ["skills", "Skills", renderSkillsPart],
  ["project_bank", "Experience", renderTextPart],
  ["story_bank", "Stories", renderTextPart],
  ["targeting", "Targeting", renderTextPart],
  ["voice", "Voice", renderTextPart],
  ["questions", "Extra answers", renderQuestionsPart],
];

// Draws the profile section: the tabs, the status at their right, and the open part. A "profile" event draws it again
// (live.js) only without unsaved edits; edits you start while it loads win too, and the section stays as it is.
async function renderProfileSettings(box, part) {
  S.profileSection = PROFILE_PARTS.some(([key]) => key === part) ? part : "answers";
  const profile = (S.profileCache = await api("/api/profile"));
  if (S.route[1] !== "profile" || S.dirty) return;
  box.innerHTML = `<div class="set-page">
    <div><div class="set-head"><nav class="tabs" aria-label="Profile">${PROFILE_PARTS.map(([key, label]) =>
      `<a class="tab${S.profileSection === key ? " active" : ""}" href="#/settings/profile/${key}"${S.profileSection === key ? ' aria-current="page"' : ""}>${label}</a>`).join("")}</nav>
      <div class="prof-status" id="profile-status"></div></div>
      <div class="banner bad" id="profile-error" role="alert" hidden></div></div>
    <div class="set-scroll" id="profile-part"></div></div>`;
  renderProfileStatusLine();
  setSaver();
  const current = PROFILE_PARTS.find(([key]) => key === S.profileSection);
  await current[2]($("#profile-part"), profile, S.profileSection);
}

// Whether the profile is up to date, when it was built, and the buttons to add answers now or build it again, with what
// went wrong in a line under the tabs when the last update failed. Also redrawn by "profile_status" events.
function renderProfileStatusLine() {
  const el = $("#profile-status");
  if (!el) return;
  const st = S.profileStatus || {};
  let state;
  if (st.busy) state = `${spinner()}<b>${esc(humanize(st.phase || "Updating"))}</b>`;
  else if (st.error) state = `<span class="status-dot bad"></span><b>Update failed</b>`;
  else if (!st.built) state = `<span class="status-dot off"></span><b>Not built</b>`;
  else if (st.unsynced) state = `<span class="status-dot warn"></span><b>${plural(st.unsynced, "new answer")}</b>`;
  else state = `<span class="status-dot"></span><b>Up to date</b>`;
  const built = st.last_built && !st.error ? `<small>${esc(fmtTs(st.last_built))}</small>` : "";
  const failed = $("#profile-error");
  failed.hidden = !st.error || !!st.busy;
  failed.textContent = st.error || "";
  el.innerHTML = `<span class="prof-state">${state}${built}</span>
    ${st.unsynced ? `<button class="button outline small" type="button" data-act="sync-answers">Add answers</button>` : ""}
    <button class="button outline small" type="button" data-act="profile-build"${st.busy || !st.has_resume ? " disabled" : ""}>${icon("refresh")}Rebuild</button>`;
}

// Marks the part's edits as unsaved, so live updates leave it alone until you save or leave.
const trackEdits = (box) => box.addEventListener("input", () => (S.dirty = true));

// ---------------------------------------------------------------- standard answers
// The full standard questions form. Saving rebuilds the profile so the search follows.
async function renderAnswersPart(box) {
  const d = (S.onboarding = await api("/api/onboarding"));  // missingRequired() reads the question list from here
  box.innerHTML = `<div class="set-flow" id="answers-form">${answersForm(d.questions, d.answers, d.from_resume || [])}</div>`;
  trackEdits($("#answers-form"));
  setSaver(saveAnswers);
}

async function saveAnswers() {
  const answers = readAnswersForm($("#answers-form"));
  const missing = missingRequired(answers);
  if (missing.length) {
    toast("Required", missing.join(", "), "error");
    return;
  }
  const r = await api("/api/onboarding/answers", { method: "PUT", body: { answers, build: true } });
  S.dirty = false;
  onProfileStatus(r.status);
  toast("Saved", r.building ? "Rebuilding profile" : "");
  reloadOnboarding();
  refreshSearchArea();
}

// ---------------------------------------------------------------- overview and history
// Who you are, what the profile knows, what it has made, and how it changed over time.
async function renderOverviewPart(box) {
  const d = await api("/api/profile/overview"), knows = d.knows, made = d.produced, id = d.identity;
  const stat = (n, label) => `<div><strong>${(n ?? 0).toLocaleString()}</strong><span>${label}</span></div>`;
  const tags = [id.location, id.authorization, id.clearance, id.gpa ? `GPA ${id.gpa}` : ""].filter(Boolean).map((x) => `<span class="tag">${esc(x)}</span>`).join("");
  const sub = [id.headline, id.graduation].filter(Boolean).map(esc).join(", ");
  const looking = [id.target_roles.length && `<dt>Targets</dt><dd>${id.target_roles.map(esc).join(", ")}${id.levels ? ` (${esc(id.levels)})` : ""}</dd>`,
    id.roles.length && `<dt>Search plan</dt><dd>${id.roles.slice(0, 8).map(esc).join(", ")}${id.roles.length > 8 ? ` +${id.roles.length - 8}` : ""}</dd>`].filter(Boolean).join("");
  box.innerHTML = `<section class="sect prof-who"><span class="avatar large">${esc(initials(id.name)) || icon("user")}</span>
      <div class="prof-who-main"><span class="row-title">${esc(id.name || "No name")}</span>${sub ? `<span class="row-sub">${sub}</span>` : ""}
        ${tags ? `<div class="tags">${tags}</div>` : ""}</div>
      ${looking ? `<dl class="facts">${looking}</dl>` : ""}</section>
    <div class="stat-strip prof-strip">${stat(knows.jobs, "Jobs")}${stat(knows.projects, "Projects")}${stat(knows.skills_total, "Skills")}
      ${stat(knows.stories, "Stories")}${stat(knows.answers, "Answers")}${stat(knows.answered_questions, "Questions")}</div>
    <div class="stat-strip prof-strip">${stat(made.leads_scored, "Jobs scored")}${stat(made.resumes, "Resumes")}${stat(made.cover_letters, "Cover letters")}
      ${stat(made.emails, "Emails")}${stat(made.contacts, "People")}${stat(made.answers + made.interview_preps + made.company_briefs, "Prep docs")}</div>
    ${setSect("History", (d.changelog || []).map(historyEntry).join("") || `<p class="muted">No changes yet</p>`)}`;
}

// One change to the profile: how (a build, an edit, added answers), when, why, and the first six things that changed.
function historyEntry(c) {
  const changes = (c.changes || []).slice(0, 6).map((x) => `<li>${esc(x)}</li>`).join("") || "<li>No changes</li>";
  return `<div class="prof-change"><div class="prof-change-head"><span class="tag ${c.mode === "build" ? "purple" : "blue"}">${esc(humanize(c.mode))}</span>
      <small>${esc(fmtTs(c.ts))}</small><span>${esc(c.reason || "")}</span><span class="spacer"></span>${c.tokens ? `<small>${fmtTokens(c.tokens)} tokens</small>` : ""}</div>
    <ul class="bullets">${changes}</ul></div>`;
}

// ---------------------------------------------------------------- the parts you can correct
// Facts: your contact details, education and eligibility, plus where each fact came from.
function renderFactsPart(box, profile) {
  const facts = profile.facts || {};
  const field = (path, label) => optRow(label, `<input type="text" data-fact="${path}" value="${esc(getPath(facts, path) ?? "")}">`, true);
  const source = (x) => `<div class="row"><span class="row-main"><span class="row-title">${esc(x.value)}</span>
    <span class="row-sub">${esc([humanize(x.field), x.source, x.date].filter(Boolean).join(", "))}</span></span></div>`;
  box.innerHTML = `<div class="set-split">
    <div class="set-flow">
      ${setSect("Contact", field("name", "Name") + field("email", "Email") + field("phone", "Phone") + field("city", "City") + field("state", "State")
        + field("links.site", "Website") + field("links.linkedin", "LinkedIn") + field("links.github", "GitHub"))}
      ${setSect("Education", field("school", "School") + field("degree", "Degree") + field("graduation", "Graduation") + field("gpa", "GPA"))}
      ${setSect("Eligibility", field("work_authorization", "Work authorization") + field("clearance", "Clearance"))}
      ${setSect("Matching", optRow("Skills", `<textarea data-fact="skills" rows="4">${esc(facts.skills)}</textarea>`, true))}
    </div>
    <aside class="set-rail">${setSect("Sources", (profile.provenance || []).length ? `<div class="rows">${profile.provenance.map(source).join("")}</div>` : `<p class="muted">No sources yet</p>`)}</aside></div>`;
  trackEdits(box);
  setSaver(saveFacts);
}

async function saveFacts() {
  // The facts the form doesn't show come from the profile as it is now. A "profile" event empties S.profileCache, and
  // while you have edits the section isn't drawn again to fill it, so it's read again here.
  if (!S.profileCache) S.profileCache = await api("/api/profile");
  const facts = clone(S.profileCache.facts || {});
  $$("[data-fact]").forEach((input) => setPath(facts, input.dataset.fact, input.value));
  await api("/api/profile/facts", { method: "PUT", body: { value: facts } });
  S.dirty = false;
  toast("Saved");
}

// Skills: every skill with its category, level and evidence. Edited in S.skills and redrawn from it.
function renderSkillsPart(box, profile) {
  S.skills = profile.skills_inventory || [];
  drawSkills(box);
  trackEdits(box);
  setSaver(saveSkills);
}
function drawSkills(box = $("#profile-part")) {
  const row = (x, i) => `<tr><td><input type="text" data-sk="${i}" data-sf="skill" value="${esc(x.skill)}" aria-label="Skill"></td>
      <td><input type="text" data-sk="${i}" data-sf="category" value="${esc(x.category)}" aria-label="Category"></td>
      <td><select data-sk="${i}" data-sf="level" aria-label="Level">${selectOptions(["strong", "working", "listed"].map((l) => [l, humanize(l)]), x.level)}</select></td>
      <td><input type="text" data-sk="${i}" data-sf="evidence" value="${esc((x.evidence || []).join("; "))}" aria-label="Evidence"></td>
      <td><button class="icon-button" type="button" data-act="rm-skill" data-i="${i}" aria-label="Remove ${esc(x.skill)}" title="Remove">${icon("trash")}</button></td></tr>`;
  box.innerHTML = `<div class="toolbar sticky"><b>${plural(S.skills.length, "skill")}</b><span class="spacer"></span>
      <button class="button outline small" type="button" data-act="add-skill">${icon("plus")}Add skill</button></div>
    <div class="table-wrap"><table class="table prof-skills"><thead><tr><th>Skill</th><th>Category</th><th>Level</th><th>Evidence</th>
      <th><span class="sr-only">Remove</span></th></tr></thead><tbody>${S.skills.map(row).join("")}</tbody></table></div>`;
}

// Reads the skills table back into S.skills. Evidence is a semicolon-separated list.
function readSkills() {
  $$("[data-sk]").forEach((el) => {
    const skill = S.skills[+el.dataset.sk];
    if (skill) skill[el.dataset.sf] = el.dataset.sf === "evidence" ? el.value.split(";").map((v) => v.trim()).filter(Boolean) : el.value;
  });
}

async function saveSkills() {
  readSkills();
  await api("/api/profile/skills_inventory", { method: "PUT", body: { value: S.skills.filter((x) => x.skill.trim()) } });
  S.dirty = false;
  toast("Saved");
}

// Experience, Stories, Targeting and Voice: Markdown with a preview, and a menu that brings back an earlier version
// (GET /api/profile/{part}/history).
async function renderTextPart(box, profile, key) {
  const history = await api(`/api/profile/${key}/history`);
  const versions = history.length
    ? `<select id="part-history" aria-label="Earlier versions">${selectOptions([["", "Earlier versions"], ...history.map((h) => [h.id, localStamp(h.saved_at)])])}</select>` : "";
  const learn = key === "voice" ? `<button class="button outline small" type="button" data-act="learn-voice">${icon("sparkle")}Learn voice</button>` : "";
  box.innerHTML = `<div class="prof-text">${versions || learn ? `<div class="toolbar">${versions}${learn}</div>` : ""}
    <div class="prof-editor"><textarea id="part-text" aria-label="${esc(humanize(key))}">${esc(profile[key])}</textarea>
      <div class="prose" id="part-preview"></div></div></div>`;
  const preview = () => ($("#part-preview").innerHTML = md($("#part-text").value));
  $("#part-text").addEventListener("input", debounce(preview, 200));
  preview();
  trackEdits(box);
  setSaver(() => savePart(key));
  if (history.length) {
    $("#part-history").addEventListener("change", (e) => {
      const old = history.find((h) => h.id === +e.target.value);
      if (!old) return;
      $("#part-text").value = old.value;
      S.dirty = true;
      syncSaveBar();
      preview();
      toast("Version loaded");
    });
  }
}

async function savePart(key) {
  await api(`/api/profile/${key}`, { method: "PUT", body: { value: $("#part-text").value } });
  S.dirty = false;
  toast("Saved");
}

// ---------------------------------------------------------------- extra answers
// Every answer to the questions asked along the way (with whether it's in the profile yet), and a box to tell JobPortal
// something new. The open questions are on Home.
async function renderQuestionsPart(box) {
  const questions = (S.questions = await api("/api/questions"));
  const open = questions.filter((q) => q.status === "open").length;
  const answered = questions.filter((q) => ["answered", "applied"].includes(q.status));
  const pending = answered.filter((q) => !q.synced).length;
  const answer = (q) => `<div class="row prof-answer"><span class="row-main"><span class="row-title">${esc(q.question)}</span><span class="row-sub">${esc(q.answer || "")}</span></span>
      <span class="row-end"><span class="tag ${q.synced ? "green" : "warn"}">${q.synced ? "In profile" : "Waiting"}</span></span></div>`;
  const sync = pending ? `<button class="button outline small" type="button" data-act="sync-answers">${icon("sparkle")}Add ${pending}</button>` : "";
  box.innerHTML = `<div class="set-split">
    <div>${open ? `<div class="banner">${icon("question")}<span>${plural(open, "open question")}</span><span class="spacer"></span><a class="text-button" href="#/home">Home</a></div>` : ""}
      ${setSect(`Answers <small>${answered.length}</small>`, answered.length ? `<div class="rows">${answered.slice().reverse().map(answer).join("")}</div>` : `<p class="muted">No answers yet</p>`, sync)}</div>
    <aside class="set-rail">${setSect("Add", `<div class="prof-add"><label class="field"><span class="field-label">Topic</span><input type="text" id="own-q" placeholder="A license or award"></label>
      <label class="field"><span class="field-label">Details</span><textarea id="own-a" rows="6"></textarea></label></div>`)}</aside></div>`;
  trackEdits(box);
  setSaver(saveOwnAnswer);
}

// Something new you told JobPortal, saved like an answer to your own question.
async function saveOwnAnswer() {
  const question = $("#own-q").value.trim(), answer = $("#own-a").value.trim();
  if (!question || !answer) {
    toast("Topic and details required", "", "error");
    return;
  }
  await api("/api/questions/answer", { method: "POST", body: { question, answer } });
  S.dirty = false;
  toast("Saved");
  renderSettings("profile", "questions");
}

// ---------------------------------------------------------------- actions
onAction("add-skill", () => {
  readSkills();
  S.skills.push({ skill: "", category: "", level: "working", evidence: [] });
  drawSkills();
  S.dirty = true;
  syncSaveBar();
  $$('[data-sf="skill"]').at(-1)?.focus();
});
onAction("rm-skill", (el) => {
  readSkills();
  S.skills.splice(+el.dataset.i, 1);
  drawSkills();
  S.dirty = true;
  syncSaveBar();
});
onAction("profile-build", async () => {  // Rebuild here, and Retry or Build on Home
  await api("/api/profile/build", { method: "POST" });
  toast("Building profile");
});
onAction("sync-answers", async (el) => {  // add answers to the profile now instead of waiting
  await api("/api/profile/sync-answers", { method: "POST" });
  toast("Adding answers");
  el.disabled = true;
});
onAction("learn-voice", async (el) => {
  el.disabled = true;
  el.innerHTML = `${spinner()} Reading`;
  try {
    const r = await api("/api/profile/voice", { method: "POST" });
    if (!r.ok) toast("No writing sample", r.message, "error");
  } catch (err) {
    toast("Couldn't learn voice", err.message, "error");
  }
  S.dirty = false;
  if (S.route[1] === "profile") renderSettings("profile", "voice");
});
