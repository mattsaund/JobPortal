/* One lead's page: fit and triage, the tailored resume and cover letter editors, application answers, outreach emails,
   contacts, interview prep, company intel, questions for this application, downloads and history. */
"use strict";

const LEAD_TABS = [["overview", "Overview"], ["resume", "Resume"], ["cover", "Cover letter"], ["emails", "Emails"], ["contacts", "Contacts"],
  ["intel", "Company intel"], ["prep", "Interview prep"], ["kit", "Application kit"], ["activity", "Activity"], ["posting", "Posting"]];

async function renderLead(id, fromEvent) {
  if (fromEvent && S.dirty) return; // don't clobber unsaved edits
  let l;
  try { l = await api(`/api/leads/${id}`); } catch (e) { main.innerHTML = `<div class="page"><div class="empty"><b>Lead not found</b></div></div>`; return; }
  if (fromEvent && S.lead && S.lead.stage === l.stage && S.lead.updated_at === l.updated_at) return;
  S.lead = l; S.dirty = false;
  const pkg = l.package || {}, fit = pkg.fit || {}, packaged = !!l.resume_md;
  const apply = safeUrl(l.apply_url) || safeUrl(l.url);
  let banner = "";
  if (l.stage === "packaging") banner = `<div class="banner accent"><span class="spin"></span><div><b>JobPortal is building this package:</b> reading the posting, researching the team, finding contacts, tailoring your resume and cover letter. Usually 2 to 6 minutes.</div></div>`;
  else if (l.stage === "error") banner = `<div class="banner bad"><div><b>Package failed:</b> ${esc(l.stage_error)}</div><span class="spacer"></span><button class="btn sm" data-act="regen">Retry</button></div>`;
  else if (!packaged) banner = `<div class="banner"><div>${l.stage === "filtered" ? "Triage scored this below your threshold." : "Queued for packaging."} Want the full package now?</div><span class="spacer"></span><button class="btn primary sm" data-act="regen">Build package</button></div>`;
  else if (l.stage === "closed") banner = `<div class="banner bad"><div><b>JobPortal couldn't find this posting open anymore.</b> Double-check the link before spending time on it.</div></div>`;
  if (packaged && ["applied", "assessment", "interviewing"].includes(l.app_status) && l.follow_up_at && daysUntil(l.follow_up_at) <= 0)
    banner += `<div class="banner accent"><div><b>Follow-up due.</b> A ready-to-send follow-up email is in the Emails tab.</div><span class="spacer"></span><button class="btn sm" data-act="ltabgo" data-tab="emails">Open emails</button></div>`;

  main.innerHTML = `<div class="page">
    <div class="row" style="margin-bottom:12px"><a href="#/leads" class="mono small"><i class=i-back></i> All leads</a></div>
    <div class="lh">${ring(l.score, true)}
      <div><h1>${esc(l.title)}</h1><div class="co"><b>${esc(l.company)}</b>, ${esc(l.location || "location n/a")}</div>
        <div class="row" style="margin-top:8px;gap:6px">${leadChips(l)}</div>
        ${foundList(l).length ? `<div class="row small" style="margin-top:8px;gap:6px"><span class="muted mono">FOUND AT</span>${foundList(l).map((f) => `<a class="chip blue" href="${esc(f.url)}" target="_blank" rel="noopener" title="${esc(f.label)}"><i class=i-ext></i> ${esc(foundShort(f))}</a>`).join("")}</div>` : ""}</div>
      <div class="acts">
        <button class="btn ${l.dream ? "toggled" : "ghost"}" data-act="toggle-dream" title="Mark as a dream job">${l.dream ? "<i class=i-star></i> Dream" : "<i class=i-star-o></i> Dream"}</button>
        <select id="industry" title="Industry (edit if it's wrong)">${(S.industries || []).concat(l.industry && !(S.industries || []).includes(l.industry) ? [l.industry] : []).map((x) => `<option ${x === l.industry ? "selected" : ""}>${esc(x)}</option>`).join("")}</select>
        <select id="appstatus" title="Application status">${S.meta.statuses.map((s) => `<option value="${s}" ${s === l.app_status ? "selected" : ""}>${STATUS_LABEL[s]}</option>`).join("")}</select>
        ${apply ? `<button class="btn primary" data-act="apply" data-url="${esc(apply)}">Apply ${I.ext}</button>` : ""}
        ${packaged ? `<a class="btn" href="/api/leads/${l.id}/export/package.zip" title="Resume, cover letter, emails (.eml), answers, prep, intel, contacts">${I.dl} All files</a>` : ""}
        <button class="btn" data-act="regen" title="Re-run research + tailoring">${packaged ? "<i class=i-refresh></i> Regenerate" : "Build package"}</button>
      </div></div>
    ${banner}
    ${leadQuestionsPanel(l)}
    <div class="tabs" id="dtabs">${LEAD_TABS.map(([k, t]) => `<a class="${S.leadTab === k ? "on" : ""}" data-act="ltabgo" data-tab="${k}">${t}</a>`).join("")}</div>
    <div id="dbody"></div></div>`;
  $("#appstatus").onchange = (e) => setStatus(l.id, e.target.value);
  $("#industry").onchange = async (e) => { await api(`/api/leads/${l.id}`, { method: "PATCH", body: { industry: e.target.value } }); toast("Industry updated", e.target.value); };
  renderLeadTab();
}

function renderLeadTab() {
  const old = $("#dbody"), b = old.cloneNode(false);
  old.replaceWith(b);
  const l = S.lead, pkg = l.package || {};
  $$("#dtabs a").forEach((a) => a.classList.toggle("on", a.dataset.tab === S.leadTab));
  const none = (what) => `<div class="empty"><b>No ${what} yet</b>Build the package to generate it.</div>`;
  const t = S.leadTab;
  if (t === "overview") {
    const fit = pkg.fit || {}, tri = l.triage || {}, cov = pkg.coverage || {};
    const plan = pkg.action_plan || [], done = pkg.plan_done || [];
    b.innerHTML = `<div class="cols"><div class="stack">
      ${fit.summary || tri.summary ? `<div class="card"><h3>Fit</h3><p style="margin:0 0 10px">${esc(fit.summary || tri.summary)}</p>
        ${fit.strengths?.length ? `<b class="small mono">STRENGTHS</b><ul class="clean good">${fit.strengths.map((x) => `<li>${esc(x)}</li>`).join("")}</ul>` : ""}
        ${fit.gaps?.length ? `<div style="margin-top:10px"><b class="small mono">GAPS & HOW TO HANDLE THEM</b><ul class="clean warn">${fit.gaps.map((x) => `<li>${esc(x)}</li>`).join("")}</ul></div>` : ""}
        ${fit.eligibility_notes ? `<p class="small" style="margin:10px 0 0"><b class="mono">ELIGIBILITY:</b> ${esc(fit.eligibility_notes)}</p>` : ""}</div>` : ""}
      ${plan.length ? `<div class="card"><h3>Action plan</h3><div class="checklist">${plan.map((p, i) => `<label><input type="checkbox" data-act="plan" data-i="${i}" ${done.includes(i) ? "checked" : ""}><span class="${done.includes(i) ? "done" : ""}">${esc(p)}</span></label>`).join("")}</div></div>` : ""}
      ${pkg.job_summary ? `<div class="card"><h3>The role in brief</h3><div class="md">${md(pkg.job_summary)}</div></div>` : ""}
    </div><div class="stack">
      <div class="card"><h3>At a glance</h3><dl class="kv">
        <dt>Status</dt><dd>${esc(STATUS_LABEL[l.app_status])}${l.applied_at ? `, applied ${esc(l.applied_at)}` : ""}</dd>
        <dt>Deadline</dt><dd>${esc(l.deadline || "unknown")}</dd>
        <dt>Posted</dt><dd>${esc(l.posted_at || "unknown")}</dd>
        <dt>Found via</dt><dd>${esc(l.source_detail || l.source)}</dd>
        <dt>Posting</dt><dd>${safeUrl(l.url) ? `<a href="${esc(l.url)}" target="_blank" rel="noopener">${esc(l.url.slice(0, 70))}</a>` : "none"}</dd>
        <dt>Triage</dt><dd>${tri.score ?? "-"}, ${esc(tri.eligibility || "")}${tri.reasons?.length ? `: ${esc(tri.reasons.join("; "))}` : ""}</dd>
        <dt>AI usage</dt><dd>${(+l.tokens || 0).toLocaleString()} tokens</dd></dl></div>
      ${tri.red_flags?.length ? `<div class="card"><h3>Red flags</h3><ul class="clean warn">${tri.red_flags.map((x) => `<li>${esc(x)}</li>`).join("")}</ul></div>` : ""}
      ${(cov.hit || cov.miss) ? `<div class="card"><h3>ATS keywords in your resume: ${Math.round((l.ats_coverage || 0) * 100)}%</h3><div class="cov">${(cov.hit || []).map((k) => `<span class="chip good">${esc(k)}</span>`).join("")}${(cov.miss || []).map((k) => `<span class="chip" title="Not in the resume. Add it only if it's true.">${esc(k)}</span>`).join("")}</div></div>` : ""}
    </div></div>`;
  } else if (t === "resume" || t === "cover") {
    const text = t === "resume" ? l.resume_md : l.cover_md;
    if (!text) {
      b.innerHTML = t === "resume" ? `<div class="empty"><b>No tailored resume yet</b>Build the package to generate one, or start from a resume in your collection.
        <div style="margin-top:12px"><button class="btn" data-act="lead-lib-use">Use a saved resume</button></div></div>` : none("cover letter");
      return;
    }
    let host = b;
    if (t === "resume") {
      b.innerHTML = `<div class="cols" style="margin-bottom:14px">${resumeStrategyCard(pkg)}${resumeCheckCard(pkg.resume_check, pkg.resume_review)}</div><div id="ed-host"></div>`;
      host = $("#ed-host", b);
    }
    mountEditor(host, {
      doc: t, text, leadId: l.id, theme: t === "resume" ? (pkg.resume_style || {}).theme : undefined, maxPages: t === "resume" ? (pkg.resume_style || {}).max_pages || 1 : 1,
      original: t === "resume" ? pkg.original_resume_md : pkg.original_cover_md,
      save: async (v) => { await api(`/api/leads/${l.id}`, { method: "PATCH", body: t === "resume" ? { resume_md: v } : { cover_md: v } }); l[t === "resume" ? "resume_md" : "cover_md"] = v; },
      files: t === "resume" ? ["resume.pdf", "resume.docx", "resume.md"] : ["cover_letter.pdf", "cover_letter.docx", "cover_letter.md"],
      tools: t === "resume" ? `<button class="btn" data-act="lead-lib-save" title="Keep a copy of this resume in your collection"><i class=i-star></i> Save to collection</button><button class="btn" data-act="lead-lib-use">Use a saved resume</button>` : "",
      coverage: t === "resume" ? pkg.coverage : null,
    });
  } else if (t === "emails") {
    const emails = pkg.emails || [];
    if (!emails.length && !pkg.linkedin_note) { b.innerHTML = none("emails"); return; }
    const contacts = (pkg.contacts || []).filter((c) => c.email);
    b.innerHTML = `<datalist id="cemails">${contacts.map((c) => `<option value="${esc(c.email)}">${esc(c.name)}, ${esc(c.title)}</option>`).join("")}</datalist>
      <div class="stack">${emails.map((e, i) => `<div class="card email" data-i="${i}">
        <div class="hd"><span class="chip accent">${esc(e.kind.replace(/_/g, " "))}</span><span class="muted small">${esc(e.to)}</span><span class="spacer"></span>
          <button class="btn sm" data-act="mail" data-how="gmail" data-i="${i}">Open in Gmail ${I.ext}</button>
          <button class="btn sm" data-act="mail" data-how="mailto" data-i="${i}">Mail app</button>
          <button class="btn sm" data-act="mail" data-how="copy" data-i="${i}">Copy</button>
          <button class="btn sm" data-act="mail" data-how="eml" data-i="${i}" title="Download as an unsent draft (.eml) for Thunderbird / Outlook / Apple Mail">.eml</button>
          <button class="btn sm" data-act="mail" data-how="sent" data-i="${i}">Mark sent</button></div>
        <div class="grid2"><label class="f"><span>To</span><input type="email" list="cemails" data-ef="to_addr" value="${esc(pickTo(e))}" placeholder="pick a contact or type an address"></label>
          <label class="f"><span>Subject</span><input type="text" data-ef="subject" value="${esc(e.subject)}"></label></div>
        <textarea data-ef="body">${esc(e.body)}</textarea>
        <div class="revise" style="margin:0"><input type="text" data-erev="${i}" placeholder="Say how to change this email"><button class="btn sm" data-act="revise-email" data-i="${i}">Revise</button></div></div>`).join("")}
        ${pkg.linkedin_note ? `<div class="card"><h3>LinkedIn connection note <span id="lncount" class="muted">${pkg.linkedin_note.length}/300</span></h3>
          <textarea id="lnote" rows="3" style="font-family:var(--sans)">${esc(pkg.linkedin_note)}</textarea>
          <div class="row" style="margin-top:8px"><button class="btn sm" data-act="copy-lnote">Copy</button></div></div>` : ""}
        <div class="row" style="justify-content:flex-end"><span class="muted small">Export all emails:</span>${exportBtns(l.id, "emails", ["md", "docx", "pdf"])}<button class="btn primary" data-act="save-emails">Save edits</button></div></div>`;
    b.addEventListener("input", (e) => { S.dirty = true; if (e.target.id === "lnote") $("#lncount").textContent = `${e.target.value.length}/300`; });
  } else if (t === "contacts") {
    const cs = pkg.contacts || [];
    const inp = (i, k, v, ph) => `<input type="text" data-cf="${k}" data-i="${i}" value="${esc(v || "")}" placeholder="${ph}">`;
    b.innerHTML = `<div class="card"><div class="row" style="margin-bottom:6px"><h3 style="margin:0">People to reach (${cs.length})</h3><span class="spacer"></span>${exportBtns(l.id, "contacts", ["csv"])}</div>
      <p class="muted small" style="margin-top:0">Found by the AI on the public web. Every field is editable and saves when you leave it. <b>found</b> means the email was seen publicly; <b>pattern</b> means it was inferred from the company's email format (verify it).</p>
      ${cs.length ? `<table class="t"><thead><tr><th>Name / title / org</th><th>Email</th><th>LinkedIn and notes</th><th>Why them</th><th>Status</th><th></th></tr></thead><tbody>
      ${cs.map((c, i) => `<tr><td style="min-width:200px">${inp(i, "name", c.name, "Name")}<div style="height:4px"></div>${inp(i, "title", c.title, "Title")}<div style="height:4px"></div>${inp(i, "org", c.org, "Organization")}</td>
        <td style="min-width:220px">${inp(i, "email", c.email, "email@example.com")}<div class="row" style="margin-top:5px;gap:5px"><span class="chip ${c.email_confidence === "found" ? "good" : c.email_confidence === "pattern" ? "warn" : ""}">${esc(c.email_confidence || "unknown")}</span>${c.email ? `<button class="btn sm ghost" data-act="copytext" data-text="${esc(c.email)}">copy</button>` : ""}</div></td>
        <td style="min-width:200px">${inp(i, "linkedin", c.linkedin, "LinkedIn URL")}<div style="height:4px"></div>${inp(i, "notes", c.notes, "Notes")}
          <div class="small row" style="margin-top:4px;gap:8px">${safeUrl(c.linkedin) ? `<a href="${esc(c.linkedin)}" target="_blank" rel="noopener">open LinkedIn</a>` : ""}${safeUrl(c.source_url) ? `<a href="${esc(c.source_url)}" target="_blank" rel="noopener">source</a>` : ""}</div></td>
        <td class="small" style="max-width:300px"><textarea data-cf="why" data-i="${i}" rows="3" style="font-family:var(--sans);font-size:12.5px">${esc(c.why || "")}</textarea></td>
        <td><select data-act="cstatus" data-i="${i}">${["", "to contact", "contacted", "replied", "no response", "referred me"].map((s) => `<option ${c.status === s ? "selected" : ""} value="${s}">${s || "not set"}</option>`).join("")}</select></td>
        <td><button class="btn sm ghost danger" data-act="rm-contact" data-i="${i}" title="Remove"><i class=i-x></i></button></td></tr>`).join("")}
      </tbody></table>` : `<div class="muted">No contacts found yet.</div>`}
      <div class="hr"></div><div class="grid3" id="newc">
        <input type="text" placeholder="Name" data-nc="name"><input type="text" placeholder="Title" data-nc="title"><input type="email" placeholder="Email" data-nc="email">
        <input type="url" placeholder="LinkedIn URL" data-nc="linkedin"><input type="text" placeholder="Why / notes" data-nc="why"><button class="btn" data-act="add-contact">+ Add contact</button></div></div>`;
    b.addEventListener("change", async (e) => {
      const el = e.target; if (!el.dataset.cf) return;
      await api(`/api/leads/${l.id}/contacts/${el.dataset.i}`, { method: "POST", body: { [el.dataset.cf]: el.value } });
      pkg.contacts[+el.dataset.i][el.dataset.cf] = el.value;
    });
  } else if (t === "intel" || t === "prep") {
    const key = t === "intel" ? "company_brief_md" : "interview_prep_md";
    if (!pkg[key]) { b.innerHTML = none(t === "intel" ? "company intel" : "interview prep"); return; }
    mountDocEditor(b, { text: pkg[key], leadId: l.id, stem: t === "intel" ? "company_intel" : "interview_prep", doc: t === "intel" ? "company brief" : "interview prep",
      save: async (v) => { await api(`/api/leads/${l.id}`, { method: "PATCH", body: { package: { [key]: v } } }); pkg[key] = v; } });
  } else if (t === "kit") {
    renderKit(b, l, pkg);
  } else if (t === "activity") {
    b.innerHTML = `<div class="cols"><div class="stack"><div class="card"><h3>Notes</h3><textarea id="notes" rows="8" style="font-family:var(--sans)">${esc(l.notes || "")}</textarea>
        <div class="row" style="margin-top:8px"><button class="btn sm" data-act="save-notes">Save notes</button></div></div>
      <div class="card"><h3>Timeline</h3><div class="timeline">${(l.events || []).map((e) => `<div class="ev"><span class="ts">${esc(e.ts.replace("T", " ").slice(0, 16))}</span><span class="chip">${esc(e.type)}</span><span>${esc(e.text)}</span></div>`).join("") || `<div class="muted">No activity yet.</div>`}</div></div></div>
      <div class="stack"><div class="card"><h3>Follow-up</h3><label class="f"><span>Follow up on</span><input type="date" id="fu" value="${esc(l.follow_up_at || "")}"></label>
        <div class="row" style="margin-top:8px"><button class="btn sm" data-act="save-fu">Save date</button></div></div>
        <div class="card"><h3>Log an event</h3><div class="row">${["Got online assessment", "Recruiter reached out", "Interview scheduled", "Referral submitted", "Offer!", "Rejected"].map((x) => `<button class="btn sm" data-act="logev" data-text="${esc(x)}">${esc(x)}</button>`).join("")}</div>
          <div class="row" style="margin-top:10px"><input type="text" id="evtext" placeholder="Custom event" style="flex:1"><button class="btn sm" data-act="logev">Log</button></div></div></div></div>`;
  } else if (t === "posting") {
    b.innerHTML = `<div class="card"><div class="row" style="margin-bottom:12px">${safeUrl(l.url) ? `<a class="btn sm" href="${esc(l.url)}" target="_blank" rel="noopener">Open posting ${I.ext}</a>` : ""}
      ${safeUrl(l.apply_url) && l.apply_url !== l.url ? `<a class="btn sm" href="${esc(l.apply_url)}" target="_blank" rel="noopener">Apply page ${I.ext}</a>` : ""}
      <span class="muted small">${esc(l.source_detail || "")}</span></div><pre class="jd">${esc(l.description || "No description captured.")}</pre></div>`;
  }
}

// Only pre-fill a recipient when the AI wrote a concrete address for this email, never a guessed pattern placeholder.
function pickTo(e) {
  if (e.to_addr != null) return e.to_addr;
  const m = (e.to || "").match(/[\w.+-]+@[\w-]+\.[\w.-]+/);
  return m && !/^(first|firstname|name|flast|f\.?last|last|jdoe|john|email)\b|[\[\]]/i.test(m[0]) ? m[0] : "";
}

async function renderKit(b, l, pkg) {
  if (!S.profileCache) S.profileCache = await api("/api/profile");
  const qa = S.profileCache.qa || [], f = S.profileCache.facts || {};
  const row = (q, a) => `<div class="copyrow"><div class="q">${esc(q)}</div><div class="a">${esc(a)}</div><button class="btn sm" data-act="copytext" data-text="${esc(a)}">copy</button></div>`;
  const apply = safeUrl(l.apply_url) || safeUrl(l.url);
  const answers = pkg.application_answers || [];
  b.innerHTML = `<div class="cols"><div class="stack">
    <div class="card"><h3>Files</h3><div class="row">${l.resume_md ? exportBtns(l.id, "resume", ["pdf", "docx", "md"], "Resume") : ""}</div>
      <div class="row" style="margin-top:8px">${l.cover_md ? exportBtns(l.id, "cover_letter", ["pdf", "docx", "md"], "Cover") : ""}</div>
      <div class="row" style="margin-top:12px"><a class="btn" href="/api/leads/${l.id}/export/package.zip">${I.dl} Everything (.zip)</a>
      ${apply ? `<button class="btn primary" data-act="apply" data-url="${esc(apply)}">Open application ${I.ext}</button>` : ""}</div></div>
    <div class="card"><div class="row" style="margin-bottom:10px"><h3 style="margin:0">Tailored answers</h3><span class="spacer"></span>${exportBtns(l.id, "answers", ["docx", "pdf", "md"])}</div>
      <div class="stack" id="answers">${answers.map((x, i) => `<div class="stack" style="gap:6px;padding-bottom:12px;border-bottom:1px solid var(--line)">
        <div class="row"><input type="text" data-aq="${i}" value="${esc(x.question)}" style="flex:1;font-weight:600"><button class="btn sm" data-act="copy-answer" data-i="${i}">copy</button><button class="btn sm ghost danger" data-act="rm-answer" data-i="${i}" title="Remove"><i class=i-x></i></button></div>
        <textarea data-aa="${i}" rows="5" style="font-family:var(--sans);font-size:13px">${esc(x.answer)}</textarea></div>`).join("") || `<div class="muted">Build the package to generate tailored answers.</div>`}</div>
      <div class="row" style="margin-top:12px"><button class="btn sm" data-act="add-answer">+ Add question</button><span class="spacer"></span><span class="muted small" id="ans-state"></span><button class="btn primary sm" data-act="save-answers">Save answers</button></div></div>
  </div><div class="stack"><div class="card"><h3>Standard answers</h3><p class="muted small" style="margin-top:-4px">From your answers in <a href="#/profile/answers">Profile, Standard answers</a>. Edit them there.</p>${qa.filter((x) => !x.eeo).map((x) => row(x.q, x.a)).join("") || `<div class="muted small">Answer the standard questions to fill these in.</div>`}</div>
    ${qa.some((x) => x.eeo) ? `<div class="card"><h3>Voluntary self-identification</h3><p class="muted small" style="margin-top:-4px">Only shown here for copying. Never sent to the AI.</p>${qa.filter((x) => x.eeo).map((x) => row(x.q, x.a)).join("")}</div>` : ""}</div></div>`;
  b.addEventListener("input", (e) => { if (e.target.dataset.aq != null || e.target.dataset.aa != null) { S.dirty = true; $("#ans-state").textContent = "unsaved"; } });
}

function readAnswers() {
  const pkg = S.lead.package;
  pkg.application_answers = (pkg.application_answers || []).map((x, i) => ({
    question: $(`[data-aq="${i}"]`)?.value ?? x.question, answer: $(`[data-aa="${i}"]`)?.value ?? x.answer }));
  return pkg.application_answers;
}

function exportBtns(id, stem, fmts, label = "") {
  return fmts.map((f) => `<button class="btn sm" data-act="export" data-url="/api/leads/${id}/export/${stem}.${f}">${I.dl} ${label ? label + " " : ""}${f.toUpperCase()}</button>`).join("");
}

// ---------- generic markdown document editor (company intel, interview prep)
function mountDocEditor(container, o) {
  container.innerHTML = `<div class="toolbar"><button class="btn primary" data-de="save">Save</button>
      ${["pdf", "docx", "md"].map((f) => `<button class="btn" data-de="exp" data-fmt="${f}">${I.dl} ${f.toUpperCase()}</button>`).join("")}
      <span class="muted small mono" id="destate"></span></div>
    <div class="revise"><input type="text" id="de-rev" placeholder="Say how to change it, e.g. “add 3 questions about system design, shorten the company history”"><button class="btn ai" data-de="revise"><i class=i-ai></i> Revise with AI</button></div>
    <div class="editor"><textarea id="de-ed" spellcheck="true">${esc(o.text)}</textarea><div class="card md" id="de-pv" style="max-height:76vh;overflow:auto"></div></div>`;
  const ed = $("#de-ed", container), pv = $("#de-pv", container), st = $("#destate", container);
  const draw = () => (pv.innerHTML = md(ed.value));
  ed.addEventListener("input", debounce(() => { S.dirty = true; st.textContent = "unsaved"; draw(); }, 150));
  const save = async () => { await o.save(ed.value); S.dirty = false; st.textContent = "saved"; };
  ed.addEventListener("keydown", (e) => { if ((e.ctrlKey || e.metaKey) && e.key === "s") { e.preventDefault(); save(); } });
  container.onclick = async (e) => {
    const btn = e.target.closest("[data-de]"); if (!btn) return;
    if (btn.dataset.de === "save") save();
    if (btn.dataset.de === "exp") { if (S.dirty) await save(); openUrl(`/api/leads/${o.leadId}/export/${o.stem}.${btn.dataset.fmt}`); }
    if (btn.dataset.de === "revise") {
      const ins = $("#de-rev", container).value.trim(); if (!ins) return;
      btn.disabled = true; btn.innerHTML = `<span class="spin"></span> Revising…`;
      try {
        const r = await api(`/api/leads/${o.leadId}/revise`, { method: "POST", body: { doc: o.doc, instruction: ins, text: ed.value } });
        ed.value = r.text; S.dirty = true; st.textContent = "revised: review it, then Save"; draw(); toast("Revised", r.change_summary);
      } catch (err) { toast("Revision failed", err.message, "error"); }
      btn.disabled = false; btn.innerHTML = "<i class=i-ai></i> Revise with AI";
    }
  };
  draw();
}

// ---------- document editor (tailored resume / cover letter)
function mountEditor(container, o) {
  const covHtml = (c) => c ? `<div class="cov">${(c.hit || []).map((k) => `<span class="chip good">${esc(k)}</span>`).join("")}${(c.miss || []).map((k) => `<span class="chip" title="Not in this resume">${esc(k)}</span>`).join("")}</div>` : "";
  container.innerHTML = `<div class="toolbar">
      <button class="btn primary" data-ed="save">Save</button>
      ${(o.files || []).map((f) => `<button class="btn" data-ed="file" data-file="${f}">${I.dl} ${f.split(".").pop().toUpperCase()}</button>`).join("")}
      ${o.original ? `<button class="btn ghost" data-ed="revert">Revert to AI version</button>` : ""}${o.tools || ""}
      <span class="muted small mono" id="edstate"></span><span class="spacer"></span><span class="chip warn" id="overflow" style="display:none"><i class=i-warn></i> spills past one page</span></div>
    ${o.leadId || o.reviseUrl ? `<div class="revise"><input type="text" id="revise-in" placeholder="Say how to change it, e.g. “lead with the data pipeline project, emphasize SQL, cut the retail job to one bullet”"><button class="btn ai" data-ed="revise"><i class=i-ai></i> Revise with AI</button></div>` : ""}
    ${o.coverage ? `<div style="margin-bottom:12px">${covHtml(o.coverage)}</div>` : ""}
    <div class="editor"><textarea id="ed" spellcheck="true">${esc(o.text)}</textarea>
      <div class="preview-wrap" id="pvw"><div class="preview-box" id="pvb"><iframe id="pv" sandbox="allow-same-origin" title="preview"></iframe></div></div></div>`;
  const ed = $("#ed", container), pv = $("#pv", container), state = $("#edstate", container);
  const pages = Math.max(1, +o.maxPages || 1);
  pv.style.height = `${1056 * pages}px`;
  const scale = () => {
    const w = $("#pvw", container).clientWidth - 28, s = Math.min(1, w / 816);
    pv.style.transform = `scale(${s})`; $("#pvb", container).style.width = `${816 * s}px`; $("#pvb", container).style.height = `${1056 * pages * s}px`;
  };
  const refresh = async () => {
    const html = await api("/api/preview", { method: "POST", body: { doc: o.doc, md: ed.value, lead_id: o.leadId, theme: o.theme } });
    pv.srcdoc = html;
    pv.onload = () => { // mirror the server's one-page auto-fit (shrinks to 86% max) so the preview matches the PDF
      try {
        const d = pv.contentDocument, page = d.querySelector(".page"), warn = $("#overflow", container);
        d.documentElement.style.overflow = "hidden";
        let fit = 1;
        if (o.doc === "resume" && page) {
          for (const sc of [1, 0.97, 0.94, 0.91, 0.88, 0.86]) {
            page.style.setProperty("--s", sc);
            if (sc < 0.95) { page.style.setProperty("--mt", "0.35in"); page.style.setProperty("--mx", "0.42in"); }
            fit = sc;
            if (d.documentElement.scrollHeight <= 1060 * pages) break;
          }
        }
        const over = d.documentElement.scrollHeight > 1060 * pages;
        warn.style.display = over || fit < 1 ? "" : "none";
        warn.className = `chip ${over ? "bad" : "blue"}`;
        warn.textContent = over ? `Longer than ${pages === 1 ? "one page" : `${pages} pages`}, trim it` : `auto-fit to ${pages === 1 ? "one page" : `${pages} pages`} at ${Math.round(fit * 100)}%`;
      } catch (_) {}
    };
  };
  const later = debounce(refresh, 350);
  ed.addEventListener("input", () => { S.dirty = true; state.textContent = "unsaved"; later(); });
  const save = async () => { await o.save(ed.value); S.dirty = false; state.textContent = "saved"; if (o.doc === "resume" && o.leadId) recheckResume(o.leadId); };
  o.refresh = refresh;
  S.editorOpts = o;
  ed.addEventListener("keydown", (e) => { if ((e.ctrlKey || e.metaKey) && e.key === "s") { e.preventDefault(); save(); } });
  container.onclick = async (e) => {
    const btn = e.target.closest("[data-ed]"); if (!btn) return;
    const a = btn.dataset.ed;
    if (a === "save") save();
    if (a === "file") { if (S.dirty) await save(); openUrl(o.fileHref ? o.fileHref(btn.dataset.file) : `/api/leads/${o.leadId}/export/${btn.dataset.file}`); }
    if (a === "revert" && confirm("Replace the editor contents with the original AI version?")) { ed.value = o.original; S.dirty = true; state.textContent = "unsaved"; refresh(); }
    if (a === "revise") {
      const ins = $("#revise-in", container).value.trim(); if (!ins) return;
      btn.disabled = true; btn.innerHTML = `<span class="spin"></span> Revising…`;
      try {
        const r = await api(o.reviseUrl || `/api/leads/${o.leadId}/revise`, { method: "POST", body: { doc: o.doc, instruction: ins, text: ed.value } });
        ed.value = r.text; S.dirty = true; state.textContent = "revised: review it, then Save"; refresh(); toast("Revised", r.change_summary);
      } catch (err) { toast("Revision failed", err.message, "error"); }
      btn.disabled = false; btn.innerHTML = "<i class=i-ai></i> Revise with AI";
    }
  };
  new ResizeObserver(scale).observe($("#pvw", container));
  scale(); refresh();
}

const ARCHETYPE_LABEL = { big_tech_swe: "Big-tech SWE", startup_product: "Startup / product", defense_contractor: "Defense contractor",
  aerospace_space: "Aerospace / space", research_lab: "Research lab", federal_usajobs: "Federal (USAJobs)", data_ml: "Data / ML",
  it_support_infra: "IT / infrastructure", solutions_sales_eng: "Solutions / sales engineering", experienced_professional: "Experienced professional",
  general: "General", general_tech: "General tech" };
function resumeStrategyCard(pkg) {
  const st = pkg.resume_strategy || {}, style = pkg.resume_style || { theme: "classic", max_pages: 1 }, rv = pkg.resume_review || {};
  return `<div class="card"><div class="row" style="margin-bottom:8px"><h3 style="margin:0">Strategy</h3>
      ${st.archetype ? `<span class="chip violet">${esc(ARCHETYPE_LABEL[st.archetype] || st.archetype)}</span>` : ""}<span class="spacer"></span>
      <label class="row small" style="gap:6px">Layout <select id="rs-theme" style="width:auto">${["classic", "modern", "compact", "academic"].map((x) => `<option ${x === style.theme ? "selected" : ""}>${x}</option>`).join("")}</select></label>
      <span class="chip">${style.max_pages === 2 ? "2 pages max" : "1 page"}</span></div>
    ${st.rationale ? `<p class="small" style="margin:0 0 8px">${esc(st.rationale)}</p>` : `<p class="muted small" style="margin:0 0 8px">Regenerate this package to get a strategy-driven resume.</p>`}
    ${st.section_order?.length ? `<div class="small"><b class="mono">ORDER</b> ${st.section_order.map(esc).join(" → ")}</div>` : ""}
    ${st.projects?.length ? `<div class="small" style="margin-top:4px"><b class="mono">PROJECTS</b> ${st.projects.map(esc).join(", ")}</div>` : ""}
    ${st.summary ? `<div class="small" style="margin-top:4px"><b class="mono">SUMMARY</b> ${esc(st.summary)}</div>` : ""}
    ${st.skills_grouping ? `<div class="small" style="margin-top:4px"><b class="mono">SKILLS</b> ${esc(st.skills_grouping)}</div>` : ""}
    ${rv.changes?.length ? `<details style="margin-top:8px"><summary class="small mono" style="cursor:pointer">RECRUITER CRITIC: ${rv.changes.length} change${rv.changes.length > 1 ? "s" : ""} (score ${rv.before_score} → ${rv.after_score ?? rv.before_score})</summary><ul class="clean small">${rv.changes.map((c) => `<li>${esc(c)}</li>`).join("")}</ul></details>` : ""}</div>`;
}
function resumeCheckCard(chk, rv) {
  if (!chk) return `<div class="card"><h3>Resume check</h3><p class="muted small">Not checked yet.</p><button class="btn sm" data-act="resume-recheck">Run check</button></div>`;
  const col = chk.score >= 85 ? "good" : chk.score >= 65 ? "warn" : "bad";
  return `<div class="card" id="rcheck"><div class="row" style="margin-bottom:8px"><h3 style="margin:0">Resume check</h3><span class="chip ${col}">${chk.score}/100</span>
      <span class="chip">${chk.pages ?? "?"} page${chk.pages === 1 ? "" : "s"}</span><span class="chip ${chk.coverage >= 0.75 ? "good" : "warn"}">keywords ${Math.round((chk.coverage || 0) * 100)}%</span>
      <span class="spacer"></span><button class="btn sm" data-act="resume-recheck">Re-check</button></div>
    ${chk.issues.length ? `<ul class="clean small">${chk.issues.map((i) => `<li style="color:${i.level === "error" ? "var(--bad)" : "var(--text2)"}">${i.level === "error" ? '<i class=i-x></i>' : '<i class=i-warn></i>'} ${esc(i.text)}</li>`).join("")}</ul>`
      : `<div class="small" style="color:var(--good)"><i class=i-check></i> ATS-safe, fits the page limit, and every skill is backed by your inventory.</div>`}</div>`;
}
async function recheckResume(id) {
  const box = $("#rcheck"); if (box) box.style.opacity = 0.5;
  try { const chk = await api(`/api/leads/${id}/resume-check`, { method: "POST" }); if (S.lead?.package) S.lead.package.resume_check = chk;
    const host = $("#rcheck") || $(".cols .card:last-child"); if (host) host.outerHTML = resumeCheckCard(chk); } catch (e) { toast("Check failed", e.message, "error"); }
}

function leadQuestionsPanel(l) {
  const qs = l.questions || [], open = qs.filter((q) => q.status === "open"), answered = qs.filter((q) => q.status === "answered");
  if (!l.resume_md) return "";
  if (!qs.length) return `<div class="banner"><div class="small">No open questions for this application.</div><span class="spacer"></span>
    <button class="btn sm" data-act="lead-gapq" title="Ask the AI what you could tell it that would make this resume stronger"><i class=i-question></i> Find gaps to ask me about</button></div>`;
  return `<div class="card lq" style="margin-bottom:14px"><div class="row" style="margin-bottom:6px"><h3 style="margin:0"><i class=i-question></i> Questions that could strengthen this resume</h3>
      <span class="muted small">Answers are saved to your profile, so every future application benefits.</span><span class="spacer"></span>
      ${answered.length ? `<button class="btn primary sm ai" data-act="lead-apply" title="Add your answers to your profile, then rework this resume with them"><i class=i-ai></i> Update this resume with my answers</button>` : ""}</div>
    ${open.map((q) => `<div class="lq-item"><div><b>${esc(q.question)}</b></div><div class="small muted">${esc(q.why)}</div>
      <div class="row" style="margin-top:6px"><input type="text" data-lqa="${esc(q.question)}" placeholder="Your answer" style="flex:1">
      <button class="btn sm" data-act="lead-answer">Save answer</button><button class="btn sm ghost" data-act="lead-dismiss" data-q="${esc(q.question)}" title="Not relevant"><i class=i-x></i></button></div></div>`).join("")}
    ${answered.map((q) => `<div class="lq-item done"><div class="small"><b>${esc(q.question)}</b></div><div class="small" style="color:var(--good)"><i class=i-check></i> ${esc(q.answer || "")}</div></div>`).join("")}</div>`;
}

async function setStatus(id, st) {
  try {
    await api(`/api/leads/${id}`, { method: "PATCH", body: { app_status: st } });
    toast("Status updated", STATUS_LABEL[st]);
    refreshStats();
    if (S.route[0] === "lead") renderLead(id);
  } catch (e) { toast("Couldn't update", e.message, "error"); }
}
function mailAction(how, i) {
  const card = $(`.email[data-i="${i}"]`), get = (k) => $(`[data-ef="${k}"]`, card).value;
  const to = get("to_addr"), su = get("subject"), body = get("body");
  if (how === "gmail") openUrl(`https://mail.google.com/mail/?view=cm&fs=1&to=${encodeURIComponent(to)}&su=${encodeURIComponent(su)}&body=${encodeURIComponent(body)}`);
  if (how === "mailto") { const u = `mailto:${encodeURIComponent(to)}?subject=${encodeURIComponent(su)}&body=${encodeURIComponent(body)}`; if (ownWindow()) openUrl(u); else location.href = u; }
  if (how === "copy") copy(`Subject: ${su}\n\n${body}`, "Email copied");
  if (how === "eml") saveEmails().then(() => openUrl(`/api/leads/${S.lead.id}/export/email-${i}.eml`));
  if (how === "sent") api(`/api/leads/${S.lead.id}/events`, { method: "POST", body: { type: "email", text: `Sent ${S.lead.package.emails[i].kind.replace(/_/g, " ")} to ${to || "?"}: ${su}` } }).then(() => toast("Logged", "Email marked as sent"));
}
async function saveEmails() {
  if (!$(".email")) return;
  const emails = S.lead.package.emails.map((em, i) => { const card = $(`.email[data-i="${i}"]`); return { ...em, to_addr: $('[data-ef="to_addr"]', card).value, subject: $('[data-ef="subject"]', card).value, body: $('[data-ef="body"]', card).value }; });
  const body = { emails }; if ($("#lnote")) body.linkedin_note = $("#lnote").value;
  await api(`/api/leads/${S.lead.id}`, { method: "PATCH", body: { package: body } }); Object.assign(S.lead.package, body); S.dirty = false;
}

// ---------------------------------------------------------------- actions
onAction("ltabgo", async (el, e) => { if (S.dirty && !confirm("Discard unsaved edits?")) return; S.dirty = false; S.leadTab = el.dataset.tab; renderLeadTab(); });
onAction("apply", async (el, e) => {
  openUrl(el.dataset.url);
  if (S.lead && !["applied", "assessment", "interviewing", "offer"].includes(S.lead.app_status))
    setTimeout(() => { if (confirm("Did you submit the application? Mark it as Applied (sets a 7-day follow-up)?")) setStatus(S.lead.id, "applied"); }, 800);
});
onAction("regen", async (el, e) => { if (S.lead.resume_md && !confirm("Regenerate the whole package? Your edits to the resume/cover letter will be replaced.")) return; await api(`/api/leads/${S.lead.id}/package`, { method: "POST" }); toast("Building package", "It'll update here when ready."); setTimeout(() => renderLead(S.lead.id), 800); });
onAction("plan", async (el, e) => { const pkg = S.lead.package; const done = new Set(pkg.plan_done || []); el.checked ? done.add(+el.dataset.i) : done.delete(+el.dataset.i); pkg.plan_done = [...done]; el.nextElementSibling.classList.toggle("done", el.checked); await api(`/api/leads/${S.lead.id}`, { method: "PATCH", body: { package: { plan_done: pkg.plan_done } } }); });
onAction("mail", async (el, e) => { mailAction(el.dataset.how, +el.dataset.i); });
onAction("save-emails", async (el, e) => { await saveEmails(); toast("Saved", "Emails updated"); });
onAction("revise-email", async (el, e) => {
  const i = +el.dataset.i, ins = $(`[data-erev="${i}"]`).value.trim(); if (!ins) return;
  const card = $(`.email[data-i="${i}"]`), bodyEl = $('[data-ef="body"]', card);
  el.disabled = true; el.innerHTML = `<span class="spin"></span>`;
  try { const r = await api(`/api/leads/${S.lead.id}/revise`, { method: "POST", body: { doc: `email (${S.lead.package.emails[i].kind})`, instruction: ins, text: bodyEl.value } });
    bodyEl.value = r.text; S.dirty = true; toast("Email revised", "Review it, then Save edits."); } catch (err) { toast("Revision failed", err.message, "error"); }
  el.disabled = false; el.textContent = "Revise";
});
onAction("export", async (el, e) => {
  if (S.dirty && S.leadTab === "emails") await saveEmails();
  if (S.dirty && S.leadTab === "kit") { await api(`/api/leads/${S.lead.id}`, { method: "PATCH", body: { package: { application_answers: readAnswers() } } }); S.dirty = false; }
  openUrl(el.dataset.url);
});
onAction("save-answers", async (el, e) => { await api(`/api/leads/${S.lead.id}`, { method: "PATCH", body: { package: { application_answers: readAnswers() } } }); S.dirty = false; $("#ans-state").textContent = "saved"; });
onAction("add-answer", async (el, e) => { readAnswers(); S.lead.package.application_answers.push({ question: "New question", answer: "" }); renderLeadTab(); S.dirty = true; });
onAction("rm-answer", async (el, e) => { readAnswers(); S.lead.package.application_answers.splice(+el.dataset.i, 1); renderLeadTab(); S.dirty = true; });
onAction("copy-answer", async (el, e) => { copy($(`[data-aa="${el.dataset.i}"]`).value); });
onAction("rm-contact", async (el, e) => { if (!confirm("Remove this contact?")) return; const r = await api(`/api/leads/${S.lead.id}/contacts/${el.dataset.i}`, { method: "POST", body: { delete: true } }); S.lead.package.contacts = r.contacts; renderLeadTab(); });
onAction("copy-lnote", async (el, e) => { copy($("#lnote").value, "LinkedIn note copied"); });
onAction("add-contact", async (el, e) => {
  const body = {}; $$("[data-nc]").forEach((i) => (body[i.dataset.nc] = i.value)); if (!body.name) return;
  const r = await api(`/api/leads/${S.lead.id}/contacts/-1`, { method: "POST", body }); S.lead.package.contacts = r.contacts; renderLeadTab();
});
onAction("save-notes", async (el, e) => { await api(`/api/leads/${S.lead.id}`, { method: "PATCH", body: { notes: $("#notes").value } }); toast("Saved", "Notes updated"); });
onAction("save-fu", async (el, e) => { await api(`/api/leads/${S.lead.id}`, { method: "PATCH", body: { follow_up_at: $("#fu").value || null } }); toast("Saved", "Follow-up date set"); refreshStats(); });
onAction("logev", async (el, e) => { const text = el.dataset.text || $("#evtext").value; if (!text) return; await api(`/api/leads/${S.lead.id}/events`, { method: "POST", body: { type: "update", text } }); renderLead(S.lead.id); });
onAction("lead-lib-save", async (el, e) => {
  const name = prompt("Name this resume in your collection:", `${S.lead.company}: ${S.lead.title}`.slice(0, 90)); if (name === null) return;
  const it = await api("/api/library", { method: "POST", body: { lead_id: S.lead.id, name, md: $("#ed")?.value || S.lead.resume_md, style: S.lead.package?.resume_style } });
  toast("Saved to your collection", it.name);
});
onAction("lead-lib-use", async (el, e) => { leadPickSavedModal(S.lead); });
onAction("lead-gapq", async (el, e) => { el.disabled = true; el.innerHTML = `<span class="spin"></span> Thinking…`; try { const r = await api(`/api/leads/${S.lead.id}/questions/generate`, { method: "POST" }); toast("Questions added", `${r.added} question(s) for this application`); } catch (err) { toast("Couldn't generate questions", err.message, "error"); } S.questions = await api("/api/questions"); renderNav(); renderLead(S.lead.id); });
onAction("lead-answer", async (el, e) => { const inp = el.parentElement.querySelector("[data-lqa]"); if (!inp.value.trim()) return; await api("/api/questions/answer", { method: "POST", body: { question: inp.dataset.lqa, answer: inp.value.trim() } }); toast("Answer saved", "Saved to your profile."); S.questions = await api("/api/questions"); renderNav(); renderLead(S.lead.id); });
onAction("lead-dismiss", async (el, e) => { await api("/api/questions/dismiss", { method: "POST", body: { question: el.dataset.q } }); S.questions = await api("/api/questions"); renderNav(); renderLead(S.lead.id); });
onAction("lead-apply", async (el, e) => { await api(`/api/leads/${S.lead.id}/apply-answers`, { method: "POST" }); el.disabled = true; el.innerHTML = `<span class="spin"></span> Adding your answers and reworking the resume`; toast("Updating resume", "Adding your answers to your profile, then rewriting this resume with them (a minute or two)."); });
onAction("resume-recheck", async (el, e) => { if (S.dirty && S.editorOpts) await S.editorOpts.save($("#ed").value); recheckResume(S.lead.id); });
onAction("toggle-dream", async (el, e) => { await api(`/api/leads/${S.lead.id}`, { method: "PATCH", body: { dream: S.lead.dream ? 0 : 1 } }); renderLead(S.lead.id); });
onChange(async (el) => {
  if (el.id === "rs-theme") {  // the resume layout menu
    const style = { ...(S.lead.package.resume_style || { max_pages: 1 }), theme: el.value };
    await api(`/api/leads/${S.lead.id}`, { method: "PATCH", body: { package: { resume_style: style } } });
    S.lead.package.resume_style = style;
    if (S.editorOpts) { S.editorOpts.theme = el.value; S.editorOpts.refresh(); }
    toast("Layout changed", `${el.value}: PDF and DOCX exports updated`); recheckResume(S.lead.id); return true;
  }
  if (el.dataset.act === "cstatus") {  // a contact's status on the lead's Contacts tab
    await api(`/api/leads/${S.lead.id}/contacts/${el.dataset.i}`, { method: "POST", body: { status: el.value } }); toast("Updated", "Contact status saved"); return true;
  }
});
