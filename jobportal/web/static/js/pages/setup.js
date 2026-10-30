/* setup.js: the Set up page, shown until setup is done. Four steps: Continue with ChatGPT, import your resume, check the
   standard questions, and build your profile. These, plus the questions JobPortal asks along the way, are the only
   things JobPortal learns about you from.
   APIs: GET /api/onboarding (the questions, your answers, the imported resume and the status), GET /api/ai/status and
   PUT /api/onboarding/answers (saves the answers and starts the build). The resume drop zone is in
   components/file-drops.js and the questions form in components/answers-form.js. "profile_status" events update the
   build step (setupStatusChanged). */
"use strict";

const SETUP_STEPS = [["chatgpt", "Continue with ChatGPT"], ["resume", "Import your resume"], ["answers", "Answer the standard questions"], ["build", "Build your profile"]];

// Draws the page at the given step, or else at the step you were on, or else at the first step not done yet.
async function renderSetup(step) {
  const d = (S.onboarding = await api("/api/onboarding"));
  S.profileStatus = d.status;
  renderProfilePill();
  if (step) S.setupStep = step;
  try {
    S.state.ai = await api("/api/ai/status");
    renderAI();
  } catch (_) {}
  if (!SETUP_STEPS.some(([key]) => key === S.setupStep)) {
    S.setupStep = !aiReady() ? "chatgpt" : !d.resume ? "resume" : !d.answers_saved ? "answers" : "build";
  }
  const current = S.setupStep;
  const done = { chatgpt: aiReady(), resume: !!d.resume, answers: d.answers_saved, build: d.profile_built };
  const stepLink = ([key, label], i) => `<a class="step ${key === current ? "on" : ""} ${done[key] ? "done" : ""}" data-act="setup-step" data-step="${key}">`
    + `<span class="num">${done[key] && key !== current ? "<i class=i-check></i>" : i + 1}</span>${esc(label)}</a>`;
  main.innerHTML = `<div class="page setup"><div class="page-h"><h1>Set up JobPortal</h1>
      <span class="sub">Four steps. Your data stays on this computer. Each AI task sends OpenAI only what it needs, through your
        ChatGPT sign-in.</span></div>
    <div class="stepper">${SETUP_STEPS.map(stepLink).join("")}</div>
    <div id="setup-body"></div></div>`;
  const body = $("#setup-body");
  if (current === "chatgpt") {
    renderChatGPTStep(body);
  } else if (current === "resume") {
    renderResumeStep(body, d);
  } else if (current === "answers") {
    renderAnswersStep(body, d);
  } else {
    body.innerHTML = `<div class="card" id="build-card"></div>`;
    setupStatusChanged();
  }
}

// Step 1: sign in with ChatGPT (onAIStatus in layout.js moves on to step 2 when it's done).
function renderChatGPTStep(body) {
  const ai = S.state.ai || {};
  const signIn = ai.signed_in
    ? `<div class="banner"><div><i class=i-check></i> Signed in as <b>${esc(ai.email || ai.name || "your account")}</b>.</div>
      <span class="spacer"></span><button class="btn primary sm" data-act="setup-step" data-step="resume">Continue</button></div>`
    : `<button class="btn primary" data-act="ai-signin">Continue with ChatGPT</button>`;
  body.innerHTML = `<div class="card"><h3>Step 1: connect ChatGPT</h3>
      <p style="margin-top:0">JobPortal's AI runs on your own ChatGPT plan. Sign in once, and it reads your resume, scores jobs and writes your applications. It needs a ChatGPT Go, Plus or Pro plan.</p>
      <p class="muted small">ChatGPT shares only your name and email with JobPortal. Usage counts against your plan, and you can set a weekly cap for JobPortal in ChatGPT settings.</p>
      ${signIn}</div>`;
}

// Step 2: import your resume. Once the server has read it, its answers for the standard questions pre-fill step 3.
function renderResumeStep(body, d) {
  const current = d.resume
    ? `<div class="banner"><div><i class=i-doc></i> Using <b>${esc(d.resume.filename)}</b>, imported ${esc(fmtTs(d.resume.imported_at))}.</div>
      <span class="spacer"></span><button class="btn primary sm" data-act="setup-step" data-step="answers">Keep it and continue</button></div>`
    : "";
  body.innerHTML = `<div class="card"><h3>Step 2: your resume</h3>
      <p style="margin-top:0">JobPortal reads your resume to learn your experience, projects and skills. It's a source of facts, not a template: every resume it makes for a job is written fresh.</p>
      ${current}
      ${resumeDropzone(d.accept, d.resume ? "Or import a different resume" : "Drop your resume here")}</div>`;
  wireResumeDropzone(body, async (reply) => {
    S.prefill = reply.prefill || {};
    const filled = !(reply.prefill && reply.prefill._error);  // _error: the AI couldn't pre-fill
    toast("Resume read", filled ? "The standard questions are pre-filled from it. Check them." : "Couldn't pre-fill the questions with AI, so fill them in yourself.");
    renderSetup("answers");
  });
}

// Step 3: the standard questions, pre-filled from the resume until you save them once.
function renderAnswersStep(body, d) {
  const prefill = { ...(d.prefill || {}), ...(S.prefill || {}) };
  body.innerHTML = `<div class="card" style="margin-bottom:14px"><h3>Step 3: the standard questions</h3>
      <p style="margin:0">These are the questions almost every application asks. Answer them once: JobPortal uses them to search
        (roles, levels, locations), to fill in every Application kit, and to keep your resumes truthful. Fields marked "from resume" were
        read from your resume, so check them.</p></div>
      <div id="qform">${answersForm(d.questions, answersWithPrefill(d, prefill), d.answers_saved ? {} : prefill)}</div>
      <div class="sticky-save"><button class="btn ghost" data-act="setup-step" data-step="resume">Back</button><span class="spacer"></span>
        <span class="muted small" id="setup-state"></span><button class="btn primary" data-act="setup-save">Save and build my profile</button></div>`;
  $("#qform").addEventListener("input", () => (S.dirty = true));
}

// The answers to show: your saved answers and, until you've saved once, what the AI read from your resume for the
// questions still empty. Keys that start with "_" are notes from the server, not answers.
function answersWithPrefill(d, prefill) {
  const values = { ...d.answers };
  if (d.answers_saved) return values;
  for (const [key, value] of Object.entries(prefill)) {
    if (key.startsWith("_")) continue;
    const have = values[key];
    if (have == null || (Array.isArray(have) ? !have.length : !String(have).trim())) values[key] = value;
  }
  return values;
}

// Step 4: the build's progress, its error, or "done" with what to do next. Also called on every "profile_status" event.
function setupStatusChanged() {
  const card = $("#build-card");
  if (!card) return;
  const st = S.profileStatus || {};
  if (st.busy || (!st.built && !st.error)) {
    card.innerHTML = `<h3>Step 4: building your profile</h3><div class="row" style="margin:10px 0"><span class="spin"></span><b>${esc(st.phase || "Starting")}</b></div>
      <p class="muted" style="margin:0">The AI is reading your resume and answers and writing your profile: your experience record, skills
        inventory, interview stories and search plan. This usually takes 1 to 4 minutes. You can leave this page; it keeps going.</p>`;
  } else if (st.error) {
    card.innerHTML = `<h3>Step 4: building your profile</h3><div class="banner bad"><div><b>The build failed:</b> ${esc(st.error)}</div></div>
      <p class="muted small">Check that you're signed in with ChatGPT on a Go, Plus or Pro plan, then try again.</p>
      <div class="row"><button class="btn" data-act="ai-signin">Continue with ChatGPT</button><button class="btn primary" data-act="profile-build">Try again</button><button class="btn ghost" data-act="setup-step" data-step="answers">Back to the questions</button></div>`;
  } else {
    const questions = st.open_questions
      ? `<div class="banner accent"><div><b>${plural(st.open_questions, "question")}</b> would make your applications stronger. Answer them any time; your profile
        updates on its own.</div><span class="spacer"></span><a class="btn sm" href="#/profile/questions">Answer now</a></div>` : "";
    card.innerHTML = `<h3>Step 4: done</h3><div class="row" style="margin:6px 0 12px"><i class=i-check style="color:var(--good)"></i><b>Your profile is ready.</b></div>
      <p style="margin-top:0">Run your first search: JobPortal sweeps job boards, company career sites, social media and comment threads, scores
        every job against your profile, and writes a tailored application package for the best ones.</p>
      ${questions}
      <div class="row" style="margin-top:12px"><a class="btn primary" href="#/leads">Go to Leads and run a search</a><a class="btn" href="#/profile">Review my profile</a><a class="btn ghost" href="#/settings">Settings</a></div>`;
  }
}

// ---------------------------------------------------------------- actions
onAction("setup-step", (el) => {  // the stepper and the Continue / Back buttons
  // The questions and the build need a resume first.
  if (["chatgpt", "resume"].includes(el.dataset.step) || S.onboarding?.resume) renderSetup(el.dataset.step);
});
onAction("setup-save", async (el) => {  // saves the standard answers, then the server builds the profile
  const answers = readAnswersForm($("#qform"));
  const missing = missingRequired(answers);
  if (missing.length) {
    toast("A few answers are required", missing.join(", "), "error");
    return;
  }
  el.disabled = true;
  $("#setup-state").innerHTML = `<span class="spin"></span> Saving`;
  try {
    const r = await api("/api/onboarding/answers", { method: "PUT", body: { answers, build: true } });
    S.dirty = false;
    S.profileStatus = r.status;
    renderProfilePill();
    renderSetup("build");
  } catch (err) {
    toast("Couldn't save your answers", err.message, "error");
    el.disabled = false;
    $("#setup-state").textContent = "";
  }
});
