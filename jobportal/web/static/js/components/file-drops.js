/* file-drops.js: importing resume files by drag and drop.
   - The resume drop zone (setup step 2 and Profile > Resume): drop, choose or paste your resume. This is the resume your
     profile is built from.
   - filesFromEntries(): the files inside dropped folders, for the Resumes page's collection. */
"use strict";

// System files that ride along with dropped files and folders (macOS ._* and .DS_Store, Windows Thumbs.db and
// desktop.ini). They're never imported.
const JUNK = /^(\._|\.DS_Store$|Thumbs\.db$|desktop\.ini$)/;

// The files in dropped items, including everything inside dropped folders. entries come from webkitGetAsEntry().
async function filesFromEntries(entries) {
  const files = [];
  const walk = async (entry) => {
    if (entry.isFile) {
      files.push(await new Promise((resolve, reject) => entry.file(resolve, reject)));
    } else if (entry.isDirectory) {
      const reader = entry.createReader();
      let batch;
      do {  // a folder's contents arrive in batches, until an empty one
        batch = await new Promise((resolve, reject) => reader.readEntries(resolve, reject));
        for (const child of batch) await walk(child);
      } while (batch.length);
    }
  };
  for (const entry of entries) await walk(entry);
  return files;
}

// ---------------------------------------------------------------- the resume drop zone
// The drop zone's HTML. accept lists the file types the server reads (GET /api/onboarding gives it). label is the heading.
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

// Makes the drop zone inside root work. A file goes to PUT /api/onboarding/resume, pasted text to
// POST /api/onboarding/resume-text. onDone(reply) runs once the server has read it. opts.prefill = false skips
// pre-filling the standard questions from the resume.
function wireResumeDropzone(root, onDone, opts = {}) {
  const zone = $("#rz", root);
  if (!zone) return;
  const log = (html) => ($("#rz-log", root).innerHTML = html);
  const keepCopy = () => $("#rz-lib", root).checked;  // "Also keep an editable copy in my resume collection"
  const prefill = opts.prefill !== false;
  const send = async (request) => {
    log(`<span class="spin"></span> Reading your resume. About 30 seconds.`);
    zone.classList.add("busy");
    try {
      const reply = await request();
      log("");
      await onDone(reply);
    } catch (err) {
      log("");
      toast("Couldn't read that resume", err.message, "error");
    }
    zone.classList.remove("busy");
  };
  const upload = (file) => send(() => uploadFile(
    `/api/onboarding/resume?filename=${encodeURIComponent(file.name)}&save_to_library=${keepCopy() ? 1 : 0}&prefill=${prefill ? 1 : 0}`, file));
  const highlight = (on) => (e) => {
    e.preventDefault();
    zone.classList.toggle("over", on);
  };
  ["dragenter", "dragover"].forEach((name) => zone.addEventListener(name, highlight(true)));
  ["dragleave", "dragend"].forEach((name) => zone.addEventListener(name, highlight(false)));
  zone.addEventListener("drop", (e) => {
    e.preventDefault();
    zone.classList.remove("over");
    const file = [...(e.dataTransfer.files || [])].find((f) => !JUNK.test(f.name));
    if (file) upload(file);
  });
  $("#rz-pick", root).onchange = (e) => {
    const file = e.target.files[0];
    if (file) upload(file);
  };
  zone.addEventListener("click", (e) => {
    const button = e.target.closest("[data-rz]");
    if (!button) return;
    if (button.dataset.rz === "paste") $("#rz-paste", root).style.display = "";
    if (button.dataset.rz === "paste-go") {
      const text = $("#rz-text", root).value.trim();
      if (text.length < 80) {
        toast("That's too short", "Paste the whole resume.", "error");
        return;
      }
      send(() => api("/api/onboarding/resume-text", { method: "POST", body: { text, save_to_library: keepCopy(), prefill } }));
    }
  });
}
