/* dreams.js: the Dream list page. The companies and job titles you care most about: matching leads get the dream flag
   (it never changes their score) and can skip the search area limits. Companies from your profile are listed too, and
   removing one keeps it out for good.
   APIs: GET /api/dreams and PUT /api/dreams (every change saves at once), POST /api/dreams/recheck. */
"use strict";

// Draws the page from GET /api/dreams (kept in S.dreams for the actions below).
async function renderDreams() {
  const d = (S.dreams = await api("/api/dreams"));
  const chip = (name, i, kind) => `<span class="chip">${esc(name)}<span class="x" data-act="dream-rm" data-kind="${kind}" data-i="${i}" title="Remove"><i class=i-x></i></span></span>`;
  const none = (text) => `<span class="muted small">${text}</span>`;
  const fromProfile = d.profile_companies.map((name) => `<span class="chip blue">${esc(name)}`
    + `<span class="x" data-act="dream-exclude" data-name="${esc(name)}" title="Remove from dream list"><i class=i-x></i></span></span>`).join("");
  const restoreChip = (name) => `<span class="chip">${esc(name)}`
    + `<span class="x" data-act="dream-restore" data-name="${esc(name)}" title="Restore"><i class=i-undo></i></span></span>`;
  const removed = d.excluded.length
    ? `<b class="small mono">REMOVED</b><div class="row" style="gap:6px;margin:8px 0">${d.excluded.map(restoreChip).join("")}</div>` : "";
  main.innerHTML = `<div class="page"><div class="page-h"><h1>Dream list</h1><span class="sub">Leads that match get the dream flag (it never changes their score) and can skip your search-area limits.</span></div>
    <div class="card" style="margin-bottom:14px"><div class="row"><span class="mono" style="font-size:15px;font-weight:700">${d.flagged}</span><span class="muted">leads flagged as dream right now</span>
      <span class="spacer"></span><button class="btn" data-act="dream-view">View them</button>
      <button class="btn primary" data-act="dream-recheck" title="Re-flag every lead against this list (stars you set by hand are kept)"><i class=i-refresh></i> Re-check all leads</button></div></div>
    <div class="cols" style="grid-template-columns:1fr 1fr">
      <div class="card"><h3>Dream companies</h3>
        <div class="row" style="gap:6px;margin-bottom:10px">${d.companies.map((name, i) => chip(name, i, "companies")).join("") || none("none yet")}</div>
        <div class="row"><input type="text" id="dc-add" placeholder="Add companies, comma-separated (e.g. Apple, Capital One, Mayo Clinic)" style="flex:1">
          <button class="btn" data-act="dream-add" data-kind="companies">Add</button></div>
        <div class="hr"></div>
        <b class="small mono">FROM YOUR PROFILE (derived from your resume and answers; removing one drops it for good)</b>
        <div class="row" style="gap:6px;margin:8px 0">${fromProfile || none("none")}</div>
        ${removed}
        <div class="row" style="margin-top:10px">${toggle(`data-dbyp="bypass"`, d.bypass)}<span class="small">Dream companies can be anywhere in the US (ignore my search area)</span></div></div>
      <div class="card"><h3>Dream jobs (roles)</h3><p class="muted small" style="margin-top:-4px">Any lead whose title contains one of these phrases is a dream job, at any company.</p>
        <div class="row" style="gap:6px;margin-bottom:10px">${d.jobs.map((name, i) => chip(name, i, "jobs")).join("") || none("none yet")}</div>
        <div class="row"><input type="text" id="dj-add" placeholder="Add roles, comma-separated (e.g. iOS developer, data engineer, product designer)" style="flex:1">
          <button class="btn" data-act="dream-add" data-kind="jobs">Add</button></div>
        <div class="row" style="margin-top:14px">${toggle(`data-dbyp="jobs_bypass"`, d.jobs_bypass)}<span class="small">Dream jobs can be anywhere in the US too</span></div></div></div></div>`;
  // Enter in an "Add" box clicks its Add button.
  $$("#dc-add, #dj-add").forEach((input) => input.addEventListener("keydown", (e) => {
    if (e.key === "Enter") input.nextElementSibling.click();
  }));
}

// Saves part of the dream list (PUT /api/dreams with only the changed keys) and redraws the page.
async function saveDreams(patch, message) {
  S.dreams = await api("/api/dreams", { method: "PUT", body: patch });
  toast("Dream list saved", message || "Click Re-check all leads to apply it to leads you already have.");
  renderDreams();
}

// ---------------------------------------------------------------- actions
onAction("dream-add", async (el) => {  // adds the comma-separated names, skipping ones already on the list
  const kind = el.dataset.kind;
  const input = $(kind === "companies" ? "#dc-add" : "#dj-add");
  const add = input.value.split(",").map((x) => x.trim()).filter(Boolean);
  if (!add.length) return;
  const current = S.dreams[kind];
  const isNew = (name) => !current.some((have) => have.toLowerCase() === name.toLowerCase());
  await saveDreams({ [kind]: [...current, ...add.filter(isNew)] }, `Added ${add.join(", ")}`);
});
onAction("dream-rm", async (el) => {
  const kind = el.dataset.kind, list = [...S.dreams[kind]];
  const [gone] = list.splice(+el.dataset.i, 1);
  await saveDreams({ [kind]: list }, `Removed ${gone}`);
});
onAction("dream-exclude", async (el) => {  // removes a company that came from your profile
  await saveDreams({ excluded: [...S.dreams.excluded, el.dataset.name] }, `Removed ${el.dataset.name} from the profile-derived list`);
});
onAction("dream-restore", async (el) => {
  await saveDreams({ excluded: S.dreams.excluded.filter((name) => name !== el.dataset.name) }, `Restored ${el.dataset.name}`);
});
onAction("dream-recheck", async () => {
  const r = await api("/api/dreams/recheck", { method: "POST" });
  toast("Leads re-checked", `${plural(r.changed, "lead")} changed, ${r.flagged} flagged as dream`);
  refreshStats();
  renderDreams();
});
onAction("dream-view", () => {  // the Leads page with only dream leads, on the All tab
  S.dreamOnly = true;
  S.leadsTab = "all";
  localStorage.setItem("leadsTab", "all");
  location.hash = "#/leads";
});
onChange(async (el) => {
  if (!el.dataset.dbyp) return false;  // the "anywhere in the US" switches
  await saveDreams({ [el.dataset.dbyp]: el.checked }, el.checked ? "Location bypass on" : "Location bypass off");
  return true;
});
