/* leads.js: the Leads page ("Mission control"). Start or stop a search and watch it live (the mission bar and the live
   feed), see the headline numbers, and browse leads by tab, search text, sort, industry, kind and the dream filter. Also
   the "+ Add a lead" dialog, and the lead chips and "found at" links that the lead page reuses.

   APIs: GET /api/leads (the list and the tab counts), POST /api/run and /api/run/stop, POST /api/leads/manual,
   PATCH /api/leads/{id} (save, trash or restore from the list) and POST /api/leads/retriage.
   While this page is open, live events (live.js) call renderMission, appendLog and upsertLead. */
"use strict";

const RUN_MODES = [["full", "Everything"], ["boards", "Job boards only"], ["hunt", "AI hunt only"], ["backlog", "Package queue only"]];
const LEAD_SORTS = [["score", "Best match"], ["new", "Newest found"], ["deadline", "Deadline soonest"], ["posted", "Recently posted"],
  ["industry", "Industry"]];
const LEAD_KINDS = [["", "All kinds"], ["posting", "Postings"], ["program", "Programs"], ["event", "Events"], ["intel", "Intel (no posting yet)"]];
const TAB_LABELS = { ready: "Ready", queue: "In queue", filtered: "Below threshold", closed: "Closed", trashed: "Trashed", all: "All" };

// Draws the page (header, mission bar, tiles, live feed, tabs, filters), then loads the lead list.
async function renderLeads() {
  const setupBanner = onboarded() ? "" : `<div class="banner accent">
      <div><b>Finish setting up first.</b> Import your resume and answer the standard job questions, and JobPortal builds the
        profile it searches with.</div>
      <span class="spacer"></span><a class="btn primary sm" href="#/setup">Set up</a></div>`;
  main.innerHTML = `<div class="page">
    <div class="page-h"><h1>Mission control</h1><span class="sub">Every lead, tailored and ready to fire.</span><span class="spacer"></span>
      <button class="btn" data-act="add-lead">+ Add a lead</button></div>
    ${setupBanner}
    <div id="mission"></div>
    <div class="tiles" id="tiles"></div>
    <div class="console ${S.consoleOpen ? "" : "closed"}" id="console">
      <div class="ch" data-act="toggle-console"><span><i class=i-chev></i> Live feed</span><span class="spacer"></span>
        <span id="console-n"></span><span id="console-toggle">${S.consoleOpen ? "hide" : "show"}</span></div>
      <div class="body" id="console-body"></div></div>
    <div class="tabs" id="ltabs"></div>
    <div class="filters">
      <input type="text" id="lq" placeholder="Search title, company, location, source…" value="${esc(S.q)}">
      <select id="lsort">${selectOptions(LEAD_SORTS, S.sort)}</select>
      <select id="lind"><option value="">All industries</option></select>
      <button class="btn sm ${S.dreamOnly ? "toggled" : "ghost"}" data-act="dream-only"
        title="Only dream companies / dream jobs. Edit them on the Dream list page"><i class=i-star></i> Dream</button>
      <select id="lkind">${selectOptions(LEAD_KINDS, S.kind)}</select>
      <span class="spacer"></span><span class="muted small mono" id="lcount"></span>
    </div>
    <div class="leads" id="leadlist"></div></div>`;
  // Every filter change stores the new value in S and reloads the list.
  const filter = (key) => (e) => {
    S[key] = e.target.value;
    loadLeads();
  };
  $("#lq").addEventListener("input", debounce(filter("q"), 250));
  $("#lsort").onchange = filter("sort");
  $("#lkind").onchange = filter("kind");
  $("#lind").onchange = filter("industry");
  renderMission();
  renderTiles();
  $("#console-body").innerHTML = S.logs.map(logLine).join("");
  $("#console-body").scrollTop = 1e9;  // start at the newest line
  await loadLeads();
}

// ---------------------------------------------------------------- mission bar
// Run search (with the mode menu) or Stop, what the run is doing, the search area chip and the alerts switch. Redrawn by
// "state" and "tokens" events, and every second during a run so the timer ticks.
function renderMission() {
  const el = $("#mission");
  if (!el) return;
  const st = S.state;
  const counts = st.counts || {};
  const chips = ["found", "candidates", "triaged", "qualified", "packaged"].filter((key) => counts[key] != null)
    .map((key) => `<span class="chip"><b>${counts[key]}</b> ${key}</span>`).join("");
  let runButton, phase;
  if (st.running) {
    const runTokens = (+st.tokens || 0) - (+st.run_tokens_start || 0);
    const tokens = runTokens > 0 ? `<span class="chip" title="AI tokens this run has used on your ChatGPT plan">${fmtTokens(runTokens)} tokens</span>` : "";
    const started = Date.parse(st.started_at);
    const seconds = started ? Math.max(0, Math.floor((Date.now() - started) / 1000)) : 0;
    runButton = `<button class="btn stop" data-act="stop"><i class=i-stop></i> Stop</button>`;
    phase = `<div class="p"><span class="spin"></span><b>${esc(st.phase)}</b>`
      + `<span class="muted">run #${st.run_id}, ${esc(st.mode)}, ${Math.floor(seconds / 60)}m ${seconds % 60}s</span></div>`
      + `<div class="counters">${chips}${tokens}</div>`;
  } else {
    runButton = `<button class="btn primary go" data-act="run"><i class=i-play></i> Run search</button>`
      + `<select class="mode" id="runmode" title="What to run">${selectOptions(RUN_MODES, localStorage.getItem("runmode") || "full")}</select>`;
    phase = `<div class="p muted">Idle. A run sweeps LinkedIn, company boards, job lists, HN, Reddit, Mastodon and feeds, while AI agents
      hunt social media, recruiters, labs, contracts and events.</div>`
      + (chips ? `<div class="counters">${chips}<span class="chip">last run</span></div>` : "");
  }
  const alerts = S.notify ? "<i class=i-bell></i> Alerts on" : "<i class=i-bell-off></i> Alerts off";
  el.innerHTML = `<div class="mission ${st.running ? "running" : ""}">
    <div class="runbtn">${runButton}</div>
    <div class="phase">${phase}</div>
    <div class="right"><button class="chip area-chip" data-act="edit-area" title="Where the search looks. Click to broaden or shrink it.">
        <i class=i-pin></i> ${esc(areaSummary(S.searchArea || []))} <i class=i-edit></i></button>
      <button class="btn ghost sm" data-act="notify" title="Desktop notifications when leads are ready">${alerts}</button></div></div>`;
}
setInterval(() => {
  if (S.state.running && S.route[0] === "leads") renderMission();
}, 1000);

// The five numbers under the mission bar. Ready and In the queue switch the list's tab; the rest open the Tracker.
function renderTiles() {
  const el = $("#tiles");
  if (!el) return;
  const s = S.stats || {};
  const tiles = [  // [where a click goes, label, number, extra class]
    ["ready", "Ready to apply", s.ready, "hot"],
    ["queue", "In the queue", s.queue],
    ["tracker", "Applied (last 7 days)", `${s.applied ?? 0} (${s.applied_week ?? 0})`],
    ["tracker", "Interviewing", s.interviewing],
    ["tracker", "Follow-ups due", s.followups_due, s.followups_due ? "hot" : ""],
  ];
  el.innerHTML = tiles.map(([go, label, n, cls]) => `<div class="tile ${cls || ""}" data-act="tile" data-go="${go}">`
    + `<div class="n">${n ?? 0}</div><div class="l">${label}</div></div>`).join("");
}

// ---------------------------------------------------------------- live feed
// One feed line: local time, source, message. The feed keeps spacing (pre-wrap), hence the two spaces.
const logLine = (line) => `<div class="ln ${esc(line.level)}"><span class="t">${localClock(line.ts)}</span>`
  + `<span class="s">${esc(line.source || "")}</span>  ${esc(line.msg)}</div>`;

// Adds one line to the open feed (a "log" event) and keeps at most 600. It follows new lines only if you were at the bottom.
function appendLog(line) {
  const body = $("#console-body");
  if (!body) return;
  const atBottom = body.scrollHeight - body.scrollTop - body.clientHeight < 40;
  body.insertAdjacentHTML("beforeend", logLine(line));
  while (body.childElementCount > 600) body.firstElementChild.remove();
  if (atBottom) body.scrollTop = 1e9;
  const count = $("#console-n");
  if (count) count.textContent = `${S.logs.length} lines`;
}

// ---------------------------------------------------------------- the list
// Mirrors the server's tab rules, so a live update can tell whether a changed lead still belongs in the open tab.
function inTab(lead, tab) {
  if (tab === "trashed") return lead.app_status === "trashed";
  if (lead.app_status === "trashed") return false;
  if (tab === "ready") return lead.stage === "ready" && ["new", "saved"].includes(lead.app_status);
  if (tab === "queue") return ["qualified", "packaging", "error"].includes(lead.stage);
  if (tab === "filtered" || tab === "closed") return lead.stage === tab;
  return tab === "all";
}

// Switches the list to another tab and remembers it.
function showLeadsTab(tab) {
  S.leadsTab = tab;
  localStorage.setItem("leadsTab", tab);
  loadLeads();
}

// Loads the list for the open tab and filters (GET /api/leads), then redraws the tabs, the count, the industry menu and
// the cards. silent = a live refresh: cards that weren't there before get the "fresh" highlight.
async function loadLeads(silent) {
  const params = new URLSearchParams({ tab: S.leadsTab, q: S.q, sort: S.sort, kind: S.kind, industry: S.industry || "", dream: S.dreamOnly ? 1 : 0 });
  const d = await api(`/api/leads?${params}`);
  const tabs = $("#ltabs");
  if (!tabs) return;  // you left the page while the list was loading
  tabs.innerHTML = Object.entries(TAB_LABELS).map(([key, label]) => `<a class="${S.leadsTab === key ? "on" : ""}" data-act="ltab" data-tab="${key}">`
    + `${label}<span class="n">${d.counts[key] ?? 0}</span></a>`).join("");
  const retriage = ["filtered", "queue"].includes(S.leadsTab)
    ? ` <button class="btn sm" data-act="retriage" title="Re-score these against your current profile (new answers can change the verdict)">`
      + `<i class=i-refresh></i> Re-evaluate</button>`
    : "";
  $("#lcount").innerHTML = `${d.leads.length} shown${retriage}`;
  renderIndustryMenu(d.industries || {});
  const list = $("#leadlist");
  if (!d.leads.length) {
    list.innerHTML = S.leadsTab === "ready"
      ? `<div class="empty"><b>No packaged leads yet</b>Hit Run search. Leads pop in here as each application package finishes.</div>`
      : `<div class="empty"><b>Nothing here</b></div>`;
    return;
  }
  const shown = silent ? new Set($$(".lead", list).map((card) => +card.dataset.id)) : new Set();
  list.innerHTML = d.leads.map((l) => leadCard(l, shown.size > 0 && !shown.has(l.id))).join("");
}

// The industry menu lists the industries in the results, with counts. A chosen industry with no results stays listed
// (with 0), so you can see that the filter is on.
function renderIndustryMenu(industries) {
  const choices = [["", "All industries"], ...Object.entries(industries).map(([name, n]) => [name, `${name} (${n})`])];
  if (S.industry && !industries[S.industry]) choices.push([S.industry, `${S.industry} (0)`]);
  $("#lind").innerHTML = selectOptions(choices, S.industry);
}

// A live update for one lead: replace its card, add it at the top (highlighted), or remove it if it left the open tab.
function upsertLead(lead) {
  const list = $("#leadlist");
  if (!list) return;
  const card = $(`.lead[data-id="${lead.id}"]`, list);
  if (!inTab(lead, S.leadsTab)) {
    card?.remove();
    return;
  }
  const html = leadCard(lead, !card);
  if (card) {
    card.outerHTML = html;
  } else {
    $(".empty", list)?.remove();
    list.insertAdjacentHTML("afterbegin", html);
  }
}

// ---------------------------------------------------------------- lead cards
// One lead in the list. Clicking the card opens the lead; its buttons save, trash or restore it.
function leadCard(l, fresh) {
  const summary = l.triage?.summary ? ` <span class="muted">(${esc(l.triage.summary)})</span>` : "";
  const save = l.app_status === "new"
    ? `<button class="btn sm ghost" data-act="quick-status" data-st="saved" title="Save for later"><i class=i-star-o></i></button>` : "";
  const trash = l.app_status === "trashed"
    ? `<button class="btn sm ghost" data-act="quick-status" data-st="new">restore</button>`
    : `<button class="btn sm ghost danger" data-act="quick-status" data-st="trashed" title="Trash this lead"><i class=i-x></i></button>`;
  return `<div class="lead ${fresh ? "fresh" : ""}" data-id="${l.id}" data-act="open-lead">
    ${ring(l.score)}
    <div style="min-width:0"><div class="t">${esc(l.title)}</div>
      <div class="c"><b>${esc(l.company || "Unknown company")}</b>, ${esc(l.location || "location n/a")}${summary}</div>
      <div class="meta">${leadChips(l)}</div></div>
    <div class="acts">${foundBtn(l)}${stageBadge(l)}
      ${save}
      ${trash}
    </div></div>`;
}

// The status on the right of a card: building, queued, error, below threshold, closed, your application status, or ready.
function stageBadge(l) {
  if (l.stage === "packaging") return `<span class="stage stage-packaging row" style="gap:6px"><span class="spin"></span>building package</span>`;
  if (l.stage === "qualified") return `<span class="stage stage-qualified">queued</span>`;
  if (l.stage === "error") return `<span class="stage stage-error" title="${esc(l.stage_error)}">error</span>`;
  if (l.stage === "filtered") return `<span class="stage stage-filtered">below threshold</span>`;
  if (l.stage === "closed") return `<span class="stage stage-closed">closed</span>`;
  if (l.app_status && l.app_status !== "new") {
    const color = l.app_status === "offer" ? "good" : l.app_status === "rejected" ? "bad" : "blue";
    return `<span class="chip ${color}">${STATUS_LABEL[l.app_status]}</span>`;
  }
  return `<span class="stage stage-ready"><i class=i-dot></i> ready</span>`;
}

// The chips under a lead's title: industry, dream, kind, category, sources, when it was posted, the deadline, ATS keyword
// coverage, open questions and red flags. The lead page shows them too.
function leadChips(l) {
  const chips = [];
  if (l.industry) chips.push(`<span class="chip ind">${esc(l.industry)}</span>`);
  if (l.dream) chips.push(`<span class="chip accent"><i class=i-star></i> dream</span>`);
  if (l.kind && l.kind !== "posting") chips.push(`<span class="chip violet">${esc(l.kind)}</span>`);
  if (l.category) chips.push(`<span class="chip">${esc(l.category)}</span>`);
  for (const source of l.sources || [l.source]) chips.push(`<span class="chip blue">${esc(LABEL_SRC[source] || source)}</span>`);
  if (l.posted_at) chips.push(`<span class="chip">posted ${ago(l.posted_at)}</span>`);
  const days = daysUntil(l.deadline);
  if (days != null) {
    const color = days < 0 ? "" : days <= 5 ? "bad" : days <= 14 ? "warn" : "";
    const text = days < 0 ? "deadline passed" : days === 0 ? "due today" : `due in ${days}d`;
    chips.push(`<span class="chip ${color}">${text}</span>`);
  }
  if (l.ats_coverage != null) {
    const color = l.ats_coverage >= 0.75 ? "good" : "warn";
    chips.push(`<span class="chip ${color}" title="Job keywords present in the tailored resume">ATS ${Math.round(l.ats_coverage * 100)}%</span>`);
  }
  if (l.open_q) {
    chips.push(`<span class="chip warn" title="Questions that could strengthen this application. Open the lead to answer them.">`
      + `<i class=i-question></i> ${plural(l.open_q, "question")}</span>`);
  }
  const flags = (l.triage && l.triage.red_flags) || [];
  if (flags.length) chips.push(`<span class="chip warn" title="${esc(flags.join("; "))}"><i class=i-flag></i> ${plural(flags.length, "flag")}</span>`);
  return chips.join("");
}

// ---------------------------------------------------------------- where a lead was found
// Short names for "found at" links. (LABEL_SRC in core.js names the sources on the chips.)
const FOUND_NAME = { github: "GitHub list", ats: "company board", linkedin: "LinkedIn", hackernews: "Hacker News", reddit: "Reddit",
  mastodon: "Mastodon", bluesky: "Bluesky", themuse: "The Muse", usajobs: "USAJobs", remote: "remote board", rss: "RSS feed",
  adzuna: "Adzuna", google: "Google Jobs", manual: "your link" };

// The places a lead was found that have a usable link.
const foundList = (l) => (l.found || []).filter((f) => safeUrl(f.url));

// A short name for one place. AI hunt finds are named by their site ("Reddit thread"), else by their host.
function foundShort(f) {
  let host = "";
  try { host = new URL(f.url).hostname.replace(/^www\./, ""); } catch (_) {}
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

// The "found at" button on a card: a link when there's one place, else a button that lists them all.
function foundBtn(l) {
  const places = foundList(l);
  if (!places.length) return "";
  if (places.length > 1) {
    return `<button class="btn sm ghost" data-act="found-menu" data-id="${l.id}" title="Found in ${places.length} places">`
      + `<i class=i-ext></i> ${places.length} places</button>`;
  }
  const f = places[0];
  return `<a class="btn sm ghost" data-act="ext" href="${esc(f.url)}" target="_blank" rel="noopener" title="Where this was found: ${esc(f.label)}">`
    + `<i class=i-ext></i> ${esc(foundShort(f))}</a>`;
}

// The dialog behind that button: every place the lead was found, with the full link.
function foundMenu(l) {
  const places = foundList(l).map((f) => `<a class="card" href="${esc(f.url)}" target="_blank" rel="noopener" style="display:block;text-decoration:none;color:var(--text)">
      <div class="row"><span class="chip blue">${esc(foundShort(f))}</span>`
        + `<span class="small muted mono" style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap;flex:1">${esc(f.url)}</span>${I.ext}</div>
      <div class="small" style="margin-top:6px">${esc(f.label)}</div></a>`).join("");
  modal(`<h2>Where this lead was found</h2><p class="muted small">${esc(l.title)}, ${esc(l.company || "")}</p><div class="stack">
    ${places}</div>
    <div class="row" style="justify-content:flex-end;margin-top:14px"><button class="btn" onclick="closeModal()">Close</button></div>`);
}

// ---------------------------------------------------------------- add a lead
// The "+ Add a lead" dialog: a link or the pasted posting. POST /api/leads/manual starts building its package.
function addLeadModal() {
  const kinds = [["posting", "Posting"], ["program", "Program"], ["event", "Event"], ["intel", "Intel / cold outreach"]];
  modal(`<h2>Add a lead</h2><p class="muted small">Paste any job link (LinkedIn, Workday, a post, a Reddit comment) or paste the job text.
      JobPortal builds the full package.</p>
    <div class="stack"><label class="f"><span>URL</span><input type="url" id="al-url" placeholder="https://…"></label>
    <label class="f"><span>…or paste the posting text</span><textarea id="al-text" rows="7"></textarea></label>
    <div class="grid3"><label class="f"><span>Title (optional)</span><input type="text" id="al-title"></label>
    <label class="f"><span>Company (optional)</span><input type="text" id="al-co"></label>
    <label class="f"><span>Kind</span><select id="al-kind">${selectOptions(kinds)}</select></label></div>
    <div class="row" style="justify-content:flex-end"><button class="btn ghost" onclick="closeModal()">Cancel</button>`
      + `<button class="btn primary" id="al-go">Build package</button></div></div>`);
  $("#al-go").onclick = async () => {
    try {
      const body = { url: $("#al-url").value, text: $("#al-text").value, title: $("#al-title").value, company: $("#al-co").value, kind: $("#al-kind").value };
      const lead = await api("/api/leads/manual", { method: "POST", body });
      closeModal();
      toast("Building package", "JobPortal is researching and tailoring. It pops up here when it's ready.", "", lead.id);
      location.hash = `#/lead/${lead.id}`;
    } catch (e) {
      toast("Couldn't add lead", e.message, "error");
    }
  };
}

// ---------------------------------------------------------------- actions
onAction("add-lead", () => addLeadModal());
onAction("open-lead", (el) => {
  location.hash = `#/lead/${el.dataset.id}`;
});
onAction("found-menu", async (el) => foundMenu(await api(`/api/leads/${el.dataset.id}`)));
onAction("quick-status", async (el) => {  // the save, trash and restore buttons on a card
  const id = el.closest(".lead").dataset.id;
  await api(`/api/leads/${id}`, { method: "PATCH", body: { app_status: el.dataset.st } });
  if (el.dataset.st === "trashed") toast("Trashed", "Find it under the Trashed tab.");
});
onAction("run", async () => {
  const mode = $("#runmode")?.value || "full";
  localStorage.setItem("runmode", mode);
  // In a browser tab, the first run with alerts on asks for permission to notify.
  if (S.notify && !desktop() && "Notification" in window && Notification.permission === "default") Notification.requestPermission();
  await api("/api/run", { method: "POST", body: { mode } });
  S.logs = [];
  const feed = $("#console-body");
  if (feed) feed.innerHTML = "";
});
onAction("stop", async () => {
  await api("/api/run/stop", { method: "POST" });
  toast("Stopping", "Finishing up and saving progress…");
});
onAction("notify", () => {
  S.notify = !S.notify;
  localStorage.setItem("notify", S.notify ? "1" : "0");
  if (S.notify && !desktop() && "Notification" in window) Notification.requestPermission();
  renderMission();
});
onAction("toggle-console", () => {
  S.consoleOpen = !S.consoleOpen;
  localStorage.setItem("consoleOpen", S.consoleOpen ? "1" : "0");
  $("#console").classList.toggle("closed", !S.consoleOpen);
  $("#console-toggle").textContent = S.consoleOpen ? "hide" : "show";
});
onAction("tile", (el) => {
  if (el.dataset.go === "tracker") location.hash = "#/tracker";
  else showLeadsTab(el.dataset.go);
});
onAction("ltab", (el) => showLeadsTab(el.dataset.tab));
onAction("dream-only", (el) => {
  S.dreamOnly = !S.dreamOnly;
  el.classList.toggle("toggled", S.dreamOnly);
  el.classList.toggle("ghost", !S.dreamOnly);
  loadLeads();
});
onAction("retriage", async () => {
  await api("/api/leads/retriage", { method: "POST" });
  toast("Re-evaluating", "Below-threshold and queued leads are being re-scored against your current profile.");
});
