/* The search area editor (states, cities, remote, nationwide). It sets which locations a search keeps. Used on the
   Leads page header and in Settings. */
"use strict";

const US_STATES = [["AL","Alabama"],["AK","Alaska"],["AZ","Arizona"],["AR","Arkansas"],["CA","California"],["CO","Colorado"],["CT","Connecticut"],
  ["DE","Delaware"],["DC","Washington, DC"],["FL","Florida"],["GA","Georgia"],["HI","Hawaii"],["ID","Idaho"],["IL","Illinois"],["IN","Indiana"],
  ["IA","Iowa"],["KS","Kansas"],["KY","Kentucky"],["LA","Louisiana"],["ME","Maine"],["MD","Maryland"],["MA","Massachusetts"],["MI","Michigan"],
  ["MN","Minnesota"],["MS","Mississippi"],["MO","Missouri"],["MT","Montana"],["NE","Nebraska"],["NV","Nevada"],["NH","New Hampshire"],
  ["NJ","New Jersey"],["NM","New Mexico"],["NY","New York"],["NC","North Carolina"],["ND","North Dakota"],["OH","Ohio"],["OK","Oklahoma"],
  ["OR","Oregon"],["PA","Pennsylvania"],["RI","Rhode Island"],["SC","South Carolina"],["SD","South Dakota"],["TN","Tennessee"],["TX","Texas"],
  ["UT","Utah"],["VT","Vermont"],["VA","Virginia"],["WA","Washington"],["WV","West Virginia"],["WI","Wisconsin"],["WY","Wyoming"]];
const AREA_PRESETS = { "Northeast": ["ME", "NH", "VT", "MA", "RI", "CT", "NY", "NJ", "PA"], "Mid-Atlantic": ["NY", "NJ", "PA", "DE", "MD", "DC", "VA", "WV"],
  "Southeast": ["VA", "NC", "SC", "GA", "FL", "AL", "TN", "KY", "MS", "LA", "AR"], "Midwest": ["OH", "MI", "IN", "IL", "WI", "MN", "IA", "MO", "KS", "NE", "SD", "ND"],
  "Southwest": ["TX", "OK", "NM", "AZ", "NV", "UT", "CO"], "West Coast": ["CA", "OR", "WA", "AK", "HI"] };
// "My state" preset: the state from your standard answers, when it's a US state.
function homeStateAbbr() {
  const st = String((S.profileCache?.facts || {}).state || "").trim(), low = st.toLowerCase();
  const hit = US_STATES.find(([ab, n]) => ab.toLowerCase() === low || n.toLowerCase() === low);
  return hit ? hit[0] : "";
}
const NATIONWIDE_RE = /^(anywhere( in the)?( us| usa| united states)?|nationwide|united states|usa|us)$/i;

function parseArea(allowed) {
  const byName = Object.fromEntries(US_STATES.map(([ab, n]) => [n.toLowerCase(), ab]));
  const a = { states: new Set(), cities: [], remote: false, nationwide: false };
  for (const raw of allowed || []) {
    const x = String(raw).trim(), low = x.toLowerCase();
    if (NATIONWIDE_RE.test(low)) a.nationwide = true;
    else if (/remote/.test(low)) a.remote = true;
    else if (/^(dc|d\.c\.|washington,? d\.?c\.?|district of columbia)$/i.test(x)) a.states.add("DC");
    else if (byName[low]) a.states.add(byName[low]);
    else if (US_STATES.some(([ab]) => ab === x.toUpperCase()) && x.length === 2) a.states.add(x.toUpperCase());
    else if (x) a.cities.push(x);
  }
  return a;
}
function areaToAllowed(a) {
  const name = Object.fromEntries(US_STATES);
  return [...(a.nationwide ? ["Anywhere in the US"] : []), ...[...a.states].map((ab) => name[ab]), ...a.cities, ...(a.remote ? ["Remote"] : [])];
}
function areaSummary(allowed) {
  const a = parseArea(allowed);
  if (a.nationwide) return `Anywhere in the US${a.remote ? " + Remote" : ""}`;
  const parts = [...a.states].sort(), more = parts.length > 9 ? ` +${parts.length - 9}` : "";
  return [...parts.slice(0, 9), ...(more ? [more.trim()] : []), ...a.cities, ...(a.remote ? ["Remote"] : [])].join(", ") || "nowhere yet: pick an area";
}

async function openAreaEditor() {
  const cfg = await api("/api/settings"), L = cfg.locations;
  if (!S.profileCache) { try { S.profileCache = await api("/api/profile"); } catch (_) {} }
  const a = parseArea(L.allowed), home = homeStateAbbr();
  const draw = () => {
    modal(`<h2>Search area</h2><p class="muted small" style="margin-top:-6px">Where jobs can be. Everything outside this area is filtered out before AI triage, except dream companies when the bypass is on.</p>
      <div class="row" style="margin-bottom:10px">${home ? `<button class="btn sm" data-preset="__home">My state (${home})</button>` : ""}${Object.keys(AREA_PRESETS).map((p) => `<button class="btn sm" data-preset="${esc(p)}">${esc(p)}</button>`).join("")}
        <button class="btn sm" data-preset="__clear">Clear states</button></div>
      <div class="row" style="gap:18px;margin-bottom:12px">
        <label class="row small">${toggle(`id="ar-remote"`, a.remote)} Remote jobs (US)</label>
        <label class="row small">${toggle(`id="ar-nation"`, a.nationwide)} <b>Anywhere in the US</b> (ignores the state list)</label></div>
      <div class="stategrid ${a.nationwide ? "dim" : ""}">${US_STATES.map(([ab, n]) => `<label class="st ${a.states.has(ab) ? "on" : ""}" title="${esc(n)}"><input type="checkbox" data-st="${ab}" ${a.states.has(ab) ? "checked" : ""}><b>${ab}</b><span>${esc(n)}</span></label>`).join("")}</div>
      <div style="margin-top:14px"><label class="f"><span>Specific cities or metros (matched by name, e.g. “Houston, TX”, “Denver”, “Raleigh, NC”)</span></label>
        <div class="row" style="gap:6px;margin:6px 0">${a.cities.map((c, i) => `<span class="chip">${esc(c)}<span class="x" data-rmcity="${i}"><i class=i-x></i></span></span>`).join("") || `<span class="muted small">none</span>`}</div>
        <div class="row"><input type="text" id="ar-city" placeholder="Add a city" style="max-width:300px"><button class="btn sm" id="ar-addcity">Add city</button></div></div>
      <div class="hr"></div>
      <div class="row" style="gap:18px"><label class="row small">${toggle(`id="ar-dream"`, L.dream_bypass)} Dream companies can be anywhere in the US</label>
        <label class="row small">Unknown location: <select id="ar-unknown" style="width:auto"><option value="ai" ${L.unknown_policy === "ai" ? "selected" : ""}>let AI decide</option><option value="drop" ${L.unknown_policy === "drop" ? "selected" : ""}>drop</option></select></label></div>
      <div class="row" style="justify-content:space-between;margin-top:16px"><span class="muted small" id="ar-sum"></span>
        <div class="row"><button class="btn ghost" onclick="closeModal()">Cancel</button><button class="btn primary" id="ar-save">Save search area</button></div></div>`);
    $("#ar-sum").textContent = areaSummary(areaToAllowed(a));
    const m = $("#modal");
    m.onchange = (e) => {
      const t = e.target;
      if (t.dataset.st) { t.checked ? a.states.add(t.dataset.st) : a.states.delete(t.dataset.st); t.parentElement.classList.toggle("on", t.checked); }
      if (t.id === "ar-remote") a.remote = t.checked;
      if (t.id === "ar-nation") { a.nationwide = t.checked; $(".stategrid").classList.toggle("dim", t.checked); }
      $("#ar-sum").textContent = areaSummary(areaToAllowed(a));
    };
    m.onclick = async (e) => {
      const t = e.target;
      if (t.dataset.preset) { a.states = new Set(t.dataset.preset === "__clear" ? [] : t.dataset.preset === "__home" ? [home] : AREA_PRESETS[t.dataset.preset]); a.nationwide = false; draw(); }
      if (t.dataset.rmcity != null) { a.cities.splice(+t.dataset.rmcity, 1); draw(); }
      if (t.id === "ar-addcity") { const v = $("#ar-city").value.trim(); if (v) { a.cities.push(v); draw(); } }
      if (t.id === "ar-save") {
        const fresh = await api("/api/settings");
        fresh.locations = { ...fresh.locations, allowed: areaToAllowed(a), dream_bypass: $("#ar-dream").checked, unknown_policy: $("#ar-unknown").value };
        if (!fresh.locations.allowed.length) { toast("Pick an area", "Choose at least one state, city, Remote or Anywhere.", "error"); return; }
        await api("/api/settings", { method: "PUT", body: fresh }); S.locAllowed = fresh.locations.allowed;
        closeModal(); toast("Search area saved", areaSummary(fresh.locations.allowed));
        if (S.route[0] === "leads") renderMission(); if (S.route[0] === "settings") renderSettings();
      }
    };
  };
  draw();
}

// ---------------------------------------------------------------- actions
onAction("edit-area", async (el, e) => { openAreaEditor(); });
