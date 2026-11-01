/* settings-form.js: the form plumbing shared by the Settings tabs and the Sources dialog. They edit S.cfg
   (GET /api/settings) in place: every field says where its value lives (a data-* attribute), and onCfgEdit() copies each
   edit into S.cfg and remembers its path. saveCfg() then writes only the paths you edited, on top of the settings as
   they are on the server now (PUT /api/settings), so a change saved elsewhere meanwhile (the search area, the Dream
   list, your answers) is kept. A form root is marked data-cfg; fields outside one are left alone. */
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
}

// Marks a settings path as edited (adding or removing a company board or a mission edits its whole list).
function markCfgEdit(path) {
  S.cfgEdits.add(path);
  S.cfgDirty = true;
}

// Copies one edit into S.cfg. The field says where the value goes:
//   data-path="a.b.c"   one value (data-bool or a checkbox: true/false; type="number" or data-num: a number)
//   data-list="a.b"     a list, one item per line
//   data-feeds          the RSS feeds, "name | url" per line
//   data-board + data-bf, data-mission + data-mf: one field of a company board or an AI hunt mission
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
  toast("Saved", "Your settings are updated.");
}

// The bar at the bottom of a settings form, with its Save button.
const saveBar = (label = "Save settings") => `<div class="save-bar"><button class="button primary" type="button" data-act="save-cfg">${label}</button></div>`;

// ---------------------------------------------------------------- actions
onAction("save-cfg", () => saveCfg());
