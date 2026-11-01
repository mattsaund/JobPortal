/* leads.js: the Leads page (#/leads): the jobs JobPortal found and ranked for you, as cards. Filter them (Ready, In
   progress, Filtered out, Closed, Deleted, All), sort them, narrow them to an industry or your Dream list, and search
   them from the top bar. A card opens in place to show everything about that lead (#/leads/12, or #/leads/12/emails for
   one of its tabs), one card at a time; lead.js draws the details. Also here: "Add a job", the live search feed, and the
   Sources button (sources.js). The job cards are shared with Home's top leads.
   APIs: GET /api/leads (one filter's leads, the counts per filter and the industries), GET /api/leads/{id},
   POST /api/leads/manual, PATCH /api/leads/{id} (status changes from a card), DELETE /api/leads/{id} and
   POST /api/leads/retriage. While it's open, live events (live.js) call upsertLead, appendLog and renderFeedHead. */
"use strict";

const LEAD_FILTERS = [["ready", "Ready"], ["queue", "In progress"], ["filtered", "Filtered out"], ["closed", "Closed"], ["trashed", "Deleted"], ["all", "All"]];
const LEAD_SORTS = [["score", "Best match"], ["new", "Newest found"], ["deadline", "Deadline soonest"], ["posted", "Recently posted"], ["industry", "Industry"]];

// Draws the page once (a new address on it only opens or closes a card), then opens the card the address names.
async function renderLeads(id, tab) {
  const arriving = main.dataset.page !== "leads";
  if (arriving) {
    main.dataset.page = "leads";
    S.expanded = null;
    if (S.leadView) closeLeadDetails();  // drawn again from scratch (Try again): the old card's details are gone
    main.innerHTML = `<div class="page-heading"><div><p class="eyebrow">YOUR LEADS</p><h1>Leads</h1>
        <p>Every job JobPortal found for you, ranked by how well it fits. Open one to see its tailored resume, cover letter and more.</p></div>
        <div class="heading-actions"><button class="button outline" type="button" data-act="sources">${icon("signal")} Sources</button>
          <button class="button primary" type="button" data-act="add-job">${icon("plus")} Add a job</button></div></div>
      <section class="live-panel${S.feedOpen ? " open" : ""}" id="live-panel" aria-label="Live search feed">
        <button class="live-head" type="button" data-act="toggle-feed" aria-expanded="${S.feedOpen}" aria-controls="live-log">
          <span class="live-status" id="live-status"></span><span class="live-toggle">${icon("chevron")}</span></button>
        <div class="live-log" id="live-log" role="log"></div></section>
      <div class="filters" id="lead-filters" role="group" aria-label="Which leads"></div>
      <div class="list-controls">
        <label class="control"><span>Sort</span><select id="lead-sort">${selectOptions(LEAD_SORTS, S.sort)}</select></label>
        <label class="control"><span>Industry</span><select id="lead-industry"><option value="">All industries</option></select></label>
        <button class="chip" type="button" id="dream-chip" data-act="dream-only"></button>
        <span class="list-count" id="lead-count" aria-live="polite"></span></div>
      <div class="job-list" id="lead-list"></div>`;
    renderFeedHead();
    $("#live-log").innerHTML = S.logs.map(logLine).join("");
    $("#live-log").scrollTop = 1e9;  // start at the newest line
    await loadLeads();
  }
  if (S.openSources) {  // an old #/sources link, also when it was followed with Leads already open
    S.openSources = false;
    openSources().catch((err) => toast("Couldn't open Sources", err.message, "error"));
  }
  await expandLead(id ? +id : null, tab, arriving);
}

// ---------------------------------------------------------------- the live search feed
// The feed's top line: what the search is doing (its phase, time, counts and tokens), or the last search's counts.
function renderFeedHead() {
  const el = $("#live-status");
  if (!el) return;
  const st = S.state;
  const counts = RUN_COUNTS.filter(([key]) => (st.counts || {})[key] != null)
    .map(([key, label]) => `<span class="tag"><b>${st.counts[key]}</b> ${label}</span>`).join("");
  if (st.running) {
    const started = Date.parse(st.started_at);
    const seconds = started ? Math.max(0, Math.floor((Date.now() - started) / 1000)) : 0;
    const used = (+st.tokens || 0) - (+st.run_tokens_start || 0);
    el.innerHTML = `${spinner()}<b>${esc(runPhase(st.phase))}</b><span class="muted">${Math.floor(seconds / 60)}m ${seconds % 60}s</span>${counts}`
      + (used > 0 ? `<span class="tag" title="AI tokens this search used on your ChatGPT plan">${fmtTokens(used)} tokens</span>` : "");
  } else {
    el.innerHTML = `<span class="status-dot off"></span><b>Live search</b>`
      + (counts ? `<span class="muted">Last search:</span>${counts}` : `<span class="muted">Run a search to watch it here.</span>`);
  }
}
setInterval(() => {  // the clock ticks while a search runs
  if (S.state.running && S.route[0] === "leads") renderFeedHead();
}, 1000);

// One feed line: local time, source, message.
const logLine = (line) => `<div class="log-line ${esc(line.level)}"><span class="log-time">${localClock(line.ts)}</span>`
  + `<span class="log-source">${esc(line.source || "")}</span><span class="log-msg">${esc(line.msg)}</span></div>`;

// Adds one line to the open feed (a "log" event), keeping 600 at most. It follows new lines only if you were at the bottom.
function appendLog(line) {
  const log = $("#live-log");
  if (!log) return;
  const atBottom = log.scrollHeight - log.scrollTop - log.clientHeight < 40;
  log.insertAdjacentHTML("beforeend", logLine(line));
  while (log.childElementCount > 600) log.firstElementChild.remove();
  if (atBottom) log.scrollTop = 1e9;
}

// Empties the feed when a new search starts.
function clearLog() {
  const log = $("#live-log");
  if (log) log.innerHTML = "";
}

// ---------------------------------------------------------------- the list
// Mirrors the server's filter rules, so a live update can tell whether a changed lead still belongs in the open filter.
function inFilter(lead, tab) {
  if (tab === "trashed") return lead.app_status === "trashed";
  if (lead.app_status === "trashed") return false;
  if (tab === "ready") return lead.stage === "ready" && ["new", "ready"].includes(lead.app_status);
  if (tab === "queue") return ["qualified", "packaging", "error"].includes(lead.stage);
  if (tab === "filtered" || tab === "closed") return lead.stage === tab;
  return tab === "all";
}

// Loads the open filter's leads (GET /api/leads), then redraws the filters, the counts and the cards. silent = a live
// refresh: cards that weren't there before get a highlight.
// - Only the newest load draws. Typing in the search box or clicking through the filters sends several requests, and
//   an older answer that came back last would show the wrong list.
// - The open card is never taken out of the page: the cards around it are replaced, and it moves to its place in the
//   new order (or stays on top when it left this filter). Taking it out would drop the focus from its editor in the
//   middle of typing and reload its preview, every few seconds during a search.
// - A load that fails keeps the list on screen and says so, or, with no list yet, shows the error with Try again.
let leadsLoad = 0;
async function loadLeads(silent) {
  const ticket = ++leadsLoad;
  const params = new URLSearchParams({ tab: S.leadsTab, q: S.q, sort: S.sort, industry: S.industry, dream: S.dreamOnly ? 1 : 0 });
  let d;
  try {
    d = await api(`/api/leads?${params}`);
  } catch (err) {
    const list = $("#lead-list");
    if (!list || ticket !== leadsLoad) return;
    if (!$(".job-card", list)) list.innerHTML = loadError(err);
    else if (!silent) toast("Couldn't load your leads", err.message, "error");
    return;
  }
  const list = $("#lead-list");
  if (!list || ticket !== leadsLoad) return;  // you left the page, or a newer load is on its way
  renderListControls(d);
  const known = new Set($$(".job-card", list).map((card) => +card.dataset.id));
  const openCard = S.expanded && $(`.job-card[data-id="${S.expanded}"]`, list);
  const empty = S.q || S.industry || S.dreamOnly ? "Nothing matches. Try clearing the search or a filter."
    : S.leadsTab === "ready" ? "Run a search. Leads show up here as each one's application is tailored." : "Nothing here right now.";
  const html = d.leads.map((l) => leadCard(l, silent && known.size > 0 && !known.has(l.id))).join("");
  const focus = focusKey(list);
  if (!openCard) {
    list.innerHTML = html || `<div class="empty-state"><h3>No leads here</h3><p>${empty}</p></div>`;
  } else {
    const fresh = document.createElement("template");
    fresh.innerHTML = html;
    const nodes = [...fresh.content.childNodes], slot = $(`.job-card[data-id="${S.expanded}"]`, fresh.content);
    [...list.childNodes].forEach((node) => node !== openCard && node.remove());
    if (slot) {
      refreshOpenCard(openCard, slot);
      openCard.before(...nodes.slice(0, nodes.indexOf(slot)));
      openCard.after(...nodes.slice(nodes.indexOf(slot) + 1));
    } else {
      openCard.after(...nodes);  // it left this filter while open: it stays on top until you close it
    }
  }
  refocus(list, focus);
}

// The filter chips with their counts, the industry menu, the Dream list chip and the line that says what's shown.
function renderListControls(d) {
  $("#lead-filters").innerHTML = LEAD_FILTERS.map(([key, label]) => `<button class="chip${S.leadsTab === key ? " active" : ""}" type="button"`
    + ` data-act="leads-tab" data-tab="${key}" aria-pressed="${S.leadsTab === key}">${label} <b>${d.counts[key] ?? 0}</b></button>`).join("");
  // The industry menu lists this filter's industries. A chosen one with no leads stays listed (with 0), so you can see it's on.
  const industries = [["", "All industries"], ...Object.entries(d.industries || {}).map(([name, n]) => [name, `${name} (${n})`])];
  if (S.industry && !(d.industries || {})[S.industry]) industries.push([S.industry, `${S.industry} (0)`]);
  $("#lead-industry").innerHTML = selectOptions(industries, S.industry);
  const dream = $("#dream-chip");
  dream.classList.toggle("active", S.dreamOnly);
  dream.setAttribute("aria-pressed", String(S.dreamOnly));
  dream.innerHTML = `${icon("star", S.dreamOnly ? "filled" : "")} Dream list only <b>${d.dream_count ?? 0}</b>`;
  const search = S.q ? `Results for "${esc(S.q)}" <button class="text-button" type="button" data-act="clear-search">Clear</button>` : "";
  const rescore = ["filtered", "queue"].includes(S.leadsTab)
    ? `<button class="text-button" type="button" data-act="retriage" title="Score these again against your profile as it is now">${icon("refresh")} Score again</button>` : "";
  $("#lead-count").innerHTML = `<span>${plural(d.leads.length, "lead")} shown</span>${search}${rescore}`;
}

// A live update for one lead: redraw its card, add it at the top (highlighted), or take it away if it left the filter.
function upsertLead(lead) {
  const list = $("#lead-list");
  if (!list) return;
  const card = $(`.job-card[data-id="${lead.id}"]`, list);
  const open = card && card.classList.contains("open");
  const fresh = document.createElement("template");
  fresh.innerHTML = leadCard(lead, !card).trim();
  if (open) {
    refreshOpenCard(card, fresh.content.firstElementChild);
    return;
  }
  if (!inFilter(lead, S.leadsTab)) {
    card?.remove();
  } else if (card) {
    card.replaceWith(fresh.content);
  } else {
    $(".empty-state", list)?.remove();
    list.prepend(fresh.content);
  }
}

// The open card keeps its details: only its summary (and the stage and status it carries) take the new card's.
function refreshOpenCard(card, newer) {
  $(".job-summary", card).replaceWith($(".job-summary", newer));
  card.dataset.stage = newer.dataset.stage;
  card.dataset.status = newer.dataset.status;
}

// ---------------------------------------------------------------- opening a card
// Opens the card for this lead (closing the one that was open) and shows its details on the given tab. A lead that isn't
// in the list (another filter, or a link from Home) is added on top. scroll = you just arrived: bring it into view.
async function expandLead(id, tab, scroll) {
  const list = $("#lead-list");
  if (!list) return;
  if (S.expanded && S.expanded !== id) collapseLead(S.expanded);
  S.expanded = id;
  if (!id) return;
  let card = $(`.job-card[data-id="${id}"]`, list);
  if (!card) {
    let lead;
    try {
      lead = await api(`/api/leads/${id}`);
    } catch (_) {
      toast("That lead is gone", "It may have been deleted for good.", "error");
      location.replace("#/leads");
      return;
    }
    if (S.expanded !== id || !$("#lead-list")) return;  // you moved on while it loaded
    $(".empty-state", list)?.remove();
    list.insertAdjacentHTML("afterbegin", leadCard(lead));
    card = $(`.job-card[data-id="${id}"]`, list);
  }
  setCardOpen(card, true);
  const details = $(".job-details", card);
  if (S.leadView?.box === details) {
    showLeadTab(tab || "overview");
  } else {
    if (scroll) card.scrollIntoView({ block: "start" });
    await showLeadDetails(details, id, { tab: tab || "overview", hashBase: `#/leads/${id}` });
  }
}

// Closes a card and drops its details. A lead that left the filter while it was open goes away now.
function collapseLead(id) {
  const card = $(`.job-card[data-id="${id}"]`);
  if (!card) return;
  if (S.leadView?.box.closest(".job-card") === card) closeLeadDetails();
  if (!inFilterCard(card)) {
    card.remove();
    return;
  }
  setCardOpen(card, false);
  $(".job-details", card).innerHTML = "";
}

// Whether a card's lead still belongs in the open filter (its summary carries the stage and status).
const inFilterCard = (card) => inFilter({ stage: card.dataset.stage, app_status: card.dataset.status }, S.leadsTab);

// Marks a card open or closed: its details show, and its buttons say what a click does now.
function setCardOpen(card, open) {
  card.classList.toggle("open", open);
  $(".job-details", card).hidden = !open;
  $$("[aria-expanded]", card).forEach((el) => el.setAttribute("aria-expanded", String(open)));
  const toggleLabel = $(".job-toggle span", card);
  if (toggleLabel) toggleLabel.textContent = open ? "Close" : "View details";
}

// ---------------------------------------------------------------- job cards
// One lead as a job card: the company's initial, the title, company and stage, the match pill, where and when, why it
// fits, its tags, and buttons. A click anywhere on it opens it (on Leads) or goes to it (from Home).
function leadCard(l, fresh) {
  const open = S.route[0] === "leads" && S.expanded === l.id;
  const expanding = S.route[0] === "leads" ? ` aria-expanded="${open}"` : "";
  const reason = l.triage?.summary ? `<p class="job-description">${esc(l.triage.summary)}</p>` : "";
  return `<article class="job-card${fresh ? " fresh" : ""}${open ? " open" : ""}" data-id="${l.id}" data-stage="${esc(l.stage)}" data-status="${esc(l.app_status)}">
    <div class="job-summary" data-act="lead-open" data-id="${l.id}">
      <div class="job-top">${companyLogo(l.company)}
        <div class="job-title"><h3><button class="job-open" type="button" data-act="lead-open" data-id="${l.id}"${expanding}>${esc(l.title || "Untitled job")}</button></h3>
          <div class="company-line"><span>${esc(l.company || "Company not given")}</span>${stageTag(l)}</div></div>
        ${matchPill(l.score || null)}</div>
      <div class="job-meta">${leadMeta(l)}</div>
      ${reason}
      <div class="job-bottom"><div class="tags">${leadTags(l)}</div><div class="job-actions">${cardActions(l, open)}</div></div>
    </div>
    <div class="job-details"${open ? "" : " hidden"}></div></article>`;
}

// The company's first letter in a tinted square. The tint comes from the name, so a company keeps its color.
function companyLogo(company) {
  const name = String(company || "?").trim() || "?";
  const tint = [...name].reduce((sum, c) => sum + c.charCodeAt(0), 0) % 3;
  return `<span class="company-logo tint-${tint}" aria-hidden="true">${esc(name[0].toUpperCase())}</span>`;
}

// The small tag after the company: what stage the lead is at, your status, or NEW for a lead found in the last two days.
function stageTag(l) {
  if (l.stage === "packaging") return `<span class="new-tag busy">${spinner()}TAILORING</span>`;
  if (l.stage === "qualified") return `<span class="new-tag plain">QUEUED</span>`;
  if (l.stage === "error") return `<span class="new-tag bad" title="${esc(l.stage_error)}">FAILED</span>`;
  if (l.stage === "filtered") return `<span class="new-tag plain">FILTERED OUT</span>`;
  if (l.stage === "closed") return `<span class="new-tag plain">CLOSED</span>`;
  if (l.app_status && l.app_status !== "new") return `<span class="new-tag ${l.app_status === "rejected" || l.app_status === "trashed" ? "plain" : "blue"}">${esc(statusLabel(l.app_status).toUpperCase())}</span>`;
  const isNew = l.created_at && Date.now() - Date.parse(l.created_at) < 2 * 86400000;
  return isNew ? `<span class="new-tag">NEW</span>` : "";
}

// Where and when: the location, when it was posted, the deadline and where it was found.
function leadMeta(l) {
  const items = [`<span>${icon("pin")}${esc(l.location || "Location not given")}</span>`];
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

// The tags at the bottom of a card: industry, dream, kind, category, keyword coverage, open questions and red flags.
// The lead's details show them too.
function leadTags(l) {
  const tags = [];
  if (l.dream) tags.push(`<span class="tag green">${icon("star", "filled")}Dream</span>`);
  if (l.industry) tags.push(`<span class="tag">${esc(l.industry)}</span>`);
  if (l.kind && l.kind !== "posting") tags.push(`<span class="tag purple">${esc(humanize(l.kind))}</span>`);
  if (l.category) tags.push(`<span class="tag">${esc(l.category)}</span>`);
  if (l.ats_coverage != null) {
    tags.push(`<span class="tag ${l.ats_coverage >= 0.75 ? "green" : "warn"}" title="The job's keywords found in your tailored resume">`
      + `Keywords ${Math.round(l.ats_coverage * 100)}%</span>`);
  }
  if (l.open_q) tags.push(`<span class="tag warn" title="Answer them to make this application stronger">${icon("question")}${plural(l.open_q, "question")}</span>`);
  const flags = l.triage?.red_flags || [];
  if (flags.length) tags.push(`<span class="tag warn" title="${esc(flags.join("; "))}">${icon("flag")}${plural(flags.length, "flag")}</span>`);
  return tags.join("");
}

// The buttons on a card: where it was found, Add to tracker (for a new lead), and View details. A deleted lead has
// Restore and Delete forever instead.
function cardActions(l, open) {
  if (l.app_status === "trashed") {
    return `<button class="button outline" type="button" data-act="lead-restore" data-id="${l.id}">${icon("undo")}Restore</button>`
      + `<button class="button danger" type="button" data-act="lead-purge" data-id="${l.id}">${icon("trash")}Delete forever</button>`;
  }
  const track = l.app_status === "new" ? `<button class="button light" type="button" data-act="lead-track" data-id="${l.id}">${icon("plus")}Add to tracker</button>` : "";
  return `${foundBtn(l)}${track}<button class="button primary job-toggle" type="button" data-act="lead-open" data-id="${l.id}">`
    + `<span>${open ? "Close" : "View details"}</span>${icon("arrow")}</button>`;
}

// ---------------------------------------------------------------- where a lead was found
// Short names for "found at" links. (LABEL_SRC in core.js names the sources on the cards.)
const FOUND_NAME = { github: "GitHub list", ats: "Company board", linkedin: "LinkedIn", hackernews: "Hacker News", reddit: "Reddit",
  mastodon: "Mastodon", bluesky: "Bluesky", themuse: "The Muse", usajobs: "USAJobs", remote: "Remote board", rss: "RSS feed",
  adzuna: "Adzuna", google: "Google Jobs", manual: "Your link" };

// The places a lead was found that have a usable link.
const foundList = (l) => (l.found || []).filter((f) => safeUrl(f.url));

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

// The "found at" button: a link when there's one place, else a button that lists them all.
function foundBtn(l) {
  const places = foundList(l);
  if (!places.length) return "";
  if (places.length > 1) {
    return `<button class="button outline" type="button" data-act="found-menu" data-id="${l.id}">${icon("external")}${places.length} places</button>`;
  }
  const f = places[0];
  return `<a class="button outline" data-act="ext" href="${esc(f.url)}" target="_blank" rel="noopener" title="Where it was found: ${esc(f.label)}">`
    + `${icon("external")}${esc(foundShort(f))}</a>`;
}

// The dialog behind that button: every place the lead was found, with the full link.
function foundMenu(l) {
  const places = foundList(l).map((f) => `<a class="link-row" href="${esc(f.url)}" target="_blank" rel="noopener">
      <span class="tag blue">${esc(foundShort(f))}</span><span class="link-row-text"><b>${esc(f.label)}</b><small>${esc(f.url)}</small></span>${icon("external")}</a>`).join("");
  openDialog(`<h2>Where this was found</h2><p>${esc(l.title)}, ${esc(l.company || "")}</p><div class="link-list">${places}</div>`, { eyebrow: "FOUND AT" });
}

// ---------------------------------------------------------------- add a job
// The "Add a job" dialog: a link or the pasted posting. POST /api/leads/manual starts tailoring it, or returns the saved
// lead when the same job was added before.
function addJobDialog() {
  const kinds = [["posting", "A job posting"], ["program", "A program"], ["event", "An event"], ["intel", "A lead with no posting yet"]];
  openDialog(`<h2>Add a job</h2>
    <p>Paste a link to any job, or paste the posting itself. JobPortal reads it and tailors a resume and cover letter for it.</p>
    <div class="form-grid">
      <label class="field wide"><span class="field-label">Link</span><input type="url" id="aj-url" placeholder="https://"></label>
      <label class="field wide"><span class="field-label">Or paste the posting</span><textarea id="aj-text" rows="7"></textarea></label>
      <label class="field"><span class="field-label">Job title (optional)</span><input type="text" id="aj-title"></label>
      <label class="field"><span class="field-label">Company (optional)</span><input type="text" id="aj-company"></label>
      <label class="field"><span class="field-label">What is it?</span><select id="aj-kind">${selectOptions(kinds)}</select></label></div>
    <div class="dialog-actions"><button class="button outline" type="button" data-act="close-dialog">Cancel</button>
      <button class="button primary" type="button" data-act="add-job-go">Add and tailor ${icon("arrow")}</button></div>`, { eyebrow: "ADD A JOB" });
}

// ---------------------------------------------------------------- actions
onAction("lead-open", (el) => {
  const id = +el.dataset.id;
  location.hash = S.route[0] === "leads" && S.expanded === id ? "#/leads" : `#/leads/${id}`;
});
onAction("leads-tab", (el) => {  // a filter chip here, or a link from Home that opens Leads on a filter
  S.leadsTab = el.dataset.tab;
  store.set("leadsTab", S.leadsTab);
  if (el.tagName === "A") return;  // the link opens the page
  if (S.expanded) location.hash = "#/leads";  // a new filter closes the open card
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
onAction("toggle-feed", (el) => {
  S.feedOpen = !S.feedOpen;
  store.set("feedOpen", S.feedOpen ? "1" : "0");
  $("#live-panel").classList.toggle("open", S.feedOpen);
  el.setAttribute("aria-expanded", String(S.feedOpen));
  if (S.feedOpen) $("#live-log").scrollTop = 1e9;
});
onAction("retriage", async () => {
  await api("/api/leads/retriage", { method: "POST" });
  toast("Scoring again", "Waiting and filtered-out leads are being scored against your profile as it is now.");
});
onAction("lead-track", async (el) => {
  upsertLead(await api(`/api/leads/${el.dataset.id}`, { method: "PATCH", body: { app_status: "ready" } }));
  if (S.route[0] === "home") loadTopLeads();
  refreshStats();
  toast("Added to your tracker", "It's under Ready to apply.");
});
onAction("lead-restore", async (el) => {
  upsertLead(await api(`/api/leads/${el.dataset.id}`, { method: "PATCH", body: { app_status: "new" } }));
  refreshStats();
  toast("Restored", "It's back in your leads.");
});
onAction("lead-purge", async (el) => {
  if (!confirm("Delete this lead for good? Its tailored documents go too, and a later search may find the job again.")) return;
  await api(`/api/leads/${el.dataset.id}`, { method: "DELETE" });
  if (S.expanded === +el.dataset.id) location.hash = "#/leads";
  $(`.job-card[data-id="${el.dataset.id}"]`)?.remove();
  loadLeads();
  toast("Deleted for good");
});
onAction("found-menu", async (el) => foundMenu(await api(`/api/leads/${el.dataset.id}`)));
onAction("add-job", () => addJobDialog());
onAction("add-job-go", async (el) => {
  const dialog = el.closest("dialog");
  const value = (id) => $(id, dialog).value.trim();
  const body = { url: value("#aj-url"), text: value("#aj-text"), title: value("#aj-title"), company: value("#aj-company"), kind: value("#aj-kind") };
  if (!body.url && !body.text) {
    toast("Paste a link or the posting", "JobPortal needs one of them to tailor your application.", "error");
    return;
  }
  el.disabled = true;
  try {
    const lead = await api("/api/leads/manual", { method: "POST", body });
    closeDialog(dialog);
    if (lead.existing) toast("Already in your leads", "That job is saved already. Here it is.", "", lead.id);
    else toast("Tailoring it now", "Its resume and cover letter show up here in a few minutes.", "", lead.id);
    location.hash = `#/leads/${lead.id}`;
  } finally {
    el.disabled = false;
  }
});
onChange((el) => {
  if (el.id === "lead-sort") S.sort = el.value;
  else if (el.id === "lead-industry") S.industry = el.value;
  else return false;
  loadLeads();
  return true;
});
