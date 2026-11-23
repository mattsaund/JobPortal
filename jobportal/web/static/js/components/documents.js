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

// The drop zone for documents. big = at the top of Home's questions before there's a resume.
function documentsDropZone(big) {
  return `<label class="upload-zone${big ? " big" : ""}" data-drop="documents">${icon("upload")}
      <strong>${big ? "Resume and documents" : "Add files"}</strong>
      ${big ? `<span class="button primary">Browse</span>` : ""}
      <input type="file" multiple accept="${esc(S.onboarding?.accept || "")}" aria-label="Choose documents"></label>
    <p class="upload-note" data-doc-progress>${uploadNote()}</p>`;
}

// What the upload is doing, for the line under every drop zone.
function uploadNote() {
  if (!docUpload) return "";
  if (docUpload.reading) return `${spinner()} Reading resume`;
  return `${spinner()} ${docUpload.done + 1} of ${docUpload.total}: ${esc(docUpload.name)}`;
}
const showUploadNote = () => $$("[data-doc-progress]").forEach((el) => (el.innerHTML = uploadNote()));

// The Documents section: the drop zone and the list, main resume first. Paste text shows only until there's a main resume.
function documentsPanel() {
  return `<div class="sect-head"><h2>Documents</h2></div>
    ${documentsDropZone(false)}
    <button class="text-button doc-paste" type="button" data-act="paste-resume" data-doc-paste${S.onboarding?.resume ? " hidden" : ""}>Paste text</button>
    <div data-doc-list>${documentsList()}</div>`;
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
  const main = resume ? `<li class="doc main">${icon("file")}<div class="doc-body">
      <span class="doc-name" title="${esc(resume.filename)}">${esc(resume.filename)}</span><span class="doc-sub">Main resume</span></div>
      ${docMenu([["resume-read", "View text", ""], S.onboarding.resume_from_builder && ["open-builder", "Edit answers", ""],
        ["resume-replace", "Replace", ""], ["paste-resume", "Paste text", ""]])}</li>` : "";
  if (!main && !docs.length) return "";
  return `<ul class="doc-list">${main}${docs.map(documentRow).join("")}</ul>`;
}

// A document's actions, behind one small menu button. Each item is [action, label, extra attributes].
function docMenu(items) {
  const buttons = items.filter(Boolean).map(([act, label, attrs]) => `<button type="button" role="menuitem" data-act="${act}" ${attrs}>${label}</button>`).join("");
  return `<div class="menu-wrap"><button class="icon-button" type="button" data-act="menu" aria-haspopup="menu" aria-expanded="false" aria-label="Actions" title="Actions">${icon("more")}</button>
    <div class="menu" role="menu" hidden>${buttons}</div></div>`;
}

// One document. parsed (what the AI read: its kind, title, issuer, dates, skills and a summary) and parsing (being read
// now) may be missing.
function documentRow(doc) {
  const p = doc.parsed || {};
  const kind = p.kind || doc.kind || "document";
  const dates = p.expires ? `Expires ${fmtDate(p.expires)}` : p.issued ? fmtDate(p.issued) : "";
  const sub = [p.title || humanize(kind), p.issuer, dates].filter(Boolean).join(", ");
  const resumeLike = ["resume", "document"].includes(kind);
  const id = `data-id="${esc(doc.id)}"`;
  return `<li class="doc">${icon(kind === "certificate" || kind === "license" ? "cert" : "file")}<div class="doc-body">
      <span class="doc-name" title="${esc(doc.name)}">${esc(doc.name)}</span>
      ${doc.parsing ? `<span class="doc-reading">${spinner()} Reading</span>` : `<span class="doc-sub" title="${esc(p.summary || sub)}">${esc(sub)}</span>`}</div>
      ${docMenu([resumeLike && ["doc-main", "Make main", id], ["doc-parse", "Read again", id], ["doc-remove", "Remove", `${id} data-name="${esc(doc.name)}"`]])}</li>`;
}

// Redraws every document list on the page (Home has one in its panel). A focused button gets the focus back.
const renderDocumentLists = () => $$("[data-doc-list]").forEach((el) => {
  const focus = focusKey(el);
  el.innerHTML = documentsList();
  refocus(el, focus);
});

// Whether the server can read a file, by its extension: the types in S.onboarding.accept (".pdf,.docx,...", from
// SUPPORTED in documents/extract.py). A name without one is read as text there, so it passes too.
function readable(file) {
  const dot = file.name.lastIndexOf(".");
  const ext = dot > 0 ? file.name.slice(dot).toLowerCase() : "";
  const types = (S.onboarding?.accept || "").toLowerCase().split(",").map((type) => type.trim()).filter(Boolean);
  return !ext || !types.length || types.includes(ext);
}

// "a.pdf, b.pdf, c.pdf and 4 more": the start of a long list of names, for a toast.
const someNames = (names) => names.slice(0, 3).join(", ") + (names.length > 3 ? ` and ${names.length - 3} more` : "");

// Sends the files one at a time. Then, with no main resume yet, the server makes the best resume among the documents the
// main one, and its answers fill in your questions. Summary toasts say what happened. Files the server can't read (a
// folder's photos, a spreadsheet) are skipped before they're sent, and the ones that fail are grouped by why, so a big
// folder makes a few short toasts instead of one per file.
async function addDocuments(files) {
  if (docUpload) {
    toast("Still uploading");
    return;
  }
  const skipped = files.filter((file) => !readable(file)).map((file) => file.name);
  files = files.filter(readable);
  if (skipped.length) toast(`Skipped ${plural(skipped.length, "file")}`, someNames(skipped));
  if (!files.length) return;
  const added = [], same = [], failed = new Map();  // failed: the server's message, then the names it was for
  const fail = (message, name) => failed.set(message, [...(failed.get(message) || []), name]);
  for (const [i, file] of files.entries()) {
    docUpload = { done: i, total: files.length, name: file.name };
    showUploadNote();
    try {
      const reply = await uploadFile(`/api/profile/documents?filename=${encodeURIComponent(file.name)}`, file);
      (reply.duplicate ? same : added).push(reply);
    } catch (err) {
      fail(err.message, file.name);
    }
  }
  let picked = null;
  if (!S.onboarding?.resume && (added.length || same.length)) {
    docUpload = { reading: true };
    showUploadNote();
    try {
      picked = (await api("/api/profile/documents/auto-main", { method: "POST" })).picked;
    } catch (err) {
      fail(err.message, "Your resume");
    }
  }
  docUpload = null;
  showUploadNote();
  await reloadOnboarding();
  const said = [added.length && `${plural(added.length, "document")} added`, same.length && `${same.length} already there`].filter(Boolean).join(", ");
  if (picked) toast("Main resume", picked);
  else if (said) toast(said);
  if (!S.onboarding?.resume && !picked && (added.length || same.length)) toast("No resume found", "Make one document the main resume.");
  if (failed.size) {
    const count = [...failed.values()].reduce((sum, names) => sum + names.length, 0);
    toast(`Couldn't add ${plural(count, "file")}`, [...failed].map(([message, names]) => `${someNames(names)}: ${message}`).join(" "), "error");
  }
}

// Replaces the main resume with one file. Before your answers are saved, it fills in the empty ones again; after, your
// profile is rebuilt from it. Not while files are still going up: the batch would pick a main resume of its own.
async function replaceResume(file) {
  if (docUpload) {
    toast("Still uploading");
    return;
  }
  const answered = !!S.onboarding?.answers_saved;
  docUpload = { reading: true };
  showUploadNote();
  try {
    await uploadFile(`/api/onboarding/resume?filename=${encodeURIComponent(file.name)}&prefill=${answered ? 0 : 1}`, file);
    if (answered && S.profileStatus?.built) await api("/api/profile/build", { method: "POST" });
    toast("Resume replaced");
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
  const dialog = openDialog(`<h2>Paste resume</h2>
    <textarea id="paste-text" rows="14" aria-label="Resume text"></textarea>
    <div class="dialog-actions"><button class="button outline" type="button" data-act="close-dialog">Cancel</button>
      <button class="button primary" type="button" data-act="paste-resume-go">Use text</button></div>`);
  $("#paste-text", dialog).focus();
}

// ---------------------------------------------------------------- actions
onDrop("documents", (files) => addDocuments(files));
onAction("resume-replace", () => pickOneFile(S.onboarding?.accept || "", (file) => {
  replaceResume(file).catch((err) => toast("Couldn't replace your resume", err.message, "error"));
}));
onAction("paste-resume", () => pasteResumeDialog());
onAction("resume-read", () => {  // the text read from the main resume (the server sends the first 4,000 characters)
  const ob = S.onboarding;
  openDialog(`<h2>${esc(ob.resume.filename)}</h2><pre class="posting-text">${esc(ob.resume_preview || "")}</pre>`, { wide: true });
});
onAction("paste-resume-go", async (el) => {
  const text = $("#paste-text").value.trim();
  if (text.length < 80) {
    toast("Too short", "", "error");
    return;
  }
  el.disabled = true;
  el.innerHTML = `${spinner()} Reading`;
  try {
    const answered = !!S.onboarding?.answers_saved;
    await api("/api/onboarding/resume-text", { method: "POST", body: { text, prefill: !answered } });
    if (answered && S.profileStatus?.built) await api("/api/profile/build", { method: "POST" });
    closeDialog(el.closest("dialog"));
    toast("Resume added");
    await reloadOnboarding();
  } catch (err) {
    el.disabled = false;
    el.textContent = "Use text";
    throw err;
  }
});
onAction("doc-main", async (el) => {
  el.disabled = true;
  try {
    await api(`/api/profile/documents/${el.dataset.id}/main`, { method: "POST" });
  } catch (err) {
    el.disabled = false;
    throw err;
  }
  toast("Main resume changed");
  await reloadOnboarding();
});
onAction("doc-parse", async (el) => {
  try {
    await api(`/api/profile/documents/${el.dataset.id}/parse`, { method: "POST" });
    toast("Reading again");
  } catch (err) {
    if (err.status !== 404 || err.message !== "Not Found") throw err;
    toast("Not available", "", "error");  // an older server
  }
});
onAction("doc-remove", async (el) => {
  if (!confirm(`Remove ${el.dataset.name} from your documents?`)) return;
  await api(`/api/profile/documents/${el.dataset.id}`, { method: "DELETE" });
  S.documents = S.documents.filter((doc) => doc.id !== el.dataset.id);
  homeDocumentsChanged();
  toast("Removed");
});
