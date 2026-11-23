/* sources.js: the Sources menu, a large dialog opened from Leads: where the search looks. Down the left, the groups (a click
   jumps to one). On the right, one line per source with its switch, what it has brought in, a Test button and, when it has
   settings, an arrow that opens them. Also here: the search terms, the company boards, Paste posts and the AI hunt's
   missions. The sources come from the server (S.meta.collectors and GET /api/sources/catalog, the job sites and public
   services in search/collectors/catalog.py), so a new one shows up by itself.
   APIs: GET /api/settings and PUT /api/settings (through S.cfg and saveCfg, see components/settings-form.js),
   GET /api/profile (the search plan's terms), GET /api/analysis (leads per source), GET /api/sources/catalog,
   POST /api/sources/test/{key}, POST /api/sources/detect and POST /api/settings/reset. */
"use strict";

// The menu's groups: [id, heading, the source keys in it]. A source no group names lands in Other.
const SOURCE_GROUPS = [
  ["boards", "Job boards", ["ats_boards", "linkedin", "usajobs", "remote_boards", "adzuna", "serpapi"]],
  ["community", "Communities", ["reddit", "hackernews", "mastodon", "bluesky", "x"]],
  ["feeds", "Feeds and lists", ["rss", "github_lists"]],
];
// Shown as the catalog's own groups, so they aren't listed under Other.
const NOT_LISTED = ["catalog"];
// Short names for the sources the server spells out at length. Any other shows the server's label up to its first "(".
const SOURCE_NAMES = { github_lists: "GitHub lists", ats_boards: "Company boards", linkedin: "LinkedIn", usajobs: "USAJobs", hackernews: "Hacker News",
  reddit: "Reddit", mastodon: "Mastodon", bluesky: "Bluesky", x: "X", remote_boards: "Remote boards", rss: "RSS feeds",
  adzuna: "Adzuna", serpapi: "Google Jobs" };
const sourceName = ({ key, label }) => SOURCE_NAMES[key] || String(label || "").replace(/\s*\(.*$/, "").trim() || humanize(key);
// What a source needs or is limited to, in a word or two, on its line.
const SOURCE_NOTES = { github_lists: "Tech only", hackernews: "Tech only", remote_boards: "Remote only", usajobs: "Free key", adzuna: "Free key",
  serpapi: "Free key", bluesky: "App password", x: "Paid key" };
// The source name its leads carry (lead.source), by source key, for the counts. Any other uses its key.
const COLLECTOR_SOURCE = { github_lists: "github", ats_boards: "ats", remote_boards: "remote", serpapi: "google" };

// What the menu shows besides the settings: the search plan's terms and the leads per source.
let sourcesInfo = { queries: [], counts: {}, catalog: null };
// The sources and missions with their settings open. They stay open through a redraw.
const sourcesOpen = new Set();

// Opens the menu with the saved settings.
async function openSources() {
  const [, profile, analysis, catalog] = await Promise.all([loadCfg(), api("/api/profile").catch(() => ({})), api("/api/analysis").catch(() => null),
    api("/api/sources/catalog").catch(() => null)]);
  sourcesInfo = { queries: profile.search_plan?.queries || [], counts: Object.fromEntries((analysis?.market?.sources || []).map((x) => [x.source, x])), catalog };
  const dialog = openDialog(`<div class="sources-form" data-cfg></div>`, { title: "Sources", wide: true, guard: true, onClose: () => {
    if (S.route[0] === "leads" && !S.expanded) pickFirstLead();  // leads that came in while this was open
  } });
  dialog.classList.add("sources-dialog");
  dialog.addEventListener("change", (e) => {
    if (e.target.closest(".source-row .switch")) countSources();
  });
  drawSources();
}

// The groups with the sources the server lists in them, in the groups' order.
function sourceGroups() {
  const listed = (S.meta.collectors || []).filter((c) => !NOT_LISTED.includes(c.key));
  const named = new Set(SOURCE_GROUPS.flatMap(([, , keys]) => keys));
  const groups = SOURCE_GROUPS.map(([id, heading, keys]) => [id, heading, keys.map((key) => listed.find((c) => c.key === key)).filter(Boolean)]);
  groups.push(["other", "Other", listed.filter((c) => !named.has(c.key))]);
  return groups.filter(([id, , sources]) => sources.length || id === "community");  // Communities also holds Paste posts
}

// Draws the menu from S.cfg as it is now, edits included. A focused button or field gets the focus back: after removing a
// company board, for one, the focus is on the next board's Remove button.
function drawSources() {
  const box = $(".sources-dialog .sources-form");
  if (!box) return;
  const focus = focusKey(box), top = $(".sources-main", box)?.scrollTop || 0;
  const groups = sourceGroups();
  const catalogGroups = sourcesInfo.catalog?.groups || [];
  const nav = [["terms", "Search terms"], ...groups.map(([id, heading]) => [id, heading]),
    ...catalogGroups.map((g) => [`catalog-${g.id}`, g.id === "community" ? "Community sites" : g.name]), ["hunt", "AI hunt"]];
  const paste = `<div class="row source-row"><span class="row-main"><span class="row-title">Paste posts</span><span class="row-sub">Discord, Slack, Facebook, Threads</span></span>
    <span class="row-end"><button class="button outline small" type="button" data-act="paste-posts">${icon("plus")}Paste</button></span></div>`;
  const section = ([id, heading, sources]) => `<section class="sources-group" data-group="${id}"><div class="sect-head sources-head"><h2>${esc(heading)}</h2></div>
    <div class="rows">${sources.map(sourceRow).join("")}${id === "community" ? paste : ""}</div></section>`;
  box.innerHTML = `<nav class="rows sources-nav" aria-label="Source groups">${nav.map(([id, label]) => `<button class="row" type="button" data-act="sources-jump" data-group="${id}">`
      + `<span class="row-main"><span class="row-title">${esc(label)}</span></span><span class="row-end"></span></button>`).join("")}</nav>
    <div class="sources-main">${termsSection()}${groups.map(section).join("")}${catalogGroups.map(catalogSection).join("")}${missionsSection(S.cfg.sources.ai_hunt)}</div>
    <div class="sources-foot"><button class="button outline" type="button" data-act="close-dialog">Cancel</button>
      <button class="button primary" type="button" data-act="save-sources">Save</button></div>`;
  const main = $(".sources-main", box);
  main.scrollTop = top;
  main.addEventListener("scroll", markSourcesNav, { passive: true });
  refocus(box, focus);
  countSources();
  markSourcesNav();
}

// How many are switched on, beside each group in the left column.
function countSources() {
  const box = $(".sources-dialog .sources-form");
  if (!box) return;
  $$(".sources-group", box).forEach((group) => {
    const cell = $(`.sources-nav [data-group="${group.dataset.group}"] .row-end`, box);
    const switches = $$(".source > .source-row .switch input", group);
    if (cell) cell.textContent = switches.length ? `${switches.filter((input) => input.checked).length} of ${switches.length}` : "";
  });
}

// Marks the group you've scrolled to in the left column.
function markSourcesNav() {
  const box = $(".sources-dialog .sources-form"), main = box && $(".sources-main", box);
  if (!main) return;
  const groups = $$(".sources-group", main);
  const atEnd = main.scrollTop + main.clientHeight >= main.scrollHeight - 4;
  const here = atEnd ? groups.at(-1) : groups.filter((group) => group.offsetTop - main.offsetTop <= main.scrollTop + 8).at(-1) || groups[0];
  $$(".sources-nav .row", box).forEach((item) => {
    const on = item.dataset.group === here?.dataset.group;
    item.classList.toggle("active", on);
    if (on) item.setAttribute("aria-current", "true");
    else item.removeAttribute("aria-current");
  });
}

// One source: its switch, its name and what it has brought in, Test, and its settings under an arrow when it has any.
function sourceRow(source) {
  const { key } = source, name = sourceName(source), cfg = S.cfg.sources[key];
  const count = sourcesInfo.counts[COLLECTOR_SOURCE[key] || key];
  const sub = [SOURCE_NOTES[key], count ? `${plural(count.triaged, "lead")}, ${count.qualified} good` : ""].filter(Boolean).join(", ");
  const settings = SOURCE_OPTIONS[key] ? SOURCE_OPTIONS[key](S.cfg.sources) : plainOptions(key);
  const open = !!settings && sourcesOpen.has(key);
  const text = `<span class="row-title">${esc(name)}</span>${sub ? `<span class="row-sub">${esc(sub)}</span>` : ""}`;
  const label = settings
    ? `<button class="source-open" type="button" data-act="source-more" data-key="${esc(key)}" aria-expanded="${open}"><span class="row-main">${text}</span>${icon("chevron")}</button>`
    : `<span class="row-main">${text}</span>`;
  return `<div class="source${open ? " open" : ""}"><div class="row source-row">${toggle(`data-path="sources.${esc(key)}.enabled" data-bool="1" aria-label="${esc(name)}"`, cfg?.enabled)}
      ${label}<span class="row-end"><button class="button outline small" type="button" data-act="test-src" data-key="${esc(key)}">Test</button></span></div>
    ${settings ? `<div class="source-options"${open ? "" : " hidden"}>${settings}</div>` : ""}<div class="source-test" data-test="${esc(key)}"></div></div>`;
}

// One group of the catalog, with its switch. The sources that run for you come first.
function catalogSection(group) {
  const sources = (sourcesInfo.catalog?.sources || []).filter((s) => s.group === group.id)
    .sort((a, b) => Number(b.for_you) - Number(a.for_you) || a.name.localeCompare(b.name));
  const on = S.cfg.sources.catalog?.groups?.[group.id] !== false;
  const heading = group.id === "community" ? "Community sites" : group.name;
  return `<section class="sources-group" data-group="catalog-${esc(group.id)}"><div class="sect-head sources-head"><h2>${esc(heading)}
      ${toggle(`data-path="sources.catalog.groups.${esc(group.id)}" data-bool="1" aria-label="${esc(heading)}"`, on)}</h2></div>
    <div class="rows">${sources.map(catalogRow).join("")}</div></section>`;
}

// One catalog source: its switch, name, who it's for, Test, and its key fields under an arrow when it takes a key.
function catalogRow(src) {
  const off = (S.cfg.sources.catalog?.off || []).includes(src.id);
  const fields = src.fields.includes("all") ? "" : src.fields.map(humanize).join(", ");
  const places = src.countries.length <= 3 && !src.countries.includes("*") ? src.countries.join(", ") : "";
  const keyed = (S.cfg.sources.catalog?.keys || {})[src.id] || {};
  const missing = src.needs_key && !src.keys.every((name) => keyed[name]);
  const sub = [missing ? "Needs key" : "", fields, places].filter(Boolean).join(", ");
  const text = `<span class="row-title">${esc(src.name)}${src.for_you && !missing ? ` <span class="tag green">For you</span>` : ""}</span>${sub ? `<span class="row-sub">${esc(sub)}</span>` : ""}`;
  const moreKey = `catalog:${src.id}`, open = sourcesOpen.has(moreKey);
  const settings = src.needs_key ? `<div class="form-grid">${src.keys.map((name) => cfgInput(`sources.catalog.keys.${esc(src.id)}.${esc(name)}`,
    esc(humanize(name).replace(/\bApi\b/, "API")), "password")).join("")}</div>${src.key_url ? getKey(esc(src.key_url)) : ""}` : "";
  const label = settings
    ? `<button class="source-open" type="button" data-act="source-more" data-key="${esc(moreKey)}" aria-expanded="${open}"><span class="row-main">${text}</span>${icon("chevron")}</button>`
    : `<span class="row-main">${text}</span>`;
  return `<div class="source${open ? " open" : ""}"><div class="row source-row">${toggle(`data-catalog-src="${esc(src.id)}" aria-label="${esc(src.name)}"`, !off)}
      ${label}<span class="row-end"><button class="button outline small" type="button" data-act="test-src" data-key="${esc(src.id)}">Test</button></span></div>
    ${settings ? `<div class="source-options"${open ? "" : " hidden"}>${settings}</div>` : ""}<div class="source-test" data-test="${esc(src.id)}"></div></div>`;
}

// The search terms: the ones from your profile's search plan, and your own.
function termsSection() {
  const queries = sourcesInfo.queries;
  return `<section class="sources-group" data-group="terms"><div class="sect-head sources-head"><h2>Search terms</h2></div>
    <div class="sources-opts"><div class="opt"><div class="opt-label">Profile terms</div><div class="opt-body">
        <div class="sources-line">${toggle(`data-path="search.use_profile_plan" data-bool="1" aria-label="Use profile terms"`, S.cfg.search.use_profile_plan !== false)}
          <span>${plural(queries.length, "term")}</span><a class="text-button" href="#/settings/search">Edit</a></div>
        ${queries.length ? `<div class="tags">${queries.map((q) => `<span class="tag">${esc(q)}</span>`).join("")}</div>` : ""}</div></div>
      <div class="opt"><label class="opt-label" for="src-queries">Extra terms</label><div class="opt-body">
        <textarea id="src-queries" data-list="search.queries" rows="3" aria-label="Extra terms">${esc((S.cfg.search.queries || []).join("\n"))}</textarea></div></div></div></section>`;
}

// A link to where a source's key comes from.
const getKey = (url) => `<a class="text-button" href="${url}" target="_blank" rel="noopener">Get key ${icon("external")}</a>`;

// The settings under each source this file knows, by source key.
const SOURCE_OPTIONS = {
  github_lists: () => cfgLines("sources.github_lists.urls", "List links", 3),
  ats_boards: (src) => {
    const boardRow = (b, i) => `<tr><td>${toggle(`data-board="${i}" data-bf="enabled" aria-label="Search ${esc(b.name)}"`, b.enabled !== false)}</td>
        <td><input type="text" data-board="${i}" data-bf="name" value="${esc(b.name)}" aria-label="Company"></td><td class="source-system">${esc(b.ats)}</td>
        <td><input type="text" data-board="${i}" data-bf="${b.slug ? "slug" : "url"}" value="${esc(b.slug || b.url)}" aria-label="Board"></td>
        <td>${toggle(`data-board="${i}" data-bf="dream" aria-label="${esc(b.name)} is a dream company"`, !!b.dream)}</td>
        <td><button class="icon-button" type="button" data-act="rm-board" data-i="${i}" aria-label="Remove ${esc(b.name)}" title="Remove">${icon("trash")}</button></td></tr>`;
    const boards = src.ats_boards.boards || [];
    return `<div class="inline-form"><input type="url" id="detect-url" placeholder="Careers page link" aria-label="Careers page">
        <input type="text" id="detect-name" placeholder="Company name" aria-label="Company name"><button class="button light" type="button" data-act="detect">Add</button></div>
      <p class="source-note" id="detect-result"></p>
      ${boards.length ? `<div class="table-wrap source-boards"><table class="table"><thead><tr><th><span class="sr-only">On</span></th><th>Company</th><th>System</th><th>Board</th>
        <th>Dream</th><th><span class="sr-only">Remove</span></th></tr></thead><tbody>${boards.map(boardRow).join("")}</tbody></table></div>` : ""}`;
  },
  linkedin: (src) => {
    const timeWindows = [["r86400", "24 hours"], ["r604800", "1 week"], ["r2592000", "1 month"]];  // LinkedIn's "posted within" codes
    return `<div class="form-grid three">${cfgInput("sources.linkedin.max_requests", "Searches per run", "number")}
      <label class="field"><span class="field-label">Posted within</span><select data-path="sources.linkedin.time_window">${selectOptions(timeWindows, src.linkedin.time_window)}</select></label>
      ${cfgInput("sources.linkedin.experience", "Experience filter", "text", 'placeholder="1,2"')}</div>`;
  },
  usajobs: () => `<div class="form-grid">${cfgInput("sources.usajobs.api_key", "API key", "password")}${cfgInput("sources.usajobs.email", "Email", "email")}</div>${getKey("https://developer.usajobs.gov")}`,
  hackernews: () => cfgInput("sources.hackernews.threads", "Monthly threads", "number"),
  mastodon: () => `<div class="form-grid">${cfgLines("sources.mastodon.instances", "Servers", 3)}${cfgLines("sources.mastodon.tags", "Hashtags", 3)}</div>`,
  reddit: () => `${cfgLines("sources.reddit.subreddits", "Subreddits", 4)}<div class="form-grid">${cfgInput("sources.reddit.client_id", "App ID")}
      ${cfgInput("sources.reddit.client_secret", "App secret", "password")}</div>${getKey("https://www.reddit.com/prefs/apps")}`,
  rss: (src) => {
    const feeds = (src.rss.feeds || []).map((f) => (typeof f === "object" ? `${f.name} | ${f.url}` : f)).join("\n");
    return `<label class="field"><span class="field-label">Feeds</span><textarea data-feeds="1" rows="4" placeholder="Name | https://example.com/feed">${esc(feeds)}</textarea></label>`;
  },
  adzuna: () => `<div class="form-grid">${cfgInput("sources.adzuna.app_id", "App ID")}${cfgInput("sources.adzuna.app_key", "App key", "password")}</div>${getKey("https://developer.adzuna.com")}`,
  serpapi: () => `${cfgInput("sources.serpapi.api_key", "API key", "password")}${getKey("https://serpapi.com")}`,
  bluesky: () => `<div class="form-grid">${cfgInput("sources.bluesky.handle", "Handle", "text", 'placeholder="you.bsky.social"')}${cfgInput("sources.bluesky.app_password", "App password", "password")}</div>${getKey("https://bsky.app/settings/app-passwords")}`,
  x: () => `<div class="form-grid three">${cfgInput("sources.x.bearer_token", "Bearer token", "password")}${cfgInput("sources.x.searches", "Searches per run", "number", 'min="1" max="10"')}
      ${cfgInput("sources.x.posts_per_search", "Posts per search", "number", 'min="10" max="100"')}</div>
    <p class="source-note">X bills about half a cent per post.</p>${getKey("https://developer.x.com")}`,
};

// The settings of a source this file doesn't know yet: one field per setting, by the type of its value.
function plainOptions(key) {
  const field = ([name, value]) => {
    const path = `sources.${key}.${name}`, label = esc(humanize(name).replace(/\bApi\b/, "API"));
    if (typeof value === "boolean") return cfgSwitch(path, label, value);
    if (typeof value === "number") return cfgInput(path, label, "number");
    if (Array.isArray(value)) return value.some((x) => typeof x === "object") ? "" : cfgLines(path, label, 3);
    if (value && typeof value === "object") return "";
    return cfgInput(path, label, /key|token|secret|password/i.test(name) ? "password" : "text");
  };
  const fields = Object.entries(S.cfg.sources[key] || {}).filter(([name]) => name !== "enabled").map(field).join("");
  return fields ? `<div class="form-grid">${fields}</div>` : "";
}

// The AI hunt: the main switch, how many missions an "Everything" search takes, how deep each digs, and every mission's
// name and instructions (opened with its arrow).
function missionsSection(hunt) {
  const perRun = [[0, "All"], [4, "4 in rotation"], [7, "7 in rotation"], [10, "10 in rotation"]];
  const depths = [["deep", "Deep, 30+ searches"], ["standard", "Standard, 15 searches"], ["quick", "Quick, 8 searches"]];
  const mission = (m, i) => {
    const key = `mission:${m.id}`, open = sourcesOpen.has(key);
    return `<div class="source${open ? " open" : ""}"><div class="row source-row">${toggle(`data-mission="${i}" data-mf="enabled" aria-label="Use ${esc(m.name)}"`, m.enabled !== false)}
        <input class="mission-name" type="text" data-mission="${i}" data-mf="name" value="${esc(m.name)}" aria-label="Mission name">
        <span class="row-end">${m.only_levels ? `<span class="tag">${esc(m.only_levels.map(humanize).join(", "))}</span>` : ""}
          <button class="icon-button source-arrow" type="button" data-act="source-more" data-key="${esc(key)}" aria-expanded="${open}" aria-label="Instructions" title="Instructions">${icon("chevron")}</button>
          <button class="icon-button danger" type="button" data-act="rm-mission" data-i="${i}" aria-label="Delete mission" title="Delete">${icon("trash")}</button></span></div>
      <div class="source-options"${open ? "" : " hidden"}><textarea data-mission="${i}" data-mf="prompt" rows="6" aria-label="Instructions">${esc(m.prompt)}</textarea></div></div>`;
  };
  return `<section class="sources-group" data-group="hunt"><div class="sect-head sources-head"><h2>AI hunt ${toggle(`data-path="sources.ai_hunt.enabled" data-bool="1" aria-label="AI hunt"`, hunt.enabled)}</h2>
      <div class="button-row"><button class="button outline small" type="button" data-act="add-mission">${icon("plus")}Add mission</button>
        <button class="button text small" type="button" data-act="reset-missions">Reset</button></div></div>
    <div class="sources-opts"><div class="opt"><label class="opt-label" for="src-per-run">Missions per run</label><div class="opt-body"><select id="src-per-run" data-path="sources.ai_hunt.missions_per_run" data-num="1">${selectOptions(perRun, +hunt.missions_per_run || 0)}</select></div></div>
      <div class="opt"><label class="opt-label" for="src-depth">Depth</label><div class="opt-body"><select id="src-depth" data-path="sources.ai_hunt.depth">${selectOptions(depths, hunt.depth || "standard")}</select></div></div></div>
    <div class="rows">${hunt.missions.map(mission).join("")}</div></section>`;
}

// ---------------------------------------------------------------- actions
// A catalog source's switch: the settings keep the ones turned off, so a source added later is on by itself.
onChange((el) => {
  const id = el.dataset?.catalogSrc;
  if (!id) return false;
  const catalog = S.cfg.sources.catalog, off = new Set(catalog.off || []);
  if (el.checked) off.delete(id);
  else off.add(id);
  catalog.off = [...off];
  markCfgEdit("sources.catalog.off");
  countSources();
  return true;
});
onAction("sources", () => openSources());
onAction("save-sources", async (el) => {
  await saveCfg();
  closeDialog(el.closest("dialog"));
});
onAction("sources-jump", (el) => {  // a group in the left column
  const box = el.closest(".sources-form");
  $(`.sources-group[data-group="${el.dataset.group}"]`, box)?.scrollIntoView({ block: "start" });
});
onAction("source-more", (el) => {  // the arrow that opens a source's settings or a mission's instructions
  const key = el.dataset.key, row = el.closest(".source"), opening = !sourcesOpen.has(key);
  if (opening) sourcesOpen.add(key);
  else sourcesOpen.delete(key);
  row.classList.toggle("open", opening);
  $(".source-options", row).hidden = !opening;
  el.setAttribute("aria-expanded", String(opening));
});
onAction("test-src", async (el) => {  // runs one source now (unsaved edits are saved first) and shows what it found
  const key = el.dataset.key, box = $(`[data-test="${CSS.escape(key)}"]`);
  if (S.cfgDirty) await saveCfg();
  box.innerHTML = `<div class="test-result">${spinner()} Testing</div>`;
  let r;
  try {
    r = await api(`/api/sources/test/${encodeURIComponent(key)}`, { method: "POST" });
  } catch (err) {
    box.innerHTML = "";
    throw err;
  }
  const found = r.ok
    ? `<b>${r.found}</b> found, <b>${r.pass_filters}</b> pass filters<ul>${r.sample.map((s) => `<li>${esc(s.title)}, ${esc(s.company)} (${esc(s.location)})</li>`).join("")}</ul>`
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
  // Drawn before saving too: every board moved down one place, and a field edited during the save must reach its own
  // board, not the one that used to sit there.
  drawSources();
  await saveCfg();
  toast("Company added", `${plural(r.count, "job")}, ${r.board.ats}`);
  drawSources();
});
onAction("rm-board", (el) => {
  S.cfg.sources.ats_boards.boards.splice(+el.dataset.i, 1);
  markCfgEdit("sources.ats_boards.boards");
  drawSources();
});
onAction("add-mission", () => {
  const id = "m" + Date.now();
  S.cfg.sources.ai_hunt.missions.push({ id, name: "New mission", enabled: true, prompt: "Say where to look and what to find." });
  sourcesOpen.add(`mission:${id}`);
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
  if (!confirm("Reset every mission to the built-in ones?")) return;
  const fresh = await api("/api/settings/reset", { method: "POST", body: { path: "sources.ai_hunt.missions" } });
  S.cfg.sources.ai_hunt.missions = fresh.sources.ai_hunt.missions;
  S.cfgEdits.delete("sources.ai_hunt.missions");
  S.cfgDirty = S.cfgEdits.size > 0;  // the reset is saved: only other edits are left to save
  drawSources();
});
