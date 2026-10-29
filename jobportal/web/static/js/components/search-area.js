/* search-area.js: the search area, which sets where jobs may be. Settings stores it as one list (locations.allowed) of
   state names, cities, "Remote" and "Anywhere in the US"; the search drops jobs outside it before AI triage. This file
   turns that list into the editor's parts and back, writes the short summary on the chips, and runs the editor dialog
   (states, presets, cities, remote, nationwide). The Leads page chip and Settings open it with data-act="edit-area".
   APIs: GET /api/settings and PUT /api/settings (only the locations part changes). */
"use strict";

const US_STATES = [["AL","Alabama"],["AK","Alaska"],["AZ","Arizona"],["AR","Arkansas"],["CA","California"],["CO","Colorado"],["CT","Connecticut"],
  ["DE","Delaware"],["DC","Washington, DC"],["FL","Florida"],["GA","Georgia"],["HI","Hawaii"],["ID","Idaho"],["IL","Illinois"],["IN","Indiana"],
  ["IA","Iowa"],["KS","Kansas"],["KY","Kentucky"],["LA","Louisiana"],["ME","Maine"],["MD","Maryland"],["MA","Massachusetts"],["MI","Michigan"],
  ["MN","Minnesota"],["MS","Mississippi"],["MO","Missouri"],["MT","Montana"],["NE","Nebraska"],["NV","Nevada"],["NH","New Hampshire"],
  ["NJ","New Jersey"],["NM","New Mexico"],["NY","New York"],["NC","North Carolina"],["ND","North Dakota"],["OH","Ohio"],["OK","Oklahoma"],
  ["OR","Oregon"],["PA","Pennsylvania"],["RI","Rhode Island"],["SC","South Carolina"],["SD","South Dakota"],["TN","Tennessee"],["TX","Texas"],
  ["UT","Utah"],["VT","Vermont"],["VA","Virginia"],["WA","Washington"],["WV","West Virginia"],["WI","Wisconsin"],["WY","Wyoming"]];

// One-click regions for the editor's preset buttons.
const AREA_PRESETS = {
  "Northeast": ["ME", "NH", "VT", "MA", "RI", "CT", "NY", "NJ", "PA"],
  "Mid-Atlantic": ["NY", "NJ", "PA", "DE", "MD", "DC", "VA", "WV"],
  "Southeast": ["VA", "NC", "SC", "GA", "FL", "AL", "TN", "KY", "MS", "LA", "AR"],
  "Midwest": ["OH", "MI", "IN", "IL", "WI", "MN", "IA", "MO", "KS", "NE", "SD", "ND"],
  "Southwest": ["TX", "OK", "NM", "AZ", "NV", "UT", "CO"],
  "West Coast": ["CA", "OR", "WA", "AK", "HI"],
};

// The ways people write "anywhere in the US".
const NATIONWIDE_RE = /^(anywhere( in the)?( us| usa| united states)?|nationwide|united states|usa|us)$/i;

// The "My state" preset: the state from your standard answers (needs S.profileCache), when it's a US state. "" otherwise.
function homeStateAbbr() {
  const state = String((S.profileCache?.facts || {}).state || "").trim().toLowerCase();
  const hit = US_STATES.find(([abbr, name]) => abbr.toLowerCase() === state || name.toLowerCase() === state);
  return hit ? hit[0] : "";
}

// Splits the saved list into the editor's parts: a set of state codes, cities, and the remote and nationwide switches.
// A full state name or a two-letter code is a state; anything that isn't a state, remote or nationwide is a city.
function parseArea(allowed) {
  const codeByName = Object.fromEntries(US_STATES.map(([abbr, name]) => [name.toLowerCase(), abbr]));
  const area = { states: new Set(), cities: [], remote: false, nationwide: false };
  for (const raw of allowed || []) {
    const item = String(raw).trim(), low = item.toLowerCase();
    if (NATIONWIDE_RE.test(low)) area.nationwide = true;
    else if (/remote/.test(low)) area.remote = true;
    else if (/^(dc|d\.c\.|washington,? d\.?c\.?|district of columbia)$/i.test(item)) area.states.add("DC");
    else if (codeByName[low]) area.states.add(codeByName[low]);
    else if (item.length === 2 && US_STATES.some(([abbr]) => abbr === item.toUpperCase())) area.states.add(item.toUpperCase());
    else if (item) area.cities.push(item);
  }
  return area;
}

// The editor's parts back into the list Settings saves. States are saved by their full names.
function areaToAllowed(area) {
  const nameOf = Object.fromEntries(US_STATES);
  return [
    ...(area.nationwide ? ["Anywhere in the US"] : []),
    ...[...area.states].map((abbr) => nameOf[abbr]),
    ...area.cities,
    ...(area.remote ? ["Remote"] : []),
  ];
}

// A short summary for chips: "OH, PA, Pittsburgh, Remote". Past nine states it adds "+N".
function areaSummary(allowed) {
  const area = parseArea(allowed);
  if (area.nationwide) return `Anywhere in the US${area.remote ? " + Remote" : ""}`;
  const states = [...area.states].sort();
  const more = states.length > 9 ? [`+${states.length - 9}`] : [];
  return [...states.slice(0, 9), ...more, ...area.cities, ...(area.remote ? ["Remote"] : [])].join(", ") || "nowhere yet: pick an area";
}

// The search area dialog. Every change redraws it from `area`; Save writes it to Settings.
async function openAreaEditor() {
  const cfg = await api("/api/settings");
  const loc = cfg.locations;
  if (!S.profileCache) {
    try { S.profileCache = await api("/api/profile"); } catch (_) {}  // for the "My state" preset
  }
  const area = parseArea(loc.allowed);
  const home = homeStateAbbr();
  const showSummary = () => ($("#ar-sum").textContent = areaSummary(areaToAllowed(area)));
  const draw = () => {
    const presets = (home ? `<button class="btn sm" data-preset="__home">My state (${home})</button>` : "")
      + Object.keys(AREA_PRESETS).map((name) => `<button class="btn sm" data-preset="${esc(name)}">${esc(name)}</button>`).join("");
    const stateBox = ([abbr, name]) => `<label class="st ${area.states.has(abbr) ? "on" : ""}" title="${esc(name)}">`
      + `<input type="checkbox" data-st="${abbr}" ${area.states.has(abbr) ? "checked" : ""}><b>${abbr}</b><span>${esc(name)}</span></label>`;
    const cities = area.cities.map((city, i) => `<span class="chip">${esc(city)}<span class="x" data-rmcity="${i}"><i class=i-x></i></span></span>`).join("")
      || `<span class="muted small">none</span>`;
    modal(`<h2>Search area</h2>
      <p class="muted small" style="margin-top:-6px">Where jobs can be. Everything outside this area is filtered out before AI triage, except
        dream companies when the bypass is on.</p>
      <div class="row" style="margin-bottom:10px">${presets}
        <button class="btn sm" data-preset="__clear">Clear states</button></div>
      <div class="row" style="gap:18px;margin-bottom:12px">
        <label class="row small">${toggle(`id="ar-remote"`, area.remote)} Remote jobs (US)</label>
        <label class="row small">${toggle(`id="ar-nation"`, area.nationwide)} <b>Anywhere in the US</b> (ignores the state list)</label></div>
      <div class="stategrid ${area.nationwide ? "dim" : ""}">${US_STATES.map(stateBox).join("")}</div>
      <div style="margin-top:14px"><label class="f"><span>Specific cities or metros (matched by name, e.g. “Houston, TX”, “Denver”, “Raleigh, NC”)</span></label>
        <div class="row" style="gap:6px;margin:6px 0">${cities}</div>
        <div class="row"><input type="text" id="ar-city" placeholder="Add a city" style="max-width:300px"><button class="btn sm" id="ar-addcity">Add city</button></div></div>
      <div class="hr"></div>
      <div class="row" style="gap:18px"><label class="row small">${toggle(`id="ar-dream"`, loc.dream_bypass)} Dream companies can be anywhere in the US</label>
        <label class="row small">Unknown location: <select id="ar-unknown" style="width:auto">${selectOptions([["ai", "let AI decide"], ["drop", "drop"]], loc.unknown_policy)}</select></label></div>
      <div class="row" style="justify-content:space-between;margin-top:16px"><span class="muted small" id="ar-sum"></span>
        <div class="row"><button class="btn ghost" onclick="closeModal()">Cancel</button><button class="btn primary" id="ar-save">Save search area</button></div></div>`);
    showSummary();
    // The dialog is outside <main>, so it handles its own events (modal() cleared the last dialog's handlers).
    const dialog = $("#modal");
    dialog.onchange = (e) => {  // a state box or one of the switches
      const t = e.target;
      if (t.dataset.st) {
        if (t.checked) area.states.add(t.dataset.st);
        else area.states.delete(t.dataset.st);
        t.parentElement.classList.toggle("on", t.checked);
      }
      if (t.id === "ar-remote") area.remote = t.checked;
      if (t.id === "ar-nation") {
        area.nationwide = t.checked;
        $(".stategrid").classList.toggle("dim", t.checked);
      }
      showSummary();
    };
    dialog.onclick = async (e) => {
      const preset = e.target.closest("[data-preset]");
      const removeCity = e.target.closest("[data-rmcity]");  // closest(): the click lands on the x icon inside
      if (preset) {
        const name = preset.dataset.preset;
        area.states = new Set(name === "__clear" ? [] : name === "__home" ? [home] : AREA_PRESETS[name]);
        area.nationwide = false;
        draw();
      } else if (removeCity) {
        area.cities.splice(+removeCity.dataset.rmcity, 1);
        draw();
      } else if (e.target.id === "ar-addcity") {
        const city = $("#ar-city").value.trim();
        if (city) {
          area.cities.push(city);
          draw();
        }
      } else if (e.target.id === "ar-save") {
        await saveArea(area);
      }
    };
  };
  draw();
}

// Saves the dialog's area. It re-reads the settings first, so only the locations part changes.
async function saveArea(area) {
  const fresh = await api("/api/settings");
  fresh.locations = { ...fresh.locations, allowed: areaToAllowed(area), dream_bypass: $("#ar-dream").checked, unknown_policy: $("#ar-unknown").value };
  if (!fresh.locations.allowed.length) {
    toast("Pick an area", "Choose at least one state, city, Remote or Anywhere.", "error");
    return;
  }
  await api("/api/settings", { method: "PUT", body: fresh });
  S.searchArea = fresh.locations.allowed;
  closeModal();
  toast("Search area saved", areaSummary(fresh.locations.allowed));
  if (S.route[0] === "leads") renderMission();
  if (S.route[0] === "settings") {
    // Unsaved Settings edits stay on screen: only their locations take the values just saved.
    if (S.cfgDirty && S.cfg) {
      S.cfg.locations = { ...S.cfg.locations, ...fresh.locations };
      renderSettings({ keepEdits: true });
    } else {
      renderSettings();
    }
  }
}

// ---------------------------------------------------------------- actions
onAction("edit-area", () => openAreaEditor());
