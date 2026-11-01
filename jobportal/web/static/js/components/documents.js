/* documents.js: your documents, on Home. The main resume and every extra document: certificates, licenses, cover
   letters, awards, transcripts and other resumes. Drop many files or whole folders at once, or pick them; each one is
   read on the server and goes into your next profile build, so the profile (and the jobs it finds) covers everything
   you've done. Without a main resume yet, JobPortal makes the best resume among them the main one. You can also paste
   your resume's text, replace the main resume with one file, see the text read from it, make another document the main
   resume, have one read again, or remove it.
   APIs: PUT /api/profile/documents?filename= (one file as the body), POST /api/profile/documents/auto-main,
   POST /api/profile/documents/{id}/main and /parse, DELETE /api/profile/documents/{id}, POST /api/onboarding/resume-text,
   PUT /api/onboarding/resume?filename= and POST /api/profile/build. A "documents" event carries the new list (live.js). */
"use strict";

// The upload in progress: { done, total, name } while files go up, { reading: true } while the main resume is read.
let docUpload = null;

// The drop zone for documents. big = the card at the top of Home's questions before there's a resume.
function documentsDropZone(big) {
  return `<label class="upload-zone${big ? " big" : ""}" data-drop="documents">${icon("upload")}
      <strong>${big ? "Drop your resume and other documents here" : "Drop files or folders here"}</strong>
      <small>Your resume, plus certificates, licenses, cover letters, awards and transcripts. PDF, Word, ODT, RTF or text.</small>
      <span class="button light${big ? "" : " full"}">Browse files</span>
      <input type="file" multiple accept="${esc(S.onboarding?.accept || "")}" aria-label="Choose documents"></label>
    <p class="upload-note" data-doc-progress>${uploadNote()}</p>`;
}

// What the upload is doing, for the line under every drop zone.
function uploadNote() {
  if (!docUpload) return "";
  if (docUpload.reading) return `${spinner()} Reading your resume. About 30 seconds.`;
  return `${spinner()} Adding ${docUpload.done + 1} of ${docUpload.total}: ${esc(docUpload.name)}`;
}
const showUploadNote = () => $$("[data-doc-progress]").forEach((el) => (el.innerHTML = uploadNote()));

// The "Your documents" panel: the drop zone and the list, main resume first. "Or paste your resume's text" shows only
// until there's a main resume.
function documentsPanel() {
  return `<div class="tool-heading"><span class="tool-icon blue">${icon("file")}</span>
      <div><h2>Your documents</h2><p>Everything here goes into your profile.</p></div></div>
    ${documentsDropZone(false)}
    <div data-doc-list>${documentsList()}</div>
    <button class="text-button" type="button" data-act="paste-resume" data-doc-paste${S.onboarding?.resume ? " hidden" : ""}>Or paste your resume's text ${icon("arrow")}</button>`;
}

// Draws the panel into el the first time, and after that only its list and the paste button. The drop zone stays in
// the page: a live update while its file picker is open would otherwise drop the files you pick.
function renderDocumentsPanel(el) {
  if (!el) return;
  if (!$("[data-doc-list]", el)) {
    el.innerHTML = documentsPanel();
    return;
  }
  renderDocumentLists();
  $("[data-doc-paste]", el).hidden = !!S.onboarding?.resume;
}

// The list: the main resume, then each document with what kind it is and what was read from it.
function documentsList() {
  const resume = S.onboarding?.resume, docs = S.documents || [];
  const main = resume ? `<li class="doc main"><span class="doc-icon">${icon("file")}</span><div class="doc-body">
      <div class="doc-name"><strong title="${esc(resume.filename)}">${esc(resume.filename)}</strong><span class="tag green">MAIN RESUME</span></div>
      <small>Added ${esc(fmtTs(resume.imported_at))}</small>
      <div class="doc-actions"><button class="text-button" type="button" data-act="resume-read">What it read</button>
        <button class="text-button" type="button" data-act="resume-replace">Replace</button>
        <button class="text-button" type="button" data-act="paste-resume">Paste text instead</button></div></div></li>` : "";
  if (!main && !docs.length) return `<p class="muted-note">Nothing yet. Start with your resume.</p>`;
  return `<ul class="doc-list">${main}${docs.map(documentRow).join("")}</ul>`;
}

// One document. parsed (what the AI read: its kind, title, issuer, dates, skills and a summary) and parsing (being read
// now) may be missing.
function documentRow(doc) {
  const p = doc.parsed || {};
  const kind = p.kind || doc.kind || "document";
  const dates = [p.issued && `Issued ${fmtDate(p.issued)}`, p.expires && `Expires ${fmtDate(p.expires)}`].filter(Boolean).join(", ");
  const title = p.title ? `<div class="doc-title">${esc(p.title)}${p.issuer ? `<span>, ${esc(p.issuer)}</span>` : ""}</div>` : "";
  const skills = (p.skills || []).length ? `<div class="tags">${p.skills.slice(0, 8).map((s) => `<span class="tag">${esc(s)}</span>`).join("")}</div>` : "";
  const resumeLike = ["resume", "document"].includes(kind);
  return `<li class="doc"><span class="doc-icon">${icon(kind === "certificate" || kind === "license" ? "cert" : "file")}</span><div class="doc-body">
      <div class="doc-name"><strong title="${esc(doc.name)}">${esc(doc.name)}</strong><span class="tag">${esc(kind.toUpperCase())}</span></div>
      ${title}${dates ? `<small>${esc(dates)}</small>` : ""}${p.summary ? `<p>${esc(p.summary)}</p>` : ""}${skills}
      ${doc.parsing ? `<small class="doc-reading">${spinner()} Reading it</small>` : ""}
      <div class="doc-actions">${resumeLike ? `<button class="text-button" type="button" data-act="doc-main" data-id="${esc(doc.id)}">Use as main resume</button>` : ""}
        <button class="text-button" type="button" data-act="doc-parse" data-id="${esc(doc.id)}">Read again</button>
        <button class="text-button danger" type="button" data-act="doc-remove" data-id="${esc(doc.id)}" data-name="${esc(doc.name)}">Remove</button></div></div></li>`;
}

// Redraws every document list on the page (Home has one in its panel). A focused button gets the focus back.
const renderDocumentLists = () => $$("[data-doc-list]").forEach((el) => {
  const focus = focusKey(el);
  el.innerHTML = documentsList();
  refocus(el, focus);
});

// Sends the files one at a time. Then, with no main resume yet, the server makes the best resume among the documents the
// main one, and its answers fill in your questions. A summary toast says what happened.
async function addDocuments(files) {
  if (docUpload) {
    toast("Still adding the last ones", "Drop these again in a moment.");
    return;
  }
  const added = [], same = [], failed = [];
  for (const [i, file] of files.entries()) {
    docUpload = { done: i, total: files.length, name: file.name };
    showUploadNote();
    try {
      const reply = await uploadFile(`/api/profile/documents?filename=${encodeURIComponent(file.name)}`, file);
      (reply.duplicate ? same : added).push(reply);
    } catch (err) {
      failed.push(`${file.name}: ${err.message}`);
    }
  }
  let picked = null;
  if (!S.onboarding?.resume && (added.length || same.length)) {
    docUpload = { reading: true };
    showUploadNote();
    try {
      picked = (await api("/api/profile/documents/auto-main", { method: "POST" })).picked;
    } catch (err) {
      failed.push(`Your resume: ${err.message}`);
    }
  }
  docUpload = null;
  showUploadNote();
  await reloadOnboarding();
  const said = [added.length && `${plural(added.length, "document")} added`, same.length && `${same.length} already there`].filter(Boolean).join(", ");
  if (picked) toast("Your main resume", `Using ${picked}. ${said}. Change it any time.`);
  else if (said) toast("Documents added", `${said}. They go into your profile in about a minute.`);
  if (!S.onboarding?.resume && !picked && (added.length || same.length)) {
    toast("Which one is your resume?", "None of these looks like a resume. Pick one with Use as main resume, or paste the text.");
  }
  if (failed.length) toast(`Couldn't read ${plural(failed.length, "file")}`, failed.join(" "), "error");
}

// Replaces the main resume with one file. Before your answers are saved, it fills in the empty ones again; after, your
// profile is rebuilt from it.
async function replaceResume(file) {
  const answered = !!S.onboarding?.answers_saved;
  docUpload = { reading: true };
  showUploadNote();
  try {
    await uploadFile(`/api/onboarding/resume?filename=${encodeURIComponent(file.name)}&prefill=${answered ? 0 : 1}`, file);
    if (answered && S.profileStatus?.built) await api("/api/profile/build", { method: "POST" });
    toast("Resume replaced", answered ? "Your profile is being rebuilt with it." : "Your empty answers are filled in from it.");
  } finally {
    docUpload = null;
    showUploadNote();
  }
  await reloadOnboarding();
}

// Opens the system's file picker for one file and calls pick with it. The input isn't part of any list: a live update
// that redraws the list while the picker is open can't take your choice with it.
function pickOneFile(accept, pick) {
  const input = document.createElement("input");
  input.type = "file";
  input.accept = accept;
  input.hidden = true;
  input.addEventListener("change", () => {
    input.remove();
    if (input.files[0]) pick(input.files[0]);
  });
  document.body.appendChild(input);  // some browsers open a picker only for an input that's in the page
  input.click();
}

// The paste dialog: your resume as plain text, read like a file.
function pasteResumeDialog() {
  const dialog = openDialog(`<h2>Paste your resume</h2><p>Copy all the text from your resume and paste it here.</p>
    <textarea id="paste-text" rows="14" placeholder="Paste your whole resume" aria-label="Resume text"></textarea>
    <div class="dialog-actions"><button class="button outline" type="button" data-act="close-dialog">Cancel</button>
      <button class="button primary" type="button" data-act="paste-resume-go">Use this text</button></div>`, { eyebrow: "YOUR RESUME" });
  $("#paste-text", dialog).focus();
}

// ---------------------------------------------------------------- actions
onDrop("documents", (files) => addDocuments(files));
onAction("resume-replace", () => pickOneFile(S.onboarding?.accept || "", (file) => {
  replaceResume(file).catch((err) => toast("Couldn't replace your resume", err.message, "error"));
}));
onAction("paste-resume", () => pasteResumeDialog());
onAction("resume-read", () => {  // the text JobPortal read from the main resume (the server sends the first 4,000 characters)
  const ob = S.onboarding, more = (ob.resume?.chars || 0) > 4000 ? " The first 4,000 characters are shown." : "";
  openDialog(`<h2>${esc(ob.resume.filename)}</h2><p>The text JobPortal read from your resume. It's a source of facts, never a template:
      every tailored resume is written fresh.${more}</p><pre class="posting-text">${esc(ob.resume_preview || "")}</pre>`, { eyebrow: "YOUR MAIN RESUME", wide: true });
});
onAction("paste-resume-go", async (el) => {
  const text = $("#paste-text").value.trim();
  if (text.length < 80) {
    toast("That's too short", "Paste your whole resume.", "error");
    return;
  }
  el.disabled = true;
  el.innerHTML = `${spinner()} Reading it`;
  try {
    const answered = !!S.onboarding?.answers_saved;
    await api("/api/onboarding/resume-text", { method: "POST", body: { text, prefill: !answered } });
    if (answered && S.profileStatus?.built) await api("/api/profile/build", { method: "POST" });
    closeDialog(el.closest("dialog"));
    toast("Resume read", answered ? "Your profile is being rebuilt with it." : "Your empty answers are filled in from it.");
    await reloadOnboarding();
  } catch (err) {
    el.disabled = false;
    el.textContent = "Use this text";
    throw err;
  }
});
onAction("doc-main", async (el) => {
  el.disabled = true;
  el.innerHTML = `${spinner()} Switching`;
  await api(`/api/profile/documents/${el.dataset.id}/main`, { method: "POST" });
  toast("Main resume changed", "Your old main resume stays in your documents.");
  await reloadOnboarding();
});
onAction("doc-parse", async (el) => {
  try {
    await api(`/api/profile/documents/${el.dataset.id}/parse`, { method: "POST" });
    toast("Reading it again", "What JobPortal reads from it shows up here in a moment.");
  } catch (err) {
    if (err.status !== 404 || err.message !== "Not Found") throw err;
    toast("Can't read it again yet", "This version of JobPortal doesn't do that yet.", "error");  // an older server
  }
});
onAction("doc-remove", async (el) => {
  if (!confirm(`Remove ${el.dataset.name} from your documents?`)) return;
  await api(`/api/profile/documents/${el.dataset.id}`, { method: "DELETE" });
  S.documents = S.documents.filter((doc) => doc.id !== el.dataset.id);
  homeDocumentsChanged();
  toast("Removed", "Your profile updates without it in about a minute.");
});
