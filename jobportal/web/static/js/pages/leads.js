/* leads.js: the Leads page (#/leads), a list and its details side by side, like a mail app. On the left, the jobs
   JobPortal found, ranked. On the right, the selected one (lead.js draws it). On a wide screen the first lead is selected
   by itself and the address follows the selection (#/leads/12, or #/leads/12/emails for one of its tabs). Under 981px it's
   the list alone, and a lead opens full screen with a back button.
   The stages (Ready, In progress, Filtered, Closed, Deleted, All) are tabs in the top bar, and the search box there
   searches them. Above the list: sort, industry, kind, the Dream list, Sources (sources.js) and Add job. Under the panes:
   a slim strip with the live search, which opens into its log.
   APIs: GET /api/leads (one stage's leads, the counts per stage and the industries), GET /api/leads/{id},
   POST /api/leads/manual and /paste, PATCH /api/leads/{id} (status changes from a row), DELETE /api/leads/{id} and
   POST /api/leads/retriage. While it's open, live events (live.js) call upsertLead, appendLog and renderFeedHead. */
"use strict";

const LEAD_FILTERS = [["ready", "Ready"], ["queue", "In progress"], ["filtered", "Filtered"], ["closed", "Closed"], ["trashed", "Deleted"], ["all", "All"]];
const LEAD_SORTS = [["score", "Best match"], ["new", "Newest"], ["deadline", "Deadline"], ["posted", "Recently posted"], ["industry", "Industry"]];
// What a lead is (lead.kind): a job posting, or a program, an event, or a company worth contacting before it posts a job.
const LEAD_KINDS = [["", "All kinds"], ["posting", "Jobs"], ["program", "Programs"], ["event", "Events"], ["intel", "Companies"]];

// The search log under the list stays shut until you open it, and remembers that.
S.feedOpen = store.get("feedOpen") === "1";

// Two panes need a wide window. At 980px and under (where base.css stacks panes) the list and a lead take turns.
const leadsWide = window.matchMedia("(min-width: 981px)");
leadsWide.addEventListener("change", () => {
  if (S.route[0] === "leads" && !S.expanded) pickFirstLead();
});

// Unsaved edits on screen: while there are any, nothing moves the selection by itself.
const leadsEditing = () => S.dirty || S.cfgDirty;

// The stage tabs for the top bar, with their counts once they're known.
let leadCounts = {};
const leadTabs = () => LEAD_FILTERS.map(([key, label]) => pageTab(`data-act="leads-tab" data-tab="${key}"`, label, S.leadsTab === key, leadCounts[key])).join("");

// Draws the page once (a new address on it only changes the selection), then selects the lead the address names. With
// none on a wide screen, the first lead is picked: the address moves to it and the router comes back here with its id.
async function renderLeads(id, tab) {
  const wanted = id ? +id : null;
  if (main.dataset.page !== "leads") {
    main.dataset.page = "leads";
    S.expanded = wanted;
    if (S.leadView) closeLeadDetails();  // drawn again from scratch (Retry): the old details are gone
    pageHead("Leads", leadTabs());
    main.innerHTML = `<div class="leads">
      <div class="toolbar leads-bar">
        <select id="lead-sort" aria-label="Sort">${selectOptions(LEAD_SORTS, S.sort)}</select>
        <select id="lead-industry" aria-label="Industry"><option value="">All industries</option></select>
        <select id="lead-kind" aria-label="Kind">${selectOptions(LEAD_KINDS, S.kind)}</select>
        <span class="leads-break"></span>
        <button class="button outline" type="button" id="dream-chip" data-act="dream-only" aria-pressed="false">${icon("star")}Dream list</button>
        <span class="leads-count" id="lead-count" aria-live="polite"></span>
        <span class="spacer"></span>
        <button class="button outline" type="button" data-act="export-leads">${icon("download")}Export</button>
        <button class="button outline" type="button" data-act="sources">${icon("signal")}Sources</button>
        <button class="button primary" type="button" data-act="add-job">${icon("plus")}Add job</button>
      </div>
      <div class="view-split list-first">
        <section class="pane leads-list" aria-label="Leads"><ul class="rows" id="lead-list"></ul></section>
        <section class="pane lead-pane" id="lead-detail" aria-label="Lead details"></section>
      </div>
      <section class="run-strip${S.feedOpen ? " open" : ""}" id="live-panel" aria-label="Search log" hidden>
        <button class="run-head" type="button" data-act="toggle-feed" aria-expanded="${S.feedOpen}" aria-controls="live-log">
          <span class="live-status" id="live-status"></span><span class="run-toggle">${icon("chevron")}</span></button>
        <div class="live-log" id="live-log" role="log"></div></section>
    </div>`;
    renderFeedHead();
    $("#live-log").innerHTML = S.logs.map(logLine).join("");
    $("#live-log").scrollTop = 1e9;  // start at the newest line
    await loadLeads(true);
    if (main.dataset.page !== "leads") return;  // you left while it loaded
  }
  if (S.openSources) {  // an old #/sources link, also when it was followed with Leads already open
    S.openSources = false;
    openSources().catch((err) => toast("Couldn't open Sources", err.message, "error"));
  }
  if (!wanted && pickFirstLead()) return;
  await selectLead(wanted, tab);
}

// ---------------------------------------------------------------- the live search strip
// The strip's line: what the search is doing (its phase, time, counts and tokens), or the last search's counts. With no
// search yet, there's no strip.
function renderFeedHead() {
  const el = $("#live-status");
  if (!el) return;
  const st = S.state;
  const counts = RUN_COUNTS.filter(([key]) => (st.counts || {})[key] != null)
    .map(([key, label]) => `<span><b>${st.counts[key]}</b> ${label}</span>`).join("");
  $("#live-panel").hidden = !st.running && !counts && !S.logs.length;
  if (st.running) {
    const started = Date.parse(st.started_at);
    const seconds = started ? Math.max(0, Math.floor((Date.now() - started) / 1000)) : 0;
    const used = (+st.tokens || 0) - (+st.run_tokens_start || 0);
    el.innerHTML = `${spinner()}<b>${esc(runPhase(st.phase))}</b><span>${Math.floor(seconds / 60)}m ${seconds % 60}s</span>${counts}`
      + (used > 0 ? `<span>${fmtTokens(used)} tokens</span>` : "");
  } else {
    el.innerHTML = `<span class="status-dot off"></span><b>Last search</b>${counts}`;
  }
}
setInterval(() => {  // the clock ticks while a search runs
  if (S.state.running && S.route[0] === "leads") renderFeedHead();
}, 1000);

// One log line: local time, source, message.
const logLine = (line) => `<div class="log-line ${esc(line.level)}"><span class="log-time">${localClock(line.ts)}</span>`
  + `<span class="log-source">${esc(line.source || "")}</span><span class="log-msg">${esc(line.msg)}</span></div>`;

// Adds one line to the log (a "log" event), keeping 600 at most. It follows new lines only if you were at the bottom.
function appendLog(line) {
  const log = $("#live-log");
  if (!log) return;
  const atBottom = log.scrollHeight - log.scrollTop - log.clientHeight < 40;
  log.insertAdjacentHTML("beforeend", logLine(line));
  while (log.childElementCount > 600) log.firstElementChild.remove();
  if (atBottom) log.scrollTop = 1e9;
  $("#live-panel").hidden = false;
}

// Empties the log when a new search starts.
function clearLog() {
  const log = $("#live-log");
  if (log) log.innerHTML = "";
}

// ---------------------------------------------------------------- the list
// Mirrors the server's filter rules, so a live update can tell whether a changed lead still belongs in the open stage.
function inFilter(lead, tab) {
  if (tab === "trashed") return lead.app_status === "trashed";
  if (lead.app_status === "trashed") return false;
  if (tab === "ready") return lead.stage === "ready" && ["new", "ready"].includes(lead.app_status);
  if (tab === "queue") return ["qualified", "packaging", "error"].includes(lead.stage);
  if (tab === "filtered" || tab === "closed") return lead.stage === tab;
  return tab === "all";
}

// Loads the open stage's leads (GET /api/leads), then redraws the tabs, the toolbar and the rows.
// keep = leave the selection alone: a live refresh, or the first draw from an address. Without it (the stage, a filter or
// the search changed), a selected lead that's no longer listed gives way to the first one listed.
// - Only the newest load draws. Typing in the search box or clicking through the tabs sends several requests, and an
//   older answer that came back last would show the wrong list.
// - The details are in their own pane, so redrawing the rows never touches an editor you're typing in.
// - A load that fails keeps the list on screen and says so, or, with no list yet, shows the error with Retry.
let leadsLoad = 0;
async function loadLeads(keep) {
  const ticket = ++leadsLoad;
  const params = new URLSearchParams({ tab: S.leadsTab, q: S.q, sort: S.sort, industry: S.industry, kind: S.kind, dream: S.dreamOnly ? 1 : 0 });
  let d;
  try {
    d = await api(`/api/leads?${params}`);
  } catch (err) {
    const list = $("#lead-list");
    if (!list || ticket !== leadsLoad) return;
    if (!$(".lead-item", list)) {
      list.innerHTML = `<li class="lead-empty">${loadError(err)}</li>`;
      $(".leads").classList.add("no-leads");
    } else if (!keep) {
      toast("Couldn't load leads", err.message, "error");
    }
    return;
  }
  const list = $("#lead-list");
  if (!list || ticket !== leadsLoad || S.route[0] !== "leads") return;  // you left the page, or a newer load is on its way
  renderListControls(d);
  const known = new Set($$(".lead-item", list).map((item) => +item.dataset.id));
  const gone = !!S.expanded && !d.leads.some((l) => l.id === S.expanded);
  // A selected lead that left this list stays on top of it until you move on.
  const stays = gone && (keep || leadsEditing()) && S.lead?.id === S.expanded;
  const rows = stays ? [S.lead, ...d.leads] : d.leads;
  const fresh = document.createElement("template");
  fresh.innerHTML = rows.map((l) => leadRow(l, keep && known.size > 0 && !known.has(l.id))).join("");
  if (fresh.innerHTML !== list.innerHTML) {  // an unchanged list stays as it is, so a click in progress isn't lost
    const focus = focusKey(list);
    list.replaceChildren(fresh.content);
    refocus(list, focus);
  }
  syncEmptyList();
  if (gone && !keep && !leadsEditing()) {
    if (!pickFirstLead()) location.replace("#/leads");
  } else if (!S.expanded) {
    pickFirstLead();
  }
}

// The toolbar and the tabs: the counts per stage, the industry menu, Dream list, and what's being shown.
function renderListControls(d) {
  leadCounts = d.counts;
  pageHead("Leads", leadTabs());
  // The industry menu lists this stage's industries. A chosen one with no leads stays listed (with 0), so you can see it's on.
  const industries = [["", "All industries"], ...Object.entries(d.industries || {}).map(([name, n]) => [name, `${name} (${n})`])];
  if (S.industry && !(d.industries || {})[S.industry]) industries.push([S.industry, `${S.industry} (0)`]);
  setHtml($("#lead-industry"), selectOptions(industries, S.industry));
  const dream = $("#dream-chip");
  dream.classList.toggle("on", S.dreamOnly);
  dream.setAttribute("aria-pressed", String(S.dreamOnly));
  setHtml(dream, `${icon("star", S.dreamOnly ? "filled" : "")}Dream list<span class="leads-num">${d.dream_count ?? 0}</span>`);
  const search = S.q ? `<span class="tag">${esc(S.q)}<button class="tag-x" type="button" data-act="clear-search" aria-label="Clear search" title="Clear search">${icon("close")}</button></span>` : "";
  const rescore = ["filtered", "queue"].includes(S.leadsTab)
    ? `<button class="text-button" type="button" data-act="retriage">${icon("refresh")}Score again</button>` : "";
  setHtml($("#lead-count"), `<span>${plural(d.leads.length, "lead")}</span>${search}${rescore}`);
}

// With no row left, the list says so, and the details pane steps aside so the message fills the page.
function syncEmptyList() {
  const list = $("#lead-list");
  if (!list) return;
  const none = !$(".lead-item", list);
  if (none && !$(".lead-empty", list)) {
    const text = S.q || S.industry || S.kind || S.dreamOnly ? "No matches" : S.leadsTab === "ready" ? "No leads yet" : "Nothing here";
    list.innerHTML = `<li class="lead-empty"><div class="empty fill"><h3>${text}</h3></div></li>`;
  }
  if (!none) $(".lead-empty", list)?.remove();
  $(".leads")?.classList.toggle("no-leads", none);
}

// A live update for one lead: redraw its row, add it at the top (highlighted), or take it away if it left the stage, the
// industry picked or the Dream list. The selected lead's row stays until you move on. With words in the search box, a new
// lead isn't added here: the refresh that follows every lead event (refreshSoon in live.js) asks the server, which
// searches more than a row shows.
function upsertLead(lead) {
  const list = $("#lead-list");
  if (!list) return;
  const item = $(`.lead-item[data-id="${lead.id}"]`, list);
  const shown = inFilter(lead, S.leadsTab) && (!S.industry || lead.industry === S.industry) && (!S.kind || lead.kind === S.kind)
    && (!S.dreamOnly || !!lead.dream);
  const fresh = document.createElement("template");
  fresh.innerHTML = leadRow(lead, !item).trim();
  if (!shown && S.expanded !== lead.id) {
    item?.remove();
  } else if (item) {
    const focus = focusKey(item);
    item.replaceWith(fresh.content);
    refocus(list, focus);
  } else if (shown && !S.q) {
    list.prepend(fresh.content);
  }
  syncEmptyList();
  if (!S.expanded) pickFirstLead();
}

// ---------------------------------------------------------------- the selection
// On a wide screen, with nothing selected, moves the address to the first lead listed. True when it did. The router then
// calls renderLeads with its id. Unsaved edits are never left behind this way.
function pickFirstLead() {
  if (!leadsWide.matches || leadsEditing()) return false;
  const first = $("#lead-list .lead-item");
  if (!first) return false;
  location.replace(`#/leads/${first.dataset.id}`);
  return true;
}

// The address to show after this lead goes away: the row below it, else the row above, else the bare list.
function nextLeadHash(id) {
  const item = $(`#lead-list .lead-item[data-id="${id}"]`);
  const next = item?.nextElementSibling?.dataset.id || item?.previousElementSibling?.dataset.id;
  return next ? `#/leads/${next}` : "#/leads";
}

// Marks the selected row.
function markSelectedRow() {
  $$("#lead-list .lead-item").forEach((item) => {
    const on = +item.dataset.id === S.expanded, row = $(".lead-row", item);
    item.classList.toggle("on", on);
    row.classList.toggle("active", on);
    if (on) row.setAttribute("aria-current", "true");
    else row.removeAttribute("aria-current");
  });
}

// How far the list was scrolled on a small screen when a lead opened over it.
let leadsListTop = 0;

// Selects a lead and shows it on the given tab (id null: none). A lead that isn't listed (another stage, or a link from
// Home) is added on top. One that left the stage while selected goes away once you move on.
async function selectLead(id, tab) {
  const pane = $("#lead-detail"), list = $("#lead-list");
  if (!pane) return;
  const before = S.expanded;
  S.expanded = id;
  if (before && before !== id) {
    const old = $(`.lead-item[data-id="${before}"]`, list);
    if (old && !inFilter({ stage: old.dataset.stage, app_status: old.dataset.status }, S.leadsTab)) old.remove();
  }
  markSelectedRow();
  const leads = $(".leads"), wasOpen = leads.classList.contains("has-lead");
  leads.classList.toggle("has-lead", !!id);
  if (!leadsWide.matches && wasOpen !== !!id) {  // <main> scrolls there: a lead starts at the top, the list where you left it
    if (id) leadsListTop = main.scrollTop;
    main.scrollTop = id ? 0 : leadsListTop;
  }
  if (!id) {
    if (S.leadView?.box === pane) closeLeadDetails();
    pane.innerHTML = "";
    syncEmptyList();
    return;
  }
  if (!$(`.lead-item[data-id="${id}"]`, list)) {
    let lead;
    try {
      lead = await api(`/api/leads/${id}`);
    } catch (_) {
      toast("Lead not found", "", "error");
      location.replace("#/leads");
      return;
    }
    if (S.expanded !== id || !$("#lead-list")) return;  // you moved on while it loaded
    list.insertAdjacentHTML("afterbegin", leadRow(lead));
    syncEmptyList();
  }
  $(`.lead-item[data-id="${id}"]`, list)?.scrollIntoView({ block: "nearest" });
  if (S.leadView?.box === pane && S.leadView.id === id) showLeadTab(tab || "overview");
  else await showLeadDetails(pane, id, { tab: tab || "overview", hashBase: `#/leads/${id}` });
}

// ---------------------------------------------------------------- rows
// One lead in the list: its score, title, company and place, how long ago it was posted, and small marks for its state.
// A click selects it. The buttons on its right show when you point at it or tab to it.
function leadRow(l, fresh) {
  const on = S.expanded === l.id;
  const where = [l.company, l.location].filter(Boolean).join(", ");
  return `<li class="lead-item${on ? " on" : ""}${fresh ? " fresh" : ""}" data-id="${l.id}" data-stage="${esc(l.stage)}" data-status="${esc(l.app_status)}">`
    + `<a class="row lead-row${on ? " active" : ""}" href="#/leads/${l.id}"${on ? ' aria-current="true"' : ""}>${matchPill(l.score || null)}`
    + `<span class="row-main"><span class="lead-line"><span class="row-title">${esc(l.title || "Untitled job")}</span>`
    + `<span class="lead-age">${l.posted_at ? esc(ago(l.posted_at)) : ""}</span></span>`
    + `<span class="lead-line"><span class="row-sub">${esc(where)}</span><span class="lead-marks">${leadMarks(l)}</span></span></span></a>`
    + `<span class="lead-quick">${quickActions(l)}</span></li>`;
}

// What state a lead is in, as one word and a tag color: tailoring, queued, failed, filtered, closed, your status, or new
// for one found in the last two days.
const isNewLead = (l) => !!l.created_at && Date.now() - Date.parse(l.created_at) < 2 * 86400000;
function leadState(l) {
  if (l.stage === "packaging") return { word: "Tailoring", cls: "purple", busy: true };
  if (l.stage === "qualified") return { word: "Queued", cls: "" };
  if (l.stage === "error") return { word: "Failed", cls: "bad" };
  if (l.stage === "filtered") return { word: "Filtered", cls: "" };
  if (l.stage === "closed") return { word: "Closed", cls: "" };
  if (l.app_status && l.app_status !== "new") return { word: statusLabel(l.app_status), cls: ["rejected", "trashed"].includes(l.app_status) ? "" : "blue" };
  return isNewLead(l) ? { word: "New", cls: "green" } : null;
}

// The state as a tag.
function stageTag(l) {
  const state = leadState(l);
  return state ? `<span class="tag ${state.cls}">${state.busy ? spinner() : ""}${esc(state.word)}</span>` : "";
}

// The small marks on a row: a star for a dream job, the deadline, and the state, unless the open tab already says it. New
// is a plain dot, the way a mail app marks what's unread.
function leadMarks(l) {
  const marks = [];
  if (l.dream) marks.push(`<span class="lead-mark">${icon("star", "filled")}<span class="sr-only">Dream</span></span>`);
  const days = daysUntil(l.deadline);
  if (days != null && days >= 0) marks.push(`<span class="tag${days <= 5 ? " warn" : ""}">${days === 0 ? "Due today" : `Due ${days}d`}</span>`);
  const state = leadState(l);
  const tabSaysIt = (S.leadsTab === l.stage && ["filtered", "closed"].includes(l.stage)) || (S.leadsTab === "trashed" && l.app_status === "trashed");
  if (state?.word === "New") marks.push(`<span class="lead-dot"><span class="sr-only">New</span></span>`);
  else if (state && !tabSaysIt) marks.push(stageTag(l));
  return marks.join("");
}

// The buttons on a row: Track (for a new lead) and Delete (one click, with Undo, for sorting through leads fast). A deleted
// lead has Restore and Delete forever instead.
function quickActions(l) {
  const button = (act, name, label, cls = "") => `<button class="icon-button${cls}" type="button" data-act="${act}" data-id="${l.id}" aria-label="${label}" title="${label}">${icon(name)}</button>`;
  if (l.app_status === "trashed") return button("lead-restore", "undo", "Restore") + button("lead-purge", "trash", "Delete forever", " danger");
  return (l.app_status === "new" ? button("lead-track", "plus", "Track") : "") + button("lead-trash", "trash", "Delete", " danger");
}

// Where and when, for a lead's header: when it was posted, the deadline and where it was found.
function leadMeta(l) {
  const items = [];
  const posted = ago(l.posted_at);  // "" when the posting gave a date that can't be read
  if (posted) items.push(`<span>${icon("clock")}Posted ${posted}</span>`);
  const days = daysUntil(l.deadline);
  if (days != null) {
    const text = days < 0 ? "Deadline passed" : days === 0 ? "Due today" : days === 1 ? "Due tomorrow" : `Due in ${days} days`;
    items.push(`<span class="${days >= 0 && days <= 5 ? "urgent" : ""}">${icon("calendar")}${text}</span>`);
  }
  const sources = (l.sources?.length ? l.sources : [l.source]).filter(Boolean).map((s) => LABEL_SRC[s] || humanize(s));
  if (sources.length) items.push(`<span>${icon("signal")}${esc(sources.join(", "))}</span>`);
  return items.join("");
}

// The tags in a lead's header: dream, industry, kind, category, keyword coverage, open questions and red flags.
function leadTags(l) {
  const tags = [];
  if (l.dream) tags.push(`<span class="tag green">${icon("star", "filled")}Dream</span>`);
  if (l.industry) tags.push(`<span class="tag">${esc(l.industry)}</span>`);
  if (l.kind && l.kind !== "posting") tags.push(`<span class="tag purple">${esc(humanize(l.kind))}</span>`);
  if (l.category) tags.push(`<span class="tag">${esc(l.category)}</span>`);
  if (l.ats_coverage != null) tags.push(`<span class="tag ${l.ats_coverage >= 0.75 ? "green" : "warn"}">Keywords ${Math.round(l.ats_coverage * 100)}%</span>`);
  if (l.open_q) tags.push(`<span class="tag warn">${icon("question")}${plural(l.open_q, "question")}</span>`);
  const flags = l.triage?.red_flags || [];
  if (flags.length) tags.push(`<span class="tag warn">${icon("flag")}${plural(flags.length, "flag")}</span>`);
  return tags.join("");
}

// ---------------------------------------------------------------- where a lead was found
// Short names for "found at" links. (LABEL_SRC in core.js names the sources in a lead's header.)
const FOUND_NAME = { github: "GitHub list", ats: "Company board", linkedin: "LinkedIn", hackernews: "Hacker News", reddit: "Reddit",
  mastodon: "Mastodon", bluesky: "Bluesky", themuse: "The Muse", usajobs: "USAJobs", remote: "Remote board", rss: "RSS feed",
  adzuna: "Adzuna", google: "Google Jobs", manual: "Your link", x: "X post", paste: "Your pasted post" };

// The places a lead was found that have a usable link, each with its link as safeUrl() returns it (trimmed, and only
// web or mail links), so every href built from these is safe.
const foundList = (l) => (l.found || []).map((f) => ({ ...f, url: safeUrl(f.url) })).filter((f) => f.url);

// A short name for one place. AI hunt finds are named by their site ("Reddit thread"), else by their host.
function foundShort(f) {
  let host = "";
  try {
    host = new URL(f.url).hostname.replace(/^www\./, "");
  } catch (_) {}
  if (f.source !== "ai_hunt") return FOUND_NAME[f.source] || host || f.source;
  if (/reddit\.com/.test(host)) return "Reddit thread";
  if (/linkedin\.com/.test(host)) return "LinkedIn post";
  if (/(x|twitter)\.com/.test(host)) return "X post";
  if (/news\.ycombinator/.test(host)) return "HN comment";
  if (host) return host;
  // A mail link has no host: use where the AI found it. Its labels read "AI hunt (mission name): where it was found".
  const where = (f.label || "").match(/\):\s*(.+)$/);
  return where ? where[1].trim().slice(0, 30) : "AI find";
}

// The dialog behind "Found at" in a lead's menu: every place the lead was found, with the full link.
function foundMenu(l) {
  const places = foundList(l).map((f) => `<a class="row" href="${esc(f.url)}" target="_blank" rel="noopener"><span class="row-main">`
    + `<span class="row-title">${esc(foundShort(f))}</span><span class="row-sub">${esc(f.label)}</span><span class="row-sub">${esc(f.url)}</span></span>`
    + `<span class="row-end">${icon("external")}</span></a>`).join("");
  openDialog(`<h2>Found at</h2><div class="rows found-rows">${places}</div>`);
}

// ---------------------------------------------------------------- add a job
// The Add job dialog: a link or the pasted posting. POST /api/leads/manual starts tailoring it, or returns the saved lead
// when the same job was added before. Paste posts is there too, for many jobs at once from a community.
function addJobDialog() {
  const kinds = [["posting", "Job posting"], ["program", "Program"], ["event", "Event"], ["intel", "Company to contact"]];
  openDialog(`<h2>Add job</h2>
    <div class="form-grid">
      <label class="field wide"><span class="field-label">Link</span><input type="url" id="aj-url" placeholder="https://"></label>
      <label class="field wide"><span class="field-label">Posting text</span><textarea id="aj-text" rows="7"></textarea></label>
      <label class="field"><span class="field-label">Title</span><input type="text" id="aj-title"></label>
      <label class="field"><span class="field-label">Company</span><input type="text" id="aj-company"></label>
      <label class="field"><span class="field-label">Kind</span><select id="aj-kind">${selectOptions(kinds)}</select></label></div>
    <div class="dialog-actions"><button class="button text" type="button" data-act="paste-posts">Paste posts</button><span class="spacer"></span>
      <button class="button outline" type="button" data-act="close-dialog">Cancel</button>
      <button class="button primary" type="button" data-act="add-job-go">Add job</button></div>`);
}

// The Paste posts dialog: posts copied from a community apps can't read (Discord, Slack, Facebook groups, LinkedIn,
// Threads, X). POST /api/leads/paste has the AI find each opening in them; the new leads are scored in the background, and
// the good ones are queued for their packages like any search's. It opens on top of the Sources menu (which keeps any
// edits), and in place of Add job.
function pastePostsDialog() {
  openDialog(`<h2>Paste posts</h2>
    <div class="form-grid">
      <label class="field wide"><span class="field-label">Posts</span><textarea id="pp-text" rows="12"></textarea></label>
      <label class="field wide"><span class="field-label">Source</span><input type="text" id="pp-where" placeholder="Nursing jobs Discord"></label></div>
    <div class="dialog-actions"><button class="button outline" type="button" data-act="close-dialog">Cancel</button>
      <button class="button primary" type="button" data-act="paste-posts-go">Find jobs</button></div>`);
}

// ---------------------------------------------------------------- actions
onAction("paste-posts", (el) => {
  const from = el.closest("dialog");
  if (from && $("#aj-url", from)) closeDialog(from);  // from Add job: this one takes its place
  pastePostsDialog();
});
onAction("paste-posts-go", async (el) => {
  const dialog = el.closest("dialog"), text = $("#pp-text", dialog).value.trim();
  if (!text) {
    toast("Nothing pasted", "", "error");
    return;
  }
  const label = el.innerHTML;
  el.disabled = true;
  el.innerHTML = `${spinner()}Reading`;
  try {
    const r = await api("/api/leads/paste", { method: "POST", body: { text, where: $("#pp-where", dialog).value.trim() } });
    closeDialog(dialog);
    const already = r.existing ? `${r.existing} already saved` : "";
    if (r.added) toast(`${plural(r.added, "job")} added`, already);
    else toast(r.found ? "No new jobs" : "No jobs found", already);
    if (S.route[0] === "leads") loadLeads(true);
  } finally {
    el.disabled = false;
    el.innerHTML = label;
  }
});
onAction("leads-tab", (el) => {  // a stage tab here, or a link from Home that opens Leads on a stage
  if (el.tagName === "A") {
    S.leadsTab = el.dataset.tab;
    store.set("leadsTab", S.leadsTab);
    return;  // the link opens the page
  }
  if (S.dirty) {
    if (!confirm("Discard your unsaved edits?")) return;
    S.dirty = false;
    if (S.lead) drawLeadTab();  // the open tab goes back to what's saved
  }
  S.leadsTab = el.dataset.tab;
  store.set("leadsTab", S.leadsTab);
  pageHead("Leads", leadTabs());
  if (!leadsWide.matches && S.expanded) location.hash = "#/leads";  // on a small screen, back to the list
  loadLeads();
});
onAction("dream-only", () => {
  S.dreamOnly = !S.dreamOnly;
  loadLeads();
});
onAction("clear-search", () => {
  $("#search").value = "";
  S.q = "";
  loadLeads();
});
// Export: the leads on this tab with these filters, as a zip with a spreadsheet and a folder of documents for each.
onAction("export-leads", async () => {
  const query = new URLSearchParams({ tab: S.leadsTab, q: S.q, sort: S.sort, kind: S.kind, industry: S.industry, dream: S.dreamOnly ? 1 : 0 });
  toast("Exporting");
  await openUrl(`/api/export/leads.zip?${query}`);
});
onAction("toggle-feed", (el) => {
  S.feedOpen = !S.feedOpen;
  store.set("feedOpen", S.feedOpen ? "1" : "0");
  $("#live-panel").classList.toggle("open", S.feedOpen);
  el.setAttribute("aria-expanded", String(S.feedOpen));
  if (S.feedOpen) $("#live-log").scrollTop = 1e9;
});
onAction("retriage", async () => {
  await api("/api/leads/retriage", { method: "POST" });
  toast("Scoring again");
});
onAction("lead-track", async (el) => {
  leadChanged(await api(`/api/leads/${el.dataset.id}`, { method: "PATCH", body: { app_status: "ready" } }));
  toast("Added to Tracker");
});
onAction("lead-trash", async (el) => {  // a row's Delete: trash it (later searches won't add the job again), with Undo
  const id = +el.dataset.id;
  if (S.expanded === id) {  // its details are open: let them ask about unsaved edits and move on to the next lead
    return ACTIONS["detail-delete"](el);
  }
  const before = $(`.lead-item[data-id="${id}"]`)?.dataset.status || "new";
  const lead = await api(`/api/leads/${id}`, { method: "PATCH", body: { app_status: "trashed" } });
  leadChanged(lead);
  toast("Deleted", lead.title || "", "", null, { label: "Undo", run: async () => leadChanged(await api(`/api/leads/${id}`, { method: "PATCH", body: { app_status: before } })) });
});
onAction("lead-restore", async (el) => {
  leadChanged(await api(`/api/leads/${el.dataset.id}`, { method: "PATCH", body: { app_status: "new" } }));
  toast("Restored");
});
onAction("lead-purge", async (el) => {
  if (!confirm("Delete this lead and its files for good?")) return;
  const id = +el.dataset.id;
  await api(`/api/leads/${id}`, { method: "DELETE" });
  if (S.leadView?.id === id) {
    S.dirty = false;  // what was being edited is gone
    const dialog = S.leadView.box.closest("dialog");
    if (dialog) closeDialog(dialog);
    else location.hash = nextLeadHash(id);
  }
  $(`.lead-item[data-id="${id}"]`)?.remove();
  syncEmptyList();
  if (S.route[0] === "leads") loadLeads(true);
  refreshStats();
  toast("Deleted for good");
});
onAction("found-menu", async (el) => foundMenu(await api(`/api/leads/${el.dataset.id}`)));
onAction("add-job", () => addJobDialog());
onAction("add-job-go", async (el) => {
  const dialog = el.closest("dialog");
  const value = (id) => $(id, dialog).value.trim();
  const body = { url: value("#aj-url"), text: value("#aj-text"), title: value("#aj-title"), company: value("#aj-company"), kind: value("#aj-kind") };
  if (!body.url && !body.text) {
    toast("Link or text needed", "", "error");
    return;
  }
  el.disabled = true;
  try {
    const lead = await api("/api/leads/manual", { method: "POST", body });
    closeDialog(dialog);
    toast(lead.existing ? "Already in Leads" : "Tailoring", "", "", lead.id);
    location.hash = `#/leads/${lead.id}`;
  } finally {
    el.disabled = false;
  }
});
onChange((el) => {
  if (el.id === "lead-sort") S.sort = el.value;
  else if (el.id === "lead-industry") S.industry = el.value;
  else if (el.id === "lead-kind") S.kind = el.value;
  else return false;
  loadLeads();
  return true;
});
