/* The Runs page: past search runs with their stats and full logs. */
"use strict";

async function renderRuns(id) {
  const runs = await api("/api/runs");
  const dur = (r) => r.finished_at ? Math.round((new Date(r.finished_at) - new Date(r.started_at)) / 60000) + " min" : "…";
  main.innerHTML = `<div class="page"><div class="page-h"><h1>Runs</h1><span class="sub">History of every mega search.</span></div>
    <div class="card" style="margin-bottom:16px"><table class="t"><thead><tr><th>#</th><th>Started</th><th>Mode</th><th>Status</th><th>Duration</th><th>Found</th><th>Candidates</th><th>Triaged</th><th>Qualified</th><th>Packaged</th><th>Tokens</th></tr></thead><tbody>
    ${runs.map((r) => `<tr style="cursor:pointer" data-act="runlog" data-id="${r.id}"><td class="mono">${r.id}</td><td>${esc(new Date(r.started_at).toLocaleString())}</td><td>${esc(r.mode)}</td>
      <td><span class="chip ${r.status === "done" ? "good" : r.status === "running" ? "accent" : "warn"}">${esc(r.status)}</span></td><td>${dur(r)}</td>
      <td>${r.stats.found ?? ""}</td><td>${r.stats.candidates ?? ""}</td><td>${r.stats.triaged ?? ""}</td><td>${r.stats.qualified ?? ""}</td><td>${r.stats.packaged ?? ""}</td><td>${fmtTokens(+r.tokens || 0)}</td></tr>`).join("") || `<tr><td colspan="11" class="muted">No runs yet.</td></tr>`}</tbody></table></div>
    <div id="runlog"></div></div>`;
  if (id || runs[0]) showRunLog(id || runs[0].id, runs.find((r) => r.id === +(id || runs[0].id)));
}
async function showRunLog(id, run) {
  const lines = await api(`/api/runs/${id}/log`);
  const st = run?.stats || {};
  const filt = Object.entries(st).filter(([k]) => k.startsWith("filtered") || ["already known", "duplicate", "deferred to next run", "below threshold"].includes(k));
  $("#runlog").innerHTML = `<div class="cols"><div class="console" style="margin:0"><div class="ch">run #${id} log, ${lines.length} lines</div><div class="body" style="height:60vh">${lines.map(logLine).join("")}</div></div>
    <div class="card"><h3>Where candidates went</h3><table class="t"><tbody>${filt.sort((a, b) => b[1] - a[1]).map(([k, v]) => `<tr><td>${esc(k)}</td><td class="mono">${v}</td></tr>`).join("") || `<tr><td class="muted">none</td></tr>`}</tbody></table></div></div>`;
}

// ---------------------------------------------------------------- actions
onAction("runlog", async (el, e) => { showRunLog(el.dataset.id, (await api("/api/runs")).find((r) => r.id === +el.dataset.id)); });
