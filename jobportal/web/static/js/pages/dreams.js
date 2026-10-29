/* The Dream list page: companies and job titles you care most about, and whether they may skip the location filter. */
"use strict";

async function renderDreams() {
  const d = (S.dreams = await api("/api/dreams"));
  const chip = (x, i, kind) => `<span class="chip">${esc(x)}<span class="x" data-act="dream-rm" data-kind="${kind}" data-i="${i}" title="Remove"><i class=i-x></i></span></span>`;
  main.innerHTML = `<div class="page"><div class="page-h"><h1>Dream list</h1><span class="sub">Leads that match get the dream flag (it never changes their score) and can skip your search-area limits.</span></div>
    <div class="card" style="margin-bottom:14px"><div class="row"><span class="mono" style="font-size:15px;font-weight:700">${d.flagged}</span><span class="muted">leads flagged as dream right now</span>
      <span class="spacer"></span><button class="btn" data-act="dream-view">View them</button><button class="btn primary" data-act="dream-recheck" title="Re-flag every lead against this list (stars you set by hand are kept)"><i class=i-refresh></i> Re-check all leads</button></div></div>
    <div class="cols" style="grid-template-columns:1fr 1fr">
      <div class="card"><h3>Dream companies</h3>
        <div class="row" style="gap:6px;margin-bottom:10px">${d.companies.map((x, i) => chip(x, i, "companies")).join("") || `<span class="muted small">none yet</span>`}</div>
        <div class="row"><input type="text" id="dc-add" placeholder="Add companies, comma-separated (e.g. Apple, Capital One, Mayo Clinic)" style="flex:1"><button class="btn" data-act="dream-add" data-kind="companies">Add</button></div>
        <div class="hr"></div>
        <b class="small mono">FROM YOUR PROFILE (derived from your resume and answers; removing one drops it for good)</b>
        <div class="row" style="gap:6px;margin:8px 0">${d.profile_companies.map((x) => `<span class="chip blue">${esc(x)}<span class="x" data-act="dream-exclude" data-name="${esc(x)}" title="Remove from dream list"><i class=i-x></i></span></span>`).join("") || `<span class="muted small">none</span>`}</div>
        ${d.excluded.length ? `<b class="small mono">REMOVED</b><div class="row" style="gap:6px;margin:8px 0">${d.excluded.map((x) => `<span class="chip">${esc(x)}<span class="x" data-act="dream-restore" data-name="${esc(x)}" title="Restore"><i class=i-undo></i></span></span>`).join("")}</div>` : ""}
        <div class="row" style="margin-top:10px">${toggle(`data-dbyp="bypass"`, d.bypass)}<span class="small">Dream companies can be anywhere in the US (ignore my search area)</span></div></div>
      <div class="card"><h3>Dream jobs (roles)</h3><p class="muted small" style="margin-top:-4px">Any lead whose title contains one of these phrases is a dream job, at any company.</p>
        <div class="row" style="gap:6px;margin-bottom:10px">${d.jobs.map((x, i) => chip(x, i, "jobs")).join("") || `<span class="muted small">none yet</span>`}</div>
        <div class="row"><input type="text" id="dj-add" placeholder="Add roles, comma-separated (e.g. iOS developer, data engineer, product designer)" style="flex:1"><button class="btn" data-act="dream-add" data-kind="jobs">Add</button></div>
        <div class="row" style="margin-top:14px">${toggle(`data-dbyp="jobs_bypass"`, d.jobs_bypass)}<span class="small">Dream jobs can be anywhere in the US too</span></div></div></div></div>`;
  $$("#dc-add, #dj-add").forEach((inp) => inp.addEventListener("keydown", (e) => { if (e.key === "Enter") inp.nextElementSibling.click(); }));
}
async function saveDreams(patch, msg) {
  S.dreams = await api("/api/dreams", { method: "PUT", body: patch });
  toast("Dream list saved", msg || "Click Re-check all leads to apply it to leads you already have.");
  renderDreams();
}

// ---------------------------------------------------------------- actions
onAction("dream-add", async (el, e) => {
  const kind = el.dataset.kind, inp = $(kind === "companies" ? "#dc-add" : "#dj-add");
  const add = inp.value.split(",").map((x) => x.trim()).filter(Boolean); if (!add.length) return;
  await saveDreams({ [kind]: [...S.dreams[kind], ...add.filter((x) => !S.dreams[kind].some((y) => y.toLowerCase() === x.toLowerCase()))] }, `Added ${add.join(", ")}`); });
onAction("dream-rm", async (el, e) => { const kind = el.dataset.kind, list = [...S.dreams[kind]]; const [gone] = list.splice(+el.dataset.i, 1); await saveDreams({ [kind]: list }, `Removed ${gone}`); });
onAction("dream-exclude", async (el, e) => { await saveDreams({ excluded: [...S.dreams.excluded, el.dataset.name] }, `Removed ${el.dataset.name} from the profile-derived list`); });
onAction("dream-restore", async (el, e) => { await saveDreams({ excluded: S.dreams.excluded.filter((x) => x !== el.dataset.name) }, `Restored ${el.dataset.name}`); });
onAction("dream-recheck", async (el, e) => { const r = await api("/api/dreams/recheck", { method: "POST" }); toast("Leads re-checked", `${r.changed} lead${r.changed === 1 ? "" : "s"} changed, ${r.flagged} flagged as dream`); refreshStats(); renderDreams(); });
onAction("dream-view", async (el, e) => { S.dreamOnly = true; S.leadsTab = "all"; localStorage.setItem("leadsTab", "all"); location.hash = "#/leads"; });
onChange(async (el) => {
  if (!el.dataset.dbyp) return false;  // the "skip the location filter" switches
  await saveDreams({ [el.dataset.dbyp]: el.checked }, el.checked ? "Location bypass on" : "Location bypass off");
  return true;
});
