/* resumes.js: Settings, Resumes (#/settings/resumes, or #/settings/resumes/12 to edit one). Your saved resumes: import
   them (files, whole folders or pasted text) or save ones you like from a lead, edit them, download them, and use one on
   any lead, as it is or tailored by the AI. Saved resumes never change your profile: tailored resumes are still written
   fresh from it. Below the collection: the recruiter review and the resume playbook every tailored resume follows.
   APIs: GET /api/library, POST /api/library, PUT /api/library/import, GET/PUT/DELETE /api/library/{id},
   POST /api/library/{id}/revise, POST /api/library/{id}/apply/{lead id}, GET /api/library/{id}/export/{pdf|docx|md},
   GET /api/library/{id}/html (the thumbnails), GET /api/resume-playbook and PUT /api/settings. */
"use strict";

// The file types the collection imports, the same as SUPPORTED in documents/extract.py on the server. (Old .doc, .pages
// and .wps files need LibreOffice installed.) LIB_EXT checks a file name; LIB_ACCEPT is the file picker's filter.
const LIB_TYPES = ["pdf", "docx", "doc", "odt", "rtf", "pages", "wps", "md", "markdown", "txt"];
const LIB_EXT = new RegExp(`\\.(${LIB_TYPES.join("|")})$`, "i");
const LIB_ACCEPT = LIB_TYPES.map((type) => "." + type).join(",");

// What the import is doing, for the line under the drop zone.
let libProgress = "";

// Where a saved resume came from: imported, or saved from a lead (with a link to it).
const libSource = (item) => (item.source === "imported" ? "Imported" : item.lead_id ? `Saved from <a href="#/leads/${item.lead_id}">a lead</a>` : "Saved");

// The collection, or one resume's editor.
async function renderLibrary(box, id) {
  if (id) return renderLibraryItem(box, +id);
  const items = await api("/api/library");
  if (S.route[1] !== "resumes" || S.route[2]) return;
  const tags = [...new Set(items.flatMap((x) => x.tags || []))].sort();
  if (S.libTag && !tags.includes(S.libTag)) S.libTag = "";  // that tag is gone
  const search = S.libQ.toLowerCase();
  const shown = items.filter((x) => (!S.libTag || (x.tags || []).includes(S.libTag))
    && (!search || `${x.name} ${(x.tags || []).join(" ")} ${x.notes} ${x.preview}`.toLowerCase().includes(search)));
  const card = (it) => `<article class="resume-card">
      <a class="resume-thumb" href="#/settings/resumes/${it.id}" aria-label="Edit ${esc(it.name)}"><iframe loading="lazy" src="/api/library/${it.id}/html?v=${encodeURIComponent(it.updated_at)}" sandbox tabindex="-1" title="${esc(it.name)}"></iframe></a>
      <div class="resume-body"><a class="resume-name" href="#/settings/resumes/${it.id}">${esc(it.name)}</a>
        <small>${libSource(it)}, ${esc(humanize(it.style?.theme || "classic"))} layout, ${ago(it.updated_at)}</small>
        ${(it.tags || []).length ? `<div class="tags">${it.tags.map((t) => `<span class="tag">${esc(t)}</span>`).join("")}</div>` : ""}
        <div class="button-row"><button class="button primary small" type="button" data-act="lib-use" data-id="${it.id}">Use on a lead</button>
          <button class="button outline small" type="button" data-act="lib-dl" data-url="/api/library/${it.id}/export/pdf">${icon("download")}PDF</button>
          <button class="button outline small" type="button" data-act="lib-dl" data-url="/api/library/${it.id}/export/docx">${icon("download")}Word</button></div></div></article>`;
  box.innerHTML = `<div class="stack">
    <section class="panel"><h2>Your saved resumes</h2>
      <p class="panel-note">Import resumes, or save ones you like from a lead, then use them on any job. Tailored resumes are still written fresh
        from your profile; nothing here is used as a template.</p>
      <label class="upload-zone" data-drop="library">${icon("upload")}<strong>Drop resumes or folders here</strong>
        <small>PDF, Word, ODT, RTF, Pages, Markdown or text. Each one becomes an editable copy, wording kept exactly.</small>
        <span class="button light">Browse files</span><input type="file" multiple accept="${LIB_ACCEPT}" aria-label="Choose resumes"></label>
      <p class="upload-note" id="lib-progress">${libProgress}</p>
      <div class="block-actions"><button class="text-button" type="button" data-act="lib-paste">Or paste a resume's text ${icon("arrow")}</button></div>
      <div class="list-controls"><label class="control"><span>Find</span><input type="search" id="lib-q" placeholder="Names, tags, notes" value="${esc(S.libQ)}"></label>
        <div class="filters">${tags.map((t) => `<button class="chip${t === S.libTag ? " active" : ""}" type="button" data-act="lib-tag" data-tag="${esc(t)}" aria-pressed="${t === S.libTag}">${esc(t)}</button>`).join("")}</div>
        <span class="list-count">${shown.length} of ${items.length}</span></div>
      ${items.length ? `<div class="resume-grid">${shown.map(card).join("")}</div>`
        : `<div class="empty-state"><h3>No saved resumes yet</h3><p>Drop a resume above, or open a lead's Resume tab and choose Save to my resumes.</p></div>`}</section>
    <section class="panel" id="playbook-card" data-cfg></section></div>`;
  $("#lib-q").addEventListener("input", debounce((e) => {
    S.libQ = e.target.value;
    renderLibrary(box).then(() => {  // the tab redraws, so put the cursor back at the end of the search box
      const input = $("#lib-q");
      input.focus();
      input.setSelectionRange(input.value.length, input.value.length);
    });
  }, 250));
  renderPlaybookCard();
}

// How tailored resumes are written: the recruiter review switch and the resume playbook. The playbook saves on its own.
async function renderPlaybookCard() {
  const [, playbook] = await Promise.all([loadCfg(), api("/api/resume-playbook")]);
  const card = $("#playbook-card");
  if (!card) return;
  card.innerHTML = `<h2>How tailored resumes are written</h2>
    ${cfgSwitch("run.resume_review", "A recruiter review of every tailored resume: it fixes what the check finds and sharpens each line (one more AI request each)", S.cfg.run.resume_review !== false)}
    <div class="block-actions"><button class="button outline small" type="button" data-act="save-cfg">Save</button></div>
    <label class="field"><span class="field-label">Resume playbook: the researched practices the AI follows (rules, layouts, and kinds of resumes)</span>
      <textarea id="playbook" rows="14">${esc(playbook.text)}</textarea></label>
    <div class="block-actions"><span class="muted-note" id="playbook-state">${playbook.custom ? "Your own playbook" : "The researched playbook (October 2026)"}</span><span class="spacer"></span>
      <button class="button text" type="button" data-act="playbook-reset">Back to the researched one</button>
      <button class="button primary" type="button" data-act="playbook-save">Save playbook</button></div>`;
  $("#playbook").addEventListener("input", () => (S.dirty = true));
}

// Saves only the playbook: the settings as they are now, with the new playbook text.
async function savePlaybook(text) {
  const cfg = await api("/api/settings");
  cfg.resume_playbook = text;
  await api("/api/settings", { method: "PUT", body: cfg });
  if (S.cfg) S.cfg.resume_playbook = text;
  S.dirty = false;
}

// Imports resume files one at a time (PUT /api/library/import), showing progress under the drop zone. names gives a
// name per file (from the paste dialog). Returns the last item imported.
async function importResumes(files, names = []) {
  files = files.filter((f) => LIB_EXT.test(f.name));
  if (!files.length) {
    toast("Nothing to import", "Use PDF, Word, ODT, RTF, Pages, Markdown or text files.", "error");
    return null;
  }
  let imported = 0, last = null;
  const show = (html) => {
    libProgress = html;
    const line = $("#lib-progress");
    if (line) line.innerHTML = html;
  };
  for (const [i, file] of files.entries()) {
    show(`${spinner()} Importing ${i + 1} of ${files.length}: ${esc(file.name)} (reading and converting, usually under a minute)`);
    try {
      last = await uploadFile(`/api/library/import?filename=${encodeURIComponent(file.name)}&name=${encodeURIComponent(names[i] || "")}`, file);
      imported++;
    } catch (err) {
      toast("Couldn't import it", `${file.name}: ${err.message}`, "error");
    }
  }
  show(`${imported} of ${files.length} imported.`);
  if (imported) toast("Added to your resumes", imported === 1 ? last.name : `${imported} resumes`);
  if (S.route[1] === "resumes" && !S.route[2]) renderLibrary($("#settings-body"));
  return last;
}

// The paste dialog: the pasted resume is imported like a text file, with the name you give it.
function libPasteDialog() {
  openDialog(`<h2>Paste a resume</h2><p>It's turned into an editable copy, wording kept exactly.</p>
    <label class="field"><span class="field-label">Name it</span><input type="text" id="lib-paste-name" placeholder="For example: General, or Teaching jobs"></label>
    <label class="field"><span class="field-label">The resume</span><textarea id="lib-paste-text" rows="14"></textarea></label>
    <div class="dialog-actions"><button class="button outline" type="button" data-act="close-dialog">Cancel</button>
      <button class="button primary" type="button" data-act="lib-paste-go">Import</button></div>`, { eyebrow: "YOUR RESUMES" });
}

// One saved resume: its name, tags, layout, page limit and notes (each saves as you change it), and the editor.
async function renderLibraryItem(box, id) {
  let it;
  try {
    it = await api(`/api/library/${id}`);
  } catch (_) {
    box.innerHTML = `<div class="empty-state"><h3>That resume is gone</h3><p><a href="#/settings/resumes">Back to your resumes</a></p></div>`;
    return;
  }
  const style = { theme: "classic", max_pages: 1, ...(it.style || {}) };
  box.innerHTML = `<div class="stack"><section class="panel">
      <div class="panel-heading"><a class="text-button" href="#/settings/resumes">${icon("back")}All resumes</a>
        <div class="heading-actions"><button class="button primary" type="button" data-act="lib-use" data-id="${it.id}">Use on a lead</button>
          <button class="button outline" type="button" data-act="lib-dup" data-id="${it.id}">${icon("copy")}Duplicate</button>
          <button class="button danger" type="button" data-act="lib-del" data-id="${it.id}">${icon("trash")}Delete</button></div></div>
      <p class="panel-note">${libSource(it)}${it.original_file ? `, from ${esc(it.original_file)}` : ""}, created ${esc(fmtDate((it.created_at || "").slice(0, 10)))}.</p>
      <div class="form-grid three"><label class="field"><span class="field-label">Name</span><input type="text" data-lib="name" value="${esc(it.name)}"></label>
        <label class="field"><span class="field-label">Tags (separated by commas)</span><input type="text" data-lib="tags" value="${esc((it.tags || []).join(", "))}" placeholder="For example: teaching, favorite"></label>
        <label class="field"><span class="field-label">Notes</span><input type="text" data-lib="notes" value="${esc(it.notes || "")}" placeholder="When to use this one"></label>
        <label class="field"><span class="field-label">Layout</span><select data-lib="theme">${selectOptions(RESUME_THEMES.map((t) => [t, humanize(t)]), style.theme)}</select></label>
        <label class="field"><span class="field-label">Pages</span><select data-lib="max_pages">${selectOptions([[1, "One page"], [2, "Up to two pages"]], +style.max_pages)}</select></label></div>
      <p class="muted-note" id="lib-state"></p></section>
    <section class="panel" id="lib-editor"></section></div>`;
  const state = $("#lib-state");
  const editor = {
    doc: "resume",
    text: it.md,
    theme: style.theme,
    maxPages: style.max_pages,
    files: ["resume.pdf", "resume.docx", "resume.md"],
    fileHref: (file) => `/api/library/${it.id}/export/${file.split(".").pop()}`,
    reviseUrl: `/api/library/${it.id}/revise`,
    save: async (value) => {
      await api(`/api/library/${it.id}`, { method: "PUT", body: { md: value } });
      it.md = value;
    },
  };
  // Saves the details half a second after you stop changing them. A new layout redraws the preview; a new page limit
  // redraws the page.
  const saveDetails = debounce(async () => {
    const tags = $('[data-lib="tags"]').value.split(",").map((x) => x.trim()).filter(Boolean);
    style.theme = $('[data-lib="theme"]').value;
    style.max_pages = +$('[data-lib="max_pages"]').value;
    await api(`/api/library/${it.id}`, { method: "PUT", body: { name: $('[data-lib="name"]').value.trim() || it.name, tags, notes: $('[data-lib="notes"]').value, style } });
    state.textContent = "Saved";
    if (editor.theme !== style.theme) {
      editor.theme = style.theme;
      editor.refresh?.();
    }
    if (editor.maxPages !== style.max_pages) renderLibraryItem(box, id);
  }, 500);
  $$("[data-lib]", box).forEach((el) => el.addEventListener(el.tagName === "SELECT" ? "change" : "input", () => {
    state.textContent = "Saving";
    saveDetails();
  }));
  mountEditor($("#lib-editor"), editor);
}

// "Use on a lead" from your resumes: find a lead, then use the resume as it is or have the AI tailor it to the job
// (POST /api/library/{id}/apply/{lead id}). Then that lead's Resume tab opens.
async function libUseDialog(itemId) {
  const it = await api(`/api/library/${itemId}`);
  const dialog = openDialog(`<h2>Use "${esc(it.name)}" on a lead</h2>
    <label class="control wide"><span>Find</span><input type="search" id="pick-q" placeholder="A company or a job title"></label>
    <div class="pick-list" id="pick-list"><p class="muted-note">${spinner()} Loading</p></div>
    <label class="switch-row">${toggle(`id="pick-backup"`, false)}<span>Save the lead's current resume to my resumes first</span></label>
    <p class="panel-note">The lead's resume is replaced. "Back to the AI's version" in its editor still brings back the one JobPortal wrote.</p>
    <div class="dialog-actions"><button class="button outline" type="button" data-act="close-dialog">Cancel</button>
      <button class="button outline" type="button" data-act="lib-apply" data-tailor="0" disabled>Use it as it is</button>
      <button class="button primary" type="button" data-act="lib-apply" data-tailor="1" disabled title="The AI angles it toward the job, then it gets the usual check and review">${icon("sparkle")}Tailor it to the job</button></div>`,
    { eyebrow: "YOUR RESUMES" });
  dialog.jp.pick = { item: itemId, lead: null, choosing: "lead" };
  // Without a search, your Ready leads; with one, matches from all your leads.
  const load = async (search) => {
    const d = await api(`/api/leads?tab=${search ? "all" : "ready"}&q=${encodeURIComponent(search || "")}&limit=60`);
    $("#pick-list", dialog).innerHTML = d.leads.filter((l) => l.app_status !== "trashed").map((l) => `<label class="pick-row"><input type="radio" name="pick" value="${l.id}">
        <span class="pick-score">${l.score ?? "-"}</span><span class="pick-text"><b>${esc(l.company)}</b> ${esc(l.title)}</span>
        <small>${l.has_resume ? "Has a resume" : "No resume yet"}</small></label>`).join("")
      || `<p class="muted-note">No matching leads${search ? "" : " under Ready. Search to find any lead"}.</p>`;
  };
  $("#pick-q", dialog).addEventListener("input", debounce((e) => load(e.target.value.trim()), 250));
  load("");
}

// The same from a lead's Resume tab ("Use a saved resume"): pick one of your resumes for this lead.
async function leadPickSavedDialog(lead) {
  const items = await api("/api/library");
  if (!items.length) {
    toast("You have no saved resumes", "Import some in Settings, Resumes, or save this one first.");
    return;
  }
  const row = (it) => `<label class="pick-row"><input type="radio" name="pick" value="${it.id}"><span class="pick-text"><b>${esc(it.name)}</b>
      ${(it.tags || []).map((t) => `<span class="tag">${esc(t)}</span>`).join("")}</span><small>${ago(it.updated_at)}</small></label>`;
  const dialog = openDialog(`<h2>Use a saved resume for ${esc(lead.company)}</h2>
    <div class="pick-list">${items.map(row).join("")}</div>
    ${lead.resume_md ? `<label class="switch-row">${toggle(`id="pick-backup"`, false)}<span>Save this lead's current resume to my resumes first</span></label>` : ""}
    <div class="dialog-actions"><button class="button outline" type="button" data-act="close-dialog">Cancel</button>
      <button class="button outline" type="button" data-act="lib-apply" data-tailor="0" disabled>Use it as it is</button>
      <button class="button primary" type="button" data-act="lib-apply" data-tailor="1" disabled>${icon("sparkle")}Tailor it to this job</button></div>`,
    { eyebrow: "YOUR RESUMES" });
  dialog.jp.pick = { item: null, lead: lead.id, choosing: "item" };
}

// ---------------------------------------------------------------- actions
onDrop("library", (files) => importResumes(files));
onAction("lib-use", (el) => libUseDialog(+el.dataset.id));
onAction("lib-dl", (el) => openUrl(el.dataset.url));
onAction("lib-tag", (el) => {  // a tag filters your resumes; clicking it again clears the filter
  S.libTag = S.libTag === el.dataset.tag ? "" : el.dataset.tag;
  renderLibrary($("#settings-body"));
});
onAction("lib-paste", () => libPasteDialog());
onAction("lib-paste-go", (el) => {
  const dialog = el.closest("dialog");
  const text = $("#lib-paste-text", dialog).value.trim(), name = $("#lib-paste-name", dialog).value.trim();
  if (text.length < 80) {
    toast("That's too short", "Paste the whole resume.", "error");
    return;
  }
  closeDialog(dialog);
  const fileName = (name || "Pasted resume").replace(/[\\/:*?"<>|]/g, "-");  // characters file names can't have
  importResumes([new File([text], `${fileName}.txt`, { type: "text/plain" })], [name]);
});
onAction("lib-dup", async (el) => {
  const it = await api(`/api/library/${el.dataset.id}`);
  const body = { name: `${it.name} (copy)`, md: S.editor?.text() || it.md, style: it.style, tags: it.tags, notes: it.notes, source: it.source };
  const copied = await api("/api/library", { method: "POST", body });
  S.dirty = false;
  toast("Duplicated", copied.name);
  location.hash = `#/settings/resumes/${copied.id}`;
});
onAction("lib-del", async (el) => {
  if (!confirm("Delete this resume from your saved resumes?")) return;
  await api(`/api/library/${el.dataset.id}`, { method: "DELETE" });
  S.dirty = false;
  toast("Deleted");
  location.hash = "#/settings/resumes";
});
onAction("lib-apply", async (el) => {  // Use it as it is, or Tailor it, in either dialog
  const dialog = el.closest("dialog"), pick = dialog.jp.pick, tailor = el.dataset.tailor === "1";
  if (!pick.item || !pick.lead) return;
  el.disabled = true;
  el.innerHTML = `${spinner()} ${tailor ? "Tailoring" : "Applying"}`;
  try {
    const r = await api(`/api/library/${pick.item}/apply/${pick.lead}`, { method: "POST", body: { tailor, backup: !!$("#pick-backup", dialog)?.checked } });
    closeDialog(dialog);
    toast(tailor ? "Tailored and applied" : "Resume applied", `Resume check: ${r.check ?? "-"}${r.change_summary ? `. ${r.change_summary.slice(0, 140)}` : ""}`, "", pick.lead);
    if (S.leadView?.id === pick.lead) {  // used from the lead itself: show its new resume
      S.leadView.tab = "resume";
      refreshLeadDetails();
    } else {
      location.hash = `#/leads/${pick.lead}/resume`;
    }
  } catch (err) {
    el.disabled = false;
    el.innerHTML = tailor ? `${icon("sparkle")}Tailor it to the job` : "Use it as it is";
    throw err;
  }
});
onChange((el) => {  // picking a lead or a resume in either dialog
  const dialog = el.closest("dialog");
  if (el.name !== "pick" || !dialog?.jp.pick) return false;
  dialog.jp.pick[dialog.jp.pick.choosing] = +el.value;
  $$("[data-act=lib-apply]", dialog).forEach((button) => (button.disabled = false));
  return true;
});
onAction("playbook-save", async () => {
  await savePlaybook($("#playbook").value);
  $("#playbook-state").textContent = "Your own playbook, saved";
});
onAction("playbook-reset", async () => {
  if (!confirm("Replace your playbook with the researched one?")) return;
  await savePlaybook("");  // an empty playbook means "use the researched one"
  $("#playbook").value = (await api("/api/resume-playbook")).text;
  $("#playbook-state").textContent = "The researched playbook";
});
