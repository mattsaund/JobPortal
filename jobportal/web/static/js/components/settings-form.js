/* settings-form.js: the form plumbing shared by the Settings and Sources pages. Both pages edit S.cfg (GET /api/settings)
   in place: every field says where its value lives (a data-* attribute), onCfgEdit() copies each edit into S.cfg, and
   saveCfg() sends the whole object back with PUT /api/settings. */
"use strict";

// A text, number, password or email field for the setting at a dotted path ("sources.linkedin.max_requests"). extra adds
// attributes such as step="0.5" or a placeholder.
const cfgInput = (path, label, type = "text", extra = "") => `<label class="f"><span>${label}</span>`
  + `<input type="${type}" data-path="${path}" value="${esc(getPath(S.cfg, path) ?? "")}" ${extra}></label>`;

// A textarea for a list setting, one item per line.
const cfgLines = (path, label, rows) => `<label class="f"><span>${label}</span>`
  + `<textarea data-list="${path}" rows="${rows}">${esc((getPath(S.cfg, path) || []).join("\n"))}</textarea></label>`;

// "name | url", or just the url, to { name, url } (the RSS feeds box on Sources).
function parseFeed(line) {
  const [name, url] = line.includes("|") ? line.split("|").map((s) => s.trim()) : [line, line];
  return { name, url };
}

// Copies one edit into S.cfg and marks it unsaved. The field says where the value goes:
//   data-path="a.b.c"   one value (data-bool or a checkbox: true/false; type="number" or data-num: a number)
//   data-list="a.b"     a list, one item per line
//   data-feeds          the RSS feeds, "name | url" per line
//   data-board + data-bf, data-mission + data-mf: one field of a company board or an AI hunt mission
function onCfgEdit(e) {
  if (!["settings", "sources"].includes(S.route[0])) return;
  const t = e.target, cfg = S.cfg;
  const lines = () => t.value.split("\n").map((x) => x.trim()).filter(Boolean);
  const checkOrText = () => (t.type === "checkbox" ? t.checked : t.value);
  if (t.dataset.path) {
    const value = t.dataset.bool || t.type === "checkbox" ? t.checked : t.type === "number" || t.dataset.num ? +t.value : t.value;
    setPath(cfg, t.dataset.path, value);
  } else if (t.dataset.list) {
    setPath(cfg, t.dataset.list, lines());
  } else if (t.dataset.feeds) {
    cfg.sources.rss.feeds = lines().map(parseFeed);
  } else if (t.dataset.board != null) {
    cfg.sources.ats_boards.boards[+t.dataset.board][t.dataset.bf] = checkOrText();
  } else if (t.dataset.mission != null) {
    cfg.sources.ai_hunt.missions[+t.dataset.mission][t.dataset.mf] = checkOrText();
  } else {
    return;  // not a settings field
  }
  S.cfgDirty = true;
}
main.addEventListener("input", onCfgEdit);
main.addEventListener("change", onCfgEdit);

// Saves S.cfg (PUT /api/settings). The server answers with the saved settings, which replace S.cfg.
async function saveCfg() {
  S.cfg = await api("/api/settings", { method: "PUT", body: S.cfg });
  S.cfgDirty = false;
  S.searchArea = S.cfg.locations.allowed;
  S.industries = S.cfg.industries;
  toast("Saved", "Settings updated");
}

// ---------------------------------------------------------------- actions
onAction("save-cfg", () => saveCfg());  // the Save button at the bottom of Settings and Sources
