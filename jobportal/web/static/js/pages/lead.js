/* lead.js: everything about one lead, drawn into any container: the right pane of Leads (#/leads/12, or #/leads/12/emails
   for a tab) or the Tracker's large dialog. At the top: the title, company and place, the score, and the actions (Track,
   Apply, the status, Dream, and a menu with the downloads, tailoring and Delete), then banners for the application's state.
   Under them, the tabs: the overview (the fit, the plan, the role, and questions that would make the application stronger),
   the resume (editor, live preview, layouts, the strategy and the resume check), the cover letter, emails, contacts,
   interview prep, the company brief, the application kit, the posting, and activity. Each tab runs edge to edge and scrolls
   on its own, and the editors fill the pane's height with the text and preview side by side when there's room.

   APIs: GET /api/leads/{id} (the lead with its package), PATCH /api/leads/{id} (every edit), POST /api/preview (the
   editor's live preview), POST /api/leads/{id}/revise, /package, /resume-check, /events, /contacts/{i},
   /questions/generate and /apply-answers, POST /api/questions/answer and /dismiss, GET /api/questions, GET /api/profile
   (the kit's standard answers), POST /api/library (Save copy), and the downloads under /api/leads/{id}/export/.
   S.lead is the lead on screen and S.leadView where it's drawn; S.dirty marks unsaved edits. A "lead" event redraws
   it (refreshLeadDetails, from live.js), but never the open tab while it has unsaved edits or you're typing in it. */
"use strict";

// ---------------------------------------------------------------- showing a lead
// Shows a lead in box. opts: tab (the one to open; an unknown one, from an old or mistyped address, opens the overview)
// and hashBase (tabs change the address, as on Leads: #/leads/12/emails). The lead before stays on screen, unusable, while
// this one loads, so moving down the list doesn't flash "Loading".
async function showLeadDetails(box, id, opts = {}) {
  const tab = DETAIL_TABS.some(([key]) => key === opts.tab) ? opts.tab : "overview";
  const view = S.leadView = { box, id, tab, hashBase: opts.hashBase || "" };
  S.lead = null;
  S.editor = null;
  box.closest("dialog")?.classList.add("lead-host");
  box.firstElementChild?.setAttribute("inert", "");
  const slow = setTimeout(() => {
    if (S.leadView === view && !S.lead) box.innerHTML = `<p class="loading">${spinner()} Loading</p>`;
  }, 200);
  let lead;
  try {
    lead = await api(`/api/leads/${id}`);
  } catch (err) {
    clearTimeout(slow);
    if (S.leadView === view) box.innerHTML = `<div class="empty fill"><h3>Lead not found</h3><p>${esc(err.message)}</p></div>`;
    return;
  }
  clearTimeout(slow);
  if (S.leadView !== view) return;  // something else opened while it loaded
  S.lead = lead;
  box.innerHTML = "";
  drawLeadDetails();
}

// Forgets the lead on screen: another one was picked, or its dialog closed.
function closeLeadDetails() {
  S.lead = null;
  S.leadView = null;
  S.editor = null;
  S.dirty = false;
}

// Reads the lead again and redraws it on the same tab. summary = the lead's summary from a live "lead" event: then
// nothing happens while you have unsaved edits, and nothing is even read when the summary shows no change from what's
// on screen (the stage, the status and the time of the last update), as after a question was added to it.
async function refreshLeadDetails(summary) {
  const view = S.leadView, live = !!summary;
  if (!view || (live && (S.dirty || sameLead(S.lead, summary)))) return;
  let lead;
  try {
    lead = await api(`/api/leads/${view.id}`);
  } catch (_) {
    return;
  }
  if (S.leadView !== view || (live && (S.dirty || sameLead(S.lead, lead)))) return;
  S.lead = lead;
  drawLeadDetails();
}
const sameLead = (a, b) => !!a && ["stage", "updated_at", "app_status"].every((key) => a[key] === b[key]);

// An element inside the lead on screen.
const lv = (selector) => $(selector, S.leadView.box);

// Draws the lead: the header with the actions, the banners, the tabs and the open tab. Drawn again after a change, it
// replaces only what's above the tabs, and draws the open tab again unless it has unsaved edits or you're typing in it:
// the tab stays in the page, so its text, cursor and scroll position stay too. A focused button or menu above the tabs
// gets the focus back in the new HTML.
function drawLeadDetails() {
  const l = S.lead, view = S.leadView, packaged = !!l.resume_md;
  const where = [l.company, l.location].filter(Boolean).join(", ");
  const back = view.hashBase ? `<a class="icon-button lead-back" href="#/leads" aria-label="Back" title="Back">${icon("back")}</a>` : "";
  const head = `<header class="lead-head">${back}${matchPill(l.score || null)}
      <div class="lead-title"><h2>${esc(l.title || "Untitled job")}</h2><div class="row-sub">${esc(where)}</div></div>
      <div class="lead-actions">${leadActions(l, packaged)}</div>
      <div class="lead-meta">${stageTag(l)}${leadMeta(l)}${leadTags(l)}</div></header>${leadBanners(l, packaged)}`;
  const body = lv("[data-lead-body]");
  if (!body) {  // the first time
    const tabs = DETAIL_TABS.map(([key, label]) => `<button class="tab${view.tab === key ? " active" : ""}" type="button" role="tab"`
      + ` aria-selected="${view.tab === key}" data-act="lead-tab" data-tab="${key}">${label}</button>`).join("");
    view.box.innerHTML = `<div class="lead-details">${head}<div class="tabs" role="tablist" aria-label="Lead">${tabs}</div>`
      + `<div class="tab-body" data-lead-body></div></div>`;
    drawLeadTab();
    return;
  }
  const details = lv(".lead-details"), tabs = lv(".tabs"), focus = focusKey(details);
  while (details.firstChild !== tabs) details.firstChild.remove();
  tabs.insertAdjacentHTML("beforebegin", head);
  if (!S.dirty && !typingIn(body)) drawLeadTab();
  refocus(details, focus);
}

// The actions in the header: Track (for a new lead), Apply, the status on the Tracker, Dream, and a menu with the rest.
// A deleted lead's menu has Restore and Delete forever instead of Delete.
function leadActions(l, packaged) {
  const apply = safeUrl(l.apply_url) || safeUrl(l.url);
  const statuses = S.meta.statuses.filter((s) => s !== "trashed" || l.app_status === "trashed").map((s) => [s, statusLabel(s)]);
  const item = (attrs, label) => `<button type="button" role="menuitem" ${attrs}>${label}</button>`;
  const places = foundList(l);
  const found = places.length > 1 ? item(`data-act="found-menu" data-id="${l.id}"`, `${icon("external")}Found at`)
    : places.length ? item(`data-act="open-url" data-url="${esc(places[0].url)}"`, `${icon("external")}Found at`) : "";
  const remove = l.app_status === "trashed"
    ? item(`data-act="lead-restore" data-id="${l.id}"`, `${icon("undo")}Restore`)
      + item(`class="danger" data-act="lead-purge" data-id="${l.id}"`, `${icon("trash")}Delete forever`)
    : item(`class="danger" data-act="detail-delete"`, `${icon("trash")}Delete`);
  const menu = (packaged ? item(`data-act="export" data-url="/api/leads/${l.id}/export/package.zip"`, `${icon("download")}All files`) : "")
    + item(`data-act="regen"`, `${icon("refresh")}${packaged ? "Tailor again" : "Tailor"}`) + found + remove;
  return (l.app_status === "new" ? `<button class="button light" type="button" data-act="detail-track">${icon("plus")}Track</button>` : "")
    + (apply ? `<button class="button primary" type="button" data-act="apply" data-url="${esc(apply)}">Apply ${icon("external")}</button>` : "")
    + `<select class="lead-status" data-lead-status aria-label="Status">${selectOptions(statuses, l.app_status)}</select>`
    + `<button class="icon-button lead-dream${l.dream ? " on" : ""}" type="button" data-act="toggle-dream" aria-pressed="${!!l.dream}" aria-label="Dream" title="Dream">${icon("star", l.dream ? "filled" : "")}</button>`
    + `<div class="menu-wrap"><button class="icon-button" type="button" data-act="menu" aria-haspopup="menu" aria-expanded="false" aria-label="More" title="More">${icon("more")}</button>`
    + `<div class="menu" role="menu" hidden>${menu}</div></div>`;
}

// A banner: a line across the details with an icon and, sometimes, a button.
const banner = (cls, mark, text, action = "") => `<div class="banner ${cls}">${mark}<div>${text}</div>${action}</div>`;

// The banners: the application is being tailored, failed or isn't tailored yet, the posting looks closed, or a
// follow-up is due.
function leadBanners(l, packaged) {
  let html = "";
  if (l.stage === "packaging") {
    html = banner("", spinner(), "Tailoring");
  } else if (l.stage === "error") {
    html = banner("bad", icon("warning"), `Tailoring failed: ${esc(l.stage_error)}`,
      `<button class="button outline small" type="button" data-act="regen">Retry</button>`);
  } else if (!packaged) {
    html = banner("", icon("sparkle"), l.stage === "filtered" ? "Filtered out" : "Not tailored",
      `<button class="button primary small" type="button" data-act="regen">Tailor</button>`);
  } else if (l.stage === "closed") {
    html = banner("bad", icon("warning"), "Posting looks closed");
  }
  const waiting = ["applied", "interviewing"].includes(l.app_status);
  if (packaged && waiting && l.follow_up_at && daysUntil(l.follow_up_at) <= 0) {
    html += banner("warn", icon("bell"), "Follow-up due",
      `<button class="button outline small" type="button" data-act="lead-tab" data-tab="emails">Emails</button>`);
  }
  return html;
}

// ---------------------------------------------------------------- tabs
// The tabs in order: [key, label, function that fills the tab]. The key also works in the address: #/leads/12/emails.
const DETAIL_TABS = [
  ["overview", "Overview", renderOverviewTab],
  ["resume", "Resume", (box, l, pkg) => renderDocumentTab(box, l, pkg, "resume")],
  ["cover", "Cover letter", (box, l, pkg) => renderDocumentTab(box, l, pkg, "cover")],
  ["emails", "Emails", renderEmailsTab],
  ["contacts", "Contacts", renderContactsTab],
  ["prep", "Interview", (box, l, pkg) => renderNotesTab(box, l, pkg, "prep")],
  ["intel", "Company", (box, l, pkg) => renderNotesTab(box, l, pkg, "intel")],
  ["kit", "Kit", renderKitTab],
  ["posting", "Posting", renderPostingTab],
  ["activity", "Activity", renderActivityTab],
];

// Fills the tab body. It swaps in a fresh, empty body first, which drops the listeners the last tab added. A tab that fills
// the pane's height (the editors) adds the class "fill" to it.
function drawLeadTab() {
  const view = S.leadView;
  const old = lv("[data-lead-body]");
  const body = old.cloneNode(false);
  body.className = "tab-body";
  old.replaceWith(body);
  $$(".tabs .tab", view.box).forEach((tab) => {
    tab.classList.toggle("active", tab.dataset.tab === view.tab);
    tab.setAttribute("aria-selected", String(tab.dataset.tab === view.tab));
  });
  S.editor = null;
  const tab = DETAIL_TABS.find(([key]) => key === view.tab) || DETAIL_TABS[0];
  tab[2](body, S.lead, S.lead.package || {});
}

// Opens another tab of the lead on screen. While the lead is still loading, it opens on this tab.
function showLeadTab(tab) {
  const view = S.leadView;
  const key = DETAIL_TABS.some(([k]) => k === tab) ? tab : "overview";
  if (!view || view.tab === key) return;
  view.tab = key;
  if (S.lead) drawLeadTab();
}

// A section of the details: a heading (head adds buttons or tags on its line), then its content, ended by a line.
const block = (title, html, head = "", cls = "") => `<section class="sect${cls ? " " + cls : ""}">`
  + `${title || head ? `<div class="sect-head"><h2>${title}</h2>${head}</div>` : ""}${html}</section>`;

// The empty state of a tab whose part of the application doesn't exist yet.
const noneYet = (what) => `<div class="empty fill"><h3>No ${what} yet</h3>
  <button class="button primary" type="button" data-act="regen">Tailor</button></div>`;

// Keyword tags: green for the job's keywords the resume has, plain for the ones it lacks.
function keywordTags(coverage) {
  const hits = (coverage.hit || []).map((k) => `<span class="tag green">${esc(k)}</span>`).join("");
  const misses = (coverage.miss || []).map((k) => `<span class="tag">${esc(k)}</span>`).join("");
  return `<div class="tags">${hits}${misses}</div>`;
}

// Overview: questions that would make this application stronger, then the fit, the plan and the role. On the side, the
// facts at a glance (with the industry menu), red flags and the keywords.
function renderOverviewTab(box, l, pkg) {
  const fit = pkg.fit || {}, triage = l.triage || {}, coverage = pkg.coverage || {};
  const plan = pkg.action_plan || [], done = pkg.plan_done || [];
  const fitBlock = fit.summary || triage.summary ? block("Fit", `<p class="lead-text">${esc(fit.summary || triage.summary)}</p>
      ${fit.strengths?.length ? `<h3>Strengths</h3>${bulletList(fit.strengths, "good")}` : ""}
      ${fit.gaps?.length ? `<h3>Gaps</h3>${bulletList(fit.gaps, "warn")}` : ""}
      ${fit.eligibility_notes ? `<h3>Eligibility</h3><p class="lead-text">${esc(fit.eligibility_notes)}</p>` : ""}`) : "";
  const planItem = (step, i) => `<label class="check-row"><input type="checkbox" data-plan="${i}"${done.includes(i) ? " checked" : ""}>`
    + `<span class="${done.includes(i) ? "done" : ""}">${esc(step)}</span></label>`;
  const planBlock = plan.length ? block("Plan", `<div class="check-list">${plan.map(planItem).join("")}</div>`) : "";
  const roleBlock = pkg.job_summary ? block("Role", `<div class="prose">${md(pkg.job_summary)}</div>`) : "";
  const postingUrl = safeUrl(l.url);
  const posting = postingUrl ? `<a href="${esc(postingUrl)}" target="_blank" rel="noopener">${esc(postingUrl.replace(/^https?:\/\//, "").slice(0, 60))}</a>` : "None";
  const foundAt = foundList(l).map((f) => `<a class="tag blue" href="${esc(f.url)}" target="_blank" rel="noopener">${icon("external")}${esc(foundShort(f))}</a>`).join("");
  // "82, eligible: reason; reason". The eligibility part is left out when the scoring didn't give one. The score comes
  // from the AI's answer, so it's escaped like any other text.
  const scored = [esc(triage.score ?? "-"), esc(triage.eligibility || "")].filter((part) => part !== "").join(", ")
    + (triage.reasons?.length ? `: ${esc(triage.reasons.join("; "))}` : "");
  const flagsBlock = triage.red_flags?.length ? block("Red flags", bulletList(triage.red_flags, "warn")) : "";
  const coverageBlock = coverage.hit || coverage.miss
    ? block(`Keywords <small>${Math.round((l.ats_coverage || 0) * 100)}%</small>`, keywordTags(coverage)) : "";
  // The industry menu offers the Settings list, plus the lead's own industry when it isn't on that list.
  const industries = S.industries || [];
  const industryChoices = l.industry && !industries.includes(l.industry) ? [...industries, l.industry] : industries;
  box.innerHTML = `${leadQuestionsBlock(l)}<div class="lead-cols"><div class="lead-main">${fitBlock}${planBlock}${roleBlock}
      ${fitBlock || planBlock || roleBlock ? "" : `<div class="empty"><h3>Not tailored yet</h3></div>`}</div>
    <div class="lead-side">${block("Details", `<dl class="facts">
        <dt>Status</dt><dd>${esc(statusLabel(l.app_status))}${l.applied_at ? `, applied ${esc(fmtDate(l.applied_at))}` : ""}</dd>
        <dt>Industry</dt><dd><select data-lead-industry aria-label="Industry">${selectOptions([["", "Not set"], ...industryChoices], l.industry || "")}</select></dd>
        <dt>Deadline</dt><dd>${esc(l.deadline ? fmtDate(l.deadline) : "None")}</dd>
        <dt>Posted</dt><dd>${esc(l.posted_at ? fmtDate(l.posted_at) : "Unknown")}</dd>
        <dt>Found</dt><dd>${foundAt ? `<div class="tags">${foundAt}</div>` : esc(l.source_detail || LABEL_SRC[l.source] || l.source)}</dd>
        <dt>Posting</dt><dd>${posting}</dd>
        <dt>Score</dt><dd>${scored}</dd>
        <dt>AI used</dt><dd>${(+l.tokens || 0).toLocaleString()} tokens</dd></dl>`)}
      ${flagsBlock}${coverageBlock}</div></div>`;
}

// Questions for this application, once it has a resume: answer or dismiss each, then rework the resume with your
// answers. With none yet, a button asks the AI to find some.
function leadQuestionsBlock(l) {
  if (!l.resume_md) return "";
  const questions = l.questions || [];
  if (!questions.length) {
    return block("Questions", "", `<button class="button outline small" type="button" data-act="lead-gapq">${icon("sparkle")}Find gaps</button>`, "lead-slim");
  }
  const open = questions.filter((q) => q.status === "open"), answered = questions.filter((q) => q.status === "answered");
  const openItem = (q) => `<div class="question-row"><b>${esc(q.question)}</b>${q.why ? `<small>${esc(q.why)}</small>` : ""}
      <div class="inline-form"><input type="text" data-lead-answer="${esc(q.question)}" aria-label="Answer">
        <button class="button outline" type="button" data-act="lead-answer">Save</button>
        <button class="icon-button" type="button" data-act="lead-dismiss" data-q="${esc(q.question)}" aria-label="Dismiss" title="Dismiss">${icon("close")}</button></div></div>`;
  const answeredItem = (q) => `<div class="question-row done"><b>${esc(q.question)}</b><small>${icon("check")}${esc(q.answer || "")}</small></div>`;
  const rework = answered.length
    ? `<div class="lead-foot"><button class="button primary" type="button" data-act="lead-apply-answers">${icon("sparkle")}Update resume</button></div>` : "";
  return block("Questions", `${open.map(openItem).join("")}${answered.map(answeredItem).join("")}${rework}`);
}

// Whether the Strategy and check panel above the resume editor is open. It stays that way as you move between leads.
let resumeInfoOpen = false;

// Resume and Cover letter: the editor with its live preview, downloads and Revise. They fill the pane's height. The resume
// tab adds the layout menu, the buttons for your saved resumes, and a panel with the strategy, the check and the keywords.
function renderDocumentTab(box, l, pkg, doc) {
  const isResume = doc === "resume";
  const text = isResume ? l.resume_md : l.cover_md;
  if (!text) {
    box.innerHTML = isResume
      ? `<div class="empty fill"><h3>No resume yet</h3><div class="button-row">
          <button class="button primary" type="button" data-act="regen">Tailor</button>
          <button class="button outline" type="button" data-act="lead-lib-use">Use saved</button></div></div>`
      : noneYet("cover letter");
    return;
  }
  box.classList.add("fill");
  let host = box;
  if (isResume) {
    box.innerHTML = `${resumeInfo(l, pkg)}<div class="editor-host"></div>`;
    $(".resume-info", box).addEventListener("toggle", (e) => (resumeInfoOpen = e.target.open));
    host = $(".editor-host", box);
  }
  const style = pkg.resume_style || {};
  const field = isResume ? "resume_md" : "cover_md";
  mountEditor(host, {
    doc,
    text,
    leadId: l.id,
    theme: isResume ? style.theme : undefined,
    maxPages: isResume ? style.max_pages || 1 : 1,
    original: isResume ? pkg.original_resume_md : pkg.original_cover_md,
    save: async (value) => {
      await api(`/api/leads/${l.id}`, { method: "PATCH", body: { [field]: value } });
      l[field] = value;
    },
    files: isResume ? ["resume.pdf", "resume.docx", "resume.md"] : ["cover_letter.pdf", "cover_letter.docx", "cover_letter.md"],
    tools: isResume
      ? `<label class="control"><span>Layout</span><select data-resume-theme>${selectOptions(RESUME_THEMES.map((t) => [t, humanize(t)]), style.theme)}</select></label>`
        + `<button class="button outline" type="button" data-act="lead-lib-save">${icon("star")}Save copy</button>`
        + `<button class="button outline" type="button" data-act="lead-lib-use">Use saved</button>`
      : "",
  });
}

// The panel above the resume editor: one line with the strategy and the check's score, which opens into their details.
function resumeInfo(l, pkg) {
  const st = pkg.resume_strategy || {}, coverage = pkg.coverage || {};
  const keywords = coverage.hit || coverage.miss
    ? block(`Keywords <small>${Math.round((l.ats_coverage || 0) * 100)}%</small>`, keywordTags(coverage)) : "";
  return `<details class="resume-info"${resumeInfoOpen ? " open" : ""}><summary>${icon("chevron")}<span>Strategy and check</span>
      ${st.archetype ? `<span class="tag purple">${esc(archetypeLabel(st.archetype))}</span>` : ""}<span data-check-tag>${checkTag(pkg.resume_check)}</span></summary>
    <div class="lead-cols"><div class="lead-main">${resumeStrategyBlock(pkg)}</div><div class="lead-side">${resumeCheckBlock(pkg.resume_check)}${keywords}</div></div></details>`;
}

// Emails: each email with its recipient, subject and body to edit, the ways to send it, and Revise by instruction. Then the
// LinkedIn connection note, and a bar to download or save them all.
function renderEmailsTab(box, l, pkg) {
  const emails = pkg.emails || [];
  if (!emails.length && !pkg.linkedin_note) {
    box.innerHTML = noneYet("emails");
    return;
  }
  // The "To" box suggests the contacts that have an email address.
  const suggestions = (pkg.contacts || []).filter((c) => c.email)
    .map((c) => `<option value="${esc(c.email)}">${esc(c.name)}, ${esc(c.title)}</option>`).join("");
  const emailCard = (e, i) => `<section class="sect lead-email" data-email="${i}">
      <div class="sect-head"><h2>${esc(humanize(e.kind))}${e.to ? ` <small>${esc(e.to)}</small>` : ""}</h2>
        <div class="button-row"><button class="button outline small" type="button" data-act="mail" data-how="gmail" data-i="${i}">Gmail ${icon("external")}</button>
          <button class="button outline small" type="button" data-act="mail" data-how="mailto" data-i="${i}">Mail app</button>
          <button class="button outline small" type="button" data-act="mail" data-how="copy" data-i="${i}">${icon("copy")}Copy</button>
          <button class="button outline small" type="button" data-act="mail" data-how="eml" data-i="${i}">.eml</button>
          <button class="button light small" type="button" data-act="mail" data-how="sent" data-i="${i}">${icon("check")}Mark sent</button></div></div>
      <div class="form-grid"><label class="field"><span class="field-label">To</span><input type="email" list="contact-emails" data-ef="to_addr" value="${esc(pickTo(e))}"></label>
        <label class="field"><span class="field-label">Subject</span><input type="text" data-ef="subject" value="${esc(e.subject)}"></label></div>
      <textarea data-ef="body" rows="9" aria-label="Email text">${esc(e.body)}</textarea>
      <div class="inline-form"><input type="text" data-erev="${i}" placeholder="Make it shorter" aria-label="Revision">
        <button class="button light" type="button" data-act="revise-email" data-i="${i}">${icon("sparkle")}Revise</button></div></section>`;
  const note = pkg.linkedin_note ? block("LinkedIn note",
    `<textarea data-note rows="3" aria-label="LinkedIn note">${esc(pkg.linkedin_note)}</textarea>
      <div class="lead-foot"><button class="button outline small" type="button" data-act="copy-note">${icon("copy")}Copy</button></div>`,
    `<small class="muted" data-note-count>${pkg.linkedin_note.length}/300</small>`) : "";
  box.innerHTML = `<datalist id="contact-emails">${suggestions}</datalist>${emails.map(emailCard).join("")}${note}
    <div class="toolbar lead-savebar"><span class="muted">All emails</span>${exportButtons(l.id, "emails", ["md", "docx", "pdf"])}<span class="spacer"></span>
      <button class="button primary" type="button" data-act="save-emails">Save</button></div>`;
  box.addEventListener("input", (e) => {
    if (e.target.dataset.erev != null) return;  // a "how to change it" instruction isn't an edit to save
    S.dirty = true;
    if (e.target.matches("[data-note]")) lv("[data-note-count]").textContent = `${e.target.value.length}/300`;  // LinkedIn allows 300 characters
  });
}

// The recipient to fill in: the address the AI wrote for this email. A guessed pattern ("first.last@...") or a
// placeholder is left out, so you never send to an invented address.
function pickTo(e) {
  if (e.to_addr != null) return e.to_addr;
  const m = (e.to || "").match(/[\w.+-]+@[\w-]+\.[\w.-]+/);
  return m && !/^(first|firstname|name|flast|f\.?last|last|jdoe|john|email)\b|[\[\]]/i.test(m[0]) ? m[0] : "";
}

// Contacts: the people the AI found for this application. Every field saves when you leave it, the status menu saves
// right away, and you can add or remove people. An email tagged Guessed was worked out from the company's email format.
function renderContactsTab(box, l, pkg) {
  const contacts = pkg.contacts || [];
  const input = (i, key, value, label) => `<input type="text" data-cf="${key}" data-i="${i}" value="${esc(value || "")}" placeholder="${label}" aria-label="${label}">`;
  const confidence = (c) => (c.email_confidence === "found" ? "green" : c.email_confidence === "pattern" ? "warn" : "");
  const confidenceWord = (c) => ({ found: "Found", pattern: "Guessed" })[c.email_confidence] || humanize(c.email_confidence || "unknown");
  const link = (url, label) => (safeUrl(url) ? `<a href="${esc(safeUrl(url))}" target="_blank" rel="noopener">${label}</a>` : "");
  const row = (c, i) => `<div class="lead-contact">
      <div class="contact-grid">${input(i, "name", c.name, "Name")}${input(i, "title", c.title, "Title")}${input(i, "org", c.org, "Organization")}
        ${input(i, "email", c.email, "Email")}${input(i, "linkedin", c.linkedin, "LinkedIn link")}${input(i, "notes", c.notes, "Notes")}
        <textarea class="why" data-cf="why" data-i="${i}" rows="2" placeholder="Why them" aria-label="Why them">${esc(c.why || "")}</textarea></div>
      <div class="contact-end"><span class="tag ${confidence(c)}">${esc(confidenceWord(c))}</span>
        ${c.email ? `<button class="text-button" type="button" data-act="copytext" data-text="${esc(c.email)}">Copy</button>` : ""}
        ${link(c.linkedin, "LinkedIn")}${link(c.source_url, "Source")}<span class="spacer"></span>
        ${contactStatusSelect(l.id, i, c.status, c.name)}
        <button class="icon-button danger" type="button" data-act="rm-contact" data-i="${i}" aria-label="Remove ${esc(c.name)}" title="Remove">${icon("trash")}</button></div></div>`;
  box.innerHTML = block(`Contacts <small>${contacts.length}</small>`,
    contacts.length ? contacts.map(row).join("") : `<p class="muted">No contacts yet</p>`, exportButtons(l.id, "contacts", ["csv"]))
    + block("Add contact", `<div class="contact-grid"><input type="text" placeholder="Name" data-nc="name" aria-label="Name">
        <input type="text" placeholder="Title" data-nc="title" aria-label="Title"><input type="email" placeholder="Email" data-nc="email" aria-label="Email">
        <input type="url" placeholder="LinkedIn link" data-nc="linkedin" aria-label="LinkedIn link"><input type="text" placeholder="Why them" data-nc="why" aria-label="Why them"></div>
      <div class="lead-foot"><button class="button outline" type="button" data-act="add-contact">${icon("plus")}Add</button></div>`);
  // An edited contact field saves that one field when you leave it. The value also goes into the lead on screen (S.lead,
  // which a live update may have read again since this tab was drawn), so the tab shows it when it's drawn again.
  box.addEventListener("change", async (e) => {
    const el = e.target;
    if (!el.dataset.cf) return;
    try {
      await api(`/api/leads/${l.id}/contacts/${el.dataset.i}`, { method: "POST", body: { [el.dataset.cf]: el.value } });
    } catch (err) {
      toast("Couldn't save contact", err.message, "error");
      return;
    }
    const contact = S.lead?.id === l.id && S.lead.package?.contacts?.[+el.dataset.i];
    if (contact) contact[el.dataset.cf] = el.value;
  });
}

// Interview prep and the company brief: Markdown documents with a preview, downloads and Revise. For each tab: key (where
// the package keeps it), name (what the empty tab and the AI call it) and stem (the download's file name).
const NOTES_DOCS = {
  intel: { key: "company_brief_md", name: "company brief", stem: "company_intel" },
  prep: { key: "interview_prep_md", name: "interview prep", stem: "interview_prep" },
};
function renderNotesTab(box, l, pkg, tab) {
  const { key, name, stem } = NOTES_DOCS[tab];
  if (!pkg[key]) {
    box.innerHTML = noneYet(name);
    return;
  }
  mountDocEditor(box, {
    text: pkg[key],
    leadId: l.id,
    stem,
    doc: name,
    save: async (value) => {
      await api(`/api/leads/${l.id}`, { method: "PATCH", body: { package: { [key]: value } } });
      pkg[key] = value;
    },
  });
}

// Application kit: the files to download, the tailored answers to this application's questions (editable), and your
// standard answers ready to copy. Reads GET /api/profile once for the standard answers; when that fails, the kit is
// drawn without them (with a note) instead of staying blank.
async function renderKitTab(box, l, pkg) {
  let qa = null;
  try {
    if (!S.profileCache) S.profileCache = await api("/api/profile");
    qa = S.profileCache.qa || [];
  } catch (_) {}
  const copyRow = (q, a) => `<div class="copy-row"><span class="copy-q">${esc(q)}</span><span class="copy-a">${esc(a)}</span>`
    + `<button class="icon-button" type="button" data-act="copytext" data-text="${esc(a)}" aria-label="Copy" title="Copy">${icon("copy")}</button></div>`;
  const apply = safeUrl(l.apply_url) || safeUrl(l.url);
  const answers = pkg.application_answers || [];
  const answerEditor = (x, i) => `<div class="answer-edit"><div class="inline-form"><input type="text" data-aq="${i}" value="${esc(x.question)}" aria-label="Question">
        <button class="icon-button" type="button" data-act="copy-answer" data-i="${i}" aria-label="Copy" title="Copy">${icon("copy")}</button>
        <button class="icon-button danger" type="button" data-act="rm-answer" data-i="${i}" aria-label="Remove" title="Remove">${icon("trash")}</button></div>
      <textarea data-aa="${i}" rows="5" aria-label="Answer">${esc(x.answer)}</textarea></div>`;
  const fileRow = (label, buttons) => `<div class="kit-file"><span>${label}</span><div class="button-row">${buttons}</div></div>`;
  const standard = (qa || []).filter((x) => !x.eeo), selfId = (qa || []).filter((x) => x.eeo);  // eeo = voluntary self-identification
  const selfIdBlock = selfId.length ? block("Self-identification", `<p class="lead-note">Never sent to the AI.</p>${selfId.map((x) => copyRow(x.q, x.a)).join("")}`) : "";
  box.innerHTML = `<div class="lead-cols"><div class="lead-main">
    ${block("Answers",
      `<div class="kit-answers">${answers.map(answerEditor).join("") || `<p class="muted">No answers yet</p>`}</div>
      <div class="lead-foot"><button class="button outline" type="button" data-act="add-answer">${icon("plus")}Add question</button><span class="spacer"></span>
        <span class="muted" data-answers-state></span><button class="button primary" type="button" data-act="save-answers">Save</button></div>`,
      `<div class="button-row">${exportButtons(l.id, "answers", ["docx", "pdf", "md"])}</div>`)}
    ${block("Standard answers", standard.map((x) => copyRow(x.q, x.a)).join("") || `<p class="muted">${qa ? "No answers yet" : "Couldn't load"}</p>`,
      `<a class="text-button" href="#/settings/profile/answers">Edit</a>`)}
    ${selfIdBlock}</div>
  <div class="lead-side">${block("Files", `${l.resume_md ? fileRow("Resume", exportButtons(l.id, "resume", ["pdf", "docx", "md"])) : ""}
      ${l.cover_md ? fileRow("Cover letter", exportButtons(l.id, "cover_letter", ["pdf", "docx", "md"])) : ""}
      ${fileRow("All files", `<button class="button outline small" type="button" data-act="export" data-url="/api/leads/${l.id}/export/package.zip">${icon("download")}ZIP</button>`)}
      ${apply ? `<div class="lead-foot"><button class="button primary" type="button" data-act="apply" data-url="${esc(apply)}">Apply ${icon("external")}</button></div>` : ""}`)}</div></div>`;
  box.addEventListener("input", (e) => {
    if (e.target.dataset.aq == null && e.target.dataset.aa == null) return;
    S.dirty = true;
    lv("[data-answers-state]").textContent = "Unsaved";
  });
}

// Reads the kit's answer fields back into S.lead.package.application_answers and returns them.
function readKitAnswers() {
  const pkg = S.lead.package;
  pkg.application_answers = (pkg.application_answers || []).map((x, i) => ({
    question: lv(`[data-aq="${i}"]`)?.value ?? x.question,
    answer: lv(`[data-aa="${i}"]`)?.value ?? x.answer,
  }));
  return pkg.application_answers;
}

// Saves the kit's answers into the lead's package.
async function saveKitAnswers() {
  await api(`/api/leads/${S.lead.id}`, { method: "PATCH", body: { package: { application_answers: readKitAnswers() } } });
  S.dirty = false;
}

// Posting: the job description as JobPortal captured it, with links to the posting and the apply page.
function renderPostingTab(box, l) {
  const postingUrl = safeUrl(l.url), applyUrl = safeUrl(l.apply_url);
  const posting = postingUrl ? `<a class="button outline small" href="${esc(postingUrl)}" target="_blank" rel="noopener">Open posting ${icon("external")}</a>` : "";
  const applyPage = applyUrl && applyUrl !== postingUrl
    ? `<a class="button outline small" href="${esc(applyUrl)}" target="_blank" rel="noopener">Apply page ${icon("external")}</a>` : "";
  box.innerHTML = block(`Posting${l.source_detail ? ` <small>${esc(l.source_detail)}</small>` : ""}`,
    `<pre class="posting-text">${esc(l.description || "No description")}</pre>`, `<div class="button-row">${posting}${applyPage}</div>`);
}

// Activity: your notes, the timeline, the follow-up date, and buttons to log what happened.
const EVENT_PRESETS = ["Recruiter contact", "Assessment", "Interview", "Referral", "Offer", "Rejected"];
function renderActivityTab(box, l) {
  const timeline = (l.events || []).map((e) => `<li class="timeline-row"><span class="timeline-time">${esc(localStamp(e.ts))}</span>`
    + `<span class="tag">${esc(humanize(e.type))}</span><span>${esc(e.text)}</span></li>`).join("");
  const presets = EVENT_PRESETS.map((text) => `<button class="choice" type="button" data-act="log-event" data-text="${esc(text)}">${esc(text)}</button>`).join("");
  box.innerHTML = `<div class="lead-cols"><div class="lead-main">
      ${block("Notes", `<textarea data-notes rows="8" aria-label="Notes">${esc(l.notes || "")}</textarea>
        <div class="lead-foot"><button class="button outline" type="button" data-act="save-notes">Save</button></div>`)}
      ${block("Timeline", timeline ? `<ul class="timeline">${timeline}</ul>` : `<p class="muted">No activity yet</p>`)}</div>
    <div class="lead-side">${block("Follow-up", `<input type="date" data-follow-up value="${esc(l.follow_up_at || "")}" aria-label="Follow-up date">
        <div class="lead-foot"><button class="button outline" type="button" data-act="save-follow-up">Save</button></div>`)}
      ${block("Log", `<div class="choice-row">${presets}</div>
        <div class="inline-form lead-log"><input type="text" data-event-text placeholder="Phone screen" aria-label="What happened">
          <button class="button outline" type="button" data-act="log-event">Log</button></div>`)}</div></div>`;
  // The notes and the follow-up date have Save buttons, so a change to either is an unsaved edit until it's saved: moving
  // away asks first, and live updates leave the tab alone. The log isn't: it's sent as you log it.
  box.addEventListener("input", () => (S.dirty = activityEdited()));
}

// True when the notes or the follow-up date on screen differ from what was saved. Saving one of them updates its
// defaultValue, so an unsaved change to the other one still counts.
function activityEdited() {
  return ["[data-notes]", "[data-follow-up]"].some((selector) => {
    const field = lv(selector);
    return !!field && field.value !== field.defaultValue;
  });
}

// Saves the notes or the follow-up date (one field of the lead), then marks what was sent as saved.
async function saveActivityField(selector, key, emptyValue) {
  const field = lv(selector), value = field.value;
  await api(`/api/leads/${S.lead.id}`, { method: "PATCH", body: { [key]: value || emptyValue } });
  field.defaultValue = value;  // what you typed while it saved stays unsaved
  S.lead[key] = value || emptyValue;
  S.dirty = activityEdited();
}

// Download buttons: exportButtons(12, "resume", ["pdf", "docx"]) makes "PDF" and "DOCX".
function exportButtons(leadId, stem, formats) {
  return formats.map((fmt) => `<button class="button outline small" type="button" data-act="export" data-url="/api/leads/${leadId}/export/${stem}.${fmt}">`
    + `${icon("download")}${fmt.toUpperCase()}</button>`).join("");
}

// ---------------------------------------------------------------- editors
// Ctrl+S (Cmd+S on a Mac) in an editor saves it.
function saveOnCtrlS(textarea, save) {
  textarea.addEventListener("keydown", (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key === "s") {
      e.preventDefault();
      save();
    }
  });
}

// The Save of both editors: saves the text with o.save and says so in the toolbar (state). Returns false when it failed,
// after a toast that says why: the editor's own buttons and Ctrl+S run outside the action registry, so nothing else
// would show the error. Text typed while the save was on its way stays an unsaved edit.
async function saveEditor(o, editor, state) {
  const text = editor.value;
  try {
    await o.save(text);
  } catch (err) {
    state.textContent = "Not saved";
    toast("Couldn't save", err.message, "error");
    return false;
  }
  S.dirty = editor.value !== text;
  state.textContent = S.dirty ? "Unsaved" : "Saved";
  return true;
}

// Revise in both editors: sends the text and your instruction (POST .../revise) and puts the AI's version in the editor.
// Nothing is saved until you click Save.
async function reviseWithAI(button, url, doc, instruction, textarea, afterRevise) {
  if (!instruction) return;
  button.disabled = true;
  button.innerHTML = `${spinner()} Revising`;
  try {
    const r = await api(url, { method: "POST", body: { doc, instruction, text: textarea.value } });
    textarea.value = r.text;
    S.dirty = true;
    afterRevise();
    toast("Revised", r.change_summary);
  } catch (err) {
    toast("Revision failed", err.message, "error");
  }
  button.disabled = false;
  button.innerHTML = `${icon("sparkle")}Revise`;
}

// The Download button of both editors, with a menu of formats. items: [[attributes, label], ...]. The items run through
// the editor's own click handler, which closes the menu.
const downloadMenu = (items) => `<div class="menu-wrap"><button class="button outline" type="button" data-act="menu" aria-haspopup="menu" aria-expanded="false">${icon("download")}Download</button>`
  + `<div class="menu" role="menu" hidden>${items.map(([attrs, label]) => `<button type="button" role="menuitem" ${attrs}>${label}</button>`).join("")}</div></div>`;

// The box for telling the AI what to change, in both editors. attr is what its button says to the editor's click handler.
const reviseField = (attr, example) => `<div class="inline-form editor-revise"><input type="text" data-revise placeholder="${esc(example)}" aria-label="Revision">`
  + `<button class="button light" type="button" ${attr}>${icon("sparkle")}Revise</button></div>`;

// The Markdown editor for interview prep and the company brief: text on the left, a rendered preview on the right.
// o: { text, leadId, stem (the download's file name), doc (the name the AI sees), save(text) }
function mountDocEditor(container, o) {
  container.classList.add("fill");
  container.innerHTML = `<div class="toolbar editor-bar"><button class="button primary" type="button" data-de="save">Save</button>
      ${downloadMenu(["pdf", "docx", "md"].map((fmt) => [`data-de="exp" data-fmt="${fmt}"`, fmt.toUpperCase()]))}
      ${reviseField('data-de="revise"', "Add three likely questions")}<span class="muted" data-state></span></div>
    <div class="editor"><textarea class="editor-text" spellcheck="true" aria-label="Text">${esc(o.text)}</textarea><div class="prose editor-preview"></div></div>`;
  const editor = $(".editor-text", container), preview = $(".editor-preview", container), state = $("[data-state]", container);
  const draw = () => (preview.innerHTML = md(editor.value));
  const drawSoon = debounce(draw, 150);
  const save = () => saveEditor(o, editor, state);
  editor.addEventListener("input", () => {
    S.dirty = true;  // at once, not with the preview: leaving right after typing must still ask first
    state.textContent = "Unsaved";
    drawSoon();
  });
  saveOnCtrlS(editor, save);
  container.onclick = async (e) => {
    const button = e.target.closest("[data-de]");
    if (!button) return;
    const what = button.dataset.de;
    if (what === "save") save();
    if (what === "exp") closeMenus();
    if (what === "exp" && (!S.dirty || (await save()))) {  // download what you see
      openUrl(`/api/leads/${o.leadId}/export/${o.stem}.${button.dataset.fmt}`);
    }
    if (what === "revise") {
      await reviseWithAI(button, `/api/leads/${o.leadId}/revise`, o.doc, $("[data-revise]", container).value.trim(), editor, () => {
        state.textContent = "Revised, not saved";
        draw();
      });
    }
  };
  draw();
}

// A US Letter page at 96 pixels per inch, the size the preview is drawn at before it's scaled to fit.
const PAGE_W = 816, PAGE_H = 1056;

// The resume and cover letter editor, used on a lead and for saved resumes (Settings, Resumes): Markdown on the left,
// the page exactly as its PDF will look on the right (POST /api/preview renders it on the server).
// o: { doc ("resume" or "cover"), text, save(text), files (download names), leadId, theme, maxPages, original (the AI's
//      version, for Revert), tools (more toolbar buttons), reviseUrl and fileHref (saved resumes) }
// It adds o.refresh() (redraw the preview), o.saveNow(), o.text() (what's in the editor) and o.setPages(n) (a new page
// limit: the preview gets taller or shorter, and the text stays as it is), and keeps o in S.editor for the layout menu
// and Check again.
function mountEditor(container, o) {
  container.innerHTML = `<div class="toolbar editor-bar">
      <button class="button primary" type="button" data-ed="save">Save</button>
      ${downloadMenu((o.files || []).map((f) => [`data-ed="file" data-file="${f}"`, f.split(".").pop().toUpperCase()]))}
      ${o.original ? `<button class="button text" type="button" data-ed="revert">${icon("undo")}Revert</button>` : ""}${o.tools || ""}
      ${reviseField('data-ed="revise"', "Shorten the summary")}
      <span class="muted" data-state></span><span class="tag" data-fit hidden></span></div>
    <div class="editor"><textarea class="editor-text" spellcheck="true" aria-label="${o.doc === "cover" ? "Cover letter" : "Resume"} text">${esc(o.text)}</textarea>
      <div class="preview"><div class="preview-page"><iframe sandbox="allow-same-origin" title="Preview"></iframe></div></div></div>`;
  const editor = $(".editor-text", container), frame = $("iframe", container), state = $("[data-state]", container);
  const wrap = $(".preview", container), page = $(".preview-page", container), fitTag = $("[data-fit]", container);
  let pages = Math.max(1, +o.maxPages || 1);
  // Shrink the full-size page to the width of the preview column.
  const scale = () => {
    const s = Math.max(0.1, Math.min(1, (wrap.clientWidth - 28) / PAGE_W));
    frame.style.height = `${PAGE_H * pages}px`;
    frame.style.transform = `scale(${s})`;
    page.style.width = `${PAGE_W * s}px`;
    page.style.height = `${PAGE_H * pages * s}px`;
  };
  // Typing sends a preview request every pause, and they can come back out of order: only the newest one is shown. A
  // failed one leaves the last good preview up and says so in the toolbar; the next edit tries again.
  let newest = 0;
  const refresh = async () => {
    const ticket = ++newest;
    let html;
    try {
      html = await api("/api/preview", { method: "POST", body: { doc: o.doc, md: editor.value, lead_id: o.leadId, theme: o.theme } });
    } catch (_) {
      if (ticket !== newest) return;
      fitTag.hidden = false;
      fitTag.className = "tag bad";
      fitTag.textContent = "Preview failed";
      return;
    }
    if (ticket !== newest) return;
    frame.onload = () => showFit(frame, o.doc, pages, fitTag);
    frame.srcdoc = html;
  };
  const later = debounce(refresh, 350);
  const save = async () => {
    const saved = await saveEditor(o, editor, state);
    if (saved && o.doc === "resume" && o.leadId) recheckResume(o.leadId);
    return saved;
  };
  o.refresh = refresh;
  o.saveNow = save;
  o.text = () => editor.value;
  o.setPages = (n) => {
    pages = Math.max(1, +n || 1);
    scale();
    refresh();
  };
  S.editor = o;
  editor.addEventListener("input", () => {
    S.dirty = true;
    state.textContent = "Unsaved";
    later();
  });
  saveOnCtrlS(editor, save);
  container.onclick = async (e) => {
    const button = e.target.closest("[data-ed]");
    if (!button) return;
    const what = button.dataset.ed;
    if (what === "save") save();
    if (what === "file") closeMenus();
    if (what === "file" && (!S.dirty || (await save()))) {  // download what you see
      openUrl(o.fileHref ? o.fileHref(button.dataset.file) : `/api/leads/${o.leadId}/export/${button.dataset.file}`);
    }
    if (what === "revert" && confirm("Replace this text with the AI's version?")) {
      editor.value = o.original;
      S.dirty = true;
      state.textContent = "Unsaved";
      refresh();
    }
    if (what === "revise") {
      const url = o.reviseUrl || `/api/leads/${o.leadId}/revise`;
      await reviseWithAI(button, url, o.doc, $("[data-revise]", container).value.trim(), editor, () => {
        state.textContent = "Revised, not saved";
        refresh();
      });
    }
  };
  // Rescale when the column changes width. Once the editor is gone (another tab, a redraw), the observer lets go of it.
  const resized = new ResizeObserver(() => (wrap.isConnected ? scale() : resized.disconnect()));
  resized.observe(wrap);
  scale();
  refresh();
}

// The text scales the server tries when it fits a resume to its page limit, largest first (FIT_SCALES in
// documents/render.py). Below 95% the server also tightens the margins (_resume_margins there).
const FIT_SCALES = [1, 0.97, 0.94, 0.91, 0.88, 0.86];

// After the preview loads: shrink a resume step by step until it fits its page limit, the same way the server fits the
// PDF, so the preview matches the download. The tag in the toolbar then says "Fits one page at 94%" or "Over one page".
function showFit(frame, doc, pages, tag) {
  try {
    const d = frame.contentDocument, page = d.querySelector(".page");
    d.documentElement.style.overflow = "hidden";
    // The tallest the preview may be: PAGE_H per page plus a few pixels of slack. When the page has
    // box-decoration-break: clone (render.py sets it), every printed page repeats the top and bottom margins, but the
    // preview is one tall sheet that has them once. So a two-page resume loses one set of margins at the page break.
    const tallest = (PAGE_H + 4) * pages;
    // How far the text reaches. The window's own scroll height won't do: the frame is as tall as the page limit.
    const used = () => (page ? page.getBoundingClientRect().bottom : d.documentElement.scrollHeight);
    const limit = () => {
      if (!page) return tallest;
      const css = getComputedStyle(page);  // this window's: the sandboxed preview runs no script of its own
      const repeats = (css.boxDecorationBreak || css.webkitBoxDecorationBreak) === "clone";
      const margins = parseFloat(css.paddingTop) + parseFloat(css.paddingBottom);
      return tallest - (repeats ? (pages - 1) * margins : 0);
    };
    let fit = 1;
    if (doc === "resume" && page) {
      for (const s of FIT_SCALES) {
        page.style.setProperty("--s", s);
        if (s < 0.95) {
          page.style.setProperty("--mt", "0.35in");
          page.style.setProperty("--mx", "0.42in");
        }
        fit = s;
        if (used() <= limit()) break;
      }
    }
    const over = used() > limit();
    const pageLimit = pages === 1 ? "one page" : `${pages} pages`;
    tag.hidden = !(over || fit < 1);
    tag.className = `tag ${over ? "bad" : "blue"}`;
    tag.textContent = over ? `Over ${pageLimit}` : `Fits ${pageLimit} at ${Math.round(fit * 100)}%`;
  } catch (_) {}  // the preview went away before it loaded
}

// ---------------------------------------------------------------- the resume's strategy and check
// The kinds of resume the AI writes (resume_strategy.archetype, from the package prompt in ai/prompts.py). A key that isn't
// here, such as one from a lead tailored by an older version, shows as its words with the first letter capitalized.
const ARCHETYPE_LABEL = { large_employer: "Large employer", small_business: "Small business or startup", public_sector: "Public sector",
  federal_usajobs: "Federal (USAJobs)", nonprofit: "Nonprofit", healthcare: "Healthcare", education: "Education",
  skilled_trades: "Skilled trades", service_retail: "Service and retail", creative_agency: "Creative or agency", technical: "Technical",
  research_lab: "Research lab", career_changer: "Career changer", experienced_professional: "Experienced professional", general: "General" };
const archetypeLabel = (key) => ARCHETYPE_LABEL[key] || humanize(key);

// The strategy section: the page limit, why the AI wrote the resume the way it did, and what the recruiter review changed.
// The kind of resume it wrote is on the line above, next to the check's score.
function resumeStrategyBlock(pkg) {
  const st = pkg.resume_strategy || {}, style = pkg.resume_style || { theme: "classic", max_pages: 1 }, review = pkg.resume_review || {};
  const detail = (label, text) => `<p class="lead-text"><b>${label}:</b> ${text}</p>`;
  const critic = review.changes?.length  // the scores come from the AI's answer, so they're escaped like its text
    ? `<details class="disclosure"><summary>Recruiter review: ${plural(review.changes.length, "change")} (${esc(review.before_score)}
        to ${esc(review.after_score ?? review.before_score)})</summary>${bulletList(review.changes)}</details>`
    : "";
  return block("Strategy",
    `${st.rationale ? `<p class="lead-text">${esc(st.rationale)}</p>` : `<p class="muted">No strategy yet</p>`}
    ${st.section_order?.length ? detail("Order", st.section_order.map(esc).join(", ")) : ""}
    ${st.projects?.length ? detail("Projects", st.projects.map(esc).join(", ")) : ""}
    ${st.summary ? detail("Summary", esc(st.summary)) : ""}
    ${st.skills_grouping ? detail("Skills", esc(st.skills_grouping)) : ""}
    ${critic}`,
    `<span class="tag">${style.max_pages === 2 ? "Two pages" : "One page"}</span>`);
}

// The check's score as a tag, for the line above the editor. "" before the first check.
function checkTag(check) {
  if (!check) return "";
  const level = check.score >= 85 ? "green" : check.score >= 65 ? "warn" : "bad";
  return `<span class="tag ${level}">Check ${esc(check.score)}/100</span>`;
}

// The resume check section: the score, pages, keyword coverage, and each issue the check found.
function resumeCheckBlock(check) {
  if (!check) {
    return block("Resume check", `<p class="muted">Not checked</p>`,
      `<button class="button outline small" type="button" data-act="resume-recheck">Check</button>`, "resume-check");
  }
  const level = check.score >= 85 ? "green" : check.score >= 65 ? "warn" : "bad";
  const issue = (i) => `<li class="${i.level === "error" ? "bad" : ""}">${icon(i.level === "error" ? "close" : "warning")}${esc(i.text)}</li>`;
  const issues = check.issues.length
    ? `<ul class="issue-list">${check.issues.map(issue).join("")}</ul>`
    : `<p class="good-note">${icon("check")}No issues</p>`;
  const tags = `<p class="tags"><span class="tag ${level}">${check.score}/100</span><span class="tag">${plural(check.pages ?? 0, "page")}</span>`
    + `<span class="tag ${check.coverage >= 0.75 ? "green" : "warn"}">Keywords ${Math.round((check.coverage || 0) * 100)}%</span></p>`;
  return block("Resume check", tags + issues,
    `<button class="button outline small" type="button" data-act="resume-recheck">Check again</button>`, "resume-check");
}

// Runs the resume check again (POST /api/leads/{id}/resume-check) and swaps in the new section. It dims meanwhile. Check
// again keeps the focus when it was the button you pressed. A check that comes back after you moved to another lead only
// updates that lead's data.
async function recheckResume(id) {
  const shown = S.leadView && lv(".resume-check");
  if (shown) shown.style.opacity = 0.5;
  try {
    const check = await api(`/api/leads/${id}/resume-check`, { method: "POST" });
    if (S.lead?.id === id && S.lead.package) S.lead.package.resume_check = check;
    const current = S.leadView?.id === id && lv(".resume-check");
    if (current) {
      const parent = current.parentElement, focus = focusKey(current);
      current.outerHTML = resumeCheckBlock(check);
      refocus(parent, focus);
      const tag = lv("[data-check-tag]");
      if (tag) tag.innerHTML = checkTag(check);
    }
  } catch (e) {
    if (shown) shown.style.opacity = "";
    toast("Check failed", e.message, "error");
  }
}

// ---------------------------------------------------------------- saving
// After a lead changed (its status, mostly): redraw it and every list that shows it, and the counts.
function leadChanged(summary) {
  if (S.route[0] === "leads" && summary) {
    upsertLead(summary);
    loadLeads(true);  // puts it in its place in the sort, and updates the counts on the tabs
  }
  if (S.route[0] === "tracker") refreshTracker();
  if (S.route[0] === "home") loadTopLeads();
  refreshStats();
  refreshLeadDetails();
}

// Sets the application status (PATCH). Marking it sent also sets a follow-up in 7 days on the server.
async function setStatus(id, status) {
  leadChanged(await api(`/api/leads/${id}`, { method: "PATCH", body: { app_status: status } }));
  toast("Status changed");
}

// The send buttons on an email: Gmail, the mail app, copy, download as .eml, or log it as sent.
async function mailAction(how, i) {
  const card = lv(`[data-email="${i}"]`);
  const field = (name) => $(`[data-ef="${name}"]`, card).value;
  const to = field("to_addr"), subject = field("subject"), body = field("body");
  const query = (pairs) => pairs.map(([key, value]) => `${key}=${encodeURIComponent(value)}`).join("&");
  if (how === "gmail") {
    openUrl(`https://mail.google.com/mail/?view=cm&fs=1&${query([["to", to], ["su", subject], ["body", body]])}`);
  } else if (how === "mailto") {
    const url = `mailto:${encodeURIComponent(to)}?${query([["subject", subject], ["body", body]])}`;
    if (ownWindow()) openUrl(url);
    else location.href = url;
  } else if (how === "copy") {
    copy(`Subject: ${subject}\n\n${body}`, "Email copied");
  } else if (how === "eml") {
    await saveEmails();  // the download is made from the saved email
    openUrl(`/api/leads/${S.lead.id}/export/email-${i}.eml`);
  } else if (how === "sent") {
    const kind = humanize(S.lead.package.emails[i].kind).toLowerCase();
    await api(`/api/leads/${S.lead.id}/events`, { method: "POST", body: { type: "email", text: `Sent ${kind} to ${to || "?"}: ${subject}` } });
    toast("Marked sent");
  }
}

// Saves the edited emails and the LinkedIn note into the lead's package. Does nothing when the Emails tab isn't open.
async function saveEmails() {
  if (!lv("[data-email]") && !lv("[data-note]")) return;
  const emails = (S.lead.package.emails || []).map((email, i) => {
    const card = lv(`[data-email="${i}"]`);
    const field = (name) => $(`[data-ef="${name}"]`, card).value;
    return { ...email, to_addr: field("to_addr"), subject: field("subject"), body: field("body") };
  });
  const changes = { emails };
  if (lv("[data-note]")) changes.linkedin_note = lv("[data-note]").value;
  await api(`/api/leads/${S.lead.id}`, { method: "PATCH", body: { package: changes } });
  Object.assign(S.lead.package, changes);
  S.dirty = false;
}

// After answering, dismissing or adding questions: reload them (for Home and the sidebar) and redraw the lead. When the
// list doesn't load, the lead is still redrawn; the sidebar catches up with the next "questions" event.
async function refreshLeadQuestions() {
  try {
    S.questions = await api("/api/questions");
    renderSideRun();
  } catch (_) {}
  await refreshLeadDetails();
}

// ---------------------------------------------------------------- actions
// Esc with a menu open in the Tracker's dialog closes only the menu (core.js does that), not the dialog around it.
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape" && $("dialog[open] .menu:not([hidden])")) e.preventDefault();
}, true);
onAction("lead-tab", (el) => {  // a tab (or the Emails button in the follow-up banner)
  if (S.dirty && !confirm("Discard your unsaved edits?")) return;
  S.dirty = false;
  if (S.leadView.hashBase) location.hash = `${S.leadView.hashBase}/${el.dataset.tab}`;  // on Leads the address follows
  else showLeadTab(el.dataset.tab);
});
onAction("apply", (el) => {
  openUrl(el.dataset.url);
  const lead = S.lead;
  if (lead && !["applied", "interviewing", "accepted"].includes(lead.app_status)) {
    toast("Did you apply?", "", "", null, { label: "Mark applied", run: () => setStatus(lead.id, "applied") });
  }
});
onAction("open-url", (el) => openUrl(el.dataset.url));  // Found at, in the header's menu
onAction("detail-track", () => setStatus(S.lead.id, "ready"));
onAction("detail-delete", async () => {
  // Ask about unsaved edits now: once it's deleted, moving on or closing its dialog must not ask again (and get a no).
  if (S.dirty && !confirm("Discard your unsaved edits?")) return;
  const { id, title, app_status: before } = S.lead;
  const summary = await api(`/api/leads/${id}`, { method: "PATCH", body: { app_status: "trashed" } });
  S.dirty = false;
  toast("Deleted", title, "", null, { label: "Undo", run: async () => leadChanged(await api(`/api/leads/${id}`, { method: "PATCH", body: { app_status: before } })) });
  if (S.leadView.hashBase) location.hash = nextLeadHash(id);  // on Leads, the next lead takes its place
  else closeDialog(S.leadView.box.closest("dialog"));
  leadChanged(summary);
});
onAction("regen", async () => {
  if (S.lead.resume_md && !confirm("Tailor again? This replaces your resume and letter edits.")) return;
  await api(`/api/leads/${S.lead.id}/package`, { method: "POST" });
  toast("Tailoring");
  setTimeout(() => refreshLeadDetails(), 800);
});
onAction("toggle-dream", async () => {
  leadChanged(await api(`/api/leads/${S.lead.id}`, { method: "PATCH", body: { dream: S.lead.dream ? 0 : 1 } }));
});
onAction("export", async (el) => {  // save open edits first, so the file matches the screen
  if (S.dirty && S.leadView?.tab === "emails") await saveEmails();
  if (S.dirty && S.leadView?.tab === "kit") await saveKitAnswers();
  openUrl(el.dataset.url);
});
// Resume tab
onAction("resume-recheck", async () => {
  if (S.dirty && S.editor) await S.editor.saveNow();  // saving a lead's resume runs the check
  else recheckResume(S.lead.id);
});
onAction("lead-lib-save", async () => {
  const name = prompt("Resume name", [S.lead.company, S.lead.title].filter(Boolean).join(": ").slice(0, 90));
  if (name === null) return;
  const item = await api("/api/library", { method: "POST", body: { lead_id: S.lead.id, name, md: S.editor?.text() || S.lead.resume_md, style: S.lead.package?.resume_style } });
  toast("Saved to resumes", item.name);
});
onAction("lead-lib-use", () => leadPickSavedDialog(S.lead));
// Emails tab
onAction("mail", (el) => mailAction(el.dataset.how, +el.dataset.i));
onAction("save-emails", async () => {
  await saveEmails();
  toast("Saved");
});
onAction("revise-email", async (el) => {
  const i = +el.dataset.i;
  const instruction = lv(`[data-erev="${i}"]`).value.trim();
  if (!instruction) return;
  const body = $('[data-ef="body"]', lv(`[data-email="${i}"]`));
  el.disabled = true;
  el.innerHTML = spinner();
  try {
    const r = await api(`/api/leads/${S.lead.id}/revise`, { method: "POST", body: { doc: `email (${S.lead.package.emails[i].kind})`, instruction, text: body.value } });
    body.value = r.text;
    S.dirty = true;
    toast("Email revised");
  } catch (err) {
    toast("Revision failed", err.message, "error");
  }
  el.disabled = false;
  el.innerHTML = `${icon("sparkle")}Revise`;
});
onAction("copy-note", () => copy(lv("[data-note]").value, "LinkedIn note copied"));
// Contacts tab
onAction("add-contact", async () => {
  const contact = {};
  $$("[data-nc]", S.leadView.box).forEach((input) => (contact[input.dataset.nc] = input.value.trim()));
  if (!contact.name) {
    toast("Name required", "", "error");
    return;
  }
  const r = await api(`/api/leads/${S.lead.id}/contacts/-1`, { method: "POST", body: contact });  // index -1 adds a contact
  S.lead.package.contacts = r.contacts;
  drawLeadTab();
});
onAction("rm-contact", async (el) => {
  if (!confirm("Remove this contact?")) return;
  const r = await api(`/api/leads/${S.lead.id}/contacts/${el.dataset.i}`, { method: "POST", body: { delete: true } });
  S.lead.package.contacts = r.contacts;
  drawLeadTab();
});
// Application kit tab
onAction("save-answers", async () => {
  await saveKitAnswers();
  lv("[data-answers-state]").textContent = "Saved";
});
onAction("add-answer", () => {
  readKitAnswers();
  S.lead.package.application_answers.push({ question: "New question", answer: "" });
  drawLeadTab();
  S.dirty = true;
});
onAction("rm-answer", (el) => {
  readKitAnswers();
  S.lead.package.application_answers.splice(+el.dataset.i, 1);
  drawLeadTab();
  S.dirty = true;
});
onAction("copy-answer", (el) => copy(lv(`[data-aa="${el.dataset.i}"]`).value));
// Activity tab
onAction("save-notes", async () => {
  await saveActivityField("[data-notes]", "notes", "");
  toast("Saved");
});
onAction("save-follow-up", async () => {
  await saveActivityField("[data-follow-up]", "follow_up_at", null);
  toast("Follow-up set");
  refreshStats();
});
onAction("log-event", async (el) => {  // a preset, or Log with your own text
  const text = el.dataset.text || lv("[data-event-text]").value.trim();
  if (!text) return;
  await api(`/api/leads/${S.lead.id}/events`, { method: "POST", body: { type: "update", text } });
  refreshLeadDetails();
});
// Questions for this application (Overview tab)
onAction("lead-gapq", async (el) => {
  el.disabled = true;
  el.innerHTML = `${spinner()} Thinking`;
  try {
    const r = await api(`/api/leads/${S.lead.id}/questions/generate`, { method: "POST" });
    toast(`${plural(r.added, "question")} added`);
  } catch (err) {
    toast("Couldn't find gaps", err.message, "error");
  }
  await refreshLeadQuestions();
  if (el.isConnected) {  // not drawn again (the lead didn't load, or you're editing this tab): usable again
    el.disabled = false;
    el.innerHTML = `${icon("sparkle")}Find gaps`;
  }
});
onAction("lead-answer", async (el) => {
  const input = $("[data-lead-answer]", el.closest(".question-row"));
  if (!input.value.trim()) return;
  await api("/api/questions/answer", { method: "POST", body: { question: input.dataset.leadAnswer, answer: input.value.trim() } });
  toast("Saved to profile");
  await refreshLeadQuestions();
});
onAction("lead-dismiss", async (el) => {
  await api("/api/questions/dismiss", { method: "POST", body: { question: el.dataset.q } });
  await refreshLeadQuestions();
});
onAction("lead-apply-answers", async (el) => {
  el.disabled = true;  // before the request, not after it: a second click mustn't start a second rework
  el.innerHTML = `${spinner()} Updating`;
  try {
    await api(`/api/leads/${S.lead.id}/apply-answers`, { method: "POST" });
  } catch (err) {
    el.disabled = false;
    el.innerHTML = `${icon("sparkle")}Update resume`;
    throw err;
  }
  toast("Updating resume");
});
// The menus and checkboxes in a lead's details save as soon as they change. When a save fails, the control goes back to
// what's saved (and the error shows in a toast), so the screen never shows a status or a layout the lead doesn't have.
onChange(async (el) => {
  if (!S.leadView || !S.leadView.box.contains(el)) return false;
  if (el.matches("[data-lead-status]")) {
    await setStatus(S.lead.id, el.value).catch((err) => {
      el.value = S.lead.app_status;
      throw err;
    });
  } else if (el.matches("[data-lead-industry]")) {
    const summary = await api(`/api/leads/${S.lead.id}`, { method: "PATCH", body: { industry: el.value } }).catch((err) => {
      el.value = S.lead.industry || "";
      throw err;
    });
    leadChanged(summary);
    toast("Industry changed");
  } else if (el.matches("[data-plan]")) {  // an action plan step done or not
    const pkg = S.lead.package, before = pkg.plan_done || [];
    const done = new Set(before);
    if (el.checked) done.add(+el.dataset.plan);
    else done.delete(+el.dataset.plan);
    pkg.plan_done = [...done];
    el.nextElementSibling.classList.toggle("done", el.checked);
    await api(`/api/leads/${S.lead.id}`, { method: "PATCH", body: { package: { plan_done: pkg.plan_done } } }).catch((err) => {
      pkg.plan_done = before;
      el.checked = !el.checked;
      el.nextElementSibling.classList.toggle("done", el.checked);
      throw err;
    });
  } else if (el.matches("[data-resume-theme]")) {  // the Layout menu in the resume's toolbar
    const style = { ...(S.lead.package.resume_style || { max_pages: 1 }), theme: el.value };
    await api(`/api/leads/${S.lead.id}`, { method: "PATCH", body: { package: { resume_style: style } } }).catch((err) => {
      el.value = S.lead.package.resume_style?.theme || "classic";
      throw err;
    });
    S.lead.package.resume_style = style;
    if (S.editor) {
      S.editor.theme = el.value;
      S.editor.refresh();
    }
    toast("Layout changed");
    recheckResume(S.lead.id);
  } else {
    return false;
  }
  return true;
});
