/* resumes.js: Settings, Resumes (#/settings/resumes, #/settings/resumes/12 for one resume, #/settings/resumes/playbook for
   the playbook). A list of your saved resumes, and beside it the selected one with its details, editor and preview.
   Import them (files, whole folders or pasted text) or save ones you like from a lead, edit them, download them, and use
   one on any lead, as it is or tailored by the AI. Saved resumes never change your profile: tailored resumes are still
   written fresh from it. The last row of the list opens the recruiter review switch and the resume playbook every
   tailored resume follows.
   APIs: GET /api/library, POST /api/library, PUT /api/library/import, GET/PUT/DELETE /api/library/{id},
   POST /api/library/{id}/revise, POST /api/library/{id}/apply/{lead id}, GET /api/library/{id}/export/{pdf|docx|md},
   GET /api/leads (the lead picker), GET /api/resume-playbook, and GET and PUT /api/settings (the playbook and the recruiter
   review switch). */
"use strict";

// The file types the collection imports, the same as SUPPORTED in documents/extract.py on the server. (Old .doc, .pages
// and .wps files need LibreOffice installed.) LIB_EXT checks a file name; LIB_ACCEPT is the file picker's filter.
const LIB_TYPES = ["pdf", "docx", "doc", "odt", "rtf", "pages", "wps", "md", "markdown", "txt"];
const LIB_EXT = new RegExp(`\\.(${LIB_TYPES.join("|")})$`, "i");
const LIB_ACCEPT = LIB_TYPES.map((type) => "." + type).join(",");

// What the import is doing, for the line under the list's buttons.
let libProgress = "";
// Your saved resumes (GET /api/library), as last loaded. The search box and the tags filter these in the page.
let libItems = [];
// What the right side shows: a resume's id, "playbook", or null when there's nothing to show.
let libShown = null;

// Where a saved resume came from: imported, or saved from a lead. link = with a link to that lead.
const libSource = (item, link = false) => (item.source === "imported" ? "Imported" : item.source === "builder" ? "Resume builder"
  : item.lead_id ? (link ? `From <a href="#/leads/${item.lead_id}">a lead</a>` : "From a lead") : "Saved");

// The section: the list is drawn once and kept (searching and picking a tag only show and hide its rows), and the right
// side follows the address. Without a resume in the address, it opens the first one.
async function renderLibrary(box, id) {
  const items = await api("/api/library");
  if (S.route[1] !== "resumes") return;
  libItems = items;
  if (!$(".lib", box)) {
    box.innerHTML = `<div class="lib"><aside class="lib-list" data-drop="library" aria-label="Resumes">
        <div class="toolbar"><label class="button primary small">${icon("upload")}Import<input class="sr-only" type="file" multiple accept="${LIB_ACCEPT}" aria-label="Import resumes"></label>
          <button class="button outline small" type="button" data-act="lib-paste">Paste</button><span class="spacer"></span><span class="muted" id="lib-count"></span></div>
        <div class="lib-find"><input type="search" id="lib-q" placeholder="Search" aria-label="Search resumes" value="${esc(S.libQ)}"><div class="lib-tags" id="lib-tags"></div></div>
        <p class="upload-note lib-progress" id="lib-progress">${libProgress}</p>
        <div class="rows lib-rows" id="lib-items"></div>
        <a class="row lib-playbook-link" href="#/settings/resumes/playbook" id="lib-playbook-link"><span class="row-main"><span class="row-title">Playbook</span></span>${icon("book")}</a>
      </aside><section class="lib-detail" id="lib-detail"></section></div>`;
    $("#lib-q").addEventListener("input", (e) => {
      S.libQ = e.target.value;
      filterLibrary();
    });
  }
  libShown = id === "playbook" ? "playbook" : +id || items[0]?.id || null;
  drawLibraryItems();
  const detail = $("#lib-detail");
  setSaver();
  if (libShown === "playbook") await renderPlaybook(detail);
  else if (libShown) await renderLibraryItem(detail, libShown);
  else detail.innerHTML = `<div class="empty fill"><p>No resumes yet</p></div>`;
}

// Loads the collection again and redraws its rows (after an import). The search and the tag stay as they are. When the
// right side was empty, it opens the first resume.
async function reloadLibraryItems() {
  const items = await api("/api/library");
  if (!$("#lib-items")) return;
  libItems = items;
  if (!libShown && items.length) {
    await renderLibrary($("#settings-body"), S.route[2]);
    return;
  }
  drawLibraryItems();
}

// The rows, one per saved resume. Then filterLibrary() shows the ones that match.
function drawLibraryItems() {
  const box = $("#lib-items");
  if (!box) return;
  const row = (it) => {
    const on = it.id === libShown;
    return `<a class="row${on ? " active" : ""}" data-id="${it.id}" href="#/settings/resumes/${it.id}"${on ? ' aria-current="true"' : ""}>
      <span class="row-main"><span class="row-title">${esc(it.name)}</span><span class="row-sub">${[libSource(it), ago(it.updated_at)].filter(Boolean).join(", ")}</span>
        ${(it.tags || []).length ? `<span class="tags">${it.tags.map((t) => `<span class="tag">${esc(t)}</span>`).join("")}</span>` : ""}</span></a>`;
  };
  setHtml(box, libItems.map(row).join(""));
  const playbook = $("#lib-playbook-link");
  playbook.classList.toggle("active", libShown === "playbook");
  if (libShown === "playbook") playbook.setAttribute("aria-current", "true");
  else playbook.removeAttribute("aria-current");
  filterLibrary();
}

// Shows the rows that match the search box and the tag, and redraws the tag buttons and the count. A tag that no resume
// has any more stops filtering.
function filterLibrary() {
  const tags = [...new Set(libItems.flatMap((x) => x.tags || []))].sort();
  if (S.libTag && !tags.includes(S.libTag)) S.libTag = "";
  const search = S.libQ.toLowerCase();
  let shown = 0;
  for (const it of libItems) {
    const match = (!S.libTag || (it.tags || []).includes(S.libTag))
      && (!search || `${it.name} ${(it.tags || []).join(" ")} ${it.notes} ${it.preview}`.toLowerCase().includes(search));
    const row = $(`#lib-items [data-id="${it.id}"]`);
    if (row) row.hidden = !match;
    shown += match ? 1 : 0;
  }
  setHtml($("#lib-tags"), tags.map((t) => `<button class="choice${t === S.libTag ? " active" : ""}" type="button" data-act="lib-tag" data-tag="${esc(t)}"`
    + ` aria-pressed="${t === S.libTag}">${esc(t)}</button>`).join(""));
  $("#lib-count").textContent = shown === libItems.length ? `${libItems.length}` : `${shown} of ${libItems.length}`;
}

// How tailored resumes are written: the recruiter review switch and the resume playbook, filling the right side. The
// Save bar saves what changed of the two.
let playbookEdited = false;
async function renderPlaybook(box) {
  let playbook;
  try {
    [, playbook] = await Promise.all([loadCfg(), api("/api/resume-playbook")]);
  } catch (err) {
    box.innerHTML = loadError(err);
    return;
  }
  if (!box.isConnected || libShown !== "playbook") return;
  playbookEdited = false;
  box.innerHTML = `<div class="lib-playbook" data-cfg>
    <div class="toolbar"><b>Playbook</b><span class="tag" id="playbook-state">${playbook.custom ? "Custom" : "Default"}</span><span class="spacer"></span>
      <button class="button outline small" type="button" data-act="playbook-reset">${icon("undo")}Reset</button></div>
    <div class="lib-review">${cfgOptSwitch("run.resume_review", "Recruiter review", S.cfg.run.resume_review !== false, "One more AI request per resume")}</div>
    <textarea id="playbook" aria-label="Playbook">${esc(playbook.text)}</textarea></div>`;
  $("#playbook").addEventListener("input", () => {
    playbookEdited = true;
    S.dirty = true;
  });
  setSaver(savePlaybookView);
}

// The Save bar on the playbook.
async function savePlaybookView() {
  if (playbookEdited) {
    await savePlaybook($("#playbook").value);
    playbookEdited = false;
    $("#playbook-state").textContent = "Custom";
  }
  if (S.cfgDirty) await saveCfg();
  else toast("Saved");
}

// Saves only the playbook: the settings as they are now, with the new playbook text.
async function savePlaybook(text) {
  const cfg = await api("/api/settings");
  cfg.resume_playbook = text;
  await api("/api/settings", { method: "PUT", body: cfg });
  if (S.cfg) S.cfg.resume_playbook = text;
  S.dirty = false;
}

// Imports resume files one at a time (PUT /api/library/import), showing progress in the list. names gives a name per
// file (from the paste dialog). Returns the last item imported.
async function importResumes(files, names = []) {
  files = files.filter((f) => LIB_EXT.test(f.name));
  if (!files.length) {
    toast("Unsupported file type", "PDF, Word, ODT, RTF, Pages, Markdown or text", "error");
    return null;
  }
  let imported = 0, last = null;
  const show = (html) => {
    libProgress = html;
    const line = $("#lib-progress");
    if (line) line.innerHTML = html;
  };
  for (const [i, file] of files.entries()) {
    show(`${spinner()} ${i + 1} of ${files.length}: ${esc(file.name)}`);
    try {
      last = await uploadFile(`/api/library/import?filename=${encodeURIComponent(file.name)}&name=${encodeURIComponent(names[i] || "")}`, file);
      imported++;
    } catch (err) {
      toast("Import failed", `${file.name}: ${err.message}`, "error");
    }
  }
  show("");
  if (imported) toast(imported === 1 ? "Resume imported" : `${imported} resumes imported`, imported === 1 ? last.name : "");
  if (imported && S.route[1] === "resumes") await reloadLibraryItems().catch(() => {});  // the new rows; failing, they show next visit
  return last;
}

// The paste dialog: the pasted resume is imported like a text file, with the name you give it.
function libPasteDialog() {
  openDialog(`<h2>Paste resume</h2>
    <label class="field"><span class="field-label">Name</span><input type="text" id="lib-paste-name" placeholder="Teaching jobs"></label>
    <label class="field"><span class="field-label">Resume</span><textarea id="lib-paste-text" rows="14"></textarea></label>
    <div class="dialog-actions"><button class="button outline" type="button" data-act="close-dialog">Cancel</button>
      <button class="button primary" type="button" data-act="lib-paste-go">Import</button></div>`);
}

// One saved resume: its actions, its name, tags, layout, page limit and notes (each saves as you change it), and the
// editor filling the rest.
async function renderLibraryItem(box, id) {
  let it;
  try {
    it = await api(`/api/library/${id}`);
  } catch (_) {
    if (libShown === id) box.innerHTML = `<div class="empty fill"><h3>Resume not found</h3></div>`;
    return;
  }
  if (!box.isConnected || libShown !== id) return;  // you picked another one while this one loaded
  const style = { theme: "classic", max_pages: 1, ...(it.style || {}) };
  const made = [libSource(it, true), it.original_file ? esc(it.original_file) : "", esc(fmtDate((it.created_at || "").slice(0, 10)))].filter(Boolean).join(", ");
  box.innerHTML = `<div class="toolbar lib-actions"><span class="lib-made">${made}</span><span class="muted" id="lib-state" role="status"></span><span class="spacer"></span>
      <button class="button primary small" type="button" data-act="lib-use" data-id="${it.id}">Use resume</button>
      <button class="button outline small" type="button" data-act="lib-dup" data-id="${it.id}">${icon("copy")}Duplicate</button>
      <button class="button danger small" type="button" data-act="lib-del" data-id="${it.id}">${icon("trash")}Delete</button></div>
    <div class="lib-fields"><label class="field"><span class="field-label">Name</span><input type="text" data-lib="name" value="${esc(it.name)}"></label>
      <label class="field"><span class="field-label">Tags</span><input type="text" data-lib="tags" value="${esc((it.tags || []).join(", "))}" placeholder="teaching, favorite"></label>
      <label class="field"><span class="field-label">Notes</span><input type="text" data-lib="notes" value="${esc(it.notes || "")}"></label>
      <label class="field"><span class="field-label">Layout</span><select data-lib="theme">${selectOptions(RESUME_THEMES.map((t) => [t, humanize(t)]), style.theme)}</select></label>
      <label class="field"><span class="field-label">Pages</span><select data-lib="max_pages">${selectOptions([[1, "One page"], [2, "Two pages"]], +style.max_pages)}</select></label></div>
    <div class="lib-editor" id="lib-editor"></div>`;
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
  // Saves the details half a second after you stop changing them. They're read from the form as you change them, so
  // the save still goes out when you leave the page within that half second. A new layout redraws the preview, and a
  // new page limit resizes it; the text in the editor stays as it is (it may have edits you haven't saved).
  const field = (name) => $(`[data-lib="${name}"]`, box);
  const details = () => ({
    name: field("name").value.trim() || it.name, tags: field("tags").value.split(",").map((x) => x.trim()).filter(Boolean),
    notes: field("notes").value, style: { ...style, theme: field("theme").value, max_pages: +field("max_pages").value },
  });
  const saveDetails = debounce(async (body) => {
    try {
      await api(`/api/library/${it.id}`, { method: "PUT", body });
    } catch (err) {
      state.textContent = "Not saved";
      toast("Couldn't save details", err.message, "error");
      return;
    }
    Object.assign(style, body.style);
    const listed = libItems.find((x) => x.id === it.id);  // the list shows the name and the tags
    if (listed) {
      Object.assign(listed, { name: body.name, tags: body.tags, notes: body.notes, style: body.style });
      drawLibraryItems();
    }
    if (!state.isConnected) return;  // you've moved on: the save is done, there's nothing to show
    state.textContent = "Saved";
    if (editor.theme !== style.theme) {
      editor.theme = style.theme;
      editor.refresh();
    }
    if (editor.maxPages !== style.max_pages) {
      editor.maxPages = style.max_pages;
      editor.setPages(style.max_pages);
    }
  }, 500);
  $$("[data-lib]", box).forEach((el) => el.addEventListener(el.tagName === "SELECT" ? "change" : "input", () => {
    state.textContent = "Saving";
    saveDetails(details());
  }));
  mountEditor($("#lib-editor"), editor);
}

// Use resume, from your resumes: find a lead, then use the resume as it is or have the AI tailor it to the job
// (POST /api/library/{id}/apply/{lead id}). Then that lead's Resume tab opens.
async function libUseDialog(itemId) {
  const it = await api(`/api/library/${itemId}`);
  const dialog = openDialog(`<h2>Use ${esc(it.name)}</h2>
    <input type="search" id="pick-q" placeholder="Company or job title" aria-label="Search leads">
    <div class="pick-list" id="pick-list"><p class="loading">${spinner()} Loading</p></div>
    <label class="switch-row">${toggle(`id="pick-backup"`, false)}<span>Save current resume first</span></label>
    <p class="pick-warn">Replaces the lead's current resume.</p>
    <div class="dialog-actions"><button class="button outline" type="button" data-act="close-dialog">Cancel</button>
      <button class="button outline" type="button" data-act="lib-apply" data-tailor="0" disabled>As is</button>
      <button class="button primary" type="button" data-act="lib-apply" data-tailor="1" disabled>${icon("sparkle")}Tailor</button></div>`);
  const pick = dialog.jp.pick = { item: itemId, lead: null, choosing: "lead" };
  // Without a search, your Ready leads; with one, matches from all your leads. Only the newest search draws (typing
  // sends several). The lead you picked stays picked when the new list has it; when it doesn't, it's unpicked, so the
  // buttons never use the resume on a lead you can't see.
  let newest = 0;
  const load = async (search) => {
    const ticket = ++newest, list = $("#pick-list", dialog);
    let d;
    try {
      d = await api(`/api/leads?tab=${search ? "all" : "ready"}&q=${encodeURIComponent(search || "")}&limit=60`);
    } catch (err) {
      if (ticket === newest) list.innerHTML = `<p class="pick-none">${esc(err.message)}</p>`;
      return;
    }
    if (ticket !== newest) return;
    const leads = d.leads.filter((l) => l.app_status !== "trashed");
    if (pick.lead && !leads.some((l) => l.id === pick.lead)) {
      pick.lead = null;
      $$("[data-act=lib-apply]", dialog).forEach((button) => (button.disabled = true));
    }
    list.innerHTML = leads.map((l) => `<label class="pick-row"><input type="radio" name="pick" value="${l.id}"${l.id === pick.lead ? " checked" : ""}>
        <span class="pick-score">${esc(l.score ?? "-")}</span><span class="pick-text"><b>${esc(l.company)}</b> ${esc(l.title)}</span>
        <small>${l.has_resume ? "Has resume" : "No resume"}</small></label>`).join("")
      || `<p class="pick-none">No leads</p>`;
  };
  $("#pick-q", dialog).addEventListener("input", debounce((e) => load(e.target.value.trim()), 250));
  load("");
}

// The same from a lead's Resume tab: pick one of your resumes for this lead.
async function leadPickSavedDialog(lead) {
  const items = await api("/api/library");
  if (!items.length) {
    toast("No saved resumes");
    return;
  }
  const row = (it) => `<label class="pick-row"><input type="radio" name="pick" value="${it.id}"><span class="pick-text"><b>${esc(it.name)}</b>
      ${(it.tags || []).map((t) => `<span class="tag">${esc(t)}</span>`).join("")}</span><small>${ago(it.updated_at)}</small></label>`;
  const dialog = openDialog(`<h2>Saved resumes</h2>
    <div class="pick-list">${items.map(row).join("")}</div>
    ${lead.resume_md ? `<label class="switch-row">${toggle(`id="pick-backup"`, false)}<span>Save current resume first</span></label>
      <p class="pick-warn">Replaces the lead's current resume.</p>` : ""}
    <div class="dialog-actions"><button class="button outline" type="button" data-act="close-dialog">Cancel</button>
      <button class="button outline" type="button" data-act="lib-apply" data-tailor="0" disabled>As is</button>
      <button class="button primary" type="button" data-act="lib-apply" data-tailor="1" disabled>${icon("sparkle")}Tailor</button></div>`);
  dialog.jp.pick = { item: null, lead: lead.id, choosing: "item" };
}

// Goes to an address in Resumes. The first resume shows at the bare address, so going there may not change the hash:
// then it's drawn here.
function libGo(hash) {
  if (location.hash === hash) renderSettings("resumes", S.route[2]);
  else location.hash = hash;
}

// ---------------------------------------------------------------- actions
onDrop("library", (files) => importResumes(files));
onAction("lib-use", (el) => libUseDialog(+el.dataset.id));
onAction("lib-tag", (el) => {  // a tag filters your resumes; clicking it again clears the filter
  S.libTag = S.libTag === el.dataset.tag ? "" : el.dataset.tag;
  filterLibrary();
});
onAction("lib-paste", () => libPasteDialog());
onAction("lib-paste-go", (el) => {
  const dialog = el.closest("dialog");
  const text = $("#lib-paste-text", dialog).value.trim(), name = $("#lib-paste-name", dialog).value.trim();
  if (text.length < 80) {
    toast("Too short", "", "error");
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
  libGo(`#/settings/resumes/${copied.id}`);
});
onAction("lib-del", async (el) => {
  if (!confirm("Delete this resume?")) return;
  await api(`/api/library/${el.dataset.id}`, { method: "DELETE" });
  S.dirty = false;
  toast("Deleted");
  libShown = null;
  libGo("#/settings/resumes");
});
onAction("lib-apply", async (el) => {  // As is, or Tailor, in either dialog
  const dialog = el.closest("dialog"), pick = dialog.jp.pick, tailor = el.dataset.tailor === "1", label = el.innerHTML;
  if (!pick.item || !pick.lead) return;
  // Used on the lead on screen, its new resume replaces the editor: unsaved edits there would be lost, so ask first.
  const onScreen = S.leadView?.id === pick.lead;
  if (onScreen && S.dirty && !confirm("Discard your unsaved edits?")) return;
  el.disabled = true;
  el.innerHTML = `${spinner()} ${tailor ? "Tailoring" : "Applying"}`;
  try {
    const r = await api(`/api/library/${pick.item}/apply/${pick.lead}`, { method: "POST", body: { tailor, backup: !!$("#pick-backup", dialog)?.checked } });
    closeDialog(dialog);
    toast(tailor ? "Resume tailored" : "Resume applied", `Resume check ${r.check ?? "-"}`, "", pick.lead);
    if (onScreen && S.leadView?.id === pick.lead) {  // used from the lead itself: show its new resume
      S.dirty = false;
      S.leadView.tab = "resume";
      refreshLeadDetails();
    } else {
      location.hash = `#/leads/${pick.lead}/resume`;
    }
  } catch (err) {
    el.disabled = false;
    el.innerHTML = label;
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
onAction("playbook-reset", async () => {
  if (!confirm("Reset playbook to default?")) return;
  await savePlaybook("");  // an empty playbook means "use the researched one"
  $("#playbook").value = (await api("/api/resume-playbook")).text;
  playbookEdited = false;
  $("#playbook-state").textContent = "Default";
  syncSaveBar();
  toast("Playbook reset");
});
