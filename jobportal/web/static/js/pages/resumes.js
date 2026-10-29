/* resumes.js: the Resumes page, your resume collection. Import resumes (files, whole folders or pasted text) or save
   ones you like from a lead, edit them, download them, and use one on any lead (as it is, or tailored by the AI). The
   collection never changes your profile: tailored resumes are still written fresh from it.
   APIs: GET /api/library, POST /api/library, PUT /api/library/import, GET/PUT/DELETE /api/library/{id},
   POST /api/library/{id}/revise, POST /api/library/{id}/apply/{lead id}, GET /api/library/{id}/export/{pdf|docx|md}
   and GET /api/library/{id}/html (the thumbnails). */
"use strict";

// The file types the collection imports, the same as SUPPORTED in documents/extract.py on the server. (Old .doc, .pages
// and .wps files need LibreOffice installed.) LIB_EXT checks a file name; LIB_ACCEPT is the file picker's filter.
const LIB_TYPES = ["pdf", "docx", "doc", "odt", "rtf", "pages", "wps", "md", "markdown", "txt"];
const LIB_EXT = new RegExp(`\\.(${LIB_TYPES.join("|")})$`, "i");
const LIB_ACCEPT = LIB_TYPES.map((type) => "." + type).join(",");
const LIB_TYPES_TEXT = "PDF, DOCX, DOC, ODT, RTF, Pages, WPS, Markdown or text";

// Where a saved resume came from: imported, or saved from a lead (with a link to it).
const libSource = (item) => (item.source === "imported" ? "Imported" : item.lead_id ? `Saved from <a href="#/lead/${item.lead_id}">lead #${item.lead_id}</a>` : "Saved");

// The collection (#/resumes), or one resume's editor (#/resumes/12).
async function renderLibrary(id) {
  if (id) return renderLibraryItem(+id);
  const items = await api("/api/library");
  const tags = [...new Set(items.flatMap((x) => x.tags || []))].sort();
  if (S.libTag && !tags.includes(S.libTag)) S.libTag = "";  // that tag is gone
  const search = S.libQ.toLowerCase();
  const shown = items.filter((x) => (!S.libTag || (x.tags || []).includes(S.libTag))
    && (!search || `${x.name} ${(x.tags || []).join(" ")} ${x.notes} ${x.preview}`.toLowerCase().includes(search)));
  const card = (it) => `<div class="libcard" data-act="lib-open" data-id="${it.id}">
        <div class="thumb"><iframe loading="lazy" src="/api/library/${it.id}/html?v=${encodeURIComponent(it.updated_at)}" sandbox tabindex="-1" title="${esc(it.name)}"></iframe></div>
        <div class="lib-body"><b class="lib-name">${esc(it.name)}</b>
          <div class="small muted">${libSource(it)}, ${esc(it.style?.theme || "classic")}, ${ago(it.updated_at)}</div>
          ${(it.tags || []).length ? `<div class="row" style="gap:4px;margin-top:6px">${it.tags.map((t) => `<span class="chip">${esc(t)}</span>`).join("")}</div>` : ""}
          <div class="row" style="gap:6px">
            <button class="btn sm primary" data-act="lib-use" data-id="${it.id}">Use on a lead</button>
            <button class="btn sm" data-act="lib-dl" data-url="/api/library/${it.id}/export/pdf">${I.dl} PDF</button>
            <button class="btn sm" data-act="lib-dl" data-url="/api/library/${it.id}/export/docx">${I.dl} DOCX</button></div></div></div>`;
  main.innerHTML = `<div class="page"><div class="page-h"><h1>Resume collection</h1><span class="sub">Import resumes or save ones you like from a lead, then reuse them on any job.
      Tailored resumes are still written fresh from your profile; nothing here is used as a template.</span></div>
    <div class="dropzone" id="lib-drop" style="margin-bottom:14px"><div class="dz-big">Drop resumes here</div>
      <div class="muted small">${LIB_TYPES_TEXT}. Folders work too. Each one becomes an editable copy, wording kept exactly.</div>
      <div class="row" style="justify-content:center;margin-top:10px;gap:8px">
        <label class="btn">Choose files<input type="file" id="lib-pick" multiple accept="${LIB_ACCEPT}" hidden></label>
        <button class="btn" data-act="lib-paste">Paste text</button></div>
      <div class="small mono muted" id="lib-log" style="margin-top:8px">${esc(S.libLog)}</div></div>
    <div class="row" style="margin-bottom:12px;gap:8px"><input type="text" id="lib-q" placeholder="Search names, tags, notes" value="${esc(S.libQ)}" style="width:280px">
      ${tags.map((t) => `<button class="chip ${t === S.libTag ? "accent" : ""}" data-act="lib-tag" data-tag="${esc(t)}">${esc(t)}</button>`).join("")}
      <span class="spacer"></span><span class="muted small">${shown.length} of ${items.length}</span></div>
    ${items.length ? `<div class="libgrid">${shown.map(card).join("")}</div>`
      : `<div class="empty"><b>No saved resumes yet</b>Drop a resume above, or open any lead's Resume tab and click “Save to collection”.</div>`}</div>`;
  const zone = $("#lib-drop");
  const highlight = (on) => (e) => {
    e.preventDefault();
    zone.classList.toggle("over", on);
  };
  ["dragenter", "dragover"].forEach((name) => zone.addEventListener(name, highlight(true)));
  ["dragleave", "dragend"].forEach((name) => zone.addEventListener(name, highlight(false)));
  zone.addEventListener("drop", async (e) => {
    e.preventDefault();
    zone.classList.remove("over");
    // Entries can be folders: collect every file inside them. Without entries, take the dropped files as they are.
    const entries = [...(e.dataTransfer.items || [])].map((item) => item.webkitGetAsEntry && item.webkitGetAsEntry()).filter(Boolean);
    importResumes(entries.length ? await filesFromEntries(entries) : [...e.dataTransfer.files]);
  });
  $("#lib-pick").onchange = (e) => importResumes([...e.target.files]);
  $("#lib-q").addEventListener("input", debounce((e) => {
    S.libQ = e.target.value;
    renderLibrary().then(() => {  // the page redraws, so put the cursor back at the end of the search box
      const box = $("#lib-q");
      box.focus();
      box.setSelectionRange(box.value.length, box.value.length);
    });
  }, 250));
}

// Imports resume files one at a time (PUT /api/library/import), showing progress under the drop zone. names gives a
// name per file (from the paste dialog). Returns the last item imported.
async function importResumes(files, names = []) {
  files = files.filter((f) => !JUNK.test(f.name) && LIB_EXT.test(f.name));
  if (!files.length) {
    toast("Nothing to import", `Use ${LIB_TYPES_TEXT} files.`, "error");
    return;
  }
  let imported = 0, last = null;
  for (const [i, file] of files.entries()) {
    S.libLog = `importing ${i + 1}/${files.length}: ${file.name} (reading and converting, usually under a minute)`;
    const log = $("#lib-log");
    if (log) log.innerHTML = `<span class="spin"></span> ${esc(S.libLog)}`;
    try {
      last = await uploadFile(`/api/library/import?filename=${encodeURIComponent(file.name)}&name=${encodeURIComponent(names[i] || "")}`, file);
      imported++;
    } catch (err) {
      toast("Import failed", `${file.name}: ${err.message}`, "error");
    }
  }
  S.libLog = `${imported} of ${files.length} imported`;
  if (imported) toast("Added to your collection", imported === 1 ? last.name : `${imported} resumes`);
  if (S.route[0] === "resumes" && !S.route[1]) renderLibrary();
  return last;
}

// The "Paste text" dialog: the pasted resume is imported like a .txt file with the name you give it.
function libPasteModal() {
  modal(`<h2>Paste a resume</h2><p class="muted small">Paste the text of a resume. It's converted to the editable format with the wording kept exactly.</p>
    <input type="text" id="lp-name" placeholder="Name it (e.g. General, data roles)" style="width:100%;margin-bottom:8px">
    <textarea id="lp-text" rows="14" style="width:100%" placeholder="Paste here"></textarea>
    <div class="row" style="margin-top:12px;justify-content:flex-end;gap:8px"><button class="btn ghost" onclick="closeModal()">Cancel</button><button class="btn primary" id="lp-go">Import</button></div>`);
  $("#lp-go").onclick = async () => {
    const text = $("#lp-text").value.trim(), name = $("#lp-name").value.trim();
    if (text.length < 80) {
      toast("Too short", "Paste the whole resume.", "error");
      return;
    }
    closeModal();
    const safeName = (name || "Pasted resume").replace(/[\\/:*?"<>|]/g, "-");  // characters file names can't have
    importResumes([new File([text], `${safeName}.txt`, { type: "text/plain" })], [name]);
  };
}

// One saved resume: its name, tags, layout, page limit and notes (each saves as you change it), and the editor.
async function renderLibraryItem(id) {
  let it;
  try {
    it = await api(`/api/library/${id}`);
  } catch (_) {
    main.innerHTML = `<div class="page"><div class="empty"><b>That resume is gone</b><a href="#/resumes">Back to the collection</a></div></div>`;
    return;
  }
  const style = { theme: "classic", max_pages: 1, ...(it.style || {}) };
  const label = (text) => `<span class="small mono muted">${text}</span>`;
  main.innerHTML = `<div class="page"><div class="page-h"><a href="#/resumes" class="btn ghost sm"><i class=i-back></i> Collection</a>
      <h1 style="min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${esc(it.name)}</h1>
      <span class="sub">${libSource(it)}${it.original_file ? `, from ${esc(it.original_file)}` : ""}, created ${esc((it.created_at || "").slice(0, 10))}</span></div>
    <div class="card" style="margin-bottom:14px"><div class="row" style="gap:10px;align-items:flex-end">
      <label class="stack" style="gap:4px;flex:2;min-width:220px">${label("NAME")}<input type="text" data-lib="name" value="${esc(it.name)}"></label>
      <label class="stack" style="gap:4px;flex:2;min-width:200px">${label("TAGS (comma-separated)")}
        <input type="text" data-lib="tags" value="${esc((it.tags || []).join(", "))}" placeholder="e.g. software, finance, favorite"></label>
      <label class="stack" style="gap:4px">${label("LAYOUT")}<select data-lib="theme" style="width:auto">${selectOptions(RESUME_THEMES, style.theme)}</select></label>
      <label class="stack" style="gap:4px">${label("PAGES")}<select data-lib="max_pages" style="width:auto">${selectOptions([1, 2], +style.max_pages)}</select></label>
      <span class="spacer"></span>
      <button class="btn primary" data-act="lib-use" data-id="${it.id}">Use on a lead</button>
      <button class="btn" data-act="lib-dup" data-id="${it.id}">Duplicate</button>
      <button class="btn ghost" data-act="lib-del" data-id="${it.id}">Delete</button></div>
      <label class="stack" style="gap:4px;margin-top:10px">${label("NOTES")}<input type="text" data-lib="notes" value="${esc(it.notes || "")}" placeholder="When to use this one"></label>
      <div class="small mono muted" id="lib-meta-state" style="margin-top:6px"></div></div>
    <div id="lib-ed"></div></div>`;
  const metaState = $("#lib-meta-state");
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
    metaState.textContent = "saved";
    if (editor.theme !== style.theme) {
      editor.theme = style.theme;
      editor.refresh?.();
    }
    if (editor.maxPages !== style.max_pages) {
      editor.maxPages = style.max_pages;
      renderLibraryItem(id);
    }
  }, 500);
  $$("[data-lib]").forEach((el) => el.addEventListener(el.tagName === "SELECT" ? "change" : "input", () => {
    metaState.textContent = "saving";
    saveDetails();
  }));
  mountEditor($("#lib-ed"), editor);
}

// The "Use on a lead" dialog from the collection: search your leads, pick one, then use the resume as it is or have the
// AI tailor it to the job (POST /api/library/{id}/apply/{lead id}). Then it opens that lead's Resume tab.
async function libUseModal(itemId) {
  const it = await api(`/api/library/${itemId}`);
  modal(`<h2>Use “${esc(it.name)}” on a lead</h2>
    <input type="text" id="lu-q" placeholder="Search leads by company or title" style="width:100%;margin-bottom:8px">
    <div class="lu-list" id="lu-list"><div class="muted small">loading</div></div>
    <label class="row small" style="gap:8px;margin-top:10px">${toggle(`id="lu-backup"`, false)}Save the lead's current resume to the collection first</label>
    <p class="muted small" style="margin:8px 0 0">The lead's resume is replaced. “Revert to AI version” in its editor still brings back the generated one.</p>
    <div class="row" style="margin-top:12px;justify-content:flex-end;gap:8px"><button class="btn ghost" onclick="closeModal()">Cancel</button>
      <button class="btn" id="lu-asis" disabled>Use as-is</button>
      <button class="btn primary ai" id="lu-tailor" disabled title="The AI re-angles it toward the job, then it gets the usual check and recruiter review"><i class=i-ai></i> Tailor to the job</button></div>`);
  let pick = null;
  // Without a search, the Ready tab's leads; with one, matches from all leads.
  const load = async (search) => {
    const d = await api(`/api/leads?tab=${search ? "all" : "ready"}&q=${encodeURIComponent(search || "")}&limit=60`);
    const leads = d.leads.filter((l) => l.app_status !== "trashed");
    $("#lu-list").innerHTML = leads.map((l) => `<label class="lu-row"><input type="radio" name="lu" value="${l.id}" ${pick === l.id ? "checked" : ""}>
        <span class="mono small" style="width:28px">${l.score ?? "-"}</span><span style="flex:1;min-width:0"><b>${esc(l.company)}</b>, ${esc(l.title)}</span>
        <span class="small muted">${l.has_resume ? "has a resume" : "no resume yet"}</span></label>`).join("")
      || `<div class="muted small">No matching leads${search ? "" : " in Ready. Search to find any lead"}.</div>`;
    $$('#lu-list input[name="lu"]').forEach((radio) => (radio.onchange = () => {
      pick = +radio.value;
      $("#lu-asis").disabled = $("#lu-tailor").disabled = false;
    }));
  };
  $("#lu-q").addEventListener("input", debounce((e) => load(e.target.value.trim()), 250));
  const go = async (tailor, button) => {
    if (!pick) return;
    button.disabled = true;
    button.innerHTML = `<span class="spin"></span> ${tailor ? "Tailoring" : "Applying"}`;
    try {
      const r = await api(`/api/library/${itemId}/apply/${pick}`, { method: "POST", body: { tailor, backup: $("#lu-backup").checked } });
      closeModal();
      toast(tailor ? "Tailored and applied" : "Resume applied", `Resume check ${r.check ?? "-"}${r.change_summary ? `. ${r.change_summary.slice(0, 140)}` : ""}`, "", pick);
      S.leadTab = "resume";
      location.hash = `#/lead/${pick}/resume`;
    } catch (err) {
      toast("Couldn't apply it", err.message, "error");
      button.disabled = false;
      button.innerHTML = tailor ? "<i class=i-ai></i> Tailor to the job" : "Use as-is";
    }
  };
  $("#lu-asis").onclick = (e) => go(false, e.currentTarget);
  $("#lu-tailor").onclick = (e) => go(true, e.currentTarget);
  load("");
}

// The same from a lead's Resume tab ("Use a saved resume"): pick a resume from the collection for this lead.
async function leadPickSavedModal(lead) {
  const items = await api("/api/library");
  if (!items.length) {
    toast("Your collection is empty", "Import resumes on the Resumes page, or save this one first.");
    return;
  }
  const row = (it) => `<label class="lu-row"><input type="radio" name="lp" value="${it.id}"><span style="flex:1;min-width:0"><b>${esc(it.name)}</b>
      ${(it.tags || []).map((t) => `<span class="chip">${esc(t)}</span>`).join(" ")}</span><span class="small muted">${ago(it.updated_at)}</span></label>`;
  modal(`<h2>Use a saved resume for ${esc(lead.company)}</h2>
    <div class="lu-list">${items.map(row).join("")}</div>
    ${lead.resume_md ? `<label class="row small" style="gap:8px;margin-top:10px">${toggle(`id="lp-backup"`, false)}Save this lead's current resume to the collection first</label>` : ""}
    <div class="row" style="margin-top:12px;justify-content:flex-end;gap:8px"><button class="btn ghost" onclick="closeModal()">Cancel</button>
      <button class="btn" id="lp-asis" disabled>Use as-is</button><button class="btn primary ai" id="lp-tailor" disabled><i class=i-ai></i> Tailor to this job</button></div>`);
  let pick = null;
  $$('input[name="lp"]').forEach((radio) => (radio.onchange = () => {
    pick = +radio.value;
    $("#lp-asis").disabled = $("#lp-tailor").disabled = false;
  }));
  const go = async (tailor, button) => {
    button.disabled = true;
    button.innerHTML = `<span class="spin"></span> ${tailor ? "Tailoring" : "Applying"}`;
    try {
      const r = await api(`/api/library/${pick}/apply/${lead.id}`, { method: "POST", body: { tailor, backup: !!$("#lp-backup")?.checked } });
      closeModal();
      toast(tailor ? "Tailored and applied" : "Resume applied", `Resume check ${r.check ?? "-"}`);
      S.leadTab = "resume";
      renderLead(lead.id);
    } catch (err) {
      toast("Couldn't apply it", err.message, "error");
      button.disabled = false;
      button.innerHTML = tailor ? "<i class=i-ai></i> Tailor to this job" : "Use as-is";
    }
  };
  $("#lp-asis").onclick = (e) => go(false, e.currentTarget);
  $("#lp-tailor").onclick = (e) => go(true, e.currentTarget);
}

// ---------------------------------------------------------------- actions
onAction("lib-open", (el) => {
  location.hash = `#/resumes/${el.dataset.id}`;
});
onAction("lib-use", (el) => libUseModal(+el.dataset.id));
onAction("lib-dl", (el) => openUrl(el.dataset.url));
onAction("lib-tag", (el) => {  // a tag filters the collection; clicking it again clears the filter
  S.libTag = S.libTag === el.dataset.tag ? "" : el.dataset.tag;
  renderLibrary();
});
onAction("lib-paste", () => libPasteModal());
onAction("lib-dup", async (el) => {
  const it = await api(`/api/library/${el.dataset.id}`);
  const body = { name: `${it.name} (copy)`, md: $("#ed")?.value || it.md, style: it.style, tags: it.tags, notes: it.notes, source: it.source };
  const copied = await api("/api/library", { method: "POST", body });
  toast("Duplicated", copied.name);
  location.hash = `#/resumes/${copied.id}`;
});
onAction("lib-del", async (el) => {
  if (!confirm("Delete this resume from your collection?")) return;
  await api(`/api/library/${el.dataset.id}`, { method: "DELETE" });
  S.dirty = false;
  toast("Deleted");
  location.hash = "#/resumes";
});
