/* runs.js: Settings, History (#/settings/history, or #/settings/history/5 for search 5). Every past search with its
   numbers, and the full log of the one you pick, next to where the jobs it found went. Picking a search changes the
   address, so settings.js draws the tab again (without "Loading": it's the same tab) and the log follows.
   APIs: GET /api/runs, GET /api/runs/{id}/log. */
"use strict";

// The table's number columns: [key in a search's stats, heading].
const RUN_COLUMNS = [["found", "Found"], ["candidates", "New"], ["triaged", "Scored"], ["qualified", "Good fits"], ["packaged", "Tailored"]];

// The table of searches (newest first), and the log of the search in the address, or of the newest one.
async function renderRuns(box, id) {
  const runs = await api("/api/runs");
  if (S.route[1] !== "history") return;
  const shown = +id || runs[0]?.id;
  const minutes = (r) => (r.finished_at ? `${Math.round((new Date(r.finished_at) - new Date(r.started_at)) / 60000)} min` : "Running");
  const statusTag = (status) => `<span class="tag ${status === "done" ? "green" : status === "running" ? "blue" : "warn"}">${esc(humanize(status))}</span>`;
  const mode = (m) => (RUN_MODES.find(([key]) => key === m) || [m, humanize(m)])[1];
  const row = (r) => `<tr class="run-row${r.id === shown ? " active" : ""}" data-act="run-log" data-id="${r.id}" tabindex="0"><td>${r.id}</td>
      <td class="nowrap">${esc(fmtTs(r.started_at))}</td><td>${esc(mode(r.mode))}</td><td>${statusTag(r.status)}</td><td>${minutes(r)}</td>
      ${RUN_COLUMNS.map(([key]) => `<td>${r.stats[key] ?? ""}</td>`).join("")}<td>${fmtTokens(+r.tokens || 0)}</td></tr>`;
  const focus = focusKey(box);  // the row you picked with the keyboard keeps the focus
  box.innerHTML = `<div class="stack">${settingsPanel("Your searches", "Click one to read its log.",
      `<div class="table-wrap"><table class="table numbers"><thead><tr><th>#</th><th>Started</th><th>What</th><th>Status</th><th>Took</th>
        ${RUN_COLUMNS.map(([, heading]) => `<th>${heading}</th>`).join("")}<th>Tokens</th></tr></thead>
        <tbody>${runs.map(row).join("") || `<tr><td colspan="11" class="muted-note">No searches yet.</td></tr>`}</tbody></table></div>`)}
    <div id="run-log"></div></div>`;
  refocus(box, focus);
  if (shown) showRunLog(shown, runs.find((r) => r.id === shown));
}

// The stats that say where the jobs a search found went, besides the "filtered: ..." ones. "deferred to next run" is the
// older name of "backlog for next run", kept for searches saved by JobPortal 0.1.0.
const DROP_REASONS = ["already known", "duplicate", "backlog for next run", "deferred to next run", "below threshold"];

// One search's log (GET /api/runs/{id}/log), next to the reasons jobs were set aside, biggest first. Clicking through
// the searches quickly loads several logs at once: only the newest one picked is drawn. A log that doesn't load says so.
let runLogLoad = 0;
async function showRunLog(id, run) {
  const ticket = ++runLogLoad;
  let lines;
  try {
    lines = await api(`/api/runs/${id}/log`);
  } catch (err) {
    if (ticket === runLogLoad && $("#run-log")) $("#run-log").innerHTML = loadError(err);
    return;
  }
  const box = $("#run-log");
  if (!box || ticket !== runLogLoad) return;
  const dropped = Object.entries(run?.stats || {})
    .filter(([reason]) => reason.startsWith("filtered") || DROP_REASONS.includes(reason))
    .sort((a, b) => b[1] - a[1]);
  box.innerHTML = `<div class="two-col wide-left">
    <section class="live-panel open"><div class="live-head static"><span class="live-status"><b>Search #${id}</b><span class="muted">${plural(lines.length, "line")}</span></span></div>
      <div class="live-log tall" role="log">${lines.map(logLine).join("")}</div></section>
    ${settingsPanel("Where the jobs went", "",
      `<table class="table numbers"><tbody>${dropped.map(([reason, n]) => `<tr><td>${esc(humanize(reason))}</td><td>${n}</td></tr>`).join("")
        || `<tr><td class="muted-note">Nothing set aside.</td></tr>`}</tbody></table>`)}</div>`;
}

// ---------------------------------------------------------------- actions
onAction("run-log", (el) => {
  location.hash = `#/settings/history/${el.dataset.id}`;
});
// Enter on a focused row opens its log, like a click.
document.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && e.target.matches?.("tr[data-act=run-log]")) e.target.click();
});
