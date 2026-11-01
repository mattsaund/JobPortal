/* lead.js: everything about one lead, drawn into any container: an open card on Leads (#/leads/12, or #/leads/12/emails
   for a tab) or the Tracker's large dialog. At the top: the actions (Add to tracker, Apply, the status, the industry,
   Dream, downloads, tailor again, Delete) and banners for the application's state. Then the tabs: the overview (the fit,
   the action plan, the role in brief, and questions that would make this application stronger), the tailored resume
   (editor, live preview, layouts and the resume check), the cover letter, emails, contacts, interview prep, the company
   brief, the application kit, the posting, and activity.

   APIs: GET /api/leads/{id} (the lead with its package), PATCH /api/leads/{id} (every edit), POST /api/preview (the
   editor's live preview), POST /api/leads/{id}/revise, /package, /resume-check, /events, /contacts/{i},
   /questions/generate and /apply-answers, POST /api/questions/answer and /dismiss, GET /api/questions, GET /api/profile
   (the kit's standard answers), POST /api/library (Save to my resumes), and the downloads under /api/leads/{id}/export/.
   S.lead is the lead on screen and S.leadView where it's drawn; S.dirty marks unsaved edits. A "lead" event redraws
   it (refreshLeadDetails, from live.js), but never the open tab while it has unsaved edits or you're typing in it. */
"use strict";

// ---------------------------------------------------------------- showing a lead
// Shows a lead in box. opts: tab (the one to open; an unknown one, from an old or mistyped address, opens the
// overview), hashBase (tabs change the address, as on Leads: #/leads/12/emails), header (draw the title, company and
// match pill too: the Tracker's dialog has no card around it).
async function showLeadDetails(box, id, opts = {}) {
  const tab = DETAIL_TABS.some(([key]) => key === opts.tab) ? opts.tab : "overview";
  S.leadView = { box, id, tab, hashBase: opts.hashBase || "", header: !!opts.header };
  S.lead = null;
  box.innerHTML = `<p class="loading">${spinner()} Loading</p>`;
  let lead;
  try {
    lead = await api(`/api/leads/${id}`);
  } catch (err) {
    if (S.leadView?.box === box) box.innerHTML = `<div class="empty-state"><h3>That lead is gone</h3><p>${esc(err.message)}</p></div>`;
    return;
  }
  if (S.leadView?.box !== box || S.leadView.id !== id) return;  // something else opened while it loaded
  S.lead = lead;
  drawLeadDetails();
}

// Forgets the lead on screen: its card closed, or its dialog.
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

// Draws the lead: the header (in the Tracker's dialog), the actions, the banners, the tabs and the open tab. Drawn
// again after a change, it replaces only what's above the tabs, and draws the open tab again unless it has unsaved edits
// or you're typing in it: the tab stays in the page, so its text, cursor and scroll position stay too. A focused button
// or menu above the tabs gets the focus back in the new HTML.
function drawLeadDetails() {
  const l = S.lead, view = S.leadView, packaged = !!l.resume_md;
  const head = (view.header ? `<div class="detail-header">${companyLogo(l.company)}
      <div class="job-title"><h2>${esc(l.title)}</h2><div class="company-line"><span>${esc(l.company)}</span>${stageTag(l)}</div>
        <div class="job-meta">${leadMeta(l)}</div></div>${matchPill(l.score || null)}</div>
    <div class="tags">${leadTags(l)}</div>` : "")
    + `<div class="detail-actions">${leadActions(l, packaged)}</div>${leadBanners(l, packaged)}`;
  const body = lv("[data-lead-body]");
  if (!body) {  // the first time
    const tabs = DETAIL_TABS.map(([key, label]) => `<button class="tab${view.tab === key ? " active" : ""}" type="button" role="tab"`
      + ` aria-selected="${view.tab === key}" data-act="lead-tab" data-tab="${key}">${label}</button>`).join("");
    view.box.innerHTML = `<div class="lead-details">${head}<div class="tabs" role="tablist" aria-label="About this lead">${tabs}</div>`
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

// The actions row. A deleted lead has Restore and Delete forever instead of Delete.
function leadActions(l, packaged) {
  const apply = safeUrl(l.apply_url) || safeUrl(l.url);
  const statuses = S.meta.statuses.filter((s) => s !== "trashed" || l.app_status === "trashed").map((s) => [s, statusLabel(s)]);
  // The industry menu offers the Settings list, plus the lead's own industry when it isn't on that list.
  const industries = S.industries || [];
  const industryChoices = l.industry && !industries.includes(l.industry) ? [...industries, l.industry] : industries;
  const remove = l.app_status === "trashed"
    ? `<button class="button outline" type="button" data-act="lead-restore" data-id="${l.id}">${icon("undo")}Restore</button>`
      + `<button class="button danger" type="button" data-act="lead-purge" data-id="${l.id}">${icon("trash")}Delete forever</button>`
    : `<button class="button danger" type="button" data-act="detail-delete">${icon("trash")}Delete</button>`;
  return (l.app_status === "new" ? `<button class="button light" type="button" data-act="detail-track">${icon("plus")}Add to tracker</button>` : "")
    + (apply ? `<button class="button primary" type="button" data-act="apply" data-url="${esc(apply)}">Apply ${icon("external")}</button>` : "")
    + `<label class="control"><span>Status</span><select data-lead-status>${selectOptions(statuses, l.app_status)}</select></label>`
    + `<label class="control"><span>Industry</span><select data-lead-industry>${selectOptions([["", "Not set"], ...industryChoices], l.industry || "")}</select></label>`
    + `<button class="button outline${l.dream ? " on" : ""}" type="button" data-act="toggle-dream" aria-pressed="${!!l.dream}">${icon("star", l.dream ? "filled" : "")}Dream job</button>`
    + (packaged ? `<a class="button outline" href="/api/leads/${l.id}/export/package.zip" title="Resume, cover letter, emails, answers, prep, brief and contacts">${icon("download")}All files</a>` : "")
    + `<button class="button outline" type="button" data-act="regen">${icon("refresh")}${packaged ? "Tailor again" : "Tailor it now"}</button>`
    + `<span class="spacer"></span>${remove}`;
}

// A banner: a note across the details with an icon and, sometimes, a button.
const banner = (cls, mark, text, action = "") => `<div class="banner ${cls}">${mark}<div>${text}</div>${action}</div>`;

// The banners: the application is being tailored, failed or isn't tailored yet, the posting looks closed, or a
// follow-up is due.
function leadBanners(l, packaged) {
  let html = "";
  if (l.stage === "packaging") {
    html = banner("info", spinner(), `<b>JobPortal is tailoring this application:</b> reading the posting, researching the company, finding
      people to contact, and writing your resume and cover letter. Usually 2 to 6 minutes.`);
  } else if (l.stage === "error") {
    html = banner("bad", icon("warning"), `<b>Tailoring failed:</b> ${esc(l.stage_error)}`,
      `<button class="button outline" type="button" data-act="regen">Try again</button>`);
  } else if (!packaged) {
    const why = l.stage === "filtered" ? "This one scored below your bar, so it wasn't tailored." : "This one isn't tailored yet.";
    html = banner("", icon("sparkle"), `${why} JobPortal can write its resume, cover letter and emails now.`,
      `<button class="button primary" type="button" data-act="regen">Tailor it now</button>`);
  } else if (l.stage === "closed") {
    html = banner("bad", icon("warning"), "<b>This posting looks closed.</b> Check the link before you spend time on it.");
  }
  const waiting = ["applied", "interviewing"].includes(l.app_status);
  if (packaged && waiting && l.follow_up_at && daysUntil(l.follow_up_at) <= 0) {
    html += banner("warn", icon("bell"), "<b>Time to follow up.</b> A follow-up email is ready under Emails.",
      `<button class="button outline" type="button" data-act="lead-tab" data-tab="emails">Open emails</button>`);
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
  ["prep", "Interview prep", (box, l, pkg) => renderNotesTab(box, l, pkg, "prep")],
  ["intel", "Company brief", (box, l, pkg) => renderNotesTab(box, l, pkg, "intel")],
  ["kit", "Application kit", renderKitTab],
  ["posting", "Posting", renderPostingTab],
  ["activity", "Activity", renderActivityTab],
];

// Fills the tab body. It swaps in a fresh, empty body first, which drops the listeners the last tab added.
function drawLeadTab() {
  const view = S.leadView;
  const old = lv("[data-lead-body]");
  const body = old.cloneNode(false);
  old.replaceWith(body);
  $$(".tabs .tab", view.box).forEach((tab) => {
    tab.classList.toggle("active", tab.dataset.tab === view.tab);
    tab.setAttribute("aria-selected", String(tab.dataset.tab === view.tab));
  });
  S.editor = null;
  const tab = DETAIL_TABS.find(([key]) => key === view.tab) || DETAIL_TABS[0];
  tab[2](body, S.lead, S.lead.package || {});
}

// Opens another tab of the lead on screen.
function showLeadTab(tab) {
  const view = S.leadView;
  const key = DETAIL_TABS.some(([k]) => k === tab) ? tab : "overview";
  if (!view || !S.lead || view.tab === key) return;
  view.tab = key;
  drawLeadTab();
}

// A block: a titled box inside the details. head adds buttons or tags on the title's line; cls adds classes.
const block = (title, html, head = "", cls = "") => `<section class="block${cls ? " " + cls : ""}">`
  + `${title || head ? `<div class="block-head"><h3>${title}</h3>${head}</div>` : ""}${html}</section>`;

// The empty state of a tab whose part of the application doesn't exist yet.
const noneYet = (what) => `<div class="empty-state"><h3>No ${what} yet</h3><p>Tailor this application to write it.</p>
  <button class="button primary" type="button" data-act="regen">Tailor it now</button></div>`;

// Keyword tags: green for the job's keywords your resume has, plain (with a tip) for the ones it lacks.
function keywordTags(coverage, missingTip) {
  const hits = (coverage.hit || []).map((k) => `<span class="tag green">${esc(k)}</span>`).join("");
  const misses = (coverage.miss || []).map((k) => `<span class="tag" title="${missingTip}">${esc(k)}</span>`).join("");
  return `<div class="tags">${hits}${misses}</div>`;
}

// Overview: questions that would make this application stronger, the fit (summary, strengths, gaps, eligibility), the
// action plan and the role in brief; on the right the facts at a glance, red flags and the keywords in your resume.
function renderOverviewTab(box, l, pkg) {
  const fit = pkg.fit || {}, triage = l.triage || {}, coverage = pkg.coverage || {};
  const plan = pkg.action_plan || [], done = pkg.plan_done || [];
  const fitBlock = fit.summary || triage.summary ? block("Why it fits", `<p>${esc(fit.summary || triage.summary)}</p>
      ${fit.strengths?.length ? `<h4>Your strengths</h4>${bulletList(fit.strengths, "good")}` : ""}
      ${fit.gaps?.length ? `<h4>Gaps, and how to handle them</h4>${bulletList(fit.gaps, "warn")}` : ""}
      ${fit.eligibility_notes ? `<p><b>Eligibility:</b> ${esc(fit.eligibility_notes)}</p>` : ""}`) : "";
  const planItem = (step, i) => `<label class="check-row"><input type="checkbox" data-plan="${i}"${done.includes(i) ? " checked" : ""}>`
    + `<span class="${done.includes(i) ? "done" : ""}">${esc(step)}</span></label>`;
  const planBlock = plan.length ? block("Your action plan", `<div class="check-list">${plan.map(planItem).join("")}</div>`) : "";
  const roleBlock = pkg.job_summary ? block("The role in brief", `<div class="prose">${md(pkg.job_summary)}</div>`) : "";
  const postingUrl = safeUrl(l.url);
  const posting = postingUrl ? `<a href="${esc(postingUrl)}" target="_blank" rel="noopener">${esc(postingUrl.replace(/^https?:\/\//, "").slice(0, 60))}</a>` : "None";
  const foundAt = foundList(l).map((f) => `<a class="tag blue" href="${esc(f.url)}" target="_blank" rel="noopener" title="${esc(f.label)}">${icon("external")}${esc(foundShort(f))}</a>`).join("");
  // "82, eligible: reason; reason". The eligibility part is left out when the scoring didn't give one. The score comes
  // from the AI's answer, so it's escaped like any other text.
  const scored = [esc(triage.score ?? "-"), esc(triage.eligibility || "")].filter((part) => part !== "").join(", ")
    + (triage.reasons?.length ? `: ${esc(triage.reasons.join("; "))}` : "");
  const flagsBlock = triage.red_flags?.length ? block("Red flags", bulletList(triage.red_flags, "warn")) : "";
  const coverageBlock = coverage.hit || coverage.miss
    ? block(`Job keywords in your resume: ${Math.round((l.ats_coverage || 0) * 100)}%`, keywordTags(coverage, "Not in your resume. Add it only if it's true."))
    : "";
  box.innerHTML = `${leadQuestionsBlock(l)}<div class="two-col"><div class="stack">${fitBlock}${planBlock}${roleBlock}
      ${fitBlock || planBlock || roleBlock ? "" : `<div class="empty-state"><h3>Not tailored yet</h3><p>The fit and an action plan show up here once it's tailored.</p></div>`}</div>
    <div class="stack">${block("At a glance", `<dl class="facts">
        <dt>Status</dt><dd>${esc(statusLabel(l.app_status))}${l.applied_at ? `, applied ${esc(fmtDate(l.applied_at))}` : ""}</dd>
        <dt>Deadline</dt><dd>${esc(l.deadline ? fmtDate(l.deadline) : "Not given")}</dd>
        <dt>Posted</dt><dd>${esc(l.posted_at ? fmtDate(l.posted_at) : "Not given")}</dd>
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
    return `<div class="banner">${icon("question")}<div>Could anything you haven't told JobPortal make this resume stronger?</div>
      <button class="button outline" type="button" data-act="lead-gapq">${icon("sparkle")}Ask me about gaps</button></div>`;
  }
  const open = questions.filter((q) => q.status === "open"), answered = questions.filter((q) => q.status === "answered");
  const openItem = (q) => `<div class="question-row"><b>${esc(q.question)}</b>${q.why ? `<small>${esc(q.why)}</small>` : ""}
      <div class="inline-form"><input type="text" data-lead-answer="${esc(q.question)}" placeholder="Your answer" aria-label="Your answer">
        <button class="button outline" type="button" data-act="lead-answer">Save</button>
        <button class="icon-button" type="button" data-act="lead-dismiss" data-q="${esc(q.question)}" aria-label="Not relevant" title="Not relevant">${icon("close")}</button></div></div>`;
  const answeredItem = (q) => `<div class="question-row done"><b>${esc(q.question)}</b><small>${icon("check")}${esc(q.answer || "")}</small></div>`;
  const rework = answered.length
    ? `<button class="button primary" type="button" data-act="lead-apply-answers">${icon("sparkle")}Update this resume with my answers</button>` : "";
  return block(`${icon("question")}Questions that could make this application stronger`, `<p class="block-note">Your answers go into your
      profile, so every future application gets them too.</p>${open.map(openItem).join("")}${answered.map(answeredItem).join("")}
      ${rework ? `<div class="block-actions">${rework}</div>` : ""}`, "", "questions-block");
}

// Resume and Cover letter: the editor with its live preview, downloads and "Revise with AI". The resume tab adds the
// strategy and resume check, and the buttons for your resume collection.
function renderDocumentTab(box, l, pkg, doc) {
  const isResume = doc === "resume";
  const text = isResume ? l.resume_md : l.cover_md;
  if (!text) {
    box.innerHTML = isResume
      ? `<div class="empty-state"><h3>No tailored resume yet</h3><p>Tailor this application to write one, or start from a resume you saved.</p>
          <div class="block-actions"><button class="button primary" type="button" data-act="regen">Tailor it now</button>
          <button class="button outline" type="button" data-act="lead-lib-use">Use a saved resume</button></div></div>`
      : noneYet("cover letter");
    return;
  }
  let host = box;
  if (isResume) {
    box.innerHTML = `<div class="two-col">${resumeStrategyBlock(pkg)}${resumeCheckBlock(pkg.resume_check)}</div><div class="editor-host"></div>`;
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
      ? `<button class="button outline" type="button" data-act="lead-lib-save" title="Keep a copy in Settings, Resumes">${icon("star")}Save to my resumes</button>`
        + `<button class="button outline" type="button" data-act="lead-lib-use">Use a saved resume</button>`
      : "",
    coverage: isResume ? pkg.coverage : null,
  });
}

// Emails: each email with its recipient, subject and body to edit, the ways to send it, and "Revise" by instruction.
// Then the LinkedIn connection note, and buttons to download or save them all.
function renderEmailsTab(box, l, pkg) {
  const emails = pkg.emails || [];
  if (!emails.length && !pkg.linkedin_note) {
    box.innerHTML = noneYet("emails");
    return;
  }
  // The "To" box suggests the contacts that have an email address.
  const suggestions = (pkg.contacts || []).filter((c) => c.email)
    .map((c) => `<option value="${esc(c.email)}">${esc(c.name)}, ${esc(c.title)}</option>`).join("");
  const emailCard = (e, i) => `<section class="block email-card" data-email="${i}">
      <div class="email-head"><span class="tag green">${esc(humanize(e.kind))}</span><small>${esc(e.to)}</small><span class="spacer"></span>
        <button class="button outline small" type="button" data-act="mail" data-how="gmail" data-i="${i}">Gmail ${icon("external")}</button>
        <button class="button outline small" type="button" data-act="mail" data-how="mailto" data-i="${i}">Mail app</button>
        <button class="button outline small" type="button" data-act="mail" data-how="copy" data-i="${i}">${icon("copy")}Copy</button>
        <button class="button outline small" type="button" data-act="mail" data-how="eml" data-i="${i}" title="Download as an unsent draft for Outlook, Apple Mail or Thunderbird">.eml</button>
        <button class="button light small" type="button" data-act="mail" data-how="sent" data-i="${i}">${icon("check")}Mark sent</button></div>
      <div class="form-grid"><label class="field"><span class="field-label">To</span><input type="email" list="contact-emails" data-ef="to_addr" value="${esc(pickTo(e))}" placeholder="Pick a contact or type an address"></label>
        <label class="field"><span class="field-label">Subject</span><input type="text" data-ef="subject" value="${esc(e.subject)}"></label></div>
      <textarea data-ef="body" rows="9" aria-label="Email text">${esc(e.body)}</textarea>
      <div class="inline-form"><input type="text" data-erev="${i}" placeholder="Say how to change this email" aria-label="How to change it">
        <button class="button light" type="button" data-act="revise-email" data-i="${i}">${icon("sparkle")}Revise</button></div></section>`;
  const note = pkg.linkedin_note ? block("LinkedIn connection note",
    `<textarea data-note rows="3" aria-label="LinkedIn note">${esc(pkg.linkedin_note)}</textarea>
      <div class="block-actions"><button class="button outline small" type="button" data-act="copy-note">${icon("copy")}Copy</button></div>`,
    `<small class="count" data-note-count>${pkg.linkedin_note.length}/300</small>`) : "";
  box.innerHTML = `<datalist id="contact-emails">${suggestions}</datalist><div class="stack">${emails.map(emailCard).join("")}${note}
      <div class="block-actions end"><span class="muted-note">Download all emails:</span>${exportButtons(l.id, "emails", ["md", "docx", "pdf"])}
        <button class="button primary" type="button" data-act="save-emails">Save edits</button></div></div>`;
  box.addEventListener("input", (e) => {
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
// right away, and you can add or remove people.
function renderContactsTab(box, l, pkg) {
  const contacts = pkg.contacts || [];
  const input = (i, key, value, placeholder) => `<input type="text" data-cf="${key}" data-i="${i}" value="${esc(value || "")}" placeholder="${placeholder}" aria-label="${placeholder}">`;
  const confidence = (c) => (c.email_confidence === "found" ? "green" : c.email_confidence === "pattern" ? "warn" : "");
  const link = (url, label) => (safeUrl(url) ? `<a href="${esc(safeUrl(url))}" target="_blank" rel="noopener">${label}</a>` : "");
  const links = (c) => link(c.linkedin, "LinkedIn") + link(c.source_url, "Source");
  const row = (c, i) => `<tr><td><div class="cell-stack">${input(i, "name", c.name, "Name")}${input(i, "title", c.title, "Title")}${input(i, "org", c.org, "Organization")}</div></td>
      <td><div class="cell-stack">${input(i, "email", c.email, "Email")}<div class="cell-row"><span class="tag ${confidence(c)}">${esc(humanize(c.email_confidence || "unknown"))}</span>
        ${c.email ? `<button class="text-button" type="button" data-act="copytext" data-text="${esc(c.email)}">Copy</button>` : ""}</div></div></td>
      <td><div class="cell-stack">${input(i, "linkedin", c.linkedin, "LinkedIn link")}${input(i, "notes", c.notes, "Notes")}<div class="cell-row">${links(c)}</div></div></td>
      <td><textarea class="why" data-cf="why" data-i="${i}" rows="4" aria-label="Why them">${esc(c.why || "")}</textarea></td>
      <td>${contactStatusSelect(l.id, i, c.status)}</td>
      <td><button class="icon-button" type="button" data-act="rm-contact" data-i="${i}" aria-label="Remove ${esc(c.name)}">${icon("trash")}</button></td></tr>`;
  const table = contacts.length ? `<div class="table-wrap"><table class="table"><thead><tr><th>Name, title, organization</th><th>Email</th><th>LinkedIn and notes</th>
      <th>Why them</th><th>Status</th><th><span class="sr-only">Remove</span></th></tr></thead><tbody>${contacts.map(row).join("")}</tbody></table></div>`
    : `<p class="muted-note">No contacts found yet.</p>`;
  box.innerHTML = block(`People to reach (${contacts.length})`,
    `<p class="block-note">Found by the AI on the public web. Every field saves when you leave it. <b>Found</b> means the email was seen in
      public; <b>Pattern</b> means it was worked out from the company's email format, so check it first.</p>${table}
    <h4>Add someone</h4><div class="form-grid three"><input type="text" placeholder="Name" data-nc="name" aria-label="Name">
      <input type="text" placeholder="Title" data-nc="title" aria-label="Title"><input type="email" placeholder="Email" data-nc="email" aria-label="Email">
      <input type="url" placeholder="LinkedIn link" data-nc="linkedin" aria-label="LinkedIn link"><input type="text" placeholder="Why them, or notes" data-nc="why" aria-label="Why them">
      <button class="button outline" type="button" data-act="add-contact">${icon("plus")}Add contact</button></div>`,
    exportButtons(l.id, "contacts", ["csv"]));
  // An edited contact field saves that one field when you leave it. The value also goes into the lead on screen (S.lead,
  // which a live update may have read again since this tab was drawn), so the tab shows it when it's drawn again.
  box.addEventListener("change", async (e) => {
    const el = e.target;
    if (!el.dataset.cf) return;
    try {
      await api(`/api/leads/${l.id}/contacts/${el.dataset.i}`, { method: "POST", body: { [el.dataset.cf]: el.value } });
    } catch (err) {
      toast("Couldn't save the contact", err.message, "error");
      return;
    }
    const contact = S.lead?.id === l.id && S.lead.package?.contacts?.[+el.dataset.i];
    if (contact) contact[el.dataset.cf] = el.value;
  });
}

// Interview prep and the company brief: Markdown documents with a preview, downloads and "Revise with AI".
const NOTES_DOCS = {
  intel: { key: "company_brief_md", name: "company brief", stem: "company_intel", doc: "company brief" },
  prep: { key: "interview_prep_md", name: "interview prep", stem: "interview_prep", doc: "interview prep" },
};
function renderNotesTab(box, l, pkg, tab) {
  const { key, name, stem, doc } = NOTES_DOCS[tab];
  if (!pkg[key]) {
    box.innerHTML = noneYet(name);
    return;
  }
  mountDocEditor(box, {
    text: pkg[key],
    leadId: l.id,
    stem,
    doc,
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
    + `<button class="text-button" type="button" data-act="copytext" data-text="${esc(a)}">${icon("copy")}Copy</button></div>`;
  const apply = safeUrl(l.apply_url) || safeUrl(l.url);
  const answers = pkg.application_answers || [];
  const answerEditor = (x, i) => `<div class="answer-edit"><div class="inline-form"><input type="text" data-aq="${i}" value="${esc(x.question)}" aria-label="Question">
        <button class="button outline small" type="button" data-act="copy-answer" data-i="${i}">${icon("copy")}Copy</button>
        <button class="icon-button" type="button" data-act="rm-answer" data-i="${i}" aria-label="Remove this question">${icon("trash")}</button></div>
      <textarea data-aa="${i}" rows="5" aria-label="Answer">${esc(x.answer)}</textarea></div>`;
  const standard = (qa || []).filter((x) => !x.eeo), selfId = (qa || []).filter((x) => x.eeo);  // eeo = voluntary self-identification
  const noStandard = qa ? "Answer the standard questions to fill these in." : "Your standard answers didn't load. Open this tab again to see them.";
  const selfIdBlock = selfId.length ? block("Voluntary self-identification", `<p class="block-note">Shown here only so you can copy it.
      It's never sent to the AI.</p>${selfId.map((x) => copyRow(x.q, x.a)).join("")}`) : "";
  box.innerHTML = `<div class="two-col"><div class="stack">
    ${block("Files", `<div class="button-row">${l.resume_md ? exportButtons(l.id, "resume", ["pdf", "docx", "md"], "Resume") : ""}</div>
      <div class="button-row">${l.cover_md ? exportButtons(l.id, "cover_letter", ["pdf", "docx", "md"], "Cover letter") : ""}</div>
      <div class="button-row"><a class="button outline" href="/api/leads/${l.id}/export/package.zip">${icon("download")}Everything (.zip)</a>
        ${apply ? `<button class="button primary" type="button" data-act="apply" data-url="${esc(apply)}">Open the application ${icon("external")}</button>` : ""}</div>`)}
    ${block("Tailored answers",
      `<div class="stack">${answers.map(answerEditor).join("") || `<p class="muted-note">Tailor this application to write answers to its questions.</p>`}</div>
      <div class="block-actions"><button class="button outline" type="button" data-act="add-answer">${icon("plus")}Add a question</button><span class="spacer"></span>
        <span class="muted-note" data-answers-state></span><button class="button primary" type="button" data-act="save-answers">Save answers</button></div>`,
      exportButtons(l.id, "answers", ["docx", "pdf", "md"]))}
  </div><div class="stack">${block("Your standard answers", `<p class="block-note">From your answers in <a href="#/settings/profile/answers">Settings, Profile</a>.
      Change them there.</p>${standard.map((x) => copyRow(x.q, x.a)).join("") || `<p class="muted-note">${noStandard}</p>`}`)}
    ${selfIdBlock}</div></div>`;
  box.addEventListener("input", (e) => {
    if (e.target.dataset.aq == null && e.target.dataset.aa == null) return;
    S.dirty = true;
    lv("[data-answers-state]").textContent = "Not saved yet";
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
  const posting = postingUrl ? `<a class="button outline" href="${esc(postingUrl)}" target="_blank" rel="noopener">Open the posting ${icon("external")}</a>` : "";
  const applyPage = applyUrl && applyUrl !== postingUrl
    ? `<a class="button outline" href="${esc(applyUrl)}" target="_blank" rel="noopener">Apply page ${icon("external")}</a>` : "";
  box.innerHTML = block("", `<div class="button-row">${posting}${applyPage}<span class="muted-note">${esc(l.source_detail || "")}</span></div>
    <pre class="posting-text">${esc(l.description || "No description was captured for this job.")}</pre>`);
}

// Activity: your notes, the timeline, the follow-up date, and buttons to log what happened.
const EVENT_PRESETS = ["Recruiter reached out", "Got an assessment", "Interview scheduled", "Referral submitted", "Got an offer", "Rejected"];
function renderActivityTab(box, l) {
  const timeline = (l.events || []).map((e) => `<li class="timeline-row"><span class="timeline-time">${esc(localStamp(e.ts))}</span>`
    + `<span class="tag">${esc(humanize(e.type))}</span><span>${esc(e.text)}</span></li>`).join("");
  const presets = EVENT_PRESETS.map((text) => `<button class="chip" type="button" data-act="log-event" data-text="${esc(text)}">${esc(text)}</button>`).join("");
  box.innerHTML = `<div class="two-col"><div class="stack">
      ${block("Notes", `<textarea data-notes rows="8" aria-label="Notes">${esc(l.notes || "")}</textarea>
        <div class="block-actions"><button class="button outline" type="button" data-act="save-notes">Save notes</button></div>`)}
      ${block("Timeline", timeline ? `<ul class="timeline">${timeline}</ul>` : `<p class="muted-note">Nothing yet.</p>`)}</div>
    <div class="stack">${block("Follow-up", `<label class="field"><span class="field-label">Follow up on</span><input type="date" data-follow-up value="${esc(l.follow_up_at || "")}"></label>
        <div class="block-actions"><button class="button outline" type="button" data-act="save-follow-up">Save date</button></div>`)}
      ${block("Log what happened", `<div class="filters">${presets}</div>
        <div class="inline-form"><input type="text" data-event-text placeholder="Something else" aria-label="What happened">
          <button class="button outline" type="button" data-act="log-event">Log it</button></div>`)}</div></div>`;
  // The notes and the follow-up date have Save buttons, so a change to either is an unsaved edit until it's saved: moving
  // away asks first, and live updates leave the tab alone. "Log what happened" isn't: it's sent as you log it.
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

// Download buttons: exportButtons(12, "resume", ["pdf", "docx"], "Resume") makes "Resume PDF" and "Resume DOCX".
function exportButtons(leadId, stem, formats, label = "") {
  return formats.map((fmt) => `<button class="button outline small" type="button" data-act="export" data-url="/api/leads/${leadId}/export/${stem}.${fmt}">`
    + `${icon("download")}${label ? label + " " : ""}${fmt.toUpperCase()}</button>`).join("");
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
    toast("Couldn't save it", err.message, "error");
    return false;
  }
  S.dirty = editor.value !== text;
  state.textContent = S.dirty ? "Not saved yet" : "Saved";
  return true;
}

// "Revise with AI" in both editors: sends the text and your instruction (POST .../revise) and puts the AI's version in
// the editor. Nothing is saved until you click Save.
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
    toast("The revision didn't work", err.message, "error");
  }
  button.disabled = false;
  button.innerHTML = `${icon("sparkle")}Revise with AI`;
}

// The Markdown editor for interview prep and the company brief: text on the left, a rendered preview on the right.
// o: { text, leadId, stem (the download's file name), doc (the name the AI sees), save(text) }
function mountDocEditor(container, o) {
  container.innerHTML = `<div class="toolbar"><button class="button primary" type="button" data-de="save">Save</button>
      ${["pdf", "docx", "md"].map((fmt) => `<button class="button outline small" type="button" data-de="exp" data-fmt="${fmt}">${icon("download")}${fmt.toUpperCase()}</button>`).join("")}
      <span class="muted-note" data-state></span></div>
    <div class="inline-form revise"><input type="text" data-revise placeholder="Say how to change it, like: add three likely questions, shorten the history" aria-label="How to change it">
      <button class="button light" type="button" data-de="revise">${icon("sparkle")}Revise with AI</button></div>
    <div class="editor"><textarea class="editor-text" spellcheck="true" aria-label="Text">${esc(o.text)}</textarea><div class="block prose editor-preview"></div></div>`;
  const editor = $(".editor-text", container), preview = $(".editor-preview", container), state = $("[data-state]", container);
  const draw = () => (preview.innerHTML = md(editor.value));
  const drawSoon = debounce(draw, 150);
  const save = () => saveEditor(o, editor, state);
  editor.addEventListener("input", () => {
    S.dirty = true;  // at once, not with the preview: leaving right after typing must still ask first
    state.textContent = "Not saved yet";
    drawSoon();
  });
  saveOnCtrlS(editor, save);
  container.onclick = async (e) => {
    const button = e.target.closest("[data-de]");
    if (!button) return;
    const what = button.dataset.de;
    if (what === "save") save();
    if (what === "exp" && (!S.dirty || (await save()))) {  // download what you see
      openUrl(`/api/leads/${o.leadId}/export/${o.stem}.${button.dataset.fmt}`);
    }
    if (what === "revise") {
      await reviseWithAI(button, `/api/leads/${o.leadId}/revise`, o.doc, $("[data-revise]", container).value.trim(), editor, () => {
        state.textContent = "Revised: read it over, then Save";
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
//      version, for Revert), tools (more toolbar buttons), coverage (keyword tags), reviseUrl and fileHref (saved resumes) }
// It adds o.refresh() (redraw the preview), o.saveNow(), o.text() (what's in the editor) and o.setPages(n) (a new page
// limit: the preview gets taller or shorter, and the text stays as it is), and keeps o in S.editor for the layout menu
// and Re-check.
function mountEditor(container, o) {
  container.innerHTML = `<div class="toolbar">
      <button class="button primary" type="button" data-ed="save">Save</button>
      ${(o.files || []).map((f) => `<button class="button outline small" type="button" data-ed="file" data-file="${f}">${icon("download")}${f.split(".").pop().toUpperCase()}</button>`).join("")}
      ${o.original ? `<button class="button text" type="button" data-ed="revert">${icon("undo")}Back to the AI's version</button>` : ""}${o.tools || ""}
      <span class="muted-note" data-state></span><span class="spacer"></span><span class="tag" data-fit hidden></span></div>
    <div class="inline-form revise"><input type="text" data-revise placeholder="Say how to change it, like: lead with my newest job, cut the oldest one to one line" aria-label="How to change it">
      <button class="button light" type="button" data-ed="revise">${icon("sparkle")}Revise with AI</button></div>
    ${o.coverage ? keywordTags(o.coverage, "Not in this resume") : ""}
    <div class="editor"><textarea class="editor-text" spellcheck="true" aria-label="${o.doc === "cover" ? "Cover letter" : "Resume"} text">${esc(o.text)}</textarea>
      <div class="preview"><div class="preview-page"><iframe sandbox="allow-same-origin" title="Preview"></iframe></div></div></div>`;
  const editor = $(".editor-text", container), frame = $("iframe", container), state = $("[data-state]", container);
  const wrap = $(".preview", container), page = $(".preview-page", container), fitTag = $("[data-fit]", container);
  let pages = Math.max(1, +o.maxPages || 1);
  // Shrink the full-size page to the width of the preview column.
  const scale = () => {
    const s = Math.min(1, (wrap.clientWidth - 28) / PAGE_W);
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
      fitTag.textContent = "The preview didn't update";
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
    state.textContent = "Not saved yet";
    later();
  });
  saveOnCtrlS(editor, save);
  container.onclick = async (e) => {
    const button = e.target.closest("[data-ed]");
    if (!button) return;
    const what = button.dataset.ed;
    if (what === "save") save();
    if (what === "file" && (!S.dirty || (await save()))) {  // download what you see
      openUrl(o.fileHref ? o.fileHref(button.dataset.file) : `/api/leads/${o.leadId}/export/${button.dataset.file}`);
    }
    if (what === "revert" && confirm("Replace what's in the editor with the AI's original version?")) {
      editor.value = o.original;
      S.dirty = true;
      state.textContent = "Not saved yet";
      refresh();
    }
    if (what === "revise") {
      const url = o.reviseUrl || `/api/leads/${o.leadId}/revise`;
      await reviseWithAI(button, url, o.doc, $("[data-revise]", container).value.trim(), editor, () => {
        state.textContent = "Revised: read it over, then Save";
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
// PDF, so the preview matches the download. The tag in the toolbar then says "Fits one page at 94%" or "Longer than one
// page: trim it".
function showFit(frame, doc, pages, tag) {
  try {
    const d = frame.contentDocument, page = d.querySelector(".page");
    d.documentElement.style.overflow = "hidden";
    // The tallest the preview may be: PAGE_H per page plus a few pixels of slack. When the page has
    // box-decoration-break: clone (render.py sets it), every printed page repeats the top and bottom margins, but the
    // preview is one tall sheet that has them once. So a two-page resume loses one set of margins at the page break.
    const limit = () => {
      if (!page) return 1060 * pages;
      const css = getComputedStyle(page);  // this window's: the sandboxed preview runs no script of its own
      const repeats = (css.boxDecorationBreak || css.webkitBoxDecorationBreak) === "clone";
      const margins = parseFloat(css.paddingTop) + parseFloat(css.paddingBottom);
      return 1060 * pages - (repeats ? (pages - 1) * margins : 0);
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
        if (d.documentElement.scrollHeight <= limit()) break;
      }
    }
    const over = d.documentElement.scrollHeight > limit();
    const pageLimit = pages === 1 ? "one page" : `${pages} pages`;
    tag.hidden = !(over || fit < 1);
    tag.className = `tag ${over ? "bad" : "blue"}`;
    tag.textContent = over ? `Longer than ${pageLimit}: trim it` : `Fits ${pageLimit} at ${Math.round(fit * 100)}%`;
  } catch (_) {}  // the preview went away before it loaded
}

// ---------------------------------------------------------------- the resume's strategy and check
// Names for the resume strategies (archetypes) the AI picks. A strategy not listed here shows its key, made readable.
// The kinds of resume the AI writes (resume_strategy.archetype, from the package prompt in ai/prompts.py). A key that isn't
// here, such as one from a lead tailored by an older version, shows as its words with the first letter capitalized.
const ARCHETYPE_LABEL = { large_employer: "Large employer", small_business: "Small business or startup", public_sector: "Public sector",
  federal_usajobs: "Federal (USAJobs)", nonprofit: "Nonprofit", healthcare: "Healthcare", education: "Education",
  skilled_trades: "Skilled trades", service_retail: "Service and retail", creative_agency: "Creative or agency", technical: "Technical",
  research_lab: "Research lab", career_changer: "Career changer", experienced_professional: "Experienced professional", general: "General" };
const archetypeLabel = (key) => ARCHETYPE_LABEL[key] || humanize(key);

// The strategy block on the Resume tab: what kind of resume the AI wrote, the layout menu, the page limit, why it chose
// what it did, and what the recruiter review changed.
function resumeStrategyBlock(pkg) {
  const st = pkg.resume_strategy || {}, style = pkg.resume_style || { theme: "classic", max_pages: 1 }, review = pkg.resume_review || {};
  const detail = (label, text) => `<p class="detail-line"><b>${label}</b> ${text}</p>`;
  const critic = review.changes?.length  // the scores come from the AI's answer, so they're escaped like its text
    ? `<details class="disclosure"><summary>Recruiter review: ${plural(review.changes.length, "change")} (score ${esc(review.before_score)}
        to ${esc(review.after_score ?? review.before_score)})</summary>${bulletList(review.changes)}</details>`
    : "";
  return block("Strategy",
    `${st.archetype ? `<p><span class="tag purple">${esc(archetypeLabel(st.archetype))}</span></p>` : ""}
    ${st.rationale ? `<p>${esc(st.rationale)}</p>` : `<p class="muted-note">Tailor it again to get a resume written to a strategy.</p>`}
    ${st.section_order?.length ? detail("Order:", st.section_order.map(esc).join(", then ")) : ""}
    ${st.projects?.length ? detail("Projects:", st.projects.map(esc).join(", ")) : ""}
    ${st.summary ? detail("Summary:", esc(st.summary)) : ""}
    ${st.skills_grouping ? detail("Skills:", esc(st.skills_grouping)) : ""}
    ${critic}`,
    `<label class="control"><span>Layout</span><select data-resume-theme>${selectOptions(RESUME_THEMES.map((t) => [t, humanize(t)]), style.theme)}</select></label>
      <span class="tag">${style.max_pages === 2 ? "Two pages at most" : "One page"}</span>`);
}

// The resume check block: the score, pages, keyword coverage, and each issue the check found (or a clean bill).
function resumeCheckBlock(check) {
  if (!check) {
    return block("Resume check", `<p class="muted-note">Not checked yet.</p>`,
      `<button class="button outline small" type="button" data-act="resume-recheck">Check it</button>`, "resume-check");
  }
  const level = check.score >= 85 ? "green" : check.score >= 65 ? "warn" : "bad";
  const issue = (i) => `<li class="${i.level === "error" ? "bad" : ""}">${icon(i.level === "error" ? "close" : "warning")}${esc(i.text)}</li>`;
  const issues = check.issues.length
    ? `<ul class="issue-list">${check.issues.map(issue).join("")}</ul>`
    : `<p class="good-note">${icon("check")}Easy for hiring software to read, fits its page limit, and every skill is backed by your profile.</p>`;
  const tags = `<p class="tags"><span class="tag ${level}">${check.score}/100</span><span class="tag">${plural(check.pages ?? 0, "page")}</span>`
    + `<span class="tag ${check.coverage >= 0.75 ? "green" : "warn"}">Keywords ${Math.round((check.coverage || 0) * 100)}%</span></p>`;
  return block("Resume check", tags + issues,
    `<button class="button outline small" type="button" data-act="resume-recheck">Check again</button>`, "resume-check");
}

// Runs the resume check again (POST /api/leads/{id}/resume-check) and swaps in the new block. The block dims meanwhile.
async function recheckResume(id) {
  const shown = S.leadView && lv(".resume-check");
  if (shown) shown.style.opacity = 0.5;
  try {
    const check = await api(`/api/leads/${id}/resume-check`, { method: "POST" });
    if (S.lead?.id === id && S.lead.package) S.lead.package.resume_check = check;
    const current = S.leadView && lv(".resume-check");
    if (current) current.outerHTML = resumeCheckBlock(check);
  } catch (e) {
    if (shown) shown.style.opacity = "";
    toast("The check didn't run", e.message, "error");
  }
}

// ---------------------------------------------------------------- saving
// After a lead changed (its status, mostly): redraw it and every list that shows it, and the counts.
function leadChanged(summary) {
  if (S.route[0] === "leads" && summary) upsertLead(summary);
  if (S.route[0] === "tracker") refreshTracker();
  if (S.route[0] === "home") loadTopLeads();
  refreshStats();
  refreshLeadDetails();
}

// Sets the application status (PATCH). Marking it sent also sets a follow-up in 7 days on the server.
async function setStatus(id, status) {
  leadChanged(await api(`/api/leads/${id}`, { method: "PATCH", body: { app_status: status } }));
  toast("Status changed", statusLabel(status));
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
    toast("Logged", "Marked as sent.");
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
    renderNextStep();
  } catch (_) {}
  await refreshLeadDetails();
}

// ---------------------------------------------------------------- actions
onAction("lead-tab", (el) => {  // a tab (or the "Open emails" button in the follow-up banner)
  if (S.dirty && !confirm("Discard your unsaved edits?")) return;
  S.dirty = false;
  if (S.leadView.hashBase) location.hash = `${S.leadView.hashBase}/${el.dataset.tab}`;  // on Leads the address follows
  else showLeadTab(el.dataset.tab);
});
onAction("apply", (el) => {
  openUrl(el.dataset.url);
  const lead = S.lead;
  if (lead && !["applied", "interviewing", "accepted"].includes(lead.app_status)) {
    toast("Did you send it?", "Mark it as sent to track it. A follow-up reminder is set for a week later.", "", null,
      { label: "Mark as sent", run: () => setStatus(lead.id, "applied") });
  }
});
onAction("detail-track", () => setStatus(S.lead.id, "ready"));
onAction("detail-delete", async () => {
  const { id, title, app_status: before } = S.lead;
  const summary = await api(`/api/leads/${id}`, { method: "PATCH", body: { app_status: "trashed" } });
  toast("Deleted", title, "", null, { label: "Undo", run: async () => leadChanged(await api(`/api/leads/${id}`, { method: "PATCH", body: { app_status: before } })) });
  if (S.leadView.hashBase) location.hash = "#/leads";  // close its card
  else closeDialog(S.leadView.box.closest("dialog"));
  leadChanged(summary);
});
onAction("regen", async () => {
  if (S.lead.resume_md && !confirm("Tailor the whole application again? Your edits to the resume and cover letter will be replaced.")) return;
  await api(`/api/leads/${S.lead.id}/package`, { method: "POST" });
  toast("Tailoring it", "It updates here when it's ready.");
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
  const name = prompt("Name this resume:", `${S.lead.company}: ${S.lead.title}`.slice(0, 90));
  if (name === null) return;
  const item = await api("/api/library", { method: "POST", body: { lead_id: S.lead.id, name, md: S.editor?.text() || S.lead.resume_md, style: S.lead.package?.resume_style } });
  toast("Saved to your resumes", item.name);
});
onAction("lead-lib-use", () => leadPickSavedDialog(S.lead));
// Emails tab
onAction("mail", (el) => mailAction(el.dataset.how, +el.dataset.i));
onAction("save-emails", async () => {
  await saveEmails();
  toast("Saved", "Your emails are updated.");
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
    toast("Email revised", "Read it over, then Save edits.");
  } catch (err) {
    toast("The revision didn't work", err.message, "error");
  }
  el.disabled = false;
  el.innerHTML = `${icon("sparkle")}Revise`;
});
onAction("copy-note", () => copy(lv("[data-note]").value, "LinkedIn note copied"));
// Contacts tab
onAction("add-contact", async () => {
  const contact = {};
  $$("[data-nc]", S.leadView.box).forEach((input) => (contact[input.dataset.nc] = input.value));
  if (!contact.name) return;
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
  toast("Saved", "Your notes are updated.");
});
onAction("save-follow-up", async () => {
  await saveActivityField("[data-follow-up]", "follow_up_at", null);
  toast("Saved", "Follow-up date set.");
  refreshStats();
});
onAction("log-event", async (el) => {  // a preset, or Log it with your own text
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
    toast("Questions added", `${plural(r.added, "question")} for this application.`);
  } catch (err) {
    toast("Couldn't find questions", err.message, "error");
  }
  await refreshLeadQuestions();
  if (el.isConnected) {  // not drawn again (the lead didn't load, or you're editing this tab): usable again
    el.disabled = false;
    el.innerHTML = `${icon("sparkle")}Ask me about gaps`;
  }
});
onAction("lead-answer", async (el) => {
  const input = $("[data-lead-answer]", el.closest(".question-row"));
  if (!input.value.trim()) return;
  await api("/api/questions/answer", { method: "POST", body: { question: input.dataset.leadAnswer, answer: input.value.trim() } });
  toast("Answer saved", "It's in your profile now too.");
  await refreshLeadQuestions();
});
onAction("lead-dismiss", async (el) => {
  await api("/api/questions/dismiss", { method: "POST", body: { question: el.dataset.q } });
  await refreshLeadQuestions();
});
onAction("lead-apply-answers", async (el) => {
  el.disabled = true;  // before the request, not after it: a second click mustn't start a second rework
  el.innerHTML = `${spinner()} Adding your answers and reworking the resume`;
  try {
    await api(`/api/leads/${S.lead.id}/apply-answers`, { method: "POST" });
  } catch (err) {
    el.disabled = false;
    el.innerHTML = `${icon("sparkle")}Update this resume with my answers`;
    throw err;
  }
  toast("Updating the resume", "Adding your answers to your profile, then rewriting this resume with them. A minute or two.");
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
    toast("Industry changed", el.value || "Not set");
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
  } else if (el.matches("[data-resume-theme]")) {  // the Layout menu on the strategy block
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
    toast("Layout changed", `${humanize(el.value)}. The PDF and Word downloads use it too.`);
    recheckResume(S.lead.id);
  } else {
    return false;
  }
  return true;
});
