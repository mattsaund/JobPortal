/* settings-form.js: the form plumbing shared by the Settings sections and the Sources dialog. They edit S.cfg
   (GET /api/settings) in place: every field says where its value lives (a data-* attribute), and onCfgEdit() copies each
   edit into S.cfg and remembers its path. saveCfg() then writes only the paths you edited, on top of the settings as
   they are on the server now (PUT /api/settings), so a change saved elsewhere meanwhile (the search area, the Dream
   list, your answers) is kept. A form root is marked data-cfg; fields outside one are left alone.
   It also holds the setting rows (.opt) and the Save bar pinned under the open Settings section. */
"use strict";

// A text, number, password or email field for the setting at a dotted path ("sources.linkedin.max_requests"). extra adds
// attributes such as step="0.5" or a placeholder.
const cfgInput = (path, label, type = "text", extra = "") => `<label class="field"><span class="field-label">${label}</span>`
  + `<input type="${type}" data-path="${path}" value="${esc(getPath(S.cfg, path) ?? "")}" ${extra}></label>`;

// A textarea for a list setting, one item per line.
const cfgLines = (path, label, rows) => `<label class="field"><span class="field-label">${label}</span>`
  + `<textarea data-list="${path}" rows="${rows}">${esc((getPath(S.cfg, path) || []).join("\n"))}</textarea></label>`;

// A switch for an on/off setting, with its label.
const cfgSwitch = (path, label, on) => `<label class="switch-row">${toggle(`data-path="${path}" data-bool="1"`, on)}<span>${label}</span></label>`;

// ---------------------------------------------------------------- setting rows
// A setting as a row: its name on the left, its control on the right. wraps = the row is a <label> around one input, so
// a click on the name focuses it. A control with labels of its own (a switch, pills) needs a plain row.
const optRow = (label, control, wraps = false) => (wraps
  ? `<label class="opt"><span class="opt-label">${label}</span><span class="opt-body">${control}</span></label>`
  : `<div class="opt"><span class="opt-label">${label}</span><div class="opt-body">${control}</div></div>`);

// The same three kinds of setting as above, as rows.
const cfgOpt = (path, label, type = "text", extra = "") => optRow(label,
  `<input type="${type}" data-path="${path}" value="${esc(getPath(S.cfg, path) ?? "")}" ${extra}>`, true);
const cfgOptLines = (path, label, rows) => optRow(label,
  `<textarea data-list="${path}" rows="${rows}">${esc((getPath(S.cfg, path) || []).join("\n"))}</textarea>`, true);
const cfgOptSwitch = (path, label, on, note = "") => optRow(`${label}${note ? `<small>${note}</small>` : ""}`,
  toggle(`data-path="${path}" data-bool="1" aria-label="${esc(label)}"`, on));

// "name | url", or just the url, to { name, url } (the RSS feeds box in Sources).
function parseFeed(line) {
  const [name, url] = line.includes("|") ? line.split("|").map((s) => s.trim()) : [line, line];
  return { name, url };
}

// Loads the saved settings into S.cfg, forgetting any edits.
async function loadCfg() {
  S.cfg = await api("/api/settings");
  S.cfgDirty = false;
  S.cfgEdits.clear();
  syncSaveBar();
}

// Marks a settings path as edited (adding or removing a company board or a mission edits its whole list).
function markCfgEdit(path) {
  S.cfgEdits.add(path);
  S.cfgDirty = true;
  syncSaveBar();
}

// Copies one edit into S.cfg. The field says where the value goes:
//   data-path="a.b.c"   one value (data-bool or a checkbox: true/false; type="number" or data-num: a number)
//   data-list="a.b"     a list, one item per line
//   data-feeds          the RSS feeds, "name | url" per line
//   data-board + data-bf, data-mission + data-mf: one field of a company board or an AI hunt mission
//   data-time, data-day  the schedule's times of day and its days (every one of them is read again)
function onCfgEdit(e) {
  const t = e.target;
  if (!S.cfg || !t.closest?.("[data-cfg]")) return;
  const cfg = S.cfg;
  const lines = () => t.value.split("\n").map((x) => x.trim()).filter(Boolean);
  const checkOrText = () => (t.type === "checkbox" ? t.checked : t.value);
  if (t.dataset.path) {
    const value = t.dataset.bool || t.type === "checkbox" ? t.checked : t.type === "number" || t.dataset.num ? +t.value : t.value;
    setPath(cfg, t.dataset.path, value);
    markCfgEdit(t.dataset.path);
  } else if (t.dataset.list) {
    setPath(cfg, t.dataset.list, lines());
    markCfgEdit(t.dataset.list);
  } else if (t.dataset.feeds) {
    cfg.sources.rss.feeds = lines().map(parseFeed);
    markCfgEdit("sources.rss.feeds");
  } else if (t.dataset.board != null) {
    cfg.sources.ats_boards.boards[+t.dataset.board][t.dataset.bf] = checkOrText();
    markCfgEdit("sources.ats_boards.boards");
  } else if (t.dataset.mission != null) {
    cfg.sources.ai_hunt.missions[+t.dataset.mission][t.dataset.mf] = checkOrText();
    markCfgEdit("sources.ai_hunt.missions");
  } else if (t.dataset.time != null) {
    setPath(cfg, "schedule.times", $$("[data-time]", t.closest("[data-schedule]")).map((input) => input.value).filter(Boolean));
    markCfgEdit("schedule.times");
  } else if (t.dataset.day != null) {
    t.closest(".choice")?.classList.toggle("active", t.checked);
    setPath(cfg, "schedule.days", $$("[data-day]", t.closest("[data-schedule]")).filter((box) => box.checked).map((box) => +box.dataset.day));
    markCfgEdit("schedule.days");
  }
}
document.addEventListener("input", onCfgEdit);
document.addEventListener("change", onCfgEdit);

// Saves the edited paths of S.cfg over the settings as they are now, then keeps the server's answer as S.cfg. A field
// you change while the save is on its way isn't part of it: that edit is copied onto the answer and stays unsaved, so
// the field and S.cfg agree and the next save sends it. When the save fails, every edit stays unsaved.
async function saveCfg() {
  const mine = S.cfg, edits = [...S.cfgEdits];
  S.cfgEdits.clear();  // what's edited from here on is new
  let saved;
  try {
    const fresh = await api("/api/settings");
    for (const path of edits) setPath(fresh, path, getPath(mine, path));
    saved = await api("/api/settings", { method: "PUT", body: fresh });
  } catch (err) {
    edits.forEach((path) => S.cfgEdits.add(path));
    throw err;
  }
  for (const path of S.cfgEdits) setPath(saved, path, getPath(mine, path));
  S.cfg = saved;
  S.cfgDirty = S.cfgEdits.size > 0;
  S.searchArea = S.cfg.locations.allowed;
  S.industries = S.cfg.industries;
  syncSaveBar();
  toast("Saved");
}

// ---------------------------------------------------------------- the Save bar
// One bar pinned under the open Settings section (#set-save, drawn by settings.js). It shows only while the section has
// unsaved changes. Each section says what Save does with setSaver(fn); a section with nothing to save passes nothing.
let settingsSaver = null;
function setSaver(fn = null) {
  settingsSaver = fn;
  syncSaveBar();
}
function syncSaveBar() {
  const bar = $("#set-save");
  if (bar) bar.hidden = !(settingsSaver && (S.dirty || S.cfgDirty));
}

// Typing in the open section shows the bar. These run after onCfgEdit above, and after a section's own listeners.
const editedInSettings = (e) => {
  if (e.target.closest?.("#settings-body")) syncSaveBar();
};
document.addEventListener("input", editedInSettings);
document.addEventListener("change", editedInSettings);

// ---------------------------------------------------------------- actions
onAction("set-save", async (el) => {
  if (!settingsSaver) return;
  el.disabled = true;
  try {
    await settingsSaver();
  } finally {
    el.disabled = false;
    syncSaveBar();
  }
});
onAction("set-discard", () => {  // back to what's saved: the section draws itself again from the server
  S.dirty = false;
  S.cfgDirty = false;
  S.cfgEdits.clear();
  syncSaveBar();
  return renderSettings(S.route[1], S.route[2]);
});
