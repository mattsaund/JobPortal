/* file-drops.js: dropping and picking files. Any element with data-drop="name" takes files dropped on it (folders are
   opened and everything inside them taken) and files picked with the file input inside it. onDrop("name", fn) says what
   happens with them: fn(files, zone). System files that ride along (macOS ._* and .DS_Store, Windows Thumbs.db and
   desktop.ini) are left out. Files dropped anywhere else are ignored, so a missed drop never replaces the dashboard with
   the file. Used by your documents on Home (components/documents.js) and the resume collection (pages/resumes.js). */
"use strict";

const JUNK = /^(\._|\.DS_Store$|Thumbs\.db$|desktop\.ini$)/;

// The handler for each kind of drop zone, by its data-drop name.
const DROPS = {};
const onDrop = (name, fn) => {
  DROPS[name] = fn;
};

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

// The files in a drop. The entries have to be taken during the drop event itself, before anything waits, so this
// takes them first and reads the folders after.
function droppedFiles(transfer) {
  const entries = [...(transfer.items || [])].map((item) => item.webkitGetAsEntry && item.webkitGetAsEntry()).filter(Boolean);
  return entries.length ? filesFromEntries(entries) : Promise.resolve([...(transfer.files || [])]);
}

const carriesFiles = (e) => [...(e.dataTransfer?.types || [])].includes("Files");  // not a Tracker card being dragged
const zoneOf = (e) => e.target.closest?.("[data-drop]");

document.addEventListener("dragover", (e) => {
  if (!carriesFiles(e)) return;
  e.preventDefault();  // without this, the browser would open the file in place of the dashboard
  const zone = zoneOf(e);
  e.dataTransfer.dropEffect = zone ? "copy" : "none";
  $$("[data-drop].dragging").forEach((el) => el !== zone && el.classList.remove("dragging"));
  zone?.classList.add("dragging");
});
document.addEventListener("dragleave", (e) => {
  const zone = zoneOf(e);
  if (zone && !zone.contains(e.relatedTarget)) zone.classList.remove("dragging");
});
document.addEventListener("drop", async (e) => {
  if (!carriesFiles(e)) return;
  e.preventDefault();
  $$("[data-drop].dragging").forEach((el) => el.classList.remove("dragging"));
  const zone = zoneOf(e);
  if (!zone) return;
  const files = (await droppedFiles(e.dataTransfer)).filter((file) => !JUNK.test(file.name));
  if (files.length) DROPS[zone.dataset.drop](files, zone);
});

// Files picked with the file input inside a drop zone.
onChange((el) => {
  const zone = el.matches("input[type=file]") && el.closest("[data-drop]");
  if (!zone) return false;
  const files = [...el.files].filter((file) => !JUNK.test(file.name));
  el.value = "";  // so picking the same file again still counts
  if (files.length) DROPS[zone.dataset.drop](files, zone);
  return true;
});
