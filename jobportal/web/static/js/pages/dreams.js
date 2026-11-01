/* dreams.js: the Dream list, a card in Settings, Search. The companies and job titles you care most about: leads that
   match get the dream flag (it never changes their score) and can skip the search area. Companies from your profile
   are listed too, and removing one keeps it out for good. Every change saves at once.
   APIs: GET /api/dreams and PUT /api/dreams, POST /api/dreams/recheck. */
"use strict";

// Draws the card into box from GET /api/dreams (kept in S.dreams for the actions below).
async function renderDreams(box) {
  if (!box) return;
  const d = (S.dreams = await api("/api/dreams"));
  const tag = (name, i, kind) => `<span class="tag">${esc(name)}<button class="tag-x" type="button" data-act="dream-rm" data-kind="${kind}" data-i="${i}" aria-label="Remove ${esc(name)}">${icon("close")}</button></span>`;
  const none = `<span class="muted-note">None yet.</span>`;
  const fromProfile = d.profile_companies.map((name) => `<span class="tag blue">${esc(name)}`
    + `<button class="tag-x" type="button" data-act="dream-exclude" data-name="${esc(name)}" aria-label="Remove ${esc(name)}">${icon("close")}</button></span>`).join("");
  const restore = (name) => `<span class="tag">${esc(name)}<button class="tag-x" type="button" data-act="dream-restore" data-name="${esc(name)}" aria-label="Bring back ${esc(name)}">${icon("undo")}</button></span>`;
  const add = (kind, placeholder) => `<div class="inline-form"><input type="text" data-dream-add="${kind}" placeholder="${placeholder}" aria-label="Add, separated by commas">
    <button class="button outline" type="button" data-act="dream-add" data-kind="${kind}">${icon("plus")}Add</button></div>`;
  box.innerHTML = `<div class="panel-heading"><div><h2>${icon("star")}Dream list</h2>
      <p class="panel-note">Leads that match get a Dream tag. It never changes their score.</p></div>
      <div class="heading-actions"><a class="button outline" href="#/leads" data-act="dream-view">${d.flagged} on your leads</a>
        <button class="button light" type="button" data-act="dream-recheck" title="Tag every lead again (tags you set by hand stay)">${icon("refresh")}Check all leads again</button></div></div>
    <div class="two-col">
      <div><h3>Dream companies</h3><div class="tags">${d.companies.map((name, i) => tag(name, i, "companies")).join("") || none}</div>
        ${add("companies", "Add companies, separated by commas")}
        <h4>From your profile</h4><p class="panel-note">Made from your resume and answers. Removing one keeps it out for good.</p>
        <div class="tags">${fromProfile || none}</div>
        ${d.excluded.length ? `<h4>Removed</h4><div class="tags">${d.excluded.map(restore).join("")}</div>` : ""}
        <label class="switch-row">${toggle(`data-dream-bypass="bypass"`, d.bypass)}<span>Dream companies can be anywhere in the US (outside my search area)</span></label></div>
      <div><h3>Dream jobs</h3><p class="panel-note">Any lead whose title has one of these phrases is a dream job, at any company.</p>
        <div class="tags">${d.jobs.map((name, i) => tag(name, i, "jobs")).join("") || none}</div>
        ${add("jobs", "Add job titles, separated by commas")}
        <label class="switch-row">${toggle(`data-dream-bypass="jobs_bypass"`, d.jobs_bypass)}<span>Dream jobs can be anywhere in the US too</span></label></div></div>`;
}

// Saves part of the Dream list (PUT /api/dreams with only the changed keys) and redraws the card. The settings form on
// screen gets the new values too, so it shows them.
async function saveDreams(patch, message) {
  S.dreams = await api("/api/dreams", { method: "PUT", body: patch });
  if (S.cfg) {
    Object.assign(S.cfg, { dream_companies: S.dreams.companies, dream_jobs: S.dreams.jobs });
    Object.assign(S.cfg.locations, { dream_bypass: S.dreams.bypass, dream_jobs_bypass: S.dreams.jobs_bypass });
  }
  toast("Dream list saved", message || "Check all leads again to tag the ones you already have.");
  renderDreams($("#dream-card"));
}

// ---------------------------------------------------------------- actions
onAction("dream-add", async (el) => {  // adds the comma-separated names, skipping ones already on the list
  const kind = el.dataset.kind;
  const add = $(`[data-dream-add="${kind}"]`).value.split(",").map((x) => x.trim()).filter(Boolean);
  if (!add.length) return;
  const current = S.dreams[kind];
  const isNew = (name) => !current.some((have) => have.toLowerCase() === name.toLowerCase());
  await saveDreams({ [kind]: [...current, ...add.filter(isNew)] }, `Added ${add.join(", ")}.`);
});
onAction("dream-rm", async (el) => {
  const kind = el.dataset.kind, list = [...S.dreams[kind]];
  const [gone] = list.splice(+el.dataset.i, 1);
  await saveDreams({ [kind]: list }, `Removed ${gone}.`);
});
onAction("dream-exclude", async (el) => {  // removes a company that came from your profile
  await saveDreams({ excluded: [...S.dreams.excluded, el.dataset.name] }, `${el.dataset.name} won't come back from your profile.`);
});
onAction("dream-restore", async (el) => {
  await saveDreams({ excluded: S.dreams.excluded.filter((name) => name !== el.dataset.name) }, `${el.dataset.name} is back.`);
});
onAction("dream-recheck", async () => {
  const r = await api("/api/dreams/recheck", { method: "POST" });
  toast("Leads checked again", `${plural(r.changed, "lead")} changed, ${r.flagged} tagged as a dream.`);
  refreshStats();
  renderDreams($("#dream-card"));
});
onAction("dream-view", () => {  // Leads with only dream leads, on All
  S.dreamOnly = true;
  S.leadsTab = "all";
  store.set("leadsTab", "all");
});
onChange(async (el) => {
  if (!el.dataset.dreamBypass) return false;  // the "anywhere in the US" switches
  await saveDreams({ [el.dataset.dreamBypass]: el.checked }, el.checked ? "They can be anywhere in the US now." : "They follow your search area now.");
  return true;
});
// Enter in an Add box adds.
document.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && e.target.matches?.("[data-dream-add]")) $(`[data-act="dream-add"][data-kind="${e.target.dataset.dreamAdd}"]`).click();
});
