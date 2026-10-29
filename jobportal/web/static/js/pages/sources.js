/* The Sources page: turn job sources and AI hunt missions on or off, add company job boards, and test a source. */
"use strict";

const SRC_HELP = {
  github_lists: "Community-tracked internship and new-grad lists (SimplifyJobs, vanshb03), thousands of roles updated daily. Used only when internships or entry level are among your levels.",
  ats_boards: "Company job boards through their public APIs: tech, fintech, health, aerospace, defense and more. Add any company by pasting its careers URL.",
  linkedin: "LinkedIn's public job search (no login): your search queries in your locations, filtered to your experience levels.",
  usajobs: "U.S. federal jobs, including Pathways and student roles. Needs a free API key from developer.usajobs.gov/apirequest.",
  hackernews: "The monthly 'Who is hiring?' threads plus a search of recent HN comments that mention roles at your level.",
  bluesky: "Searches Bluesky posts for hiring announcements. Needs your handle and a free app password (Bluesky settings, Privacy and security, App passwords).",
  themuse: "The Muse listings at your levels in your locations.",
  reddit: "Reddit search feeds across the hiring and career subreddits below. Reddit rate-limits hard; the AI social mission covers more.",
  mastodon: "Hiring hashtags on Mastodon instances.",
  remote_boards: "Remotive and RemoteOK (only when Remote is one of your locations).",
  rss: "Any RSS or Atom feed. Tip: create Google Alerts (e.g. “data analyst jobs Austin”) delivered as an RSS feed and paste the feed URLs here.",
  adzuna: "Adzuna aggregator (indexes many boards). Free key at developer.adzuna.com.",
  serpapi: "Google Jobs results through SerpAPI (100 free searches a month at serpapi.com).",
};
async function renderSources(cfgOverride) {
  S.cfg = cfgOverride && typeof cfgOverride === "object" ? cfgOverride : await api("/api/settings");
  const plan = (await api("/api/profile")).search_plan || {};
  const c = S.cfg, src = c.sources;
  const field = (path, label, type = "text", extra = "") => `<label class="f"><span>${label}</span><input type="${type}" data-path="${path}" value="${esc(getPath(c, path) ?? "")}" ${extra}></label>`;
  const list = (path, label, rows = 4) => `<label class="f"><span>${label}</span><textarea data-list="${path}" rows="${rows}">${esc((getPath(c, path) || []).map((x) => (typeof x === "object" ? `${x.name || ""} | ${x.url}` : x)).join("\n"))}</textarea></label>`;
  const cfgFor = {
    github_lists: list("sources.github_lists.urls", "listings.json URLs (one per line)", 3),
    ats_boards: `<div class="row"><input type="url" id="det-url" placeholder="Paste any careers page or job URL to add that company…" style="flex:1"><input type="text" id="det-name" placeholder="Company name" style="width:200px"><button class="btn" data-act="detect">Detect & add</button></div><div id="det-res" class="small muted"></div>
      <div class="boards"><table class="t"><thead><tr><th></th><th>Company</th><th>ATS</th><th>Slug / URL</th><th title="Dream company"><i class=i-star></i></th><th></th></tr></thead><tbody>
      ${src.ats_boards.boards.map((b, i) => `<tr><td>${toggle(`data-board="${i}" data-bf="enabled"`, b.enabled !== false)}</td><td><input type="text" data-board="${i}" data-bf="name" value="${esc(b.name)}"></td>
        <td class="mono small">${esc(b.ats)}</td><td><input type="text" data-board="${i}" data-bf="${b.slug ? "slug" : "url"}" value="${esc(b.slug || b.url)}"></td>
        <td>${toggle(`data-board="${i}" data-bf="dream"`, !!b.dream)}</td><td><button class="btn sm ghost danger" data-act="rm-board" data-i="${i}"><i class=i-x></i></button></td></tr>`).join("")}</tbody></table></div>`,
    linkedin: `<div class="grid3">${field("sources.linkedin.max_requests", "Max searches per run", "number")}
      <label class="f"><span>Posted within</span><select data-path="sources.linkedin.time_window">${[["r86400", "24 hours"], ["r604800", "1 week"], ["r2592000", "1 month"]].map(([v, l]) => `<option value="${v}" ${src.linkedin.time_window === v ? "selected" : ""}>${l}</option>`).join("")}</select></label>
      ${field("sources.linkedin.experience", "Experience filter (blank = your levels)", "text", 'placeholder="1 intern, 2 entry, 3 associate, 4 mid-senior"')}</div>`,
    usajobs: `<div class="grid2">${field("sources.usajobs.api_key", "API key", "password")}${field("sources.usajobs.email", "Email used to register", "email")}</div>`,
    hackernews: field("sources.hackernews.threads", "Monthly threads to scan", "number"),
    themuse: field("sources.themuse.pages", "Pages per run", "number"),
    mastodon: `<div class="grid2">${list("sources.mastodon.instances", "Instances", 3)}${list("sources.mastodon.tags", "Hashtags", 3)}</div>`,
    reddit: list("sources.reddit.subreddits", "Subreddits (one per line, without r/)", 4),
    rss: `<label class="f"><span>Feeds: one per line, “name | url” or just the url</span><textarea data-feeds="1" rows="4">${esc((src.rss.feeds || []).map((f) => (typeof f === "object" ? `${f.name} | ${f.url}` : f)).join("\n"))}</textarea></label>`,
    adzuna: `<div class="grid2">${field("sources.adzuna.app_id", "App ID")}${field("sources.adzuna.app_key", "App key", "password")}</div>`,
    serpapi: field("sources.serpapi.api_key", "API key", "password"),
    bluesky: `<div class="grid2">${field("sources.bluesky.handle", "Handle (you.bsky.social)")}${field("sources.bluesky.app_password", "App password", "password")}</div>`,
  };
  main.innerHTML = `<div class="page"><div class="page-h"><h1>Sources</h1><span class="sub">Where the search looks. Locations and filters live in Settings.</span></div>
    <div class="card" style="margin-bottom:16px"><h3>Search queries <span class="muted">(LinkedIn, The Muse, aggregators)</span></h3>
      <div class="row" style="margin-bottom:8px">${toggle(`data-path="search.use_profile_plan" data-bool="1"`, c.search.use_profile_plan !== false)}<span class="small">Use the ${(plan.queries || []).length} queries from your profile's search plan</span><a class="small" href="#/profile/search_plan">edit search plan →</a></div>
      <div class="row" style="gap:5px;margin-bottom:12px">${(plan.queries || []).map((q) => `<span class="chip">${esc(q)}</span>`).join("")}</div>
      ${list("search.queries", "Your extra queries (one per line)", 4)}</div>
    <div class="card" style="margin-bottom:16px"><h3>Job sources</h3>
      ${S.meta.collectors.map(({ key, label }) => `<div class="src">${toggle(`data-path="sources.${key}.enabled" data-bool="1"`, src[key]?.enabled)}
        <div><div class="name">${esc(label)}</div><div class="desc">${esc(SRC_HELP[key] || "")}</div>${cfgFor[key] ? `<div class="cfg">${cfgFor[key]}</div>` : ""}<div id="tr-${key}"></div></div>
        <button class="btn sm" data-act="test-src" data-key="${key}">Test</button></div>`).join("")}</div>
    <div class="card"><h3>AI hunt missions</h3><p class="muted small" style="margin-top:-4px">Each mission is an AI agent with web tools that digs where no API reaches: social posts, comment threads, insiders' LinkedIn posts, forums, niche boards, recruiters, labs, campus pipelines, local news, contract awards and events. Every mission reads your profile, so it searches for your roles in your locations. “AI hunt only” runs every mission; “Everything” rotates through them so each run fits your usage window. Edit freely or add your own.</p>
      <div class="row" style="margin-bottom:12px">${toggle(`data-path="sources.ai_hunt.enabled" data-bool="1"`, src.ai_hunt.enabled)}<span class="small">AI hunting enabled</span>
        <label class="row small" style="gap:6px;margin-left:14px">Per “Everything” run <select data-path="sources.ai_hunt.missions_per_run" data-num="1" style="width:auto">${[[0, "all missions"], [4, "4 (rotate)"], [7, "7 (rotate)"], [10, "10 (rotate)"]].map(([v, l]) => `<option value="${v}" ${(+src.ai_hunt.missions_per_run || 0) === v ? "selected" : ""}>${l}</option>`).join("")}</select></label>
        <label class="row small" style="gap:6px;margin-left:14px">Depth <select data-path="sources.ai_hunt.depth" style="width:auto">${[["deep", "Deep (30+ searches each)"], ["standard", "Standard (~15)"], ["quick", "Quick (~8)"]].map(([v, l]) => `<option value="${v}" ${(src.ai_hunt.depth || "standard") === v ? "selected" : ""}>${l}</option>`).join("")}</select></label><span class="spacer"></span>
        <button class="btn sm" data-act="add-mission">+ New mission</button><button class="btn sm ghost" data-act="reset-missions">Reset to defaults</button></div>
      <div class="stack" id="missions">${src.ai_hunt.missions.map((m, i) => `<div class="mission-ed"><div class="row">${toggle(`data-mission="${i}" data-mf="enabled"`, m.enabled !== false)}
        <input type="text" data-mission="${i}" data-mf="name" value="${esc(m.name)}" style="flex:1;font-weight:600">${m.only_levels ? `<span class="chip" title="Runs only when you search at these levels">${esc(m.only_levels.join(" and "))} only</span>` : ""}<button class="btn sm ghost danger" data-act="rm-mission" data-i="${i}"><i class=i-x></i></button></div>
        <textarea data-mission="${i}" data-mf="prompt" rows="4" style="font-family:var(--sans);font-size:13px">${esc(m.prompt)}</textarea></div>`).join("")}</div></div>
    <div class="sticky-save"><button class="btn primary" data-act="save-cfg">Save sources</button></div></div>`;
  bindCfgInputs();
}
function bindCfgInputs() {
  main.oninput = main.onchange = (e) => {
    const t = e.target, c = S.cfg;
    if (t.dataset.path) setPath(c, t.dataset.path, t.dataset.bool || t.type === "checkbox" ? t.checked : t.type === "number" || t.dataset.num ? +t.value : t.value);
    else if (t.dataset.list) setPath(c, t.dataset.list, t.value.split("\n").map((x) => x.trim()).filter(Boolean));
    else if (t.dataset.feeds) c.sources.rss.feeds = t.value.split("\n").map((x) => x.trim()).filter(Boolean).map((x) => { const [a, b] = x.includes("|") ? x.split("|").map((s) => s.trim()) : [x, x]; return { name: a, url: b }; });
    else if (t.dataset.board != null) c.sources.ats_boards.boards[+t.dataset.board][t.dataset.bf] = t.type === "checkbox" ? t.checked : t.value;
    else if (t.dataset.mission != null) c.sources.ai_hunt.missions[+t.dataset.mission][t.dataset.mf] = t.type === "checkbox" ? t.checked : t.value;
    else if (t.dataset.chips) return;
    else return;
    S.cfgDirty = true;
  };
}
async function saveCfg() {
  S.cfg = await api("/api/settings", { method: "PUT", body: S.cfg });
  S.cfgDirty = false; S.locAllowed = S.cfg.locations.allowed; S.industries = S.cfg.industries; toast("Saved", "Settings updated");
}
function renderSourcesKeep() { S.cfgDirty = true; renderSources(S.cfg); }

// ---------------------------------------------------------------- actions
onAction("test-src", async (el, e) => {
  const key = el.dataset.key, box = $(`#tr-${key}`);
  if (S.cfgDirty) await saveCfg();
  box.innerHTML = `<div class="testres"><span class="spin"></span> testing…</div>`;
  const r = await api(`/api/sources/test/${key}`, { method: "POST" });
  box.innerHTML = `<div class="testres">${r.ok ? `<b>${r.found}</b> found, <b>${r.pass_filters}</b> pass your filters<br>${r.sample.map((s) => `• ${esc(s.title)}, ${esc(s.company)} (${esc(s.location)})`).join("<br>")}` : `<span style="color:var(--bad)">${esc(r.error)}</span>`}${r.logs?.length ? `<br><span class="muted">${r.logs.map(esc).join("<br>")}</span>` : ""}</div>`;
});
onAction("detect", async (el, e) => {
  const res = $("#det-res"); res.textContent = "detecting…";
  const r = await api("/api/sources/detect", { method: "POST", body: { url: $("#det-url").value, name: $("#det-name").value } });
  if (r.ok) { S.cfg.sources.ats_boards.boards.unshift({ ...r.board, name: r.board.name || $("#det-name").value || r.board.slug || "New company" }); await saveCfg(); toast("Company added", `${r.count} postings, ${r.board.ats}`); renderSources(); }
  else res.textContent = r.message;
});
onAction("rm-board", async (el, e) => { S.cfg.sources.ats_boards.boards.splice(+el.dataset.i, 1); S.cfgDirty = true; renderSourcesKeep(); });
onAction("add-mission", async (el, e) => { S.cfg.sources.ai_hunt.missions.push({ id: "m" + Date.now(), name: "New mission", enabled: true, prompt: "Describe where to look and what to find…" }); renderSourcesKeep(); });
onAction("rm-mission", async (el, e) => { if (confirm("Delete this mission?")) { S.cfg.sources.ai_hunt.missions.splice(+el.dataset.i, 1); renderSourcesKeep(); } });
onAction("reset-missions", async (el, e) => { if (confirm("Reset all missions to the built-in defaults?")) { await api("/api/settings/reset", { method: "POST", body: { path: "sources.ai_hunt.missions" } }); renderSources(); } });
