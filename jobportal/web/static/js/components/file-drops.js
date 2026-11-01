/* file-drops.js: dropping and picking files. Any element with data-drop="name" takes files dropped on it (folders are
   opened and everything inside them taken) and files picked with the file input inside it. onDrop("name", fn) says what
   happens with them: fn(files, zone), which may be async; when it fails, a toast says why. System files that ride along
   (macOS ._* and .DS_Store, Windows Thumbs.db and desktop.ini) are left out, and so is anything in a dropped folder that
   can't be read (a broken link, a file without permission), so one bad file never stops the rest. Files dropped anywhere
   else are ignored, so a missed drop never replaces the dashboard with the file. Used by your documents on Home
   (components/documents.js) and the resume collection (pages/resumes.js). No API calls of its own. */
"use strict";

const JUNK = /^(\._|\.DS_Store$|Thumbs\.db$|desktop\.ini$)/;

// The handler for each kind of drop zone, by its data-drop name.
const DROPS = {};
const onDrop = (name, fn) => {
  DROPS[name] = fn;
};

// The files in dropped items, including everything inside dropped folders. entries come from webkitGetAsEntry(). An
// entry that can't be read is counted in unreadable and skipped.
async function filesFromEntries(entries) {
  const files = [];
  let unreadable = 0;
  const walk = async (entry) => {
    try {
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
    } catch (_) {
      unreadable++;
    }
  };
  for (const entry of entries) await walk(entry);
  return { files, unreadable };
}

// The files in a drop. The entries have to be taken during the drop event itself, before anything waits, so this
// takes them first and reads the folders after.
function droppedFiles(transfer) {
  const entries = [...(transfer.items || [])].map((item) => item.webkitGetAsEntry && item.webkitGetAsEntry()).filter(Boolean);
  return entries.length ? filesFromEntries(entries) : Promise.resolve({ files: [...(transfer.files || [])], unreadable: 0 });
}

// Hands the files to the zone's handler, leaving out the system files. Says so when nothing usable came along (an empty
// folder, only system files) and when some of a folder couldn't be read.
async function takeFiles(zone, files, unreadable = 0) {
  files = files.filter((file) => !JUNK.test(file.name));
  if (unreadable) toast(`Couldn't open ${plural(unreadable, "item")}`, "Some of what you dropped couldn't be read, so it was left out.", "error");
  if (!files.length) {
    if (!unreadable) toast("No files to add", "That folder is empty, or holds only system files.");
    return;
  }
  try {
    await DROPS[zone.dataset.drop](files, zone);
  } catch (err) {
    toast("Something went wrong", err.message, "error");
  }
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
  const { files, unreadable } = await droppedFiles(e.dataTransfer);
  await takeFiles(zone, files, unreadable);
});

// Files picked with the file input inside a drop zone. The input is emptied right away, so picking the same file again
// still counts as a change.
onChange(async (el) => {
  const zone = el.matches("input[type=file]") && el.closest("[data-drop]");
  if (!zone) return false;
  const files = [...el.files];
  el.value = "";
  if (files.length) await takeFiles(zone, files);
  return true;
});
