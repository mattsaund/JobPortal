/* Drag-and-drop for resume files, shared by setup and the Resumes page. */
"use strict";

const JUNK = /^(\._|\.DS_Store$|Thumbs\.db$|desktop\.ini$)/;
async function walkEntries(entries) {
  const out = [];
  const walk = async (entry, prefix) => {
    if (entry.isFile) {
      const f = await new Promise((res, rej) => entry.file(res, rej));
      out.push({ file: f, path: prefix + f.name });
    } else if (entry.isDirectory) {
      const reader = entry.createReader();
      let batch;
      do {
        batch = await new Promise((res, rej) => reader.readEntries(res, rej));
        for (const child of batch) await walk(child, prefix + entry.name + "/");
      } while (batch.length);
    }
  };
  for (const en of entries) await walk(en, "");
  return out;
}
