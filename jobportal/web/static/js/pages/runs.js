/* runs.js: Settings, History (#/settings/history, or #/settings/history/5 for search 5). Every past search in a list, and
   beside it the one you pick: its numbers, its full log, and where the jobs it found went. Picking a search changes the
   address, so settings.js draws the section again (without "Loading": it's the same section) and the log follows.
   APIs: GET /api/runs, GET /api/runs/{id}/log. */
"use strict";

// The numbers of a search: [key in its stats, label].
const RUN_COLUMNS = [["found", "Found"], ["candidates", "New"], ["triaged", "Scored"], ["qualified", "Good fits"], ["packaged", "Tailored"]];

// How long a search took, or that it's still going.
const runTook = (r) => (r.finished_at ? `${Math.round((new Date(r.finished_at) - new Date(r.started_at)) / 60000)} min` : "Running");
// What kind of search it was, by the Run menu's names.
const runMode = (m) => (RUN_MODES.find(([key]) => key === m) || [m, humanize(m)])[1];

// The list of searches (newest first), and the log of the search in the address, or of the newest one.
async function renderRuns(box, id) {
  const runs = await api("/api/runs");
  if (S.route[1] !== "history") return;
  setSaver();
  const shown = +id || runs[0]?.id;
  const statusTag = (status) => `<span class="tag ${status === "done" ? "green" : status === "running" ? "blue" : "warn"}">${esc(humanize(status))}</span>`;
  const row = (r) => `<button class="row${r.id === shown ? " active" : ""}" type="button" data-act="run-log" data-id="${r.id}"${r.id === shown ? ' aria-current="true"' : ""}>
      <span class="row-main"><span class="row-title">#${r.id} ${esc(runMode(r.mode))}</span><span class="row-sub">${esc(fmtTs(r.started_at))}</span></span>
      <span class="row-end">${statusTag(r.status)}</span></button>`;
  if (!runs.length) {
    box.innerHTML = `<div class="empty fill"><p>No runs yet</p></div>`;
    return;
  }
  if (!$(".runs", box)) box.innerHTML = `<div class="runs"><nav class="runs-list" id="run-list" aria-label="Runs"></nav><section class="runs-detail" id="run-log"></section></div>`;
  setHtml($("#run-list"), `<div class="rows">${runs.map(row).join("")}</div>`);
  await showRunLog(shown, runs.find((r) => r.id === shown));
}

// The stats that say where the jobs a search found went, besides the "filtered: ..." ones. "deferred to next run" is the
// older name of "backlog for next run", kept for searches saved by JobPortal 0.1.0.
const DROP_REASONS = ["already known", "duplicate", "backlog for next run", "deferred to next run", "below threshold"];

// One search's numbers and log (GET /api/runs/{id}/log), next to the reasons jobs were set aside, biggest first. Clicking
// through the searches quickly loads several logs at once: only the newest one picked is drawn. A log that doesn't load
// says so.
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
  const stats = run?.stats || {};
  const dropped = Object.entries(stats)
    .filter(([reason]) => reason.startsWith("filtered") || DROP_REASONS.includes(reason))
    .sort((a, b) => b[1] - a[1]);
  const stat = (value, label) => `<div><strong>${esc(value)}</strong><span>${esc(label)}</span></div>`;
  box.innerHTML = `<div class="stat-strip runs-stats">${RUN_COLUMNS.map(([key, label]) => stat(stats[key] ?? 0, label)).join("")}
      ${stat(fmtTokens(+run?.tokens || 0), "Tokens")}${stat(run ? runTook(run) : "-", "Took")}</div>
    <div class="runs-body">
      <div class="runs-log" role="log" aria-label="Log">${lines.map(logLine).join("") || `<div class="empty"><p>No log</p></div>`}</div>
      <aside class="runs-side"><div class="sect-head"><h2>Set aside</h2></div>
        ${dropped.length ? `<table class="table"><tbody>${dropped.map(([reason, n]) => `<tr><td>${esc(humanize(reason))}</td><td>${n}</td></tr>`).join("")}</tbody></table>`
          : `<p class="muted">None</p>`}</aside></div>`;
}

// ---------------------------------------------------------------- actions
onAction("run-log", (el) => {
  location.hash = `#/settings/history/${el.dataset.id}`;
});
