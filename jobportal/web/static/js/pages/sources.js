/* sources.js: the Sources dialog, opened from Leads. Where the search looks: turn each job source on or off (with how
   many leads it has brought in), set its options, test it, add company job boards, keep your own feeds and subreddits,
   choose the search terms, and edit the AI hunt missions.
   APIs: GET /api/settings and PUT /api/settings (through S.cfg and saveCfg, see components/settings-form.js),
   GET /api/profile (the search plan's terms), GET /api/analysis (leads per source), POST /api/sources/test/{key},
   POST /api/sources/detect and POST /api/settings/reset. */
"use strict";

// What each source is, by its key in S.meta.collectors.
const SRC_HELP = {
  github_lists: "Community-kept lists of internships and new-graduate jobs, updated daily. Used only when you search for internships or entry-level jobs.",
  ats_boards: "The job boards of specific companies, read directly. Add any company by pasting its careers page.",
  linkedin: "LinkedIn's public job search (no sign-in): your search terms in your search area, at your experience levels.",
  usajobs: "U.S. government jobs, including student programs. Needs a free key from developer.usajobs.gov.",
  hackernews: "The monthly hiring threads on Hacker News, plus recent comments that mention jobs at your level.",
  bluesky: "Hiring posts on Bluesky. Needs your handle and a free app password (Bluesky settings, Privacy and security, App passwords).",
  themuse: "Listings from The Muse at your levels, in your search area.",
  reddit: "Job posts in the subreddits below. Reddit limits how often it can be read, so the AI hunt covers more of it.",
  mastodon: "Hiring hashtags on Mastodon.",
  remote_boards: "Remotive and RemoteOK, when Remote is part of your search area.",
  rss: "Any RSS or Atom feed. Tip: set up a Google Alert for the jobs you want, delivered as a feed, and paste its link here.",
  adzuna: "A job search site that gathers listings from many boards. Needs a free key from developer.adzuna.com.",
  serpapi: "Google's job results through SerpAPI (100 free searches a month at serpapi.com).",
};
// The source name its leads carry (lead.source), by source key, for the counts.
const COLLECTOR_SOURCE = { github_lists: "github", ats_boards: "ats", linkedin: "linkedin", usajobs: "usajobs", hackernews: "hackernews",
  themuse: "themuse", reddit: "reddit", mastodon: "mastodon", bluesky: "bluesky", remote_boards: "remote", rss: "rss", adzuna: "adzuna", serpapi: "google" };

// What the dialog shows besides the settings: the search plan's terms and the leads per source.
let sourcesInfo = { queries: [], counts: {} };

// Opens the dialog with the saved settings.
async function openSources() {
  const [, profile, analysis] = await Promise.all([loadCfg(), api("/api/profile").catch(() => ({})), api("/api/analysis").catch(() => null)]);
  sourcesInfo = { queries: profile.search_plan?.queries || [], counts: Object.fromEntries((analysis?.market?.sources || []).map((x) => [x.source, x])) };
  const dialog = openDialog(`<div class="sources-form" data-cfg></div>`, { eyebrow: "SOURCES", wide: true, guard: true });
  dialog.classList.add("sources-dialog");
  drawSources();
}

// Draws the dialog from S.cfg as it is now, edits included.
function drawSources() {
  const box = $(".sources-dialog .sources-form");
  if (!box) return;
  const src = S.cfg.sources, options = sourceOptions(src);
  const sourceRow = ({ key, label }) => {
    const count = sourcesInfo.counts[COLLECTOR_SOURCE[key]];
    const brought = count ? `<span class="tag">${plural(count.triaged, "lead")}, ${count.qualified} good ${count.qualified === 1 ? "fit" : "fits"}</span>` : "";
    return `<div class="source-row">${toggle(`data-path="sources.${key}.enabled" data-bool="1" aria-label="${esc(label)}"`, src[key]?.enabled)}
      <div class="source-body"><div class="source-name"><b>${esc(label)}</b>${brought}</div><p>${esc(SRC_HELP[key] || "")}</p>
        ${options[key] ? `<div class="source-options">${options[key]}</div>` : ""}<div data-test="${key}"></div></div>
      <button class="button outline small" type="button" data-act="test-src" data-key="${key}">Test</button></div>`;
  };
  const queries = sourcesInfo.queries;
  box.innerHTML = `<h2>Sources</h2><p>Where JobPortal looks for jobs. Changes count from the next search.</p>
    <section class="block"><div class="block-head"><h3>Search terms</h3></div>
      ${cfgSwitch("search.use_profile_plan", `Use the ${plural(queries.length, "search term")} from your profile's search plan`, S.cfg.search.use_profile_plan !== false)}
      <div class="tags">${queries.map((q) => `<span class="tag">${esc(q)}</span>`).join("")}</div>
      <p class="block-note">Change them under <a href="#/settings/search">Settings, Search</a>.</p>
      ${cfgLines("search.queries", "Your own search terms (one per line)", 4)}</section>
    <section class="block"><div class="block-head"><h3>Job sources</h3></div>${S.meta.collectors.map(sourceRow).join("")}</section>
    ${missionsBlock(src.ai_hunt)}
    <div class="dialog-actions sticky"><button class="button outline" type="button" data-act="close-dialog">Cancel</button>
      <button class="button primary" type="button" data-act="save-sources">Save sources</button></div>`;
}

// The options under each source that has some, by source key.
function sourceOptions(src) {
  const boardRow = (b, i) => `<tr><td>${toggle(`data-board="${i}" data-bf="enabled" aria-label="Search ${esc(b.name)}"`, b.enabled !== false)}</td>
      <td><input type="text" data-board="${i}" data-bf="name" value="${esc(b.name)}" aria-label="Company"></td><td class="nowrap">${esc(b.ats)}</td>
      <td><input type="text" data-board="${i}" data-bf="${b.slug ? "slug" : "url"}" value="${esc(b.slug || b.url)}" aria-label="Board id or link"></td>
      <td>${toggle(`data-board="${i}" data-bf="dream" aria-label="${esc(b.name)} is a dream company"`, !!b.dream)}</td>
      <td><button class="icon-button" type="button" data-act="rm-board" data-i="${i}" aria-label="Remove ${esc(b.name)}">${icon("trash")}</button></td></tr>`;
  const timeWindows = [["r86400", "24 hours"], ["r604800", "1 week"], ["r2592000", "1 month"]];  // LinkedIn's "posted within" codes
  const feeds = (src.rss.feeds || []).map((f) => (typeof f === "object" ? `${f.name} | ${f.url}` : f)).join("\n");
  return {
    github_lists: cfgLines("sources.github_lists.urls", "List addresses (one per line)", 3),
    ats_boards: `<div class="inline-form"><input type="url" id="detect-url" placeholder="Paste a company's careers page or any of its job links" aria-label="Careers page">
        <input type="text" id="detect-name" placeholder="Company name" aria-label="Company name"><button class="button light" type="button" data-act="detect">Find and add</button></div>
      <p class="block-note" id="detect-result"></p>
      <div class="table-wrap boards"><table class="table"><thead><tr><th><span class="sr-only">On</span></th><th>Company</th><th>System</th><th>Board id or link</th>
        <th title="Dream company">Dream</th><th><span class="sr-only">Remove</span></th></tr></thead><tbody>${src.ats_boards.boards.map(boardRow).join("")}</tbody></table></div>`,
    linkedin: `<div class="form-grid three">${cfgInput("sources.linkedin.max_requests", "Searches per run", "number")}
      <label class="field"><span class="field-label">Posted within</span><select data-path="sources.linkedin.time_window">${selectOptions(timeWindows, src.linkedin.time_window)}</select></label>
      ${cfgInput("sources.linkedin.experience", "Experience filter (blank: your levels)", "text", 'placeholder="1 intern, 2 entry, 3 associate, 4 mid-senior"')}</div>`,
    usajobs: `<div class="form-grid">${cfgInput("sources.usajobs.api_key", "API key", "password")}${cfgInput("sources.usajobs.email", "Email you registered with", "email")}</div>`,
    hackernews: cfgInput("sources.hackernews.threads", "Monthly threads to read", "number"),
    themuse: cfgInput("sources.themuse.pages", "Pages per run", "number"),
    mastodon: `<div class="form-grid">${cfgLines("sources.mastodon.instances", "Servers", 3)}${cfgLines("sources.mastodon.tags", "Hashtags", 3)}</div>`,
    reddit: cfgLines("sources.reddit.subreddits", "Subreddits (one per line, without r/)", 4),
    rss: `<label class="field"><span class="field-label">Feeds: one per line, "name | link" or just the link</span><textarea data-feeds="1" rows="4">${esc(feeds)}</textarea></label>`,
    adzuna: `<div class="form-grid">${cfgInput("sources.adzuna.app_id", "App ID")}${cfgInput("sources.adzuna.app_key", "App key", "password")}</div>`,
    serpapi: cfgInput("sources.serpapi.api_key", "API key", "password"),
    bluesky: `<div class="form-grid">${cfgInput("sources.bluesky.handle", "Handle (you.bsky.social)")}${cfgInput("sources.bluesky.app_password", "App password", "password")}</div>`,
  };
}

// The AI hunt missions: the main switch, how many missions an "everything" search takes, how deep each digs, and every
// mission's name and instructions.
function missionsBlock(hunt) {
  const perRun = [[0, "every mission"], [4, "4, taking turns"], [7, "7, taking turns"], [10, "10, taking turns"]];
  const depths = [["deep", "Deep (30 or more searches each)"], ["standard", "Standard (about 15)"], ["quick", "Quick (about 8)"]];
  const mission = (m, i) => `<div class="mission"><div class="inline-form">${toggle(`data-mission="${i}" data-mf="enabled" aria-label="Use this mission"`, m.enabled !== false)}
        <input type="text" data-mission="${i}" data-mf="name" value="${esc(m.name)}" aria-label="Mission name">
        ${m.only_levels ? `<span class="tag" title="Runs only when you search at these levels">${esc(m.only_levels.join(" and "))} only</span>` : ""}
        <button class="icon-button" type="button" data-act="rm-mission" data-i="${i}" aria-label="Delete this mission">${icon("trash")}</button></div>
      <textarea data-mission="${i}" data-mf="prompt" rows="4" aria-label="What this mission looks for">${esc(m.prompt)}</textarea></div>`;
  return `<section class="block"><div class="block-head"><h3>AI hunt missions</h3>
      <button class="button outline small" type="button" data-act="add-mission">${icon("plus")}New mission</button>
      <button class="button text small" type="button" data-act="reset-missions">Back to the defaults</button></div>
    <p class="block-note">Each mission is an AI agent that searches the web where job sites don't reach: social posts, forums, niche boards,
      recruiters, local news and events. Every mission reads your profile, so it looks for your kind of work in your area. "AI hunt only"
      runs every mission; "Run everything" takes turns through them so each search fits your plan's limits.</p>
    <div class="form-grid three">${cfgSwitch("sources.ai_hunt.enabled", "AI hunting on", hunt.enabled)}
      <label class="field"><span class="field-label">Missions per "Run everything"</span><select data-path="sources.ai_hunt.missions_per_run" data-num="1">${selectOptions(perRun, +hunt.missions_per_run || 0)}</select></label>
      <label class="field"><span class="field-label">How deep</span><select data-path="sources.ai_hunt.depth">${selectOptions(depths, hunt.depth || "standard")}</select></label></div>
    <div class="stack">${hunt.missions.map(mission).join("")}</div></section>`;
}

// ---------------------------------------------------------------- actions
onAction("sources", () => openSources());
onAction("save-sources", async (el) => {
  await saveCfg();
  closeDialog(el.closest("dialog"));
});
onAction("test-src", async (el) => {  // runs one source now (unsaved edits are saved first) and shows what it found
  const key = el.dataset.key, box = $(`[data-test="${key}"]`);
  if (S.cfgDirty) await saveCfg();
  box.innerHTML = `<div class="test-result">${spinner()} Testing</div>`;
  let r;
  try {
    r = await api(`/api/sources/test/${key}`, { method: "POST" });
  } catch (err) {
    box.innerHTML = "";
    throw err;
  }
  const found = r.ok
    ? `<b>${r.found}</b> found, <b>${r.pass_filters}</b> pass your filters<ul>${r.sample.map((s) => `<li>${esc(s.title)}, ${esc(s.company)} (${esc(s.location)})</li>`).join("")}</ul>`
    : `<span class="bad">${esc(r.error)}</span>`;
  const logs = r.logs?.length ? `<div class="test-log">${r.logs.map(esc).join("<br>")}</div>` : "";
  box.innerHTML = `<div class="test-result">${found}${logs}</div>`;
});
onAction("detect", async () => {  // finds the job board behind a careers page and adds the company
  const result = $("#detect-result");
  result.textContent = "Looking";
  let r;
  try {
    r = await api("/api/sources/detect", { method: "POST", body: { url: $("#detect-url").value, name: $("#detect-name").value } });
  } catch (err) {
    result.textContent = "";
    throw err;
  }
  if (!r.ok) {
    result.textContent = r.message;
    return;
  }
  S.cfg.sources.ats_boards.boards.unshift({ ...r.board, name: r.board.name || $("#detect-name").value || r.board.slug || "New company" });
  markCfgEdit("sources.ats_boards.boards");
  await saveCfg();
  toast("Company added", `${plural(r.count, "job")} on its board (${r.board.ats}).`);
  drawSources();
});
onAction("rm-board", (el) => {
  S.cfg.sources.ats_boards.boards.splice(+el.dataset.i, 1);
  markCfgEdit("sources.ats_boards.boards");
  drawSources();
});
onAction("add-mission", () => {
  S.cfg.sources.ai_hunt.missions.push({ id: "m" + Date.now(), name: "New mission", enabled: true, prompt: "Say where to look and what to find." });
  markCfgEdit("sources.ai_hunt.missions");
  drawSources();
});
onAction("rm-mission", (el) => {
  if (!confirm("Delete this mission?")) return;
  S.cfg.sources.ai_hunt.missions.splice(+el.dataset.i, 1);
  markCfgEdit("sources.ai_hunt.missions");
  drawSources();
});
onAction("reset-missions", async () => {
  if (!confirm("Put every mission back to the built-in ones?")) return;
  const fresh = await api("/api/settings/reset", { method: "POST", body: { path: "sources.ai_hunt.missions" } });
  S.cfg.sources.ai_hunt.missions = fresh.sources.ai_hunt.missions;
  S.cfgEdits.delete("sources.ai_hunt.missions");
  drawSources();
});
