/* home.js: the Home page (#/home), where JobPortal starts.
   - Before an AI is connected: the welcome, with Connect AI (components/connect.js). The "ai" event swaps it for the
     dashboard as soon as an AI is ready.
   - After: the numbers across the top. On the left, the questions (one at a time: your resume, what was read from it, the
     standard questions still empty, the profile build, then the questions asked along the way), Next moves and Top leads.
     On the right, your profile, your documents (components/documents.js) and where the search looks.
   APIs: GET /api/onboarding, PATCH /api/onboarding/answers (each answer saves on its own), GET /api/leads (the best ready
   leads), GET /api/moves and POST /api/moves/hide, GET /api/settings (the search area), POST /api/questions/answer and
   /dismiss, POST /api/profile/build.
   Live events redraw the parts that changed (live.js). A question you're answering stays as it is through them, and an
   answer you've typed counts as an unsaved edit until it's saved, skipped or dismissed. */
"use strict";

// The optional standard questions Home asks after the required ones, in this order: the ones that most improve the
// search and fill in the most application forms. Every question, these included, is in Settings, Profile.
const RECOMMENDED = ["locations", "job_types", "experience_years", "education_level", "field_of_study", "licenses", "phone", "linkedin",
  "start_date"];
// Home never asks from these sections: voluntary self-identification, and writing style. They stay in Settings.
const NOT_ON_HOME = ["eeo", "about"];
// The answers the search area is made from (LOCATION_ANSWERS in candidate/onboarding.py): saving one can change it.
const AREA_ANSWERS = ["locations", "anywhere_us", "work_modes", "state"];
// How many of the best leads Home lists.
const TOP_LEADS = 8;

// Follow-up questions answered or dismissed since Home opened, for "2 of 5".
let followUpsDone = 0;

// ---------------------------------------------------------------- the page
// Draws Home: the welcome before an AI is connected, the dashboard after.
async function renderHome() {
  main.dataset.page = "home";
  pageHead("Home");
  if (!aiReady()) {
    main.innerHTML = welcomeHtml();
    return;
  }
  followUpsDone = 0;
  main.innerHTML = `<div class="home">
    <div class="stat-strip" id="home-stats"></div>
    <div class="view-split">
      <div class="pane" aria-label="Your search">
        <section class="sect" id="home-questions"><div class="sect-head"><h2>Questions <small id="feed-progress"></small></h2></div>
          <div class="feed" id="home-feed"></div></section>
        <section class="sect" id="home-moves" hidden></section>
        <section class="sect" id="home-top"><div class="sect-head"><h2>Top leads</h2>
          <a class="text-button" href="#/leads" data-act="leads-tab" data-tab="ready">All leads ${icon("arrow")}</a></div>
          <div class="rows" id="home-leads"></div></section>
      </div>
      <aside class="pane pane-rail" aria-label="Your profile and documents">
        <section class="sect" id="home-profile"></section>
        <section class="sect" id="home-docs"></section>
        <section class="sect" id="home-area"></section>
      </aside>
    </div></div>`;
  homeDataChanged();
  renderHomeStats();
  await Promise.all([loadTopLeads(), reloadOnboarding()]);
}

// The welcome before an AI is connected.
function welcomeHtml() {
  const step = (n, label) => `<li><span>${n}</span>${label}</li>`;
  return `<div class="welcome">
    <h2>Jobs from everywhere, tailored to you.</h2>
    <button class="button primary big" type="button" data-act="ai-connect">Connect AI ${icon("arrow")}</button>
    <ol class="welcome-steps">${step(1, "Connect AI")}${step(2, "Add resume")}${step(3, "Run search")}</ol>
  </div>`;
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

// What to put in an empty answer to begin with: your name and email from your AI account's sign-in.
const suggestion = (id) => ({ name: S.state.ai?.name, email: S.state.ai?.email })[id] || "";

// The questions asked along the way that are still open.
const openFollowUps = () => (S.questions || []).filter((q) => q.status === "open");

// ---------------------------------------------------------------- the numbers
// Each number opens where it comes from.
function renderHomeStats() {
  const el = $("#home-stats");
  if (!el) return;
  const s = S.stats || {};
  const stat = (href, tab, value, label) => `<a href="${href}"${tab ? ` data-act="leads-tab" data-tab="${tab}"` : ""}><strong>${value ?? 0}</strong><span>${label}</span></a>`;
  setHtml(el, stat("#/leads", "ready", s.ready, "Ready") + stat("#/tracker", "", s.applied, "Applied")
    + stat("#/tracker", "", s.interviewing, "Interviews") + stat("#/tracker", "", s.accepted, "Offers"));
}

// ---------------------------------------------------------------- questions
// What the Questions section shows, in order: the drop zone (until there's a resume), the profile build (while it runs,
// when it failed, or before the first one), then the one thing to answer next. Each item has a key; keep marks the ones
// with inputs, which stay as they are (with whatever you typed) while their key stays the same. The resume item is kept
// too: its file picker may be open, and a new one in its place would lose the files you pick.
function feedCards() {
  const cards = [];
  if (!S.onboarding?.resume) cards.push({ key: "resume", keep: true, html: resumeCard() });
  const build = buildCard();
  if (build) cards.push(build);
  const next = nextCard();
  if (next) cards.push(next);
  return cards;
}

// Redraws the questions, keeping the items whose key hasn't changed, so an answer being typed is never wiped. An item
// you've typed in is marked data-edited (see the input listener at the bottom); S.dirty says whether one is still on
// screen, so it clears itself when that item goes (saved, skipped, dismissed, or answered in another window). With
// nothing to ask, the section goes away.
function renderFeed() {
  const box = $("#home-feed");
  if (!box) return;
  const shown = new Map($$(":scope > [data-key]", box).map((el) => [el.dataset.key, el]));
  const cards = feedCards();
  box.replaceChildren(...cards.map((card) => {
    let el = card.keep && shown.get(card.key);
    if (!el) {
      const template = document.createElement("template");
      template.innerHTML = card.html.trim();
      el = template.content.firstElementChild;
      el.dataset.key = card.key;
    }
    return el;
  }));
  $("#home-questions").hidden = !cards.length;
  $("#feed-progress").textContent = cards.find((card) => card.progress)?.progress || "";
  S.dirty = !!$("[data-edited]", box);
}

// The one thing to answer next: check what was read from your resume, a standard question, or a question asked along the
// way.
function nextCard() {
  const fields = questionFields();
  const fromResume = fromResumeIds();
  if (fromResume.length) return { key: `from-resume:${fromResume.join(",")}`, keep: true, html: fromResumeCard(fromResume, fields) };
  const queue = standardQueue();
  if (queue.ids.length) {
    const id = queue.ids[0];
    return { key: `q:${id}`, keep: true, html: questionCard(fields[id]), progress: `${queue.total - queue.ids.length + 1} of ${queue.total}` };
  }
  const open = openFollowUps();
  if (open.length) return { key: `f:${open[0].question}`, keep: true, html: followUpCard(open[0]), progress: `${followUpsDone + 1} of ${followUpsDone + open.length}` };
  return null;
}

// Before there's a resume: the big drop zone.
function resumeCard() {
  return `<article class="feed-card">
    ${documentsDropZone(true)}
    <div class="feed-actions"><button class="text-button" type="button" data-act="paste-resume">Paste text</button>
      <button class="text-button" type="button" data-act="open-builder">No resume</button></div>
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
    <h3>From your resume</h3>
    <div class="form-grid">${ids.map((id) => field(fields[id])).join("")}</div>
    <div class="feed-actions"><button class="button primary" type="button" data-act="home-confirm">${icon("check")}Confirm</button></div>
  </article>`;
}

// One standard question. A pick-one question answers as soon as you pick; the others have Save. Optional ones have Skip.
function questionCard(f) {
  const named = `aria-label="${esc(f.label)}"`;  // the input says which question it answers
  const save = f.type === "select" ? "" : `<button class="button primary" type="button" data-act="home-answer" data-id="${esc(f.id)}">Save</button>`;
  const skip = f.required ? "" : `<button class="button text" type="button" data-act="home-skip" data-id="${esc(f.id)}">Skip</button>`;
  return `<article class="feed-card">
    <h3>${esc(f.label)}${f.required ? ` <b class="req" title="Required">*</b>` : ""}</h3>
    <div class="answer" role="group" ${named}>${answerInput(f, S.onboarding.answers[f.id] || suggestion(f.id), true, named)}</div>
    ${save || skip ? `<div class="feed-actions">${save}${skip}</div>` : ""}
  </article>`;
}

// The profile build: running, failed, or ready to start (answers and resume in, no build yet).
function buildCard() {
  const st = S.profileStatus || {}, ob = S.onboarding || {};
  const card = (mark, title, text, actions = "") => `<article class="feed-card status"><span class="status-mark">${mark}</span>`
    + `<div><h3>${esc(title)}</h3>${text ? `<p>${esc(text)}</p>` : ""}</div>${actions ? `<div class="feed-actions">${actions}</div>` : ""}</article>`;
  if (st.busy) return { key: "build", html: card(spinner(), "Building profile", humanize(st.phase || "Starting")) };
  if (st.error) {
    const connect = aiReady() ? "" : `<button class="button outline" type="button" data-act="ai-connect">Connect AI</button>`;
    return { key: "build", html: card(icon("warning"), "Build failed", st.error,
      `<button class="button primary" type="button" data-act="profile-build">${icon("refresh")}Retry</button>${connect}`) };
  }
  if (ob.resume && ob.answers_saved && !st.built) {
    return { key: "build", html: card(icon("sparkle"), "Profile", "", `<button class="button primary" type="button" data-act="profile-build">Build</button>`) };
  }
  return null;
}

// One question JobPortal asked along the way, with the job it came from.
function followUpCard(q) {
  const forLead = q.lead_id ? `<a class="tag blue" href="#/leads/${q.lead_id}">${esc(String(q.source || "Job").replace(/ application$/, ""))}</a>` : "";
  return `<article class="feed-card">
    <h3>${esc(q.question)}</h3>${forLead ? `<div>${forLead}</div>` : ""}
    <textarea rows="3" data-follow aria-label="Answer"></textarea>
    <div class="feed-actions"><button class="button primary" type="button" data-act="home-follow" data-q="${esc(q.question)}">Save</button>
      <button class="button text" type="button" data-act="home-dismiss" data-q="${esc(q.question)}">Dismiss</button></div>
  </article>`;
}

// Saves standard answers (PATCH: the others stay as they are) and redraws Home. The last required answer starts the
// first profile build on the server.
async function saveHomeAnswers(answers, button) {
  if (button) button.disabled = true;
  try {
    const r = await api("/api/onboarding/answers", { method: "PATCH", body: { answers } });
    Object.assign(S.onboarding, { answers: r.answers, missing: r.missing, from_resume: r.answers._from_resume || [], answers_saved: r.complete });
    onProfileStatus(r.status);
    if (Object.keys(answers).some((id) => AREA_ANSWERS.includes(id))) refreshSearchArea();
    renderUserButton();
    homeDataChanged();
  } finally {
    if (button) button.disabled = false;
  }
}

// Skips an optional question, for good on this computer. It stays in Settings, Profile.
function skipQuestion(id) {
  store.set("homeSkipped", JSON.stringify([...new Set([...store.list("homeSkipped"), id])]));
  renderFeed();
}

// ---------------------------------------------------------------- top leads and the right side
// One lead in a list: its score, title, company and place, and how long ago it was posted. A click opens it on Leads.
function homeLeadRow(l) {
  const where = [l.company, l.location].filter(Boolean).join(", ");
  return `<a class="row" href="#/leads/${l.id}">${matchPill(l.score)}<span class="row-main"><span class="row-title">${esc(l.title)}</span>`
    + `<span class="row-sub">${esc(where)}</span></span><span class="row-end">${l.posted_at ? esc(ago(l.posted_at)) : ""}</span></a>`;
}

// The best ready leads. Live refreshes during a search redraw them only when they changed (setHtml).
async function loadTopLeads() {
  loadMoves();  // Next moves come from the leads too, so they reload together
  let d;
  try {
    d = await api(`/api/leads?tab=ready&sort=score&limit=${TOP_LEADS}`);
  } catch (_) {
    return;
  }
  const box = $("#home-leads");
  if (!box) return;  // you left Home while they loaded
  setHtml(box, d.leads.map(homeLeadRow).join("") || `<div class="empty"><p>No leads yet</p></div>`);
}

// ---------------------------------------------------------------- next moves
// A few things worth doing (GET /api/moves), found by plain rules over your leads: no reply after three weeks, a new
// opening where you were turned down before, several openings at one company. Hidden when there are none. Each has a
// button and Hide (30 days).
async function loadMoves() {
  let d;
  try {
    d = await api("/api/moves");
  } catch (_) {
    return;
  }
  const box = $("#home-moves");
  if (!box) return;
  box.hidden = !d.moves.length;
  setHtml(box, d.moves.length ? `<div class="sect-head"><h2>Next moves</h2></div><div class="rows">${d.moves.map(moveRow).join("")}</div>` : "");
}

function moveRow(m) {
  const button = m.cta.search
    ? `<button class="button outline small" type="button" data-act="leads-search" data-q="${esc(m.cta.search)}">${esc(m.cta.label)}</button>`
    : `<a class="button outline small" href="${esc(m.cta.href)}">${esc(m.cta.label)}</a>`;
  return `<div class="row"><span class="row-main"><span class="row-title">${esc(m.text)}</span><span class="row-sub">${esc(m.why)}</span></span>`
    + `<span class="row-end">${button}<button class="icon-button" type="button" data-act="hide-move" data-key="${esc(m.key)}" aria-label="Hide" title="Hide">${icon("close")}</button></span></div>`;
}

// Your profile: who you are, what you're after, and how far setup is.
function renderProfilePanel() {
  const el = $("#home-profile");
  if (!el) return;
  const ob = S.onboarding || {}, a = ob.answers || {}, st = S.profileStatus || {};
  const name = yourName();
  const role = (a.target_roles || [])[0];
  const place = [a.city, a.state].filter(Boolean).join(", ");
  const checks = [["AI", aiReady()], ["Resume", !!ob.resume], ["Documents", (S.documents || []).length > 0],
    ["Questions", !!ob.resume && !(ob.missing || []).length], ["Profile", !!st.built]];
  const done = checks.filter(([, ok]) => ok).length;
  const list = done === checks.length ? "" : `<progress value="${done}" max="${checks.length}" aria-label="Setup">${done} of ${checks.length}</progress>
    <ul class="setup-list">${checks.map(([label, ok]) => `<li class="${ok ? "done" : ""}">${ok ? icon("check") : `<span class="setup-dot"></span>`}${label}${ok ? '<span class="sr-only">, done</span>' : ""}</li>`).join("")}</ul>`;
  setHtml(el, `<div class="sect-head"><h2>Profile</h2><a class="text-button" href="#/settings/profile">Edit</a></div>
    <div class="who"><span class="avatar large">${esc(initials(name)) || icon("user")}</span>
      <div class="row-main"><span class="row-title">${esc(name || "No name")}</span>
        ${role ? `<span class="row-sub">${esc(role)}</span>` : ""}${place ? `<span class="row-sub">${esc(place)}</span>` : ""}</div></div>${list}`);
}

// Where the search looks.
function renderAreaPanel() {
  const el = $("#home-area");
  if (!el) return;
  setHtml(el, `<div class="sect-head"><h2>Search area</h2><a class="text-button" href="#/settings/search">Edit</a></div>
    <div class="tags">${areaTags(S.searchArea)}</div>`);
}

// ---------------------------------------------------------------- live updates
// Your answers, resume or documents changed.
function homeDataChanged() {
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
  renderFeed();
  renderProfilePanel();
}

// A search started or stopped. Nothing on Home depends on it now that Run lives in the top bar.
function homeRunChanged() {}

// ---------------------------------------------------------------- actions
onAction("home-answer", async (el) => {
  const id = el.dataset.id, f = questionFields()[id];
  const value = readAnswersForm(el.closest(".feed-card"))[id];
  if (filled(value)) await saveHomeAnswers({ [id]: value }, el);
  else if (f.required) toast("Required", "", "error");
  else skipQuestion(id);  // an empty optional answer is a skip
});
onAction("home-pick", (el) => saveHomeAnswers({ [el.dataset.id]: el.dataset.value }, el));
onAction("home-skip", (el) => skipQuestion(el.dataset.id));
onAction("home-confirm", (el) => saveHomeAnswers(readAnswersForm(el.closest(".feed-card")), el));
onAction("home-follow", async (el) => {
  const answer = $("[data-follow]", el.closest(".feed-card")).value.trim();
  if (!answer) {
    toast("Answer is empty", "", "error");
    return;
  }
  el.disabled = true;
  let r;
  try {
    r = await api("/api/questions/answer", { method: "POST", body: { question: el.dataset.q, answer } });
  } finally {
    el.disabled = false;  // the question is replaced when it worked; when it failed, you can try again
  }
  S.questions = r.questions;
  followUpsDone++;
  onProfileStatus(r.status);
  renderFeed();
  toast("Saved");
});
onAction("home-dismiss", async (el) => {
  S.questions = await api("/api/questions/dismiss", { method: "POST", body: { question: el.dataset.q } });
  followUpsDone++;
  renderFeed();
});
// Enter in a one-line answer saves it.
document.addEventListener("keydown", (e) => {
  if (e.key !== "Enter" || !e.target.matches("#home-feed input[data-qf]")) return;
  e.preventDefault();
  $("[data-act=home-answer]", e.target.closest(".feed-card"))?.click();
});
// Typing an answer (or ticking a choice) marks its item as edited: an unsaved edit, so moving away asks first. Picking
// files in the resume item isn't an edit; they're added at once.
document.addEventListener("input", (e) => {
  const card = e.target.type !== "file" && e.target.closest?.("#home-feed > .feed-card");
  if (!card) return;
  card.dataset.edited = "1";
  S.dirty = true;
});
onAction("leads-search", (el) => {  // a Next moves button: Leads, searched for one company, on every tab
  $("#search").value = el.dataset.q;
  S.leadsTab = "all";
  searchLeads();
});
onAction("hide-move", async (el) => {
  await api("/api/moves/hide", { method: "POST", body: { key: el.dataset.key } });
  toast("Hidden");
  loadMoves();
});
