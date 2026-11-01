/* home.js: the Home page (#/home), where JobPortal starts.
   - Before you sign in with ChatGPT: a welcome that says what JobPortal does, the plan it needs, a big "Continue with
     ChatGPT" button and the three steps. The "ai" event swaps it for the dashboard as soon as you're signed in.
   - After: the dashboard. The stats (leads ready, applications sent, interviews); "Questions for you", a feed that shows
     one thing at a time (your resume, what JobPortal read from it, the standard questions still empty, the profile
     build, then the questions asked along the way); your top leads; and on the right your profile's progress, your
     documents (components/documents.js) and where the search looks.
   APIs: GET /api/onboarding, PATCH /api/onboarding/answers (each answer saves on its own), GET /api/leads (the five best
   ready leads), GET /api/settings (the search area), POST /api/questions/answer and /dismiss, POST /api/profile/build.
   Live events redraw the parts that changed (live.js). A card you're answering stays as it is through them, and an
   answer you've typed counts as an unsaved edit until it's saved, skipped or dismissed. */
"use strict";

// The optional standard questions Home asks after the required ones, in this order: the ones that most improve the
// search and fill in the most application forms. Every question, these included, is in Settings, Profile.
const RECOMMENDED = ["locations", "job_types", "experience_years", "education_level", "field_of_study", "licenses", "phone", "linkedin",
  "start_date"];
// Home never asks from these sections: voluntary self-identification, and "Help it sound like you". They stay in Settings.
const NOT_ON_HOME = ["eeo", "about"];
// The answers the search area is made from (LOCATION_ANSWERS in candidate/onboarding.py): saving one can change it.
const AREA_ANSWERS = ["locations", "anywhere_us", "work_modes", "state"];

// Follow-up questions answered or dismissed since Home opened, for "2 of 5".
let followUpsDone = 0;

// ---------------------------------------------------------------- the page
// Draws Home: the welcome before you sign in, the dashboard after.
async function renderHome() {
  main.dataset.page = "home";
  if (!aiReady()) {
    main.innerHTML = welcomeHtml();
    return;
  }
  followUpsDone = 0;
  homeShowsRunning = S.state.running;  // drawn for the run state as it is now (see homeRunChanged)
  main.innerHTML = `<div class="page-heading"><div><p class="eyebrow">YOUR JOB SEARCH</p><h1 id="home-title"></h1><p id="home-sub"></p></div>
      <span class="semester" id="home-status"></span></div>
    <div class="dashboard-layout">
      <section class="primary-column" aria-label="Your job search">
        <div class="stats" id="home-stats"></div>
        <div class="section-heading"><div><h2>Questions for you</h2><p>One at a time. Every answer makes your matches better.</p></div></div>
        <div class="feed" id="home-feed"></div>
        <div class="section-heading"><div><h2>Top leads</h2><p>Your best matches, ready to apply.</p></div>
          <a class="text-button" href="#/leads" data-act="leads-tab" data-tab="ready">View all leads ${icon("arrow")}</a></div>
        <div class="job-list" id="home-leads"></div>
      </section>
      <aside class="right-column" aria-label="Your profile and documents">
        <section class="panel profile-panel" id="home-profile"></section>
        <section class="panel" id="home-docs"></section>
        <section class="panel" id="home-area"></section>
      </aside>
    </div>`;
  homeDataChanged();
  renderHomeStats();
  await Promise.all([loadTopLeads(), reloadOnboarding()]);
}

// The welcome before you sign in with ChatGPT.
function welcomeHtml() {
  const step = (n, title, text) => `<li class="step-card"><span class="step-num">${n}</span><h3>${title}</h3><p>${text}</p></li>`;
  return `<div class="welcome">
    <div class="page-heading"><div><p class="eyebrow">WELCOME TO JOBPORTAL</p><h1>Find the jobs that fit you.</h1>
      <p>JobPortal looks for jobs wherever they're posted, ranks each one against your experience, and writes a tailored resume
        and cover letter for the best ones. It works for any field and any level.</p></div></div>
    <section class="welcome-hero">
      <div><span class="eyebrow">START HERE</span><h2>Sign in with ChatGPT</h2>
        <p>JobPortal's AI runs on your own ChatGPT account, so there's nothing else to buy or set up. You need a ChatGPT Go, Plus
          or Pro plan.</p></div>
      <button class="button primary big" type="button" data-act="ai-signin">Continue with ChatGPT ${icon("arrow")}</button>
      <p class="privacy-note">ChatGPT shares only your name and email with JobPortal. Your files stay on this computer, and each AI
        task sends only what it needs.</p>
    </section>
    <ol class="steps">
      ${step(1, "Sign in with ChatGPT", "One click. Usage counts against your plan, and you can set a limit in ChatGPT's settings.")}
      ${step(2, "Drop your resume and documents", "Your resume, plus any certificates, licenses, awards or transcripts you have.")}
      ${step(3, "Answer a few questions", "What you want and where. Most answers are filled in from your resume.")}
    </ol></div>`;
}

// ---------------------------------------------------------------- the data behind it
// Reloads GET /api/onboarding (your answers, the main resume, the documents) and redraws what shows them.
async function reloadOnboarding() {
  try {
    S.onboarding = await api("/api/onboarding");
  } catch (_) {
    return;
  }
  S.documents = S.onboarding.documents || [];
  if (S.onboarding.status) onProfileStatus(S.onboarding.status);  // it comes along, so the frame never lags behind
  renderUserButton();
  renderNextStep();
  if (S.route[0] === "home") homeDataChanged();
}

// Reloads the search area and the industry list from Settings.
async function refreshSearchArea() {
  const cfg = await api("/api/settings");
  S.searchArea = cfg.locations.allowed;
  S.industries = cfg.industries;
  if (S.route[0] === "home") renderAreaPanel();
}

// Every standard question by id, with the id of its section.
function questionFields() {
  const fields = {};
  (S.onboarding?.questions || []).forEach((section) => section.fields.forEach((f) => (fields[f.id] = { ...f, section: section.id })));
  return fields;
}

// The standard questions Home still has to ask, in order: the required ones still empty, then the recommended ones still
// empty that you haven't skipped. total counts every question Home asks, for "3 of 7".
function standardQueue() {
  const ob = S.onboarding;
  if (!ob) return { ids: [], total: 0 };
  const fields = questionFields(), skipped = store.list("homeSkipped");
  const recommended = RECOMMENDED.filter((id) => fields[id] && !fields[id].required && !NOT_ON_HOME.includes(fields[id].section));
  const required = (ob.required || []).filter((id) => fields[id]);
  const waiting = recommended.filter((id) => !filled(ob.answers[id]) && !skipped.includes(id));
  return { ids: [...(ob.missing || []).filter((id) => fields[id]), ...waiting], total: required.length + recommended.length };
}

// The answers JobPortal read from your resume that you haven't checked yet, in the order the questions come.
function fromResumeIds() {
  const order = Object.keys(questionFields()), unchecked = S.onboarding?.from_resume || [];
  return order.filter((id) => unchecked.includes(id));
}

// What to put in an empty answer to begin with: your name and email from your ChatGPT account.
const suggestion = (id) => ({ name: S.state.ai?.name, email: S.state.ai?.email })[id] || "";

// The questions asked along the way that are still open.
const openFollowUps = () => (S.questions || []).filter((q) => q.status === "open");

// How many things Home needs from you before the next search (the sidebar card says "Answer N questions"): the required
// questions, checking what was read from your resume, and the questions asked along the way. Optional ones don't count.
const homeWaiting = () => (S.onboarding?.missing || []).length + (fromResumeIds().length ? 1 : 0) + openFollowUps().length;

// ---------------------------------------------------------------- the heading and the stats
function renderHomeHeading() {
  const title = $("#home-title");
  if (!title) return;
  const first = yourName().split(/\s+/)[0];
  const st = S.profileStatus || {}, ob = S.onboarding || {};
  title.textContent = first ? `Welcome, ${first}.` : "Welcome to JobPortal.";
  $("#home-sub").textContent = S.state.running ? "A search is running. New leads show up here as they're ready."
    : !ob.resume ? "Start with your resume. The rest takes a few minutes."
    : (ob.missing || []).length ? "A few questions and you're ready to search."
    : st.built ? "Here's where your search stands." : "Your profile is almost ready.";
  // The pill on the right: whether the profile is up to date. (setHtml: redrawn only when it changes, so its spinner
  // doesn't restart on every status event.)
  let pill = `<span class="status-dot"></span>Profile up to date`;
  if (st.busy) pill = `${spinner()}Updating your profile`;
  else if (st.error) pill = `<span class="status-dot bad"></span>Profile update failed`;
  else if (!st.built) pill = `<span class="status-dot off"></span>Profile not built yet`;
  else if (st.unsynced) pill = `<span class="status-dot warn"></span>${plural(st.unsynced, "answer")} to add`;
  setHtml($("#home-status"), pill);
}

// The three stats. Each one opens where its number comes from.
function renderHomeStats() {
  const el = $("#home-stats");
  if (!el) return;
  const s = S.stats || {};
  const stat = (href, tab, value, label, note, name, tint) => `<a class="stat" href="${href}"${tab ? ` data-act="leads-tab" data-tab="${tab}"` : ""}>`
    + `<span class="stat-icon ${tint}">${icon(name)}</span><span><strong>${value ?? 0}</strong><b>${label}</b><small>${note}</small></span>${icon("arrow")}</a>`;
  setHtml(el, stat("#/leads", "ready", s.ready, "Leads ready", "Ranked and tailored for you", "briefcase", "")
    + stat("#/tracker", "", s.applied, "Applications sent", `${s.applied_week ?? 0} in the last 7 days`, "file", "blue")
    + stat("#/tracker", "", s.interviewing, "Interviews", s.accepted ? `${s.accepted} accepted` : "Going on now", "people", "purple"));
}

// ---------------------------------------------------------------- questions for you
// The cards in the feed, in order: the drop zone (until there's a resume), the profile build (while it runs, when it
// failed, or just after it's done), then the one thing to do next. Each card has a key; keep marks the ones with inputs,
// which stay as they are (with whatever you typed) while their key stays the same. The resume card is kept too: its
// file picker may be open, and a new card in its place would lose the files you pick.
function feedCards() {
  const cards = [];
  if (!S.onboarding?.resume) cards.push({ key: "resume", keep: true, html: resumeCard() });
  const build = buildCard();
  if (build) cards.push(build);
  const next = nextCard();
  if (next) cards.push(next);
  return cards;
}

// Redraws the feed, keeping the cards whose key hasn't changed, so an answer being typed is never wiped. A card you've
// typed in is marked data-edited (see the input listener at the bottom); S.dirty says whether one is still on screen,
// so it clears itself when that card goes (saved, skipped, dismissed, or answered in another window).
function renderFeed() {
  const box = $("#home-feed");
  if (!box) return;
  const shown = new Map($$(":scope > [data-key]", box).map((el) => [el.dataset.key, el]));
  box.replaceChildren(...feedCards().map((card) => {
    let el = card.keep && shown.get(card.key);
    if (!el) {
      const template = document.createElement("template");
      template.innerHTML = card.html.trim();
      el = template.content.firstElementChild;
      el.dataset.key = card.key;
    }
    if (card.progress) $(".feed-progress", el).textContent = card.progress;
    return el;
  }));
  S.dirty = !!$("[data-edited]", box);
}

// The one thing to do next: check what was read from your resume, answer a standard question, answer a question asked
// along the way, or nothing: all caught up once the profile is built (before that, the resume or the build card above is
// the next thing).
function nextCard() {
  const fields = questionFields();
  const fromResume = fromResumeIds();
  if (fromResume.length) return { key: `from-resume:${fromResume.join(",")}`, keep: true, html: fromResumeCard(fromResume, fields) };
  const queue = standardQueue();
  if (queue.ids.length) {
    const id = queue.ids[0];
    return { key: `q:${id}`, keep: true, html: questionCard(fields[id]), progress: `QUESTION ${queue.total - queue.ids.length + 1} OF ${queue.total}` };
  }
  const open = openFollowUps();
  if (open.length) {
    return { key: `f:${open[0].question}`, keep: true, html: followUpCard(open[0]),
      progress: `FOLLOW-UP ${followUpsDone + 1} OF ${followUpsDone + open.length}` };
  }
  const caughtUp = S.onboarding?.resume && S.profileStatus?.built && !S.buildDone;  // "Your profile is ready" says it already
  return caughtUp ? { key: "caught-up", html: caughtUpCard() } : null;
}

// Before there's a resume: the big drop zone.
function resumeCard() {
  return `<article class="feed-card">
    <div class="feed-top"><span class="eyebrow">START HERE</span></div>
    <h3>Add your resume</h3>
    <p>Drop your resume and anything else that shows what you've done. JobPortal reads them all to learn your experience,
      and fills in most of your answers from your resume.</p>
    ${documentsDropZone(true)}
    <div class="feed-actions"><button class="text-button" type="button" data-act="paste-resume">Or paste your resume's text ${icon("arrow")}</button></div>
  </article>`;
}

// What was read from your resume, every value editable, with one button to confirm them all.
function fromResumeCard(ids, fields) {
  const field = (f) => {
    const wide = ["multi", "list", "textarea"].includes(f.type);
    const tagName = f.type === "multi" ? "div" : "label";
    return `<${tagName} class="field${wide ? " wide" : ""}"><span class="field-label">${esc(f.label)}</span>${answerInput(f, S.onboarding.answers[f.id])}</${tagName}>`;
  };
  return `<article class="feed-card">
    <div class="feed-top"><span class="eyebrow">FROM YOUR RESUME</span><span class="small-tag">${ids.length} TO CHECK</span></div>
    <h3>Did JobPortal get these right?</h3>
    <p>They're filled in from your resume. Fix anything that's off, then confirm.</p>
    <div class="form-grid">${ids.map((id) => field(fields[id])).join("")}</div>
    <div class="feed-actions"><button class="button primary" type="button" data-act="home-confirm">${icon("check")} Looks right</button></div>
  </article>`;
}

// One standard question. A pick-one question answers as soon as you pick; the others have Save. Optional ones have Skip.
function questionCard(f) {
  const named = `aria-label="${esc(f.label)}"`;  // the input says which question it answers
  const save = f.type === "select" ? "" : `<button class="button primary" type="button" data-act="home-answer" data-id="${esc(f.id)}">Save ${icon("arrow")}</button>`;
  const skip = f.required ? "" : `<button class="button text" type="button" data-act="home-skip" data-id="${esc(f.id)}">Skip</button>`;
  return `<article class="feed-card">
    <div class="feed-top"><span class="eyebrow feed-progress"></span><span class="small-tag${f.required ? "" : " plain"}">${f.required ? "REQUIRED" : "OPTIONAL"}</span></div>
    <h3>${esc(f.label)}</h3>
    ${f.help ? `<p>${esc(f.help)}</p>` : ""}
    <div class="answer" role="group" ${named}>${answerInput(f, S.onboarding.answers[f.id] || suggestion(f.id), true, named)}</div>
    ${f.type === "list" ? `<small class="hint">One per line.</small>` : ""}
    ${save || skip ? `<div class="feed-actions">${save}${skip}</div>` : ""}
  </article>`;
}

// The profile build: running, failed, just finished, or ready to start (answers and resume in, no build yet).
function buildCard() {
  const st = S.profileStatus || {}, ob = S.onboarding || {};
  const card = (cls, mark, eyebrow, title, text, actions = "") => `<article class="feed-card status ${cls}"><span class="status-icon">${mark}</span>`
    + `<div><span class="eyebrow">${eyebrow}</span><h3>${esc(title)}</h3>${text}${actions ? `<div class="feed-actions">${actions}</div>` : ""}</div></article>`;
  if (st.busy) {
    return { key: "build", html: card("busy", spinner(), "BUILDING YOUR PROFILE", humanize(st.phase || "Starting"),
      "<p>JobPortal is reading everything you gave it and writing your profile: your experience, your skills and what to search for. Usually 1 to 4 minutes. You can keep going meanwhile.</p>") };
  }
  if (st.error) {
    const signIn = aiReady() ? "" : `<button class="button outline" type="button" data-act="ai-signin">Sign in with ChatGPT</button>`;
    return { key: "build", html: card("error", icon("warning"), "THE PROFILE BUILD STOPPED", "Something went wrong",
      `<p>${esc(st.error)}</p><p>Check that you're signed in with ChatGPT on a Go, Plus or Pro plan, then try again.</p>`,
      `<button class="button primary" type="button" data-act="profile-build">${icon("refresh")} Try again</button>${signIn}`) };
  }
  if (S.buildDone) {
    return { key: "build", html: card("good", icon("check"), "ALL SET", "Your profile is ready",
      "<p>Run your first search. JobPortal looks through job boards, company sites and social posts, scores every job against your profile, and tailors an application for the best ones.</p>",
      `<button class="button primary" type="button" data-act="run">${icon("play", "filled")} Run search</button><button class="button text" type="button" data-act="build-seen">Got it</button>`) };
  }
  if (ob.resume && ob.answers_saved && !st.built) {
    return { key: "build", html: card("", icon("sparkle"), "ONE LAST STEP", "Build your profile",
      "<p>JobPortal builds your profile from your resume, your documents and your answers. Every search and application is made from it.</p>",
      `<button class="button primary" type="button" data-act="profile-build">Build it now ${icon("arrow")}</button>`) };
  }
  return null;
}

// One question JobPortal asked along the way, with where it came from.
function followUpCard(q) {
  const forLead = q.lead_id ? `<a class="tag blue" href="#/leads/${q.lead_id}">For ${esc(String(q.source || "a job").replace(/ application$/, ""))}</a>` : "";
  return `<article class="feed-card">
    <div class="feed-top"><span class="eyebrow feed-progress"></span>${forLead}</div>
    <h3>${esc(q.question)}</h3>
    ${q.why ? `<p>${esc(q.why)}</p>` : ""}
    <textarea rows="3" data-follow aria-label="Your answer" placeholder="Your answer, in a sentence or two"></textarea>
    <div class="feed-actions"><button class="button primary" type="button" data-act="home-follow" data-q="${esc(q.question)}">Save answer ${icon("arrow")}</button>
      <button class="button text" type="button" data-act="home-dismiss" data-q="${esc(q.question)}">Not relevant</button></div>
  </article>`;
}

// Nothing is waiting on you.
function caughtUpCard() {
  const run = S.state.running
    ? `<a class="button primary" href="#/leads">Watch the search ${icon("arrow")}</a>`
    : `<button class="button primary" type="button" data-act="run">${icon("play", "filled")} Run search</button>`;
  return `<article class="feed-card status good"><span class="status-icon">${icon("check")}</span><div>
    <span class="eyebrow">ALL CAUGHT UP</span><h3>Nothing is waiting on you</h3>
    <p>${S.state.running ? "A search is running. New leads show up below as they're ready." : "Run a search and JobPortal brings back new leads, ranked for you."}</p>
    <div class="feed-actions">${run}<a class="text-button" href="#/settings/profile/questions">Tell JobPortal something new ${icon("arrow")}</a></div></div></article>`;
}

// Saves standard answers (PATCH: the others stay as they are) and redraws Home. The last required answer starts the
// first profile build on the server.
async function saveHomeAnswers(answers, button) {
  if (button) button.disabled = true;
  try {
    const r = await api("/api/onboarding/answers", { method: "PATCH", body: { answers } });
    Object.assign(S.onboarding, { answers: r.answers, missing: r.missing, from_resume: r.answers._from_resume || [], answers_saved: r.complete });
    onProfileStatus(r.status);
    if (r.building) toast("Building your profile", "That was the last required question. JobPortal is building your profile now.");
    if (Object.keys(answers).some((id) => AREA_ANSWERS.includes(id))) refreshSearchArea();
    renderUserButton();
    renderNextStep();
    homeDataChanged();
  } finally {
    if (button) button.disabled = false;
  }
}

// Skips an optional question, for good on this computer. It stays in Settings, Profile.
function skipQuestion(id) {
  store.set("homeSkipped", JSON.stringify([...new Set([...store.list("homeSkipped"), id])]));
  renderFeed();
  renderNextStep();
}

// ---------------------------------------------------------------- top leads and the right column
// The five best ready leads, as job cards (leads.js). A click opens one on the Leads page. Live refreshes during a
// search redraw them only when they changed (setHtml).
async function loadTopLeads() {
  let d;
  try {
    d = await api("/api/leads?tab=ready&sort=score&limit=5");
  } catch (_) {
    return;
  }
  const box = $("#home-leads");
  if (!box) return;  // you left Home while they loaded
  const empty = S.profileStatus?.built ? "Run a search, and your best matches show up here."
    : "Once your profile is built, run a search and your best matches show up here.";
  setHtml(box, d.leads.map((l) => leadCard(l)).join("") || `<div class="empty-state"><h3>No leads yet</h3><p>${empty}</p></div>`);
}

// Your profile: who you are, what you're after, and the setup checklist with its progress bar.
function renderProfilePanel() {
  const el = $("#home-profile");
  if (!el) return;
  const ob = S.onboarding || {}, a = ob.answers || {}, st = S.profileStatus || {};
  const name = yourName();
  const role = (a.target_roles || [])[0];
  const place = [a.city, a.state].filter(Boolean).join(", ");
  const checks = [["Signed in with ChatGPT", aiReady()], ["Resume added", !!ob.resume], ["Other documents added", (S.documents || []).length > 0],
    ["Required questions answered", !!ob.resume && !(ob.missing || []).length], ["Profile built", !!st.built]];
  const done = checks.filter(([, ok]) => ok).length, percent = Math.round((done / checks.length) * 100);
  const tag = done === checks.length ? "COMPLETE" : st.busy ? "BUILDING" : "KEEP GOING";
  setHtml(el, `<div class="panel-heading"><h2>Your profile</h2><span class="small-tag">${tag}</span></div>
    <div class="profile-progress"><span class="avatar large">${esc(initials(name)) || icon("user")}</span>
      <div><strong>${esc(name || "Your name")}</strong><p>${esc(role || "Add the jobs you want")}</p>
        ${place ? `<span class="available"><span class="status-dot"></span>${esc(place)}</span>` : ""}</div></div>
    <div class="progress-label"><span>Profile completion</span><strong>${percent}%</strong></div>
    <progress value="${done}" max="${checks.length}" aria-label="Profile completion">${percent}%</progress>
    <ul class="checklist">${checks.map(([label, ok]) => `<li><span class="check-circle${ok ? " done" : ""}" aria-hidden="true">${ok ? icon("check") : ""}</span>`
      + `${label}${ok ? '<span class="sr-only">, done</span>' : ""}</li>`).join("")}</ul>
    <a class="button light full" href="#/settings/profile">Edit your profile ${icon("arrow")}</a>`);
}

// Where the search looks, with Run search.
function renderAreaPanel() {
  const el = $("#home-area");
  if (!el) return;
  const run = S.state.running
    ? `<a class="button outline full" href="#/leads">Watch the search ${icon("arrow")}</a>`
    : `<button class="button primary full" type="button" data-act="run">${icon("play", "filled")} Run search</button>`;
  setHtml(el, `<div class="panel-heading"><h2>Where to search</h2><a class="text-button" href="#/settings/search">Edit ${icon("arrow")}</a></div>
    <div class="tags area-tags">${areaTags(S.searchArea)}</div>${run}`);
}

// ---------------------------------------------------------------- live updates
// Your answers, resume or documents changed.
function homeDataChanged() {
  renderHomeHeading();
  renderFeed();
  renderProfilePanel();
  renderDocumentsPanel($("#home-docs"));
  renderAreaPanel();
}

// The extra documents changed (a "documents" event, or one removed).
function homeDocumentsChanged() {
  renderDocumentLists();
  renderProfilePanel();
}

// The profile build started, moved on, failed or finished.
function homeStatusChanged() {
  renderHomeHeading();
  renderFeed();
  renderProfilePanel();
}

// A search started or stopped: the buttons that run one change. "state" events come often during a search (every
// phase and count), so this redraws only when running changed from what Home shows. renderHome sets homeShowsRunning,
// because a search may have started or stopped while you were on another page.
let homeShowsRunning = null;
function homeRunChanged() {
  if (homeShowsRunning === S.state.running) return;
  homeShowsRunning = S.state.running;
  renderHomeHeading();
  renderFeed();
  renderAreaPanel();
}

// ---------------------------------------------------------------- actions
onAction("home-answer", async (el) => {
  const id = el.dataset.id, f = questionFields()[id];
  const value = readAnswersForm(el.closest(".feed-card"))[id];
  if (filled(value)) await saveHomeAnswers({ [id]: value }, el);
  else if (f.required) toast("This one's required", "Answer it to keep going.", "error");
  else skipQuestion(id);  // an empty optional answer is a skip
});
onAction("home-pick", (el) => saveHomeAnswers({ [el.dataset.id]: el.dataset.value }, el));
onAction("home-skip", (el) => skipQuestion(el.dataset.id));
onAction("home-confirm", (el) => saveHomeAnswers(readAnswersForm(el.closest(".feed-card")), el));
onAction("home-follow", async (el) => {
  const answer = $("[data-follow]", el.closest(".feed-card")).value.trim();
  if (!answer) {
    toast("Write an answer first", "Or choose Not relevant.", "error");
    return;
  }
  el.disabled = true;
  let r;
  try {
    r = await api("/api/questions/answer", { method: "POST", body: { question: el.dataset.q, answer } });
  } finally {
    el.disabled = false;  // the card is replaced when it worked; when it failed, you can try again
  }
  S.questions = r.questions;
  followUpsDone++;
  onProfileStatus(r.status);
  renderFeed();
  toast("Answer saved", "It goes into your profile in about a minute.");
});
onAction("home-dismiss", async (el) => {
  S.questions = await api("/api/questions/dismiss", { method: "POST", body: { question: el.dataset.q } });
  followUpsDone++;
  renderFeed();
  renderNextStep();
});
onAction("build-seen", () => {
  S.buildDone = false;
  renderFeed();
});
// Enter in a one-line answer saves it.
document.addEventListener("keydown", (e) => {
  if (e.key !== "Enter" || !e.target.matches("#home-feed input[data-qf]")) return;
  e.preventDefault();
  $("[data-act=home-answer]", e.target.closest(".feed-card"))?.click();
});
// Typing an answer (or ticking a choice) marks its card as edited: an unsaved edit, so moving away asks first. Picking
// files in the resume card isn't an edit; they're added at once.
document.addEventListener("input", (e) => {
  const card = e.target.type !== "file" && e.target.closest?.("#home-feed > .feed-card");
  if (!card) return;
  card.dataset.edited = "1";
  S.dirty = true;
});
