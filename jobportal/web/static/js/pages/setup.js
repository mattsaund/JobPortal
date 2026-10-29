/* The setup page shown until setup is done: Continue with ChatGPT, import a resume, check the standard questions, build
   the profile. These are the only things JobPortal learns about you from, along with questions it asks later. */
"use strict";

const SETUP_STEPS = [["chatgpt", "Continue with ChatGPT"], ["resume", "Import your resume"], ["answers", "Answer the standard questions"], ["build", "Build your profile"]];
function missingRequired(answers) {
  const req = (S.onb && S.onb.required) || [], labels = {};
  ((S.onb && S.onb.questions) || []).forEach((sec) => sec.fields.forEach((f) => (labels[f.id] = f.label)));
  return req.filter((k) => { const v = answers[k]; return Array.isArray(v) ? !v.length : !String(v ?? "").trim(); }).map((k) => labels[k] || k);
}
function resumeDropzone(accept, label) {
  return `<div class="dropzone" id="rz" style="margin-top:12px"><div class="dz-big"><i class=i-upload></i> ${esc(label)}</div>
    <div class="muted small">Drop a PDF, Word (DOCX), ODT, RTF, Markdown or text file here, or choose one. Scanned (image-only) PDFs can't be read.</div>
    <div class="row" style="justify-content:center;margin-top:10px;gap:8px"><label class="btn">Choose file<input type="file" id="rz-pick" accept="${esc(accept || "")}" hidden></label>
      <button class="btn ghost" data-rz="paste">Paste the text instead</button></div>
    <div id="rz-paste" style="display:none;margin-top:10px;text-align:left"><textarea id="rz-text" rows="10" style="width:100%" placeholder="Paste your whole resume here"></textarea>
      <div class="row" style="justify-content:flex-end;margin-top:8px"><button class="btn primary" data-rz="paste-go">Use this text</button></div></div>
    <label class="row small" style="justify-content:center;margin-top:10px;gap:8px">${toggle(`id="rz-lib"`, true)}Also keep an editable copy in my resume collection</label>
    <div class="small mono muted" id="rz-log" style="margin-top:8px"></div></div>`;
}
function wireResumeDropzone(root, onDone, opts = {}) {
  const z = $("#rz", root); if (!z) return;
  const log = (html) => ($("#rz-log", root).innerHTML = html);
  const send = async (fn) => {
    log(`<span class="spin"></span> Reading your resume. About 30 seconds.`);
    z.classList.add("busy");
    try { const r = await fn(); log(""); await onDone(r); }
    catch (err) { log(""); toast("Couldn't read that resume", err.message, "error"); }
    z.classList.remove("busy");
  };
  const lib = () => ($("#rz-lib", root).checked ? 1 : 0);
  const upload = (f) => send(async () => {
    const r = await fetch(`/api/onboarding/resume?filename=${encodeURIComponent(f.name)}&save_to_library=${lib()}&prefill=${opts.prefill === false ? 0 : 1}`, { method: "PUT", body: f });
    const j = await r.json(); if (!r.ok) throw new Error(j.detail || r.statusText); return j;
  });
  const over = (on) => (e) => { e.preventDefault(); z.classList.toggle("over", on); };
  ["dragenter", "dragover"].forEach((ev) => z.addEventListener(ev, over(true)));
  ["dragleave", "dragend"].forEach((ev) => z.addEventListener(ev, over(false)));
  z.addEventListener("drop", (e) => { e.preventDefault(); z.classList.remove("over"); const f = [...(e.dataTransfer.files || [])].find((x) => !JUNK.test(x.name)); if (f) upload(f); });
  $("#rz-pick", root).onchange = (e) => { const f = e.target.files[0]; if (f) upload(f); };
  z.addEventListener("click", (e) => {
    const t = e.target.closest("[data-rz]"); if (!t) return;
    if (t.dataset.rz === "paste") $("#rz-paste", root).style.display = "";
    if (t.dataset.rz === "paste-go") {
      const text = $("#rz-text", root).value.trim(); if (text.length < 80) { toast("That's too short", "Paste the whole resume.", "error"); return; }
      send(() => api("/api/onboarding/resume-text", { method: "POST", body: { text, save_to_library: !!lib(), prefill: opts.prefill !== false } }));
    }
  });
}

// One renderer for the standard questions, used by setup and by Profile, Standard answers.
function answersForm(sections, values, prefill) {
  const v = values || {}, pf = prefill || {};
  const fromResume = (id) => pf[id] != null && JSON.stringify(pf[id]) === JSON.stringify(v[id]) ? `<span class="chip violet pf" title="Filled in from your resume. Check it.">from resume</span>` : "";
  const field = (f) => {
    const val = v[f.id], req = f.required ? `<b class="req" title="required">*</b>` : "", help = f.help ? `<div class="small muted">${esc(f.help)}</div>` : "";
    const head = `<span>${esc(f.label)}${req}${fromResume(f.id)}</span>`;
    if (f.type === "select") return `<label class="f">${head}<select data-qf="${f.id}"><option value="">Choose one</option>${f.options.map(([k, l]) => `<option value="${esc(k)}" ${val === k ? "selected" : ""}>${esc(l)}</option>`).join("")}</select>${help}</label>`;
    if (f.type === "multi") return `<div class="f qmulti" style="grid-column:1/-1"><label class="f">${head}</label><div class="row" style="gap:6px;margin-top:4px">${f.options.map(([k, l]) => `<label class="chk ${(val || []).includes(k) ? "on" : ""}"><input type="checkbox" data-qm="${f.id}" value="${esc(k)}" ${(val || []).includes(k) ? "checked" : ""}>${esc(l)}</label>`).join("")}</div>${help}</div>`;
    if (f.type === "list") return `<label class="f">${head}<textarea data-ql="${f.id}" rows="4" placeholder="${esc(f.placeholder || "")}">${esc((val || []).join("\n"))}</textarea>${help}</label>`;
    if (f.type === "textarea") return `<label class="f" style="grid-column:1/-1">${head}<textarea data-qf="${f.id}" rows="${f.id === "writing_sample" ? 8 : 3}" placeholder="${esc(f.placeholder || "")}">${esc(val || "")}</textarea>${help}</label>`;
    return `<label class="f">${head}<input type="${f.type === "url" ? "url" : f.type === "email" ? "email" : f.type === "tel" ? "tel" : "text"}" data-qf="${f.id}" value="${esc(val || "")}" placeholder="${esc(f.placeholder || "")}">${help}</label>`;
  };
  return sections.map((sec) => `<div class="card qsec" style="margin-bottom:14px"><h3>${esc(sec.title)}</h3>${sec.help ? `<p class="muted small" style="margin-top:-4px">${esc(sec.help)}</p>` : ""}
    <div class="grid3">${sec.fields.map(field).join("")}</div></div>`).join("");
}
function readAnswersForm(root) {
  const out = {};
  $$("[data-qf]", root).forEach((el) => (out[el.dataset.qf] = el.value.trim()));
  $$("[data-ql]", root).forEach((el) => (out[el.dataset.ql] = el.value.split("\n").map((x) => x.trim()).filter(Boolean)));
  $$("[data-qm]", root).forEach((el) => { out[el.dataset.qm] = out[el.dataset.qm] || []; if (el.checked) out[el.dataset.qm].push(el.value); });
  return out;
}
document.addEventListener("change", (e) => { if (e.target.dataset && e.target.dataset.qm != null) e.target.closest(".chk")?.classList.toggle("on", e.target.checked); });

async function renderSetup(step) {
  const d = (S.onb = await api("/api/onboarding"));
  S.pstatus = d.status; renderProfilePill();
  if (step) S.setupStep = step;
  try { S.state.ai = await api("/api/ai/status"); renderAI(); } catch (_) {}
  if (!S.setupStep || !SETUP_STEPS.some(([k]) => k === S.setupStep)) S.setupStep = !aiReady() ? "chatgpt" : !d.resume ? "resume" : !d.answers_saved ? "answers" : "build";
  const cur = S.setupStep;
  const done = { chatgpt: aiReady(), resume: !!d.resume, answers: d.answers_saved, build: d.profile_built };
  main.innerHTML = `<div class="page setup"><div class="page-h"><h1>Set up JobPortal</h1><span class="sub">Four steps. Your data stays on this computer. Each AI task sends OpenAI only what it needs, through your ChatGPT sign-in.</span></div>
    <div class="stepper">${SETUP_STEPS.map(([k, l], i) => `<a class="step ${k === cur ? "on" : ""} ${done[k] ? "done" : ""}" data-step="${k}"><span class="num">${done[k] && k !== cur ? "<i class=i-check></i>" : i + 1}</span>${esc(l)}</a>`).join("")}</div>
    <div id="setup-body"></div></div>`;
  $$(".stepper .step").forEach((a) => (a.onclick = () => { if (["chatgpt", "resume"].includes(a.dataset.step) || d.resume) renderSetup(a.dataset.step); }));
  const body = $("#setup-body");
  if (cur === "chatgpt") {
    const a = S.state.ai || {};
    body.innerHTML = `<div class="card"><h3>Step 1: connect ChatGPT</h3>
      <p style="margin-top:0">JobPortal's AI runs on your own ChatGPT plan. Sign in once, and it reads your resume, scores jobs and writes your applications. It needs a ChatGPT Go, Plus or Pro plan.</p>
      <p class="muted small">ChatGPT shares only your name and email with JobPortal. Usage counts against your plan, and you can set a weekly cap for JobPortal in ChatGPT settings.</p>
      ${a.signed_in ? `<div class="banner"><div><i class=i-check></i> Signed in as <b>${esc(a.email || a.name || "your account")}</b>.</div><span class="spacer"></span><button class="btn primary sm" data-go="resume">Continue</button></div>`
        : `<button class="btn primary" data-act="ai-signin">Continue with ChatGPT</button>`}</div>`;
    body.querySelector("[data-go]")?.addEventListener("click", () => renderSetup("resume"));
  } else if (cur === "resume") {
    body.innerHTML = `<div class="card"><h3>Step 2: your resume</h3>
      <p style="margin-top:0">JobPortal reads your resume to learn your experience, projects and skills. It's a source of facts, not a template: every resume it makes for a job is written fresh.</p>
      ${d.resume ? `<div class="banner"><div><i class=i-doc></i> Using <b>${esc(d.resume.filename)}</b>, imported ${esc(fmtTs(d.resume.imported_at))}.</div><span class="spacer"></span><button class="btn primary sm" data-go="answers">Keep it and continue</button></div>` : ""}
      ${resumeDropzone(d.accept, d.resume ? "Or import a different resume" : "Drop your resume here")}</div>`;
    body.querySelector("[data-go]")?.addEventListener("click", () => renderSetup("answers"));
    wireResumeDropzone(body, async (r) => {
      S.prefill = r.prefill || {};
      toast("Resume read", r.prefill && r.prefill._error ? "Couldn't pre-fill the questions with AI, so fill them in yourself." : "The standard questions are pre-filled from it. Check them.");
      renderSetup("answers");
    });
  } else if (cur === "answers") {
    const pre = { ...(d.prefill || {}), ...(S.prefill || {}) };
    const vals = { ...d.answers };
    if (!d.answers_saved) for (const [k, v] of Object.entries(pre)) { if (k.startsWith("_")) continue; const have = vals[k]; if (have == null || (Array.isArray(have) ? !have.length : !String(have).trim())) vals[k] = v; }
    body.innerHTML = `<div class="card" style="margin-bottom:14px"><h3>Step 3: the standard questions</h3><p style="margin:0">These are the questions almost every application asks. Answer them once: JobPortal uses them to search (roles, levels, locations), to fill in every Application kit, and to keep your resumes truthful. Fields marked "from resume" were read from your resume, so check them.</p></div>
      <div id="qform">${answersForm(d.questions, vals, d.answers_saved ? {} : pre)}</div>
      <div class="sticky-save"><button class="btn ghost" data-go="resume">Back</button><span class="spacer"></span><span class="muted small" id="setup-state"></span><button class="btn primary" id="setup-save">Save and build my profile</button></div>`;
    body.querySelector("[data-go]").onclick = () => renderSetup("resume");
    $("#qform").addEventListener("input", () => (S.dirty = true));
    $("#setup-save").onclick = async (e) => {
      const answers = readAnswersForm($("#qform")), miss = missingRequired(answers);
      if (miss.length) { toast("A few answers are required", miss.join(", "), "error"); return; }
      e.currentTarget.disabled = true; $("#setup-state").innerHTML = `<span class="spin"></span> Saving`;
      try {
        const r = await api("/api/onboarding/answers", { method: "PUT", body: { answers, build: true } });
        S.dirty = false; S.pstatus = r.status; renderProfilePill(); renderSetup("build");
      } catch (err) { toast("Couldn't save your answers", err.message, "error"); e.currentTarget.disabled = false; $("#setup-state").textContent = ""; }
    };
  } else {
    body.innerHTML = `<div class="card" id="build-card"></div>`;
    setupStatusChanged();
  }
}
function setupStatusChanged() {
  const card = $("#build-card"); if (!card) return;
  const st = S.pstatus || {};
  if (st.busy || (!st.built && !st.error)) {
    card.innerHTML = `<h3>Step 4: building your profile</h3><div class="row" style="margin:10px 0"><span class="spin"></span><b>${esc(st.phase || "Starting")}</b></div>
      <p class="muted" style="margin:0">The AI is reading your resume and answers and writing your profile: your experience record, skills inventory, interview stories and search plan. This usually takes 1 to 4 minutes. You can leave this page; it keeps going.</p>`;
  } else if (st.error) {
    card.innerHTML = `<h3>Step 4: building your profile</h3><div class="banner bad"><div><b>The build failed:</b> ${esc(st.error)}</div></div>
      <p class="muted small">Check that you're signed in with ChatGPT on a Go, Plus or Pro plan, then try again.</p>
      <div class="row"><button class="btn primary" data-act="profile-build">Try again</button><button class="btn ghost" data-act="setup-step" data-step="answers">Back to the questions</button></div>`;
  } else {
    card.innerHTML = `<h3>Step 4: done</h3><div class="row" style="margin:6px 0 12px"><i class=i-check style="color:var(--good)"></i><b>Your profile is ready.</b></div>
      <p style="margin-top:0">Run your first search: JobPortal sweeps job boards, company career sites, social media and comment threads, scores every job against your profile, and writes a tailored application package for the best ones.</p>
      ${st.open_questions ? `<div class="banner accent"><div><b>${st.open_questions} question${st.open_questions > 1 ? "s" : ""}</b> would make your applications stronger. Answer them any time; your profile updates on its own.</div><span class="spacer"></span><a class="btn sm" href="#/profile/questions">Answer now</a></div>` : ""}
      <div class="row" style="margin-top:12px"><a class="btn primary" href="#/leads">Go to Leads and run a search</a><a class="btn" href="#/profile">Review my profile</a><a class="btn ghost" href="#/settings">Settings</a></div>`;
  }
}

// ---------------------------------------------------------------- actions
onAction("setup-step", async (el, e) => { renderSetup(el.dataset.step); });
