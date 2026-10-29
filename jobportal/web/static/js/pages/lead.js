/* lead.js: one lead's page (#/lead/12, or #/lead/12/emails to open a tab). The header has the score, the chips, where
   the lead was found and the main actions (dream, industry, status, apply, downloads, regenerate). Under it: banners for
   the package state, the questions for this application, and the tabs: fit and triage, the tailored resume and cover
   letter editors, outreach emails, contacts, company intel, interview prep, the application kit, activity and the posting.

   APIs: GET /api/leads/{id} (the lead with its package), PATCH /api/leads/{id} (every edit), POST /api/preview (the
   editor's live preview), POST /api/leads/{id}/revise, /package, /resume-check, /events, /contacts/{i},
   /questions/generate and /apply-answers, plus the exports under /api/leads/{id}/export/.
   S.lead is the lead on screen and S.dirty marks unsaved edits. A "lead" event redraws the page unless edits are open. */
"use strict";

// ---------------------------------------------------------------- the page
// Draws the lead page and its open tab (S.leadTab). fromEvent = a live update: skipped when you have unsaved edits or
// nothing changed.
async function renderLead(id, fromEvent) {
  if (fromEvent && S.dirty) return;
  let l;
  try {
    l = await api(`/api/leads/${id}`);
  } catch (e) {
    main.innerHTML = `<div class="page"><div class="empty"><b>Lead not found</b></div></div>`;
    return;
  }
  if (fromEvent && S.lead && S.lead.stage === l.stage && S.lead.updated_at === l.updated_at) return;
  S.lead = l;
  S.dirty = false;
  const packaged = !!l.resume_md;
  const apply = safeUrl(l.apply_url) || safeUrl(l.url);
  const foundAt = foundList(l).map((f) => `<a class="chip blue" href="${esc(f.url)}" target="_blank" rel="noopener" title="${esc(f.label)}">`
    + `<i class=i-ext></i> ${esc(foundShort(f))}</a>`).join("");
  // The industry menu offers the Settings list, plus the lead's own industry when it isn't on that list.
  const industries = S.industries || [];
  const industryChoices = l.industry && !industries.includes(l.industry) ? [...industries, l.industry] : industries;
  const statusChoices = S.meta.statuses.map((status) => [status, STATUS_LABEL[status]]);

  main.innerHTML = `<div class="page">
    <div class="row" style="margin-bottom:12px"><a href="#/leads" class="mono small"><i class=i-back></i> All leads</a></div>
    <div class="lh">${ring(l.score, true)}
      <div><h1>${esc(l.title)}</h1><div class="co"><b>${esc(l.company)}</b>, ${esc(l.location || "location n/a")}</div>
        <div class="row" style="margin-top:8px;gap:6px">${leadChips(l)}</div>
        ${foundAt ? `<div class="row small" style="margin-top:8px;gap:6px"><span class="muted mono">FOUND AT</span>${foundAt}</div>` : ""}</div>
      <div class="acts">
        <button class="btn ${l.dream ? "toggled" : "ghost"}" data-act="toggle-dream" title="Mark as a dream job">${l.dream ? "<i class=i-star></i>" : "<i class=i-star-o></i>"} Dream</button>
        <select id="industry" title="Industry (edit if it's wrong)">${selectOptions(industryChoices, l.industry)}</select>
        <select id="appstatus" title="Application status">${selectOptions(statusChoices, l.app_status)}</select>
        ${apply ? `<button class="btn primary" data-act="apply" data-url="${esc(apply)}">Apply ${I.ext}</button>` : ""}
        ${packaged ? `<a class="btn" href="/api/leads/${l.id}/export/package.zip" title="Resume, cover letter, emails (.eml), answers, prep, intel, contacts">${I.dl} All files</a>` : ""}
        <button class="btn" data-act="regen" title="Re-run research + tailoring">${packaged ? "<i class=i-refresh></i> Regenerate" : "Build package"}</button>
      </div></div>
    ${leadBanners(l, packaged)}
    ${leadQuestionsPanel(l)}
    <div class="tabs" id="dtabs">${LEAD_TABS.map(([key, label]) => `<a class="${S.leadTab === key ? "on" : ""}" data-act="ltabgo" data-tab="${key}">${label}</a>`).join("")}</div>
    <div id="dbody"></div></div>`;
  $("#appstatus").onchange = (e) => setStatus(l.id, e.target.value);
  $("#industry").onchange = async (e) => {
    await api(`/api/leads/${l.id}`, { method: "PATCH", body: { industry: e.target.value } });
    toast("Industry updated", e.target.value);
  };
  renderLeadTab();
}

// The banners under the header: the package is building, failed or missing, the posting looks closed, a follow-up is due.
function leadBanners(l, packaged) {
  let html = "";
  if (l.stage === "packaging") {
    html = `<div class="banner accent"><span class="spin"></span><div><b>JobPortal is building this package:</b> reading the posting,
      researching the team, finding contacts, tailoring your resume and cover letter. Usually 2 to 6 minutes.</div></div>`;
  } else if (l.stage === "error") {
    html = `<div class="banner bad"><div><b>Package failed:</b> ${esc(l.stage_error)}</div><span class="spacer"></span>`
      + `<button class="btn sm" data-act="regen">Retry</button></div>`;
  } else if (!packaged) {
    const why = l.stage === "filtered" ? "Triage scored this below your threshold." : "Queued for packaging.";
    html = `<div class="banner"><div>${why} Want the full package now?</div><span class="spacer"></span>`
      + `<button class="btn primary sm" data-act="regen">Build package</button></div>`;
  } else if (l.stage === "closed") {
    html = `<div class="banner bad"><div><b>JobPortal couldn't find this posting open anymore.</b> Double-check the link before spending
      time on it.</div></div>`;
  }
  const waitingOnThem = ["applied", "assessment", "interviewing"].includes(l.app_status);
  if (packaged && waitingOnThem && l.follow_up_at && daysUntil(l.follow_up_at) <= 0) {
    html += `<div class="banner accent"><div><b>Follow-up due.</b> A ready-to-send follow-up email is in the Emails tab.</div>`
      + `<span class="spacer"></span><button class="btn sm" data-act="ltabgo" data-tab="emails">Open emails</button></div>`;
  }
  return html;
}

// Questions for this application, shown once the lead has a resume: answer or dismiss each, then rework the resume with
// your answers. With no questions yet, a button asks the AI to find some.
function leadQuestionsPanel(l) {
  if (!l.resume_md) return "";
  const questions = l.questions || [];
  if (!questions.length) {
    return `<div class="banner"><div class="small">No open questions for this application.</div><span class="spacer"></span>
    <button class="btn sm" data-act="lead-gapq" title="Ask the AI what you could tell it that would make this resume stronger"><i class=i-question></i> Find gaps to ask me about</button></div>`;
  }
  const open = questions.filter((q) => q.status === "open");
  const answered = questions.filter((q) => q.status === "answered");
  const openItem = (q) => `<div class="lq-item"><div><b>${esc(q.question)}</b></div><div class="small muted">${esc(q.why)}</div>
      <div class="row" style="margin-top:6px"><input type="text" data-lqa="${esc(q.question)}" placeholder="Your answer" style="flex:1">
      <button class="btn sm" data-act="lead-answer">Save answer</button><button class="btn sm ghost" data-act="lead-dismiss" data-q="${esc(q.question)}" title="Not relevant"><i class=i-x></i></button></div></div>`;
  const answeredItem = (q) => `<div class="lq-item done"><div class="small"><b>${esc(q.question)}</b></div>`
    + `<div class="small" style="color:var(--good)"><i class=i-check></i> ${esc(q.answer || "")}</div></div>`;
  const applyButton = answered.length
    ? `<button class="btn primary sm ai" data-act="lead-apply" title="Add your answers to your profile, then rework this resume with them"><i class=i-ai></i> Update this resume with my answers</button>`
    : "";
  return `<div class="card lq" style="margin-bottom:14px"><div class="row" style="margin-bottom:6px"><h3 style="margin:0"><i class=i-question></i> Questions that could strengthen this resume</h3>
      <span class="muted small">Answers are saved to your profile, so every future application benefits.</span><span class="spacer"></span>
      ${applyButton}</div>
    ${open.map(openItem).join("")}
    ${answered.map(answeredItem).join("")}</div>`;
}

// ---------------------------------------------------------------- tabs
// The tabs in order: [key, label, function that fills the tab]. The key also works in the address: #/lead/12/emails.
const LEAD_TABS = [
  ["overview", "Overview", renderOverviewTab],
  ["resume", "Resume", (box, l, pkg) => renderDocumentTab(box, l, pkg, "resume")],
  ["cover", "Cover letter", (box, l, pkg) => renderDocumentTab(box, l, pkg, "cover")],
  ["emails", "Emails", renderEmailsTab],
  ["contacts", "Contacts", renderContactsTab],
  ["intel", "Company intel", (box, l, pkg) => renderNotesTab(box, l, pkg, "intel")],
  ["prep", "Interview prep", (box, l, pkg) => renderNotesTab(box, l, pkg, "prep")],
  ["kit", "Application kit", renderKitTab],
  ["activity", "Activity", renderActivityTab],
  ["posting", "Posting", renderPostingTab],
];

// Fills #dbody with the open tab. It swaps in a fresh, empty #dbody first, which drops the listeners the last tab added.
function renderLeadTab() {
  const old = $("#dbody");
  const box = old.cloneNode(false);
  old.replaceWith(box);
  $$("#dtabs a").forEach((a) => a.classList.toggle("on", a.dataset.tab === S.leadTab));
  const tab = LEAD_TABS.find(([key]) => key === S.leadTab);
  if (tab) tab[2](box, S.lead, S.lead.package || {});
}

// The empty state of a tab whose part of the package doesn't exist yet.
const noneYet = (what) => `<div class="empty"><b>No ${what} yet</b>Build the package to generate it.</div>`;

// Keyword chips: green for the job's keywords the resume has, plain (with a tooltip) for the ones it lacks.
function keywordChips(coverage, missingTip) {
  const hits = (coverage.hit || []).map((k) => `<span class="chip good">${esc(k)}</span>`).join("");
  const misses = (coverage.miss || []).map((k) => `<span class="chip" title="${missingTip}">${esc(k)}</span>`).join("");
  return `<div class="cov">${hits}${misses}</div>`;
}

// Overview: the fit (summary, strengths, gaps, eligibility), the action plan, the role in brief, the facts at a glance,
// red flags and the ATS keywords in your resume.
function renderOverviewTab(box, l, pkg) {
  const fit = pkg.fit || {}, triage = l.triage || {}, coverage = pkg.coverage || {};
  const plan = pkg.action_plan || [], done = pkg.plan_done || [];
  const fitCard = fit.summary || triage.summary ? `<div class="card"><h3>Fit</h3><p style="margin:0 0 10px">${esc(fit.summary || triage.summary)}</p>
        ${fit.strengths?.length ? `<b class="small mono">STRENGTHS</b>${bulletList(fit.strengths, "good")}` : ""}
        ${fit.gaps?.length ? `<div style="margin-top:10px"><b class="small mono">GAPS & HOW TO HANDLE THEM</b>${bulletList(fit.gaps, "warn")}</div>` : ""}
        ${fit.eligibility_notes ? `<p class="small" style="margin:10px 0 0"><b class="mono">ELIGIBILITY:</b> ${esc(fit.eligibility_notes)}</p>` : ""}</div>` : "";
  const planItem = (step, i) => `<label><input type="checkbox" data-act="plan" data-i="${i}" ${done.includes(i) ? "checked" : ""}>`
    + `<span class="${done.includes(i) ? "done" : ""}">${esc(step)}</span></label>`;
  const planCard = plan.length ? `<div class="card"><h3>Action plan</h3><div class="checklist">${plan.map(planItem).join("")}</div></div>` : "";
  const roleCard = pkg.job_summary ? `<div class="card"><h3>The role in brief</h3><div class="md">${md(pkg.job_summary)}</div></div>` : "";
  const posting = safeUrl(l.url) ? `<a href="${esc(l.url)}" target="_blank" rel="noopener">${esc(l.url.slice(0, 70))}</a>` : "none";
  // "82, eligible: reason; reason". The eligibility part is left out when triage didn't give one.
  const triageText = [triage.score ?? "-", esc(triage.eligibility || "")].filter((part) => part !== "").join(", ")
    + (triage.reasons?.length ? `: ${esc(triage.reasons.join("; "))}` : "");
  const flagsCard = triage.red_flags?.length ? `<div class="card"><h3>Red flags</h3>${bulletList(triage.red_flags, "warn")}</div>` : "";
  const coverageCard = coverage.hit || coverage.miss
    ? `<div class="card"><h3>ATS keywords in your resume: ${Math.round((l.ats_coverage || 0) * 100)}%</h3>${keywordChips(coverage, "Not in the resume. Add it only if it's true.")}</div>`
    : "";
  box.innerHTML = `<div class="cols"><div class="stack">
      ${fitCard}
      ${planCard}
      ${roleCard}
    </div><div class="stack">
      <div class="card"><h3>At a glance</h3><dl class="kv">
        <dt>Status</dt><dd>${esc(STATUS_LABEL[l.app_status])}${l.applied_at ? `, applied ${esc(l.applied_at)}` : ""}</dd>
        <dt>Deadline</dt><dd>${esc(l.deadline || "unknown")}</dd>
        <dt>Posted</dt><dd>${esc(l.posted_at || "unknown")}</dd>
        <dt>Found via</dt><dd>${esc(l.source_detail || l.source)}</dd>
        <dt>Posting</dt><dd>${posting}</dd>
        <dt>Triage</dt><dd>${triageText}</dd>
        <dt>AI usage</dt><dd>${(+l.tokens || 0).toLocaleString()} tokens</dd></dl></div>
      ${flagsCard}
      ${coverageCard}
    </div></div>`;
}

// Resume and Cover letter: the editor with its live preview, downloads and "Revise with AI". The resume tab adds the
// strategy and resume check cards and the collection buttons.
function renderDocumentTab(box, l, pkg, doc) {
  const isResume = doc === "resume";
  const text = isResume ? l.resume_md : l.cover_md;
  if (!text) {
    box.innerHTML = isResume
      ? `<div class="empty"><b>No tailored resume yet</b>Build the package to generate one, or start from a resume in your collection.
        <div style="margin-top:12px"><button class="btn" data-act="lead-lib-use">Use a saved resume</button></div></div>`
      : noneYet("cover letter");
    return;
  }
  let host = box;
  if (isResume) {
    box.innerHTML = `<div class="cols" style="margin-bottom:14px">${resumeStrategyCard(pkg)}${resumeCheckCard(pkg.resume_check)}</div><div id="ed-host"></div>`;
    host = $("#ed-host", box);
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
      ? `<button class="btn" data-act="lead-lib-save" title="Keep a copy of this resume in your collection"><i class=i-star></i> Save to collection</button>`
        + `<button class="btn" data-act="lead-lib-use">Use a saved resume</button>`
      : "",
    coverage: isResume ? pkg.coverage : null,
  });
}

// Emails: each outreach email with its recipient, subject and body to edit, the ways to send it, and "Revise" by
// instruction. Then the LinkedIn connection note, and buttons to export or save them all.
function renderEmailsTab(box, l, pkg) {
  const emails = pkg.emails || [];
  if (!emails.length && !pkg.linkedin_note) {
    box.innerHTML = noneYet("emails");
    return;
  }
  // The "To" box suggests the contacts that have an email address.
  const suggestions = (pkg.contacts || []).filter((c) => c.email)
    .map((c) => `<option value="${esc(c.email)}">${esc(c.name)}, ${esc(c.title)}</option>`).join("");
  const emailCard = (e, i) => `<div class="card email" data-i="${i}">
        <div class="hd"><span class="chip accent">${esc(e.kind.replace(/_/g, " "))}</span><span class="muted small">${esc(e.to)}</span><span class="spacer"></span>
          <button class="btn sm" data-act="mail" data-how="gmail" data-i="${i}">Open in Gmail ${I.ext}</button>
          <button class="btn sm" data-act="mail" data-how="mailto" data-i="${i}">Mail app</button>
          <button class="btn sm" data-act="mail" data-how="copy" data-i="${i}">Copy</button>
          <button class="btn sm" data-act="mail" data-how="eml" data-i="${i}" title="Download as an unsent draft (.eml) for Thunderbird / Outlook / Apple Mail">.eml</button>
          <button class="btn sm" data-act="mail" data-how="sent" data-i="${i}">Mark sent</button></div>
        <div class="grid2"><label class="f"><span>To</span><input type="email" list="cemails" data-ef="to_addr" value="${esc(pickTo(e))}" placeholder="pick a contact or type an address"></label>
          <label class="f"><span>Subject</span><input type="text" data-ef="subject" value="${esc(e.subject)}"></label></div>
        <textarea data-ef="body">${esc(e.body)}</textarea>
        <div class="revise" style="margin:0"><input type="text" data-erev="${i}" placeholder="Say how to change this email"><button class="btn sm" data-act="revise-email" data-i="${i}">Revise</button></div></div>`;
  const note = pkg.linkedin_note ? `<div class="card"><h3>LinkedIn connection note <span id="lncount" class="muted">${pkg.linkedin_note.length}/300</span></h3>
          <textarea id="lnote" rows="3">${esc(pkg.linkedin_note)}</textarea>
          <div class="row" style="margin-top:8px"><button class="btn sm" data-act="copy-lnote">Copy</button></div></div>` : "";
  box.innerHTML = `<datalist id="cemails">${suggestions}</datalist>
      <div class="stack">${emails.map(emailCard).join("")}
        ${note}
        <div class="row" style="justify-content:flex-end"><span class="muted small">Export all emails:</span>${exportBtns(l.id, "emails", ["md", "docx", "pdf"])}
          <button class="btn primary" data-act="save-emails">Save edits</button></div></div>`;
  box.addEventListener("input", (e) => {
    S.dirty = true;
    if (e.target.id === "lnote") $("#lncount").textContent = `${e.target.value.length}/300`;  // LinkedIn allows 300 characters
  });
}

// The recipient to pre-fill: the address the AI wrote for this email. A guessed pattern ("first.last@...") or a
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
  const input = (i, key, value, placeholder) => `<input type="text" data-cf="${key}" data-i="${i}" value="${esc(value || "")}" placeholder="${placeholder}">`;
  const gap = `<div style="height:4px"></div>`;
  const confidence = (c) => (c.email_confidence === "found" ? "good" : c.email_confidence === "pattern" ? "warn" : "");
  const links = (c) => (safeUrl(c.linkedin) ? `<a href="${esc(c.linkedin)}" target="_blank" rel="noopener">open LinkedIn</a>` : "")
    + (safeUrl(c.source_url) ? `<a href="${esc(c.source_url)}" target="_blank" rel="noopener">source</a>` : "");
  const row = (c, i) => `<tr><td style="min-width:200px">${input(i, "name", c.name, "Name")}${gap}${input(i, "title", c.title, "Title")}${gap}${input(i, "org", c.org, "Organization")}</td>
        <td style="min-width:220px">${input(i, "email", c.email, "email@example.com")}<div class="row" style="margin-top:5px;gap:5px"><span class="chip ${confidence(c)}">${esc(c.email_confidence || "unknown")}</span>
          ${c.email ? `<button class="btn sm ghost" data-act="copytext" data-text="${esc(c.email)}">copy</button>` : ""}</div></td>
        <td style="min-width:200px">${input(i, "linkedin", c.linkedin, "LinkedIn URL")}${gap}${input(i, "notes", c.notes, "Notes")}
          <div class="small row" style="margin-top:4px;gap:8px">${links(c)}</div></td>
        <td class="small" style="max-width:300px"><textarea data-cf="why" data-i="${i}" rows="3">${esc(c.why || "")}</textarea></td>
        <td>${contactStatusSelect(l.id, i, c.status)}</td>
        <td><button class="btn sm ghost danger" data-act="rm-contact" data-i="${i}" title="Remove"><i class=i-x></i></button></td></tr>`;
  const table = contacts.length ? `<table class="t"><thead><tr><th>Name / title / org</th><th>Email</th><th>LinkedIn and notes</th><th>Why them</th><th>Status</th><th></th></tr></thead><tbody>
      ${contacts.map(row).join("")}
      </tbody></table>` : `<div class="muted">No contacts found yet.</div>`;
  box.innerHTML = `<div class="card"><div class="row" style="margin-bottom:6px"><h3 style="margin:0">People to reach (${contacts.length})</h3><span class="spacer"></span>
      ${exportBtns(l.id, "contacts", ["csv"])}</div>
      <p class="muted small" style="margin-top:0">Found by the AI on the public web. Every field is editable and saves when you leave it. <b>found</b> means the
        email was seen publicly; <b>pattern</b> means it was inferred from the company's email format (verify it).</p>
      ${table}
      <div class="hr"></div><div class="grid3" id="newc">
        <input type="text" placeholder="Name" data-nc="name"><input type="text" placeholder="Title" data-nc="title"><input type="email" placeholder="Email" data-nc="email">
        <input type="url" placeholder="LinkedIn URL" data-nc="linkedin"><input type="text" placeholder="Why / notes" data-nc="why"><button class="btn" data-act="add-contact">+ Add contact</button></div></div>`;
  box.addEventListener("change", async (e) => {  // an edited contact field: save that one field
    const el = e.target;
    if (!el.dataset.cf) return;
    await api(`/api/leads/${l.id}/contacts/${el.dataset.i}`, { method: "POST", body: { [el.dataset.cf]: el.value } });
    pkg.contacts[+el.dataset.i][el.dataset.cf] = el.value;
  });
}

// Company intel and Interview prep: Markdown documents with a preview, downloads and "Revise with AI".
const NOTES_DOCS = {
  intel: { key: "company_brief_md", name: "company intel", stem: "company_intel", doc: "company brief" },
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
// standard answers ready to copy. Reads GET /api/profile once for the standard answers.
async function renderKitTab(box, l, pkg) {
  if (!S.profileCache) S.profileCache = await api("/api/profile");
  const qa = S.profileCache.qa || [];
  const copyRow = (q, a) => `<div class="copyrow"><div class="q">${esc(q)}</div><div class="a">${esc(a)}</div>`
    + `<button class="btn sm" data-act="copytext" data-text="${esc(a)}">copy</button></div>`;
  const apply = safeUrl(l.apply_url) || safeUrl(l.url);
  const answers = pkg.application_answers || [];
  const answerEditor = (x, i) => `<div class="stack" style="gap:6px;padding-bottom:12px;border-bottom:1px solid var(--line)">
        <div class="row"><input type="text" data-aq="${i}" value="${esc(x.question)}" style="flex:1;font-weight:600">
          <button class="btn sm" data-act="copy-answer" data-i="${i}">copy</button><button class="btn sm ghost danger" data-act="rm-answer" data-i="${i}" title="Remove"><i class=i-x></i></button></div>
        <textarea data-aa="${i}" rows="5" style="font-size:13px">${esc(x.answer)}</textarea></div>`;
  const standard = qa.filter((x) => !x.eeo), selfId = qa.filter((x) => x.eeo);  // eeo = voluntary self-identification
  const selfIdCard = selfId.length ? `<div class="card"><h3>Voluntary self-identification</h3><p class="muted small" style="margin-top:-4px">Only shown here for copying.
      Never sent to the AI.</p>${selfId.map((x) => copyRow(x.q, x.a)).join("")}</div>` : "";
  box.innerHTML = `<div class="cols"><div class="stack">
    <div class="card"><h3>Files</h3><div class="row">${l.resume_md ? exportBtns(l.id, "resume", ["pdf", "docx", "md"], "Resume") : ""}</div>
      <div class="row" style="margin-top:8px">${l.cover_md ? exportBtns(l.id, "cover_letter", ["pdf", "docx", "md"], "Cover") : ""}</div>
      <div class="row" style="margin-top:12px"><a class="btn" href="/api/leads/${l.id}/export/package.zip">${I.dl} Everything (.zip)</a>
      ${apply ? `<button class="btn primary" data-act="apply" data-url="${esc(apply)}">Open application ${I.ext}</button>` : ""}</div></div>
    <div class="card"><div class="row" style="margin-bottom:10px"><h3 style="margin:0">Tailored answers</h3><span class="spacer"></span>${exportBtns(l.id, "answers", ["docx", "pdf", "md"])}</div>
      <div class="stack" id="answers">${answers.map(answerEditor).join("") || `<div class="muted">Build the package to generate tailored answers.</div>`}</div>
      <div class="row" style="margin-top:12px"><button class="btn sm" data-act="add-answer">+ Add question</button><span class="spacer"></span>
        <span class="muted small" id="ans-state"></span><button class="btn primary sm" data-act="save-answers">Save answers</button></div></div>
  </div><div class="stack"><div class="card"><h3>Standard answers</h3><p class="muted small" style="margin-top:-4px">From your answers in
      <a href="#/profile/answers">Profile, Standard answers</a>. Edit them there.</p>
    ${standard.map((x) => copyRow(x.q, x.a)).join("") || `<div class="muted small">Answer the standard questions to fill these in.</div>`}</div>
    ${selfIdCard}</div></div>`;
  box.addEventListener("input", (e) => {
    if (e.target.dataset.aq == null && e.target.dataset.aa == null) return;
    S.dirty = true;
    $("#ans-state").textContent = "unsaved";
  });
}

// Reads the kit's answer fields back into S.lead.package.application_answers and returns them.
function readAnswers() {
  const pkg = S.lead.package;
  pkg.application_answers = (pkg.application_answers || []).map((x, i) => ({
    question: $(`[data-aq="${i}"]`)?.value ?? x.question,
    answer: $(`[data-aa="${i}"]`)?.value ?? x.answer,
  }));
  return pkg.application_answers;
}

// Saves the kit's answers into the lead's package.
async function saveAnswers() {
  await api(`/api/leads/${S.lead.id}`, { method: "PATCH", body: { package: { application_answers: readAnswers() } } });
  S.dirty = false;
}

// Activity: your notes, the timeline of events, the follow-up date, and buttons to log what happened.
const EVENT_PRESETS = ["Got online assessment", "Recruiter reached out", "Interview scheduled", "Referral submitted", "Offer!", "Rejected"];
function renderActivityTab(box, l) {
  const timeline = (l.events || []).map((e) => `<div class="ev"><span class="ts">${esc(localStamp(e.ts))}</span><span class="chip">${esc(e.type)}</span><span>${esc(e.text)}</span></div>`).join("")
    || `<div class="muted">No activity yet.</div>`;
  const presets = EVENT_PRESETS.map((text) => `<button class="btn sm" data-act="logev" data-text="${esc(text)}">${esc(text)}</button>`).join("");
  box.innerHTML = `<div class="cols"><div class="stack"><div class="card"><h3>Notes</h3><textarea id="notes" rows="8">${esc(l.notes || "")}</textarea>
        <div class="row" style="margin-top:8px"><button class="btn sm" data-act="save-notes">Save notes</button></div></div>
      <div class="card"><h3>Timeline</h3><div class="timeline">${timeline}</div></div></div>
      <div class="stack"><div class="card"><h3>Follow-up</h3><label class="f"><span>Follow up on</span><input type="date" id="fu" value="${esc(l.follow_up_at || "")}"></label>
        <div class="row" style="margin-top:8px"><button class="btn sm" data-act="save-fu">Save date</button></div></div>
        <div class="card"><h3>Log an event</h3><div class="row">${presets}</div>
          <div class="row" style="margin-top:10px"><input type="text" id="evtext" placeholder="Custom event" style="flex:1"><button class="btn sm" data-act="logev">Log</button></div></div></div></div>`;
}

// Posting: the job description as JobPortal captured it, with links to the posting and the apply page.
function renderPostingTab(box, l) {
  const posting = safeUrl(l.url) ? `<a class="btn sm" href="${esc(l.url)}" target="_blank" rel="noopener">Open posting ${I.ext}</a>` : "";
  const applyPage = safeUrl(l.apply_url) && l.apply_url !== l.url
    ? `<a class="btn sm" href="${esc(l.apply_url)}" target="_blank" rel="noopener">Apply page ${I.ext}</a>` : "";
  box.innerHTML = `<div class="card"><div class="row" style="margin-bottom:12px">${posting}
      ${applyPage}
      <span class="muted small">${esc(l.source_detail || "")}</span></div><pre class="jd">${esc(l.description || "No description captured.")}</pre></div>`;
}

// Download buttons: exportBtns(12, "resume", ["pdf", "docx"], "Resume") makes "Resume PDF" and "Resume DOCX".
function exportBtns(leadId, stem, formats, label = "") {
  return formats.map((fmt) => `<button class="btn sm" data-act="export" data-url="/api/leads/${leadId}/export/${stem}.${fmt}">`
    + `${I.dl} ${label ? label + " " : ""}${fmt.toUpperCase()}</button>`).join("");
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

// "Revise with AI" in both editors: sends the text and your instruction (POST .../revise) and puts the AI's version in
// the editor. Nothing is saved until you click Save.
async function reviseWithAI(button, url, doc, instruction, textarea, afterRevise) {
  if (!instruction) return;
  button.disabled = true;
  button.innerHTML = `<span class="spin"></span> Revising…`;
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
  button.innerHTML = "<i class=i-ai></i> Revise with AI";
}

// The Markdown editor for company intel and interview prep: text on the left, a rendered preview on the right.
// o: { text, leadId, stem (export file name), doc (the name the AI sees), save(text) }
function mountDocEditor(container, o) {
  container.innerHTML = `<div class="toolbar"><button class="btn primary" data-de="save">Save</button>
      ${["pdf", "docx", "md"].map((fmt) => `<button class="btn" data-de="exp" data-fmt="${fmt}">${I.dl} ${fmt.toUpperCase()}</button>`).join("")}
      <span class="muted small mono" id="destate"></span></div>
    <div class="revise"><input type="text" id="de-rev" placeholder="Say how to change it, e.g. “add 3 questions about system design, shorten the company history”">
      <button class="btn ai" data-de="revise"><i class=i-ai></i> Revise with AI</button></div>
    <div class="editor"><textarea id="de-ed" spellcheck="true">${esc(o.text)}</textarea><div class="card md" id="de-pv" style="max-height:76vh;overflow:auto"></div></div>`;
  const editor = $("#de-ed", container), preview = $("#de-pv", container), state = $("#destate", container);
  const draw = () => (preview.innerHTML = md(editor.value));
  const save = async () => {
    await o.save(editor.value);
    S.dirty = false;
    state.textContent = "saved";
  };
  editor.addEventListener("input", debounce(() => {
    S.dirty = true;
    state.textContent = "unsaved";
    draw();
  }, 150));
  saveOnCtrlS(editor, save);
  container.onclick = async (e) => {
    const button = e.target.closest("[data-de]");
    if (!button) return;
    const what = button.dataset.de;
    if (what === "save") save();
    if (what === "exp") {
      if (S.dirty) await save();  // export what you see
      openUrl(`/api/leads/${o.leadId}/export/${o.stem}.${button.dataset.fmt}`);
    }
    if (what === "revise") {
      await reviseWithAI(button, `/api/leads/${o.leadId}/revise`, o.doc, $("#de-rev", container).value.trim(), editor, () => {
        state.textContent = "revised: review it, then Save";
        draw();
      });
    }
  };
  draw();
}

// A US Letter page at 96 pixels per inch, the size the preview iframe is drawn at before it's scaled to fit.
const PAGE_W = 816, PAGE_H = 1056;

// The resume and cover letter editor, used on the lead page and for saved resumes on the Resumes page: Markdown on the
// left, the page exactly as its PDF will look on the right (POST /api/preview renders it on the server).
// o: { doc ("resume" or "cover"), text, save(text), files (download names), leadId, theme, maxPages, original (the AI's
//      version, for Revert), tools (extra toolbar HTML), coverage (keyword chips), reviseUrl and fileHref (saved resumes) }
// It adds o.refresh() (redraw the preview) and o.saveNow(), and keeps o in S.editor for the layout menu and Re-check.
function mountEditor(container, o) {
  container.innerHTML = `<div class="toolbar">
      <button class="btn primary" data-ed="save">Save</button>
      ${(o.files || []).map((f) => `<button class="btn" data-ed="file" data-file="${f}">${I.dl} ${f.split(".").pop().toUpperCase()}</button>`).join("")}
      ${o.original ? `<button class="btn ghost" data-ed="revert">Revert to AI version</button>` : ""}${o.tools || ""}
      <span class="muted small mono" id="edstate"></span><span class="spacer"></span><span class="chip warn" id="overflow" style="display:none"><i class=i-warn></i> spills past one page</span></div>
    <div class="revise"><input type="text" id="revise-in" placeholder="Say how to change it, e.g. “lead with the data pipeline project, emphasize SQL, cut the retail job to one bullet”">
      <button class="btn ai" data-ed="revise"><i class=i-ai></i> Revise with AI</button></div>
    ${o.coverage ? `<div style="margin-bottom:12px">${keywordChips(o.coverage, "Not in this resume")}</div>` : ""}
    <div class="editor"><textarea id="ed" spellcheck="true">${esc(o.text)}</textarea>
      <div class="preview-wrap" id="pvw"><div class="preview-box" id="pvb"><iframe id="pv" sandbox="allow-same-origin" title="preview"></iframe></div></div></div>`;
  const editor = $("#ed", container), frame = $("#pv", container), state = $("#edstate", container);
  const wrap = $("#pvw", container), box = $("#pvb", container);
  const pages = Math.max(1, +o.maxPages || 1);
  frame.style.height = `${PAGE_H * pages}px`;
  // Shrink the full-size page to the width of the preview column.
  const scale = () => {
    const s = Math.min(1, (wrap.clientWidth - 28) / PAGE_W);
    frame.style.transform = `scale(${s})`;
    box.style.width = `${PAGE_W * s}px`;
    box.style.height = `${PAGE_H * pages * s}px`;
  };
  const refresh = async () => {
    frame.srcdoc = await api("/api/preview", { method: "POST", body: { doc: o.doc, md: editor.value, lead_id: o.leadId, theme: o.theme } });
    frame.onload = () => showFit(frame, o.doc, pages, $("#overflow", container));
  };
  const later = debounce(refresh, 350);
  const save = async () => {
    await o.save(editor.value);
    S.dirty = false;
    state.textContent = "saved";
    if (o.doc === "resume" && o.leadId) recheckResume(o.leadId);
  };
  o.refresh = refresh;
  o.saveNow = save;
  S.editor = o;
  editor.addEventListener("input", () => {
    S.dirty = true;
    state.textContent = "unsaved";
    later();
  });
  saveOnCtrlS(editor, save);
  container.onclick = async (e) => {
    const button = e.target.closest("[data-ed]");
    if (!button) return;
    const what = button.dataset.ed;
    if (what === "save") save();
    if (what === "file") {
      if (S.dirty) await save();  // download what you see
      openUrl(o.fileHref ? o.fileHref(button.dataset.file) : `/api/leads/${o.leadId}/export/${button.dataset.file}`);
    }
    if (what === "revert" && confirm("Replace the editor contents with the original AI version?")) {
      editor.value = o.original;
      S.dirty = true;
      state.textContent = "unsaved";
      refresh();
    }
    if (what === "revise") {
      const url = o.reviseUrl || `/api/leads/${o.leadId}/revise`;
      await reviseWithAI(button, url, o.doc, $("#revise-in", container).value.trim(), editor, () => {
        state.textContent = "revised: review it, then Save";
        refresh();
      });
    }
  };
  new ResizeObserver(scale).observe(wrap);
  scale();
  refresh();
}

// The text scales the server tries when it fits a resume to its page limit, largest first (FIT_SCALES in
// documents/render.py). Below 95% the server also tightens the margins (_resume_margins there).
const FIT_SCALES = [1, 0.97, 0.94, 0.91, 0.88, 0.86];

// After the preview loads: shrink a resume step by step until it fits its page limit, the same way the server fits the
// PDF, so the preview matches the download. The chip in the toolbar then says "auto-fit at N%" or "Longer than one page,
// trim it".
function showFit(frame, doc, pages, chip) {
  try {
    const d = frame.contentDocument, page = d.querySelector(".page");
    d.documentElement.style.overflow = "hidden";
    // The tallest the preview may be: PAGE_H per page plus a few pixels of slack. When the page has
    // box-decoration-break: clone (render.py sets it), every printed page repeats the top and bottom margins, but the
    // preview is one tall sheet that has them once. So a two-page resume loses one set of margins at the page break.
    const limit = () => {
      if (!page) return 1060 * pages;
      const css = d.defaultView.getComputedStyle(page);
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
    chip.style.display = over || fit < 1 ? "" : "none";
    chip.className = `chip ${over ? "bad" : "blue"}`;
    chip.textContent = over ? `Longer than ${pageLimit}, trim it` : `auto-fit to ${pageLimit} at ${Math.round(fit * 100)}%`;
  } catch (_) {}  // the preview went away before it loaded
}

// ---------------------------------------------------------------- resume cards
// Display names for the resume strategies (archetypes) the AI picks.
const ARCHETYPE_LABEL = { big_tech_swe: "Big-tech SWE", startup_product: "Startup / product", defense_contractor: "Defense contractor",
  aerospace_space: "Aerospace / space", research_lab: "Research lab", federal_usajobs: "Federal (USAJobs)", data_ml: "Data / ML",
  it_support_infra: "IT / infrastructure", solutions_sales_eng: "Solutions / sales engineering", experienced_professional: "Experienced professional",
  general: "General", general_tech: "General tech" };

// The Strategy card on the Resume tab: the archetype the AI wrote for, the layout menu, the page limit, why it chose what
// it did, and what the recruiter critic changed.
function resumeStrategyCard(pkg) {
  const st = pkg.resume_strategy || {}, style = pkg.resume_style || { theme: "classic", max_pages: 1 }, review = pkg.resume_review || {};
  const detail = (label, text, first) => `<div class="small"${first ? "" : ` style="margin-top:4px"`}><b class="mono">${label}</b> ${text}</div>`;
  const critic = review.changes?.length
    ? `<details style="margin-top:8px"><summary class="small mono" style="cursor:pointer">RECRUITER CRITIC: ${plural(review.changes.length, "change")}
        (score ${review.before_score} → ${review.after_score ?? review.before_score})</summary>${bulletList(review.changes, "small")}</details>`
    : "";
  return `<div class="card"><div class="row" style="margin-bottom:8px"><h3 style="margin:0">Strategy</h3>
      ${st.archetype ? `<span class="chip violet">${esc(ARCHETYPE_LABEL[st.archetype] || st.archetype)}</span>` : ""}<span class="spacer"></span>
      <label class="row small" style="gap:6px">Layout <select id="rs-theme" style="width:auto">${selectOptions(RESUME_THEMES, style.theme)}</select></label>
      <span class="chip">${style.max_pages === 2 ? "2 pages max" : "1 page"}</span></div>
    ${st.rationale ? `<p class="small" style="margin:0 0 8px">${esc(st.rationale)}</p>` : `<p class="muted small" style="margin:0 0 8px">Regenerate this package to get a strategy-driven resume.</p>`}
    ${st.section_order?.length ? detail("ORDER", st.section_order.map(esc).join(" → "), true) : ""}
    ${st.projects?.length ? detail("PROJECTS", st.projects.map(esc).join(", ")) : ""}
    ${st.summary ? detail("SUMMARY", esc(st.summary)) : ""}
    ${st.skills_grouping ? detail("SKILLS", esc(st.skills_grouping)) : ""}
    ${critic}</div>`;
}

// The Resume check card: the score, pages, keyword coverage, and each issue the check found (or a clean bill).
function resumeCheckCard(check) {
  if (!check) {
    return `<div class="card" id="rcheck"><h3>Resume check</h3><p class="muted small">Not checked yet.</p><button class="btn sm" data-act="resume-recheck">Run check</button></div>`;
  }
  const color = check.score >= 85 ? "good" : check.score >= 65 ? "warn" : "bad";
  const issue = (i) => i.level === "error"
    ? `<li style="color:var(--bad)"><i class=i-x></i> ${esc(i.text)}</li>`
    : `<li style="color:var(--text2)"><i class=i-warn></i> ${esc(i.text)}</li>`;
  const issues = check.issues.length
    ? `<ul class="clean small">${check.issues.map(issue).join("")}</ul>`
    : `<div class="small" style="color:var(--good)"><i class=i-check></i> ATS-safe, fits the page limit, and every skill is backed by your inventory.</div>`;
  return `<div class="card" id="rcheck"><div class="row" style="margin-bottom:8px"><h3 style="margin:0">Resume check</h3><span class="chip ${color}">${check.score}/100</span>
      <span class="chip">${check.pages ?? "?"} page${check.pages === 1 ? "" : "s"}</span><span class="chip ${check.coverage >= 0.75 ? "good" : "warn"}">keywords ${Math.round((check.coverage || 0) * 100)}%</span>
      <span class="spacer"></span><button class="btn sm" data-act="resume-recheck">Re-check</button></div>
    ${issues}</div>`;
}

// Runs the resume check again (POST /api/leads/{id}/resume-check) and swaps in the new card. The card dims meanwhile.
async function recheckResume(id) {
  const card = $("#rcheck");
  if (card) card.style.opacity = 0.5;
  try {
    const check = await api(`/api/leads/${id}/resume-check`, { method: "POST" });
    if (S.lead?.package) S.lead.package.resume_check = check;
    const current = $("#rcheck");
    if (current) current.outerHTML = resumeCheckCard(check);
  } catch (e) {
    if (card) card.style.opacity = "";
    toast("Check failed", e.message, "error");
  }
}

// ---------------------------------------------------------------- saving
// Sets the application status (PATCH). Applying also sets a 7-day follow-up on the server.
async function setStatus(id, status) {
  try {
    await api(`/api/leads/${id}`, { method: "PATCH", body: { app_status: status } });
    toast("Status updated", STATUS_LABEL[status]);
    refreshStats();
    if (S.route[0] === "lead") renderLead(id);
  } catch (e) {
    toast("Couldn't update", e.message, "error");
  }
}

// The send buttons on an email card: Gmail, the mail app, copy, download as .eml, or log it as sent.
async function mailAction(how, i) {
  const card = $(`.email[data-i="${i}"]`);
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
    await saveEmails();  // the download is built from the saved email
    openUrl(`/api/leads/${S.lead.id}/export/email-${i}.eml`);
  } else if (how === "sent") {
    const kind = S.lead.package.emails[i].kind.replace(/_/g, " ");
    await api(`/api/leads/${S.lead.id}/events`, { method: "POST", body: { type: "email", text: `Sent ${kind} to ${to || "?"}: ${subject}` } });
    toast("Logged", "Email marked as sent");
  }
}

// Saves the edited emails and the LinkedIn note into the lead's package. Does nothing when the Emails tab isn't open.
async function saveEmails() {
  if (!$(".email") && !$("#lnote")) return;
  const emails = (S.lead.package.emails || []).map((email, i) => {
    const card = $(`.email[data-i="${i}"]`);
    const field = (name) => $(`[data-ef="${name}"]`, card).value;
    return { ...email, to_addr: field("to_addr"), subject: field("subject"), body: field("body") };
  });
  const changes = { emails };
  if ($("#lnote")) changes.linkedin_note = $("#lnote").value;
  await api(`/api/leads/${S.lead.id}`, { method: "PATCH", body: { package: changes } });
  Object.assign(S.lead.package, changes);
  S.dirty = false;
}

// After answering, dismissing or adding questions: reload them (for the navigation badge) and redraw the lead.
async function refreshLeadQuestions() {
  S.questions = await api("/api/questions");
  renderNav();
  renderLead(S.lead.id);
}

// ---------------------------------------------------------------- actions
onAction("ltabgo", (el) => {  // a tab (or the "Open emails" button in the follow-up banner)
  if (S.dirty && !confirm("Discard unsaved edits?")) return;
  S.dirty = false;
  S.leadTab = el.dataset.tab;
  renderLeadTab();
});
onAction("apply", (el) => {
  openUrl(el.dataset.url);
  if (S.lead && !["applied", "assessment", "interviewing", "offer"].includes(S.lead.app_status)) {
    setTimeout(() => {  // after the application opens, ask whether to mark it applied
      if (confirm("Did you submit the application? Mark it as Applied (sets a 7-day follow-up)?")) setStatus(S.lead.id, "applied");
    }, 800);
  }
});
onAction("regen", async () => {
  if (S.lead.resume_md && !confirm("Regenerate the whole package? Your edits to the resume/cover letter will be replaced.")) return;
  await api(`/api/leads/${S.lead.id}/package`, { method: "POST" });
  toast("Building package", "It'll update here when ready.");
  setTimeout(() => renderLead(S.lead.id), 800);
});
onAction("plan", async (el) => {  // an action plan checkbox
  const pkg = S.lead.package;
  const done = new Set(pkg.plan_done || []);
  if (el.checked) done.add(+el.dataset.i);
  else done.delete(+el.dataset.i);
  pkg.plan_done = [...done];
  el.nextElementSibling.classList.toggle("done", el.checked);
  await api(`/api/leads/${S.lead.id}`, { method: "PATCH", body: { package: { plan_done: pkg.plan_done } } });
});
onAction("toggle-dream", async () => {
  await api(`/api/leads/${S.lead.id}`, { method: "PATCH", body: { dream: S.lead.dream ? 0 : 1 } });
  renderLead(S.lead.id);
});
onAction("export", async (el) => {  // save open edits first, so the file matches the screen
  if (S.dirty && S.leadTab === "emails") await saveEmails();
  if (S.dirty && S.leadTab === "kit") await saveAnswers();
  openUrl(el.dataset.url);
});
// Resume tab
onAction("resume-recheck", async () => {
  if (S.dirty && S.editor) await S.editor.saveNow();  // saving a lead's resume runs the check
  else recheckResume(S.lead.id);
});
onAction("lead-lib-save", async () => {
  const name = prompt("Name this resume in your collection:", `${S.lead.company}: ${S.lead.title}`.slice(0, 90));
  if (name === null) return;
  const item = await api("/api/library", { method: "POST", body: { lead_id: S.lead.id, name, md: $("#ed")?.value || S.lead.resume_md, style: S.lead.package?.resume_style } });
  toast("Saved to your collection", item.name);
});
onAction("lead-lib-use", () => leadPickSavedModal(S.lead));
// Emails tab
onAction("mail", (el) => mailAction(el.dataset.how, +el.dataset.i));
onAction("save-emails", async () => {
  await saveEmails();
  toast("Saved", "Emails updated");
});
onAction("revise-email", async (el) => {
  const i = +el.dataset.i;
  const instruction = $(`[data-erev="${i}"]`).value.trim();
  if (!instruction) return;
  const body = $('[data-ef="body"]', $(`.email[data-i="${i}"]`));
  el.disabled = true;
  el.innerHTML = `<span class="spin"></span>`;
  try {
    const r = await api(`/api/leads/${S.lead.id}/revise`, { method: "POST", body: { doc: `email (${S.lead.package.emails[i].kind})`, instruction, text: body.value } });
    body.value = r.text;
    S.dirty = true;
    toast("Email revised", "Review it, then Save edits.");
  } catch (err) {
    toast("Revision failed", err.message, "error");
  }
  el.disabled = false;
  el.textContent = "Revise";
});
onAction("copy-lnote", () => copy($("#lnote").value, "LinkedIn note copied"));
// Contacts tab
onAction("add-contact", async () => {
  const contact = {};
  $$("[data-nc]").forEach((input) => (contact[input.dataset.nc] = input.value));
  if (!contact.name) return;
  const r = await api(`/api/leads/${S.lead.id}/contacts/-1`, { method: "POST", body: contact });  // index -1 adds a contact
  S.lead.package.contacts = r.contacts;
  renderLeadTab();
});
onAction("rm-contact", async (el) => {
  if (!confirm("Remove this contact?")) return;
  const r = await api(`/api/leads/${S.lead.id}/contacts/${el.dataset.i}`, { method: "POST", body: { delete: true } });
  S.lead.package.contacts = r.contacts;
  renderLeadTab();
});
// Application kit tab
onAction("save-answers", async () => {
  await saveAnswers();
  $("#ans-state").textContent = "saved";
});
onAction("add-answer", () => {
  readAnswers();
  S.lead.package.application_answers.push({ question: "New question", answer: "" });
  renderLeadTab();
  S.dirty = true;
});
onAction("rm-answer", (el) => {
  readAnswers();
  S.lead.package.application_answers.splice(+el.dataset.i, 1);
  renderLeadTab();
  S.dirty = true;
});
onAction("copy-answer", (el) => copy($(`[data-aa="${el.dataset.i}"]`).value));
// Activity tab
onAction("save-notes", async () => {
  await api(`/api/leads/${S.lead.id}`, { method: "PATCH", body: { notes: $("#notes").value } });
  toast("Saved", "Notes updated");
});
onAction("save-fu", async () => {
  await api(`/api/leads/${S.lead.id}`, { method: "PATCH", body: { follow_up_at: $("#fu").value || null } });
  toast("Saved", "Follow-up date set");
  refreshStats();
});
onAction("logev", async (el) => {  // a preset event button, or Log with the custom text
  const text = el.dataset.text || $("#evtext").value;
  if (!text) return;
  await api(`/api/leads/${S.lead.id}/events`, { method: "POST", body: { type: "update", text } });
  renderLead(S.lead.id);
});
// Questions for this application
onAction("lead-gapq", async (el) => {
  el.disabled = true;
  el.innerHTML = `<span class="spin"></span> Thinking…`;
  try {
    const r = await api(`/api/leads/${S.lead.id}/questions/generate`, { method: "POST" });
    toast("Questions added", `${r.added} question(s) for this application`);
  } catch (err) {
    toast("Couldn't generate questions", err.message, "error");
  }
  await refreshLeadQuestions();
});
onAction("lead-answer", async (el) => {
  const input = el.parentElement.querySelector("[data-lqa]");
  if (!input.value.trim()) return;
  await api("/api/questions/answer", { method: "POST", body: { question: input.dataset.lqa, answer: input.value.trim() } });
  toast("Answer saved", "Saved to your profile.");
  await refreshLeadQuestions();
});
onAction("lead-dismiss", async (el) => {
  await api("/api/questions/dismiss", { method: "POST", body: { question: el.dataset.q } });
  await refreshLeadQuestions();
});
onAction("lead-apply", async (el) => {
  await api(`/api/leads/${S.lead.id}/apply-answers`, { method: "POST" });
  el.disabled = true;
  el.innerHTML = `<span class="spin"></span> Adding your answers and reworking the resume`;
  toast("Updating resume", "Adding your answers to your profile, then rewriting this resume with them (a minute or two).");
});
onChange(async (el) => {
  if (el.id !== "rs-theme") return false;  // the Layout menu on the Strategy card
  const style = { ...(S.lead.package.resume_style || { max_pages: 1 }), theme: el.value };
  await api(`/api/leads/${S.lead.id}`, { method: "PATCH", body: { package: { resume_style: style } } });
  S.lead.package.resume_style = style;
  if (S.editor) {
    S.editor.theme = el.value;
    S.editor.refresh();
  }
  toast("Layout changed", `${el.value}: PDF and DOCX exports updated`);
  recheckResume(S.lead.id);
  return true;
});
