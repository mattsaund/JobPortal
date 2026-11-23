/* dreams.js: the Dream list, a tab in Settings, Search. The companies and job titles you care most about: leads that
   match get the dream flag (it never changes their score) and can skip the search area. Companies from your profile
   are listed too, and removing one keeps it out for good. Every change saves at once.
   APIs: GET /api/dreams and PUT /api/dreams, POST /api/dreams/recheck. */
"use strict";

// Draws the tab into box from GET /api/dreams (kept in S.dreams for the actions below). When the list doesn't load, the
// tab says so (with Retry) instead of staying empty. After a change, a focused button or Add box gets the focus back.
async function renderDreams(box) {
  if (!box) return;
  let d;
  try {
    d = S.dreams = await api("/api/dreams");
  } catch (err) {
    box.innerHTML = loadError(err);
    return;
  }
  const tag = (name, i, kind) => `<span class="tag">${esc(name)}<button class="tag-x" type="button" data-act="dream-rm" data-kind="${kind}" data-i="${i}" aria-label="Remove ${esc(name)}">${icon("close")}</button></span>`;
  const none = `<span class="muted">None</span>`;
  const fromProfile = d.profile_companies.map((name) => `<span class="tag blue">${esc(name)}`
    + `<button class="tag-x" type="button" data-act="dream-exclude" data-name="${esc(name)}" aria-label="Remove ${esc(name)}">${icon("close")}</button></span>`).join("");
  const restore = (name) => `<span class="tag">${esc(name)}<button class="tag-x" type="button" data-act="dream-restore" data-name="${esc(name)}" aria-label="Restore ${esc(name)}">${icon("undo")}</button></span>`;
  const add = (kind, placeholder, label) => `<div class="inline-form set-dream-add"><input type="text" data-dream-add="${kind}" placeholder="${placeholder}" aria-label="${label}">
    <button class="button outline" type="button" data-act="dream-add" data-kind="${kind}">${icon("plus")}Add</button></div>`;
  const bypass = (key, on) => optRow("Anywhere in the US", toggle(`data-dream-bypass="${key}" aria-label="Anywhere in the US"`, on));
  const focus = focusKey(box);
  box.innerHTML = `<div class="toolbar"><a class="button outline small" href="#/leads" data-act="dream-view">${d.flagged} on leads</a><span class="spacer"></span>
      <button class="button outline small" type="button" data-act="dream-recheck">${icon("refresh")}Recheck</button></div>
    <div class="set-columns">
      <div>${setSect("Companies", `${optRow("Dream", `<div class="tags">${d.companies.map((name, i) => tag(name, i, "companies")).join("") || none}</div>
          ${add("companies", "Acme, Northwind", "Add dream companies")}`)}
        ${optRow("From profile", `<div class="tags">${fromProfile || none}</div>`)}
        ${d.excluded.length ? optRow("Removed", `<div class="tags">${d.excluded.map(restore).join("")}</div>`) : ""}
        ${bypass("bypass", d.bypass)}`)}</div>
      <div>${setSect("Jobs", `${optRow("Titles", `<div class="tags">${d.jobs.map((name, i) => tag(name, i, "jobs")).join("") || none}</div>
          ${add("jobs", "Head chef, Charge nurse", "Add dream job titles")}`)}
        ${bypass("jobs_bypass", d.jobs_bypass)}`)}</div></div>`;
  refocus(box, focus);
}

// Saves part of the Dream list (PUT /api/dreams with only the changed keys) and redraws the tab. The settings form on
// screen gets the new values too, so it shows them.
async function saveDreams(patch, message) {
  S.dreams = await api("/api/dreams", { method: "PUT", body: patch });
  if (S.cfg) {
    Object.assign(S.cfg, { dream_companies: S.dreams.companies, dream_jobs: S.dreams.jobs });
    Object.assign(S.cfg.locations, { dream_bypass: S.dreams.bypass, dream_jobs_bypass: S.dreams.jobs_bypass });
  }
  toast(message);
  renderDreams($("#dream-card"));
  renderAreaCard();  // the Filters tab shows where dream companies can be
}

// ---------------------------------------------------------------- actions
onAction("dream-add", async (el) => {  // adds the comma-separated names, skipping ones already on the list
  const kind = el.dataset.kind;
  const add = $(`[data-dream-add="${kind}"]`).value.split(",").map((x) => x.trim()).filter(Boolean);
  if (!add.length) return;
  const current = S.dreams[kind];
  const isNew = (name) => !current.some((have) => have.toLowerCase() === name.toLowerCase());
  await saveDreams({ [kind]: [...current, ...add.filter(isNew)] }, "Added");
});
onAction("dream-rm", async (el) => {
  const kind = el.dataset.kind, list = [...S.dreams[kind]];
  list.splice(+el.dataset.i, 1);
  await saveDreams({ [kind]: list }, "Removed");
});
onAction("dream-exclude", async (el) => {  // removes a company that came from your profile
  await saveDreams({ excluded: [...S.dreams.excluded, el.dataset.name] }, "Removed");
});
onAction("dream-restore", async (el) => {
  await saveDreams({ excluded: S.dreams.excluded.filter((name) => name !== el.dataset.name) }, "Restored");
});
onAction("dream-recheck", async () => {
  const r = await api("/api/dreams/recheck", { method: "POST" });
  toast("Leads rechecked", `${r.changed} changed, ${r.flagged} tagged`);
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
  await saveDreams({ [el.dataset.dreamBypass]: el.checked }, "Saved")
    .catch((err) => {
      el.checked = !el.checked;  // not saved: the switch shows what is
      throw err;
    });
  return true;
});
// Enter in an Add box adds.
document.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && e.target.matches?.("[data-dream-add]")) $(`[data-act="dream-add"][data-kind="${e.target.dataset.dreamAdd}"]`).click();
});
