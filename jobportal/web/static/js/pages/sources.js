/* sources.js: the Sources page. Turn job sources and AI hunt missions on or off, set their options, add company job
   boards, and test a source. Locations and filters live in Settings.
   APIs: GET /api/settings and PUT /api/settings (through S.cfg and saveCfg, see components/settings-form.js),
   GET /api/profile (the search plan's queries), POST /api/sources/test/{key}, POST /api/sources/detect and
   POST /api/settings/reset. */
"use strict";

// The description under each source, by its key in S.meta.collectors.
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

// Draws the page. keepEdits = redraw from the S.cfg being edited instead of loading the saved settings.
async function renderSources(keepEdits = false) {
  if (!keepEdits) {
    S.cfg = await api("/api/settings");
    S.cfgDirty = false;
  }
  const plan = (await api("/api/profile")).search_plan || {};
  const queries = plan.queries || [];
  const src = S.cfg.sources;
  const options = sourceOptions(src);
  const sourceRow = ({ key, label }) => `<div class="src">${toggle(`data-path="sources.${key}.enabled" data-bool="1"`, src[key]?.enabled)}
        <div><div class="name">${esc(label)}</div><div class="desc">${esc(SRC_HELP[key] || "")}</div>${options[key] ? `<div class="cfg">${options[key]}</div>` : ""}<div id="tr-${key}"></div></div>
        <button class="btn sm" data-act="test-src" data-key="${key}">Test</button></div>`;
  main.innerHTML = `<div class="page"><div class="page-h"><h1>Sources</h1><span class="sub">Where the search looks. Locations and filters live in Settings.</span></div>
    <div class="card" style="margin-bottom:16px"><h3>Search queries <span class="muted">(LinkedIn, The Muse, aggregators)</span></h3>
      <div class="row" style="margin-bottom:8px">${toggle(`data-path="search.use_profile_plan" data-bool="1"`, S.cfg.search.use_profile_plan !== false)}
        <span class="small">Use the ${queries.length} queries from your profile's search plan</span><a class="small" href="#/profile/search_plan">edit search plan →</a></div>
      <div class="row" style="gap:5px;margin-bottom:12px">${queries.map((q) => `<span class="chip">${esc(q)}</span>`).join("")}</div>
      ${cfgLines("search.queries", "Your extra queries (one per line)", 4)}</div>
    <div class="card" style="margin-bottom:16px"><h3>Job sources</h3>
      ${S.meta.collectors.map(sourceRow).join("")}</div>
    ${missionsCard(src.ai_hunt)}
    <div class="sticky-save"><button class="btn primary" data-act="save-cfg">Save sources</button></div></div>`;
}

// The options under each source that has some, by source key.
function sourceOptions(src) {
  const boardRow = (b, i) => `<tr><td>${toggle(`data-board="${i}" data-bf="enabled"`, b.enabled !== false)}</td><td><input type="text" data-board="${i}" data-bf="name" value="${esc(b.name)}"></td>
        <td class="mono small">${esc(b.ats)}</td><td><input type="text" data-board="${i}" data-bf="${b.slug ? "slug" : "url"}" value="${esc(b.slug || b.url)}"></td>
        <td>${toggle(`data-board="${i}" data-bf="dream"`, !!b.dream)}</td><td><button class="btn sm ghost danger" data-act="rm-board" data-i="${i}"><i class=i-x></i></button></td></tr>`;
  const timeWindows = [["r86400", "24 hours"], ["r604800", "1 week"], ["r2592000", "1 month"]];  // LinkedIn's "posted within" codes
  const feeds = (src.rss.feeds || []).map((f) => (typeof f === "object" ? `${f.name} | ${f.url}` : f)).join("\n");
  return {
    github_lists: cfgLines("sources.github_lists.urls", "listings.json URLs (one per line)", 3),
    ats_boards: `<div class="row"><input type="url" id="det-url" placeholder="Paste any careers page or job URL to add that company…" style="flex:1">
        <input type="text" id="det-name" placeholder="Company name" style="width:200px"><button class="btn" data-act="detect">Detect & add</button></div>
      <div id="det-res" class="small muted"></div>
      <div class="boards"><table class="t"><thead><tr><th></th><th>Company</th><th>ATS</th><th>Slug / URL</th><th title="Dream company"><i class=i-star></i></th><th></th></tr></thead><tbody>
      ${src.ats_boards.boards.map(boardRow).join("")}</tbody></table></div>`,
    linkedin: `<div class="grid3">${cfgInput("sources.linkedin.max_requests", "Max searches per run", "number")}
      <label class="f"><span>Posted within</span><select data-path="sources.linkedin.time_window">${selectOptions(timeWindows, src.linkedin.time_window)}</select></label>
      ${cfgInput("sources.linkedin.experience", "Experience filter (blank = your levels)", "text", 'placeholder="1 intern, 2 entry, 3 associate, 4 mid-senior"')}</div>`,
    usajobs: `<div class="grid2">${cfgInput("sources.usajobs.api_key", "API key", "password")}${cfgInput("sources.usajobs.email", "Email used to register", "email")}</div>`,
    hackernews: cfgInput("sources.hackernews.threads", "Monthly threads to scan", "number"),
    themuse: cfgInput("sources.themuse.pages", "Pages per run", "number"),
    mastodon: `<div class="grid2">${cfgLines("sources.mastodon.instances", "Instances", 3)}${cfgLines("sources.mastodon.tags", "Hashtags", 3)}</div>`,
    reddit: cfgLines("sources.reddit.subreddits", "Subreddits (one per line, without r/)", 4),
    rss: `<label class="f"><span>Feeds: one per line, “name | url” or just the url</span><textarea data-feeds="1" rows="4">${esc(feeds)}</textarea></label>`,
    adzuna: `<div class="grid2">${cfgInput("sources.adzuna.app_id", "App ID")}${cfgInput("sources.adzuna.app_key", "App key", "password")}</div>`,
    serpapi: cfgInput("sources.serpapi.api_key", "API key", "password"),
    bluesky: `<div class="grid2">${cfgInput("sources.bluesky.handle", "Handle (you.bsky.social)")}${cfgInput("sources.bluesky.app_password", "App password", "password")}</div>`,
  };
}

// The AI hunt missions card: the master switch, how many missions an "Everything" run takes, how deep each digs, and
// every mission's name and prompt.
function missionsCard(hunt) {
  const perRun = [[0, "all missions"], [4, "4 (rotate)"], [7, "7 (rotate)"], [10, "10 (rotate)"]];
  const depths = [["deep", "Deep (30+ searches each)"], ["standard", "Standard (~15)"], ["quick", "Quick (~8)"]];
  const mission = (m, i) => `<div class="mission-ed"><div class="row">${toggle(`data-mission="${i}" data-mf="enabled"`, m.enabled !== false)}
        <input type="text" data-mission="${i}" data-mf="name" value="${esc(m.name)}" style="flex:1;font-weight:600">
        ${m.only_levels ? `<span class="chip" title="Runs only when you search at these levels">${esc(m.only_levels.join(" and "))} only</span>` : ""}
        <button class="btn sm ghost danger" data-act="rm-mission" data-i="${i}"><i class=i-x></i></button></div>
        <textarea data-mission="${i}" data-mf="prompt" rows="4" style="font-size:13px">${esc(m.prompt)}</textarea></div>`;
  return `<div class="card"><h3>AI hunt missions</h3><p class="muted small" style="margin-top:-4px">Each mission is an AI agent with web tools that digs where
      no API reaches: social posts, comment threads, insiders' LinkedIn posts, forums, niche boards, recruiters, labs, campus pipelines, local
      news, contract awards and events. Every mission reads your profile, so it searches for your roles in your locations. “AI hunt only”
      runs every mission; “Everything” rotates through them so each run fits your usage window. Edit freely or add your own.</p>
      <div class="row" style="margin-bottom:12px">${toggle(`data-path="sources.ai_hunt.enabled" data-bool="1"`, hunt.enabled)}<span class="small">AI hunting enabled</span>
        <label class="row small" style="gap:6px;margin-left:14px">Per “Everything” run <select data-path="sources.ai_hunt.missions_per_run" data-num="1"
          style="width:auto">${selectOptions(perRun, +hunt.missions_per_run || 0)}</select></label>
        <label class="row small" style="gap:6px;margin-left:14px">Depth <select data-path="sources.ai_hunt.depth" style="width:auto">${selectOptions(depths, hunt.depth || "standard")}</select></label>
        <span class="spacer"></span>
        <button class="btn sm" data-act="add-mission">+ New mission</button><button class="btn sm ghost" data-act="reset-missions">Reset to defaults</button></div>
      <div class="stack" id="missions">${hunt.missions.map(mission).join("")}</div></div>`;
}

// Redraws after adding or removing a board or mission. The change isn't saved yet.
function redrawSources() {
  S.cfgDirty = true;
  renderSources(true);
}

// ---------------------------------------------------------------- actions
onAction("test-src", async (el) => {  // runs one source now (unsaved edits are saved first) and shows a sample
  const key = el.dataset.key, box = $(`#tr-${key}`);
  if (S.cfgDirty) await saveCfg();
  box.innerHTML = `<div class="testres"><span class="spin"></span> testing…</div>`;
  let r;
  try {
    r = await api(`/api/sources/test/${key}`, { method: "POST" });
  } catch (err) {
    box.innerHTML = "";
    throw err;
  }
  const found = r.ok
    ? `<b>${r.found}</b> found, <b>${r.pass_filters}</b> pass your filters<br>${r.sample.map((s) => `• ${esc(s.title)}, ${esc(s.company)} (${esc(s.location)})`).join("<br>")}`
    : `<span style="color:var(--bad)">${esc(r.error)}</span>`;
  const logs = r.logs?.length ? `<br><span class="muted">${r.logs.map(esc).join("<br>")}</span>` : "";
  box.innerHTML = `<div class="testres">${found}${logs}</div>`;
});
onAction("detect", async () => {  // finds the job board behind a careers URL and adds the company
  const result = $("#det-res");
  result.textContent = "detecting…";
  let r;
  try {
    r = await api("/api/sources/detect", { method: "POST", body: { url: $("#det-url").value, name: $("#det-name").value } });
  } catch (err) {
    result.textContent = "";
    throw err;
  }
  if (!r.ok) {
    result.textContent = r.message;
    return;
  }
  S.cfg.sources.ats_boards.boards.unshift({ ...r.board, name: r.board.name || $("#det-name").value || r.board.slug || "New company" });
  await saveCfg();
  toast("Company added", `${r.count} postings, ${r.board.ats}`);
  renderSources();
});
onAction("rm-board", (el) => {
  S.cfg.sources.ats_boards.boards.splice(+el.dataset.i, 1);
  redrawSources();
});
onAction("add-mission", () => {
  S.cfg.sources.ai_hunt.missions.push({ id: "m" + Date.now(), name: "New mission", enabled: true, prompt: "Describe where to look and what to find…" });
  redrawSources();
});
onAction("rm-mission", (el) => {
  if (!confirm("Delete this mission?")) return;
  S.cfg.sources.ai_hunt.missions.splice(+el.dataset.i, 1);
  redrawSources();
});
onAction("reset-missions", async () => {
  if (!confirm("Reset all missions to the built-in defaults?")) return;
  await api("/api/settings/reset", { method: "POST", body: { path: "sources.ai_hunt.missions" } });
  renderSources();
});
