/* The Leads page (mission control): run a search, watch it live, and browse leads by tab, industry, search and sort. */
"use strict";

async function renderLeads() {
  main.innerHTML = `<div class="page">
    <div class="page-h"><h1>Mission control</h1><span class="sub">Every lead, tailored and ready to fire.</span><span class="spacer"></span>
      <button class="btn" data-act="add-lead">+ Add a lead</button></div>
    ${onboarded() ? "" : `<div class="banner accent"><div><b>Finish setting up first.</b> Import your resume and answer the standard job questions, and JobPortal builds the profile it searches with.</div><span class="spacer"></span><a class="btn primary sm" href="#/setup">Set up</a></div>`}
    <div id="mission"></div>
    <div class="tiles" id="tiles"></div>
    <div class="console ${S.consoleOpen ? "" : "closed"}" id="console">
      <div class="ch" data-act="toggle-console"><span><i class=i-chev></i> Live feed</span><span class="spacer"></span><span id="console-n"></span><span>${S.consoleOpen ? "hide" : "show"}</span></div>
      <div class="body" id="console-body"></div></div>
    <div class="tabs" id="ltabs"></div>
    <div class="filters">
      <input type="text" id="lq" placeholder="Search title, company, location, source…" value="${esc(S.q)}">
      <select id="lsort"><option value="score">Best match</option><option value="new">Newest found</option><option value="deadline">Deadline soonest</option><option value="posted">Recently posted</option><option value="industry">Industry</option></select>
      <select id="lind"><option value="">All industries</option></select>
      <button class="btn sm ${S.dreamOnly ? "toggled" : "ghost"}" data-act="dream-only" title="Only dream companies / dream jobs. Edit them on the Dream list page"><i class=i-star></i> Dream</button>
      <select id="lkind"><option value="">All kinds</option><option value="posting">Postings</option><option value="program">Programs</option><option value="event">Events</option><option value="intel">Intel (no posting yet)</option></select>
      <span class="spacer"></span><span class="muted small mono" id="lcount"></span>
    </div>
    <div class="leads" id="leadlist"></div></div>`;
  $("#lsort").value = S.sort; $("#lkind").value = S.kind;
  $("#lq").addEventListener("input", debounce((e) => { S.q = e.target.value; loadLeads(); }, 250));
  $("#lsort").onchange = (e) => { S.sort = e.target.value; loadLeads(); };
  $("#lkind").onchange = (e) => { S.kind = e.target.value; loadLeads(); };
  $("#lind").onchange = (e) => { S.industry = e.target.value; loadLeads(); };
  renderMission(); renderTiles();
  $("#console-body").innerHTML = S.logs.map(logLine).join("");
  $("#console-body").scrollTop = 1e9;
  await loadLeads();
}

function renderMission() {
  const el = $("#mission"); if (!el) return;
  const st = S.state, c = st.counts || {};
  const chips = [["found", c.found], ["candidates", c.candidates], ["triaged", c.triaged], ["qualified", c.qualified], ["packaged", c.packaged]]
    .filter(([, v]) => v != null).map(([k, v]) => `<span class="chip"><b>${v}</b> ${k}</span>`).join("");
  const used = (+st.tokens || 0) - (+st.run_tokens_start || 0);
  const cost = st.running && used > 0 ? `<span class="chip" title="AI tokens this run has used on your ChatGPT plan">${fmtTokens(used)} tokens</span>` : "";
  const t0 = st.started_at ? Date.parse(st.started_at) : S.runStart;
  const el2 = st.running && t0 ? Math.max(0, Math.floor((Date.now() - t0) / 1000)) : 0;
  el.innerHTML = `<div class="mission ${st.running ? "running" : ""}">
    <div class="runbtn">${st.running
      ? `<button class="btn stop" data-act="stop"><i class=i-stop></i> Stop</button>`
      : `<button class="btn primary go" data-act="run"><i class=i-play></i> Run search</button><select class="mode" id="runmode" title="What to run">
          <option value="full">Everything</option><option value="boards">Job boards only</option><option value="hunt">AI hunt only</option><option value="backlog">Package queue only</option></select>`}</div>
    <div class="phase">${st.running
      ? `<div class="p"><span class="spin"></span><b>${esc(st.phase)}</b><span class="muted">run #${st.run_id}, ${esc(st.mode)}, ${Math.floor(el2 / 60)}m ${el2 % 60}s</span></div><div class="counters">${chips}${cost}</div>`
      : `<div class="p muted">Idle. A run sweeps LinkedIn, company boards, job lists, HN, Reddit, Mastodon and feeds, while AI agents hunt social media, recruiters, labs, contracts and events.</div>${chips ? `<div class="counters">${chips}${cost}<span class="chip">last run</span></div>` : ""}`}</div>
    <div class="right"><button class="chip area-chip" data-act="edit-area" title="Where the search looks. Click to broaden or shrink it."><i class=i-pin></i> ${esc(areaSummary(S.locAllowed || []))} <i class=i-edit></i></button>
      <button class="btn ghost sm" data-act="notify" title="Desktop notifications when leads are ready">${S.notify ? '<i class=i-bell></i> Alerts on' : '<i class=i-bell-off></i> Alerts off'}</button></div></div>`;
  if (!st.running) { const m = localStorage.getItem("runmode"); if (m && $("#runmode")) $("#runmode").value = m; }
}
setInterval(() => { if (S.state.running && S.route[0] === "leads") renderMission(); }, 1000);

function renderTiles() {
  const el = $("#tiles"); if (!el) return;
  const s = S.stats || {};
  const t = [["ready", "Ready to apply", s.ready, "hot"], ["queue", "In the queue", s.queue], ["tracker", "Applied (last 7 days)", `${s.applied ?? 0} (${s.applied_week ?? 0})`],
    ["tracker", "Interviewing", s.interviewing], ["tracker", "Follow-ups due", s.followups_due, s.followups_due ? "hot" : ""]];
  el.innerHTML = t.map(([go, l, n, cls]) => `<div class="tile ${cls || ""}" data-act="tile" data-go="${go}"><div class="n">${n ?? 0}</div><div class="l">${l}</div></div>`).join("");
}

const cleanMsg = (m) => String(m || "").replace(/^\u2713 (\d+) /, "qualified $1: ").replace(/^\u2605 (\d+) /, "ready $1: ").replace(/^[\u25A0\u25B6\u23F8] ?/, "")
  .replace(/^\uD83D\uDD0E ?/, "search: ").replace(/^\uD83C\uDF10 ?/, "read: ");
const logLine = (l) => `<div class="ln ${esc(l.level)}"><span class="t">${esc((l.ts || new Date().toISOString()).slice(11, 19))}</span><span class="s">${esc(l.source || "")}</span>  ${esc(cleanMsg(l.msg))}</div>`;
function appendLog(l) {
  const b = $("#console-body"); if (!b) return;
  const atBottom = b.scrollHeight - b.scrollTop - b.clientHeight < 40;
  b.insertAdjacentHTML("beforeend", logLine(l));
  while (b.childElementCount > 600) b.firstElementChild.remove();
  if (atBottom) b.scrollTop = 1e9;
  const n = $("#console-n"); if (n) n.textContent = `${S.logs.length} lines`;
}

const TAB_LABELS = { ready: "Ready", queue: "In queue", filtered: "Below threshold", closed: "Closed", trashed: "Trashed", all: "All" };
function inTab(l, tab) {
  if (tab === "trashed") return l.app_status === "trashed";
  if (l.app_status === "trashed") return false;
  return { ready: l.stage === "ready" && ["new", "saved"].includes(l.app_status), queue: ["qualified", "packaging", "error"].includes(l.stage),
    filtered: l.stage === "filtered", closed: l.stage === "closed", all: true }[tab];
}
async function loadLeads(silent) {
  const p = new URLSearchParams({ tab: S.leadsTab, q: S.q, sort: S.sort, kind: S.kind, industry: S.industry || "", dream: S.dreamOnly ? 1 : 0 });
  const d = await api(`/api/leads?${p}`);
  const tabs = $("#ltabs"); if (!tabs) return;
  tabs.innerHTML = Object.entries(TAB_LABELS).map(([k, l]) => `<a class="${S.leadsTab === k ? "on" : ""}" data-act="ltab" data-tab="${k}">${l}<span class="n">${d.counts[k] ?? 0}</span></a>`).join("");
  $("#lcount").innerHTML = `${d.leads.length} shown` + (["filtered", "queue"].includes(S.leadsTab) ? ` <button class="btn sm" data-act="retriage" title="Re-score these against your current profile (new answers can change the verdict)"><i class=i-refresh></i> Re-evaluate</button>` : "");
  const li = $("#lind");
  if (li) li.innerHTML = `<option value="">All industries</option>` + Object.entries(d.industries || {}).map(([k, n]) => `<option value="${esc(k)}" ${S.industry === k ? "selected" : ""}>${esc(k)} (${n})</option>`).join("")
    + (S.industry && !(d.industries || {})[S.industry] ? `<option selected value="${esc(S.industry)}">${esc(S.industry)} (0)</option>` : "");
  const list = $("#leadlist");
  if (!d.leads.length) {
    list.innerHTML = `<div class="empty"><b>${S.leadsTab === "ready" ? "No packaged leads yet" : "Nothing here"}</b>${S.leadsTab === "ready" ? "Hit Run search. Leads pop in here as each application package finishes." : ""}</div>`;
    return;
  }
  if (silent) {
    const have = new Set($$(".lead", list).map((e) => +e.dataset.id));
    list.innerHTML = d.leads.map((l) => leadCard(l, !have.has(l.id) && have.size > 0)).join("");
  } else list.innerHTML = d.leads.map((l) => leadCard(l)).join("");
}
function upsertLead(l) {
  const list = $("#leadlist"); if (!list) return;
  const el = $(`.lead[data-id="${l.id}"]`, list);
  if (!inTab(l, S.leadsTab)) { el?.remove(); return; }
  const html = leadCard(l, !el);
  if (el) el.outerHTML = html;
  else { $(".empty", list)?.remove(); list.insertAdjacentHTML("afterbegin", html); }
}
function stageBadge(l) {
  if (l.stage === "packaging") return `<span class="stage stage-packaging row" style="gap:6px"><span class="spin"></span>building package</span>`;
  if (l.stage === "qualified") return `<span class="stage stage-qualified">queued</span>`;
  if (l.stage === "error") return `<span class="stage stage-error" title="${esc(l.stage_error)}">error</span>`;
  if (l.stage === "filtered") return `<span class="stage stage-filtered">below threshold</span>`;
  if (l.stage === "closed") return `<span class="stage stage-closed">closed</span>`;
  if (l.app_status && l.app_status !== "new") return `<span class="chip ${l.app_status === "offer" ? "good" : l.app_status === "rejected" ? "bad" : "blue"}">${STATUS_LABEL[l.app_status]}</span>`;
  return `<span class="stage stage-ready"><i class=i-dot></i> ready</span>`;
}
function leadChips(l) {
  const c = [];
  if (l.industry) c.push(`<span class="chip ind">${esc(l.industry)}</span>`);
  if (l.dream) c.push(`<span class="chip accent"><i class=i-star></i> dream</span>`);
  if (l.kind && l.kind !== "posting") c.push(`<span class="chip violet">${esc(l.kind)}</span>`);
  if (l.category) c.push(`<span class="chip">${esc(l.category)}</span>`);
  (l.sources || [l.source]).forEach((s) => c.push(`<span class="chip blue">${esc(LABEL_SRC[s] || s)}</span>`));
  if (l.posted_at) c.push(`<span class="chip">posted ${ago(l.posted_at)}</span>`);
  const du = daysUntil(l.deadline);
  if (du != null) c.push(`<span class="chip ${du < 0 ? "" : du <= 5 ? "bad" : du <= 14 ? "warn" : ""}">${du < 0 ? "deadline passed" : `due in ${du}d`}</span>`);
  if (l.ats_coverage != null) c.push(`<span class="chip ${l.ats_coverage >= 0.75 ? "good" : "warn"}" title="Job keywords present in the tailored resume">ATS ${Math.round(l.ats_coverage * 100)}%</span>`);
  if (l.open_q) c.push(`<span class="chip warn" title="Questions that could strengthen this application. Open the lead to answer them."><i class=i-question></i> ${l.open_q} question${l.open_q > 1 ? "s" : ""}</span>`);
  const rf = (l.triage && l.triage.red_flags) || [];
  if (rf.length) c.push(`<span class="chip warn" title="${esc(rf.join("; "))}"><i class=i-flag></i> ${rf.length} flag${rf.length > 1 ? "s" : ""}</span>`);
  return c.join("");
}
// ---------- where a lead was found
const FOUND_NAME = { github: "GitHub list", ats: "company board", linkedin: "LinkedIn", hackernews: "Hacker News", reddit: "Reddit",
  mastodon: "Mastodon", bluesky: "Bluesky", themuse: "The Muse", usajobs: "USAJobs", remote: "remote board", rss: "RSS feed",
  adzuna: "Adzuna", google: "Google Jobs", manual: "your link" };
const foundList = (l) => (l.found || []).filter((f) => safeUrl(f.url));
function foundShort(f) {
  let host = ""; try { host = new URL(f.url).hostname.replace(/^www\./, ""); } catch (_) {}
  if (f.source === "ai_hunt") {
    const m = (f.label || "").match(/\):\s*(.+)$/) || (f.label || "").match(/\u00b7\s*([^\u00b7]+)$/);
    if (/reddit\.com/.test(host)) return "Reddit thread";
    if (/linkedin\.com/.test(host)) return "LinkedIn post";
    if (/(x|twitter)\.com/.test(host)) return "X post";
    if (/news\.ycombinator/.test(host)) return "HN comment";
    return host || (m ? m[1].trim().slice(0, 30) : "AI find");
  }
  return FOUND_NAME[f.source] || host || f.source;
}
function foundBtn(l) {
  const fs = foundList(l);
  if (!fs.length) return "";
  if (fs.length === 1) return `<a class="btn sm ghost" data-act="ext" href="${esc(fs[0].url)}" target="_blank" rel="noopener" title="Where this was found: ${esc(fs[0].label)}"><i class=i-ext></i> ${esc(foundShort(fs[0]))}</a>`;
  return `<button class="btn sm ghost" data-act="found-menu" data-id="${l.id}" title="Found in ${fs.length} places"><i class=i-ext></i> ${fs.length} places</button>`;
}
function foundMenu(l) {
  modal(`<h2>Where this lead was found</h2><p class="muted small">${esc(l.title)}, ${esc(l.company || "")}</p><div class="stack">
    ${foundList(l).map((f) => `<a class="card" href="${esc(f.url)}" target="_blank" rel="noopener" style="display:block;text-decoration:none;color:var(--text)">
      <div class="row"><span class="chip blue">${esc(foundShort(f))}</span><span class="small muted mono" style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap;flex:1">${esc(f.url)}</span>${I.ext}</div>
      <div class="small" style="margin-top:6px">${esc(f.label)}</div></a>`).join("")}</div>
    <div class="row" style="justify-content:flex-end;margin-top:14px"><button class="btn" onclick="closeModal()">Close</button></div>`);
}

function leadCard(l, fresh) {
  return `<div class="lead ${fresh ? "fresh" : ""}" data-id="${l.id}" data-act="open-lead">
    ${ring(l.score)}
    <div style="min-width:0"><div class="t">${esc(l.title)}</div>
      <div class="c"><b>${esc(l.company || "Unknown company")}</b>, ${esc(l.location || "location n/a")}${l.triage?.summary ? ` <span class="muted">(${esc(l.triage.summary)})</span>` : ""}</div>
      <div class="meta">${leadChips(l)}</div></div>
    <div class="acts">${foundBtn(l)}${stageBadge(l)}
      ${l.app_status === "new" ? `<button class="btn sm ghost" data-act="quick-status" data-st="saved" title="Save for later"><i class=i-star-o></i></button>` : ""}
      ${l.app_status !== "trashed" ? `<button class="btn sm ghost danger" data-act="quick-status" data-st="trashed" title="Trash this lead"><i class=i-x></i></button>` : `<button class="btn sm ghost" data-act="quick-status" data-st="new">restore</button>`}
    </div></div>`;
}

function addLeadModal() {
  modal(`<h2>Add a lead</h2><p class="muted small">Paste any job link (LinkedIn, Workday, a post, a Reddit comment) or paste the job text. JobPortal builds the full package.</p>
    <div class="stack"><label class="f"><span>URL</span><input type="url" id="al-url" placeholder="https://…"></label>
    <label class="f"><span>…or paste the posting text</span><textarea id="al-text" rows="7"></textarea></label>
    <div class="grid3"><label class="f"><span>Title (optional)</span><input type="text" id="al-title"></label>
    <label class="f"><span>Company (optional)</span><input type="text" id="al-co"></label>
    <label class="f"><span>Kind</span><select id="al-kind"><option value="posting">Posting</option><option value="program">Program</option><option value="event">Event</option><option value="intel">Intel / cold outreach</option></select></label></div>
    <div class="row" style="justify-content:flex-end"><button class="btn ghost" onclick="closeModal()">Cancel</button><button class="btn primary" id="al-go">Build package</button></div></div>`);
  $("#al-go").onclick = async () => {
    try {
      const l = await api("/api/leads/manual", { method: "POST", body: { url: $("#al-url").value, text: $("#al-text").value, title: $("#al-title").value, company: $("#al-co").value, kind: $("#al-kind").value } });
      closeModal(); toast("Building package", "JobPortal is researching and tailoring. It pops up here when it's ready.", "", l.id); location.hash = `#/lead/${l.id}`;
    } catch (e) { toast("Couldn't add lead", e.message, "error"); }
  };
}

// ---------------------------------------------------------------- actions
onAction("open-lead", async (el, e) => { location.hash = `#/lead/${el.dataset.id}`; });
onAction("found-menu", async (el, e) => { e.stopPropagation(); const d = await api(`/api/leads/${el.dataset.id}`); foundMenu(d); });
onAction("quick-status", async (el, e) => { e.stopPropagation(); const id = el.closest(".lead").dataset.id; await api(`/api/leads/${id}`, { method: "PATCH", body: { app_status: el.dataset.st } }); if (el.dataset.st === "trashed") toast("Trashed", "Find it under the Trashed tab."); });
onAction("run", async (el, e) => {
  const mode = $("#runmode")?.value || "full"; localStorage.setItem("runmode", mode);
  if (S.notify && !desktop() && "Notification" in window && Notification.permission === "default") Notification.requestPermission();
  await api("/api/run", { method: "POST", body: { mode } }); S.logs = []; const b = $("#console-body"); if (b) b.innerHTML = "";
});
onAction("stop", async (el, e) => { await api("/api/run/stop", { method: "POST" }); toast("Stopping", "Finishing up and saving progress…"); });
onAction("notify", async (el, e) => { S.notify = !S.notify; localStorage.setItem("notify", S.notify ? "1" : "0"); if (S.notify && !desktop() && "Notification" in window) Notification.requestPermission(); renderMission(); });
onAction("toggle-console", async (el, e) => { S.consoleOpen = !S.consoleOpen; localStorage.setItem("consoleOpen", S.consoleOpen ? "1" : "0"); $("#console").classList.toggle("closed", !S.consoleOpen); });
onAction("tile", async (el, e) => { const go = el.dataset.go; if (go === "tracker") location.hash = "#/tracker"; else { S.leadsTab = go; localStorage.setItem("leadsTab", go); loadLeads(); } });
onAction("ltab", async (el, e) => { S.leadsTab = el.dataset.tab; localStorage.setItem("leadsTab", S.leadsTab); loadLeads(); });
onAction("add-lead", async (el, e) => { addLeadModal(); });
onAction("dream-only", async (el, e) => { S.dreamOnly = !S.dreamOnly; el.classList.toggle("primary", S.dreamOnly); el.classList.toggle("ghost", !S.dreamOnly); loadLeads(); });
onAction("retriage", async (el, e) => { await api("/api/leads/retriage", { method: "POST" }); toast("Re-evaluating", "Below-threshold and queued leads are being re-scored against your current profile."); });
