/* search-area.js: the search area, which sets where jobs may be. Settings stores it as one list (locations.allowed) of
   state names, cities, "Remote" and "Anywhere in the US"; a search skips jobs outside it before scoring them. This file
   turns that list into the editor's parts and back, writes the short summary and the chips, and runs the editor dialog
   (states, regions, cities, remote, nationwide). Home's "Where to search" and Settings, Search open it with
   data-act="edit-area". APIs: GET /api/settings and PUT /api/settings (only the locations part changes). */
"use strict";

const US_STATES = [["AL","Alabama"],["AK","Alaska"],["AZ","Arizona"],["AR","Arkansas"],["CA","California"],["CO","Colorado"],["CT","Connecticut"],
  ["DE","Delaware"],["DC","Washington, DC"],["FL","Florida"],["GA","Georgia"],["HI","Hawaii"],["ID","Idaho"],["IL","Illinois"],["IN","Indiana"],
  ["IA","Iowa"],["KS","Kansas"],["KY","Kentucky"],["LA","Louisiana"],["ME","Maine"],["MD","Maryland"],["MA","Massachusetts"],["MI","Michigan"],
  ["MN","Minnesota"],["MS","Mississippi"],["MO","Missouri"],["MT","Montana"],["NE","Nebraska"],["NV","Nevada"],["NH","New Hampshire"],
  ["NJ","New Jersey"],["NM","New Mexico"],["NY","New York"],["NC","North Carolina"],["ND","North Dakota"],["OH","Ohio"],["OK","Oklahoma"],
  ["OR","Oregon"],["PA","Pennsylvania"],["RI","Rhode Island"],["SC","South Carolina"],["SD","South Dakota"],["TN","Tennessee"],["TX","Texas"],
  ["UT","Utah"],["VT","Vermont"],["VA","Virginia"],["WA","Washington"],["WV","West Virginia"],["WI","Wisconsin"],["WY","Wyoming"]];

// One-click regions for the editor's buttons.
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

// The "My state" button: the state from your standard answers, when it's a US state. "" otherwise.
function homeStateAbbr() {
  const state = String(S.onboarding?.answers?.state || "").trim().toLowerCase();
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

// A short summary: "OH, PA, Pittsburgh, Remote". Past nine states it adds "+N".
function areaSummary(allowed) {
  const area = parseArea(allowed);
  if (area.nationwide) return `Anywhere in the US${area.remote ? " and remote" : ""}`;
  const states = [...area.states].sort();
  const more = states.length > 9 ? [`+${states.length - 9}`] : [];
  return [...states.slice(0, 9), ...more, ...area.cities, ...(area.remote ? ["Remote"] : [])].join(", ") || "Nowhere yet";
}

// The area as tags: one per state, city, "Remote" or "Anywhere in the US" (twelve at most, then "+N more").
function areaTags(allowed) {
  const items = allowed || [];
  if (!items.length) return `<span class="tag warn">Nowhere yet: pick an area</span>`;
  const more = items.length > 12 ? `<span class="tag">+${items.length - 12} more</span>` : "";
  return items.slice(0, 12).map((item) => `<span class="tag">${icon("pin")}${esc(item)}</span>`).join("") + more;
}

// The search area dialog. Every change redraws it from `area`; Save writes it to Settings.
async function openAreaEditor() {
  const loc = (await api("/api/settings")).locations;
  const area = parseArea(loc.allowed);
  const home = homeStateAbbr();
  const dialog = openDialog(`<div class="area-editor"></div>`, { eyebrow: "SEARCH AREA" });
  const box = $(".area-editor", dialog);
  const showSummary = () => ($(".area-summary", box).textContent = areaSummary(areaToAllowed(area)));
  const draw = () => {
    const presets = (home ? `<button class="chip" type="button" data-preset="__home">My state (${home})</button>` : "")
      + Object.keys(AREA_PRESETS).map((name) => `<button class="chip" type="button" data-preset="${esc(name)}">${esc(name)}</button>`).join("")
      + `<button class="chip" type="button" data-preset="__clear">Clear states</button>`;
    const stateBox = ([abbr, name]) => `<label class="state${area.states.has(abbr) ? " on" : ""}" title="${esc(name)}">`
      + `<input type="checkbox" data-st="${abbr}"${area.states.has(abbr) ? " checked" : ""}><b>${abbr}</b><span>${esc(name)}</span></label>`;
    const cities = area.cities.map((city, i) => `<span class="tag">${esc(city)}<button class="tag-x" type="button" data-rmcity="${i}" aria-label="Remove ${esc(city)}">${icon("close")}</button></span>`).join("")
      || `<span class="muted-note">None yet.</span>`;
    box.innerHTML = `<h2>Where should JobPortal look?</h2>
      <p>Jobs outside this area are skipped before they're scored, except at dream companies when that's on below.</p>
      <div class="filters">${presets}</div>
      <div class="switch-list">
        <label class="switch-row">${toggle(`id="ar-remote"`, area.remote)}<span>Remote jobs (US)</span></label>
        <label class="switch-row">${toggle(`id="ar-nation"`, area.nationwide)}<span><b>Anywhere in the US</b> (ignores the states below)</span></label></div>
      <div class="state-grid${area.nationwide ? " dim" : ""}">${US_STATES.map(stateBox).join("")}</div>
      <h3>Cities or metro areas</h3>
      <div class="tags">${cities}</div>
      <div class="inline-form"><input type="text" id="ar-city" placeholder="Add a city, like Houston, TX" aria-label="City">
        <button class="button light" type="button" id="ar-addcity">Add city</button></div>
      <div class="switch-list">
        <label class="switch-row">${toggle(`id="ar-dream"`, loc.dream_bypass)}<span>Dream companies can be anywhere in the US</span></label>
        <label class="switch-row"><span>When a job's location is unclear:</span>
          <select id="ar-unknown">${selectOptions([["ai", "let the AI decide"], ["drop", "skip it"]], loc.unknown_policy)}</select></label></div>
      <div class="dialog-actions"><span class="area-summary muted-note"></span>
        <button class="button outline" type="button" data-act="close-dialog">Cancel</button>
        <button class="button primary" type="button" id="ar-save">Save search area</button></div>`;
    showSummary();
  };
  // The dialog keeps its own listeners: the area being edited lives here until you save.
  dialog.addEventListener("change", (e) => {
    const t = e.target;
    if (t.dataset.st) {
      if (t.checked) area.states.add(t.dataset.st);
      else area.states.delete(t.dataset.st);
      t.parentElement.classList.toggle("on", t.checked);
    }
    if (t.id === "ar-remote") area.remote = t.checked;
    if (t.id === "ar-nation") {
      area.nationwide = t.checked;
      $(".state-grid", box).classList.toggle("dim", t.checked);
    }
    showSummary();
  });
  const addCity = () => {
    const city = $("#ar-city", box).value.trim();
    if (!city) return;
    area.cities.push(city);
    draw();
    $("#ar-city", box).focus();
  };
  dialog.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && e.target.id === "ar-city") addCity();
  });
  dialog.addEventListener("click", async (e) => {
    const preset = e.target.closest("[data-preset]");
    const removeCity = e.target.closest("[data-rmcity]");
    if (preset) {
      const name = preset.dataset.preset;
      area.states = new Set(name === "__clear" ? [] : name === "__home" ? [home] : AREA_PRESETS[name]);
      area.nationwide = false;
      draw();
    } else if (removeCity) {
      area.cities.splice(+removeCity.dataset.rmcity, 1);
      draw();
    } else if (e.target.closest("#ar-addcity")) {
      addCity();
    } else if (e.target.closest("#ar-save")) {
      await saveArea(area, dialog).catch((err) => toast("Couldn't save the search area", err.message, "error"));
    }
  });
  draw();
}

// Saves the dialog's area. It re-reads the settings first, so only the locations part changes.
async function saveArea(area, dialog) {
  const fresh = await api("/api/settings");
  const box = $(".area-editor", dialog);
  fresh.locations = { ...fresh.locations, allowed: areaToAllowed(area), dream_bypass: $("#ar-dream", box).checked, unknown_policy: $("#ar-unknown", box).value };
  if (!fresh.locations.allowed.length) {
    toast("Pick an area", "Choose at least one state, a city, Remote or Anywhere in the US.", "error");
    return;
  }
  const saved = await api("/api/settings", { method: "PUT", body: fresh });
  S.searchArea = saved.locations.allowed;
  if (S.cfg) S.cfg.locations = saved.locations;  // a settings form on screen shows the new area (and only saves its own edits)
  closeDialog(dialog);
  toast("Search area saved", areaSummary(S.searchArea));
  if (S.route[0] === "home") renderAreaPanel();
  if (S.route[0] === "settings" && S.route[1] === "search") renderAreaCard();
}

// ---------------------------------------------------------------- actions
onAction("edit-area", () => openAreaEditor());
