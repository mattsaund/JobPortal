/* runs.js: the Runs page. Every past search run with its numbers, and the full log of the one you pick (#/runs/5 opens
   run 5), with a breakdown of where the candidates went. APIs: GET /api/runs, GET /api/runs/{id}/log. */
"use strict";

// The table's columns. COUNTS are the run stats shown as numbers, in column order.
const HEADINGS = ["#", "Started", "Mode", "Status", "Duration", "Found", "Candidates", "Triaged", "Qualified", "Packaged", "Tokens"];
const COUNTS = ["found", "candidates", "triaged", "qualified", "packaged"];

// The table of runs (newest first). Shows the log of the run in the address, or of the newest run.
async function renderRuns(id) {
  const runs = await api("/api/runs");
  const minutes = (r) => (r.finished_at ? Math.round((new Date(r.finished_at) - new Date(r.started_at)) / 60000) + " min" : "…");
  const statusColor = (status) => (status === "done" ? "good" : status === "running" ? "accent" : "warn");
  const row = (r) => `<tr style="cursor:pointer" data-act="runlog" data-id="${r.id}"><td class="mono">${r.id}</td><td>${esc(new Date(r.started_at).toLocaleString())}</td><td>${esc(r.mode)}</td>
      <td><span class="chip ${statusColor(r.status)}">${esc(r.status)}</span></td><td>${minutes(r)}</td>
      ${COUNTS.map((key) => `<td>${r.stats[key] ?? ""}</td>`).join("")}<td>${fmtTokens(+r.tokens || 0)}</td></tr>`;
  main.innerHTML = `<div class="page"><div class="page-h"><h1>Runs</h1><span class="sub">History of every mega search.</span></div>
    <div class="card" style="margin-bottom:16px"><table class="t"><thead><tr>${HEADINGS.map((h) => `<th>${h}</th>`).join("")}</tr></thead><tbody>
    ${runs.map(row).join("") || `<tr><td colspan="11" class="muted">No runs yet.</td></tr>`}</tbody></table></div>
    <div id="runlog"></div></div>`;
  const shown = id || runs[0]?.id;
  if (shown) showRunLog(shown, runs.find((r) => r.id === +shown));
}

// The run stats that say where candidates went, besides the "filtered ..." ones. "deferred to next run" is the older
// name of "backlog for next run", kept for runs saved by JobPortal 0.1.0.
const DROP_REASONS = ["already known", "duplicate", "backlog for next run", "deferred to next run", "below threshold"];

// One run's log (GET /api/runs/{id}/log) next to the reasons candidates were dropped, biggest first.
async function showRunLog(id, run) {
  const lines = await api(`/api/runs/${id}/log`);
  const stats = run?.stats || {};
  const dropped = Object.entries(stats)
    .filter(([reason]) => reason.startsWith("filtered") || DROP_REASONS.includes(reason))
    .sort((a, b) => b[1] - a[1]);
  $("#runlog").innerHTML = `<div class="cols"><div class="console" style="margin:0"><div class="ch">run #${id} log, ${lines.length} lines</div>
      <div class="body" style="height:60vh">${lines.map(logLine).join("")}</div></div>
    <div class="card"><h3>Where candidates went</h3>
      <table class="t"><tbody>${dropped.map(([reason, n]) => `<tr><td>${esc(reason)}</td><td class="mono">${n}</td></tr>`).join("")
        || `<tr><td class="muted">none</td></tr>`}</tbody></table></div></div>`;
}

// ---------------------------------------------------------------- actions
onAction("runlog", async (el) => {  // a row in the table
  const runs = await api("/api/runs");
  showRunLog(el.dataset.id, runs.find((r) => r.id === +el.dataset.id));
});
