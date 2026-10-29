/* analysis.js: the Analysis page. Where you fit and where the market is, per work genre: a radar chart of your fit, your
   interest and market demand, the AI's read and its top moves, a sortable genre table, skill gaps, the pipeline funnel,
   and which industries and sources produce qualified leads.
   APIs: GET /api/analysis (market numbers, the latest AI assessment and its history), POST /api/analysis/run,
   GET /api/profile and PUT /api/profile/search_plan (the "Add to search plan" buttons). An "analysis" event redraws it. */
"use strict";

// Chart colors, checked on the dark surface #111317: every pair stays distinguishable with color blindness (color
// difference ΔE 9.4 or more; 20.9 or more with normal vision), and each has at least 3:1 contrast with the background.
const VIZ = { fit: "#3987e5", demand: "#d95926", interest: "#199e70", prev: "#6b7280", surface: "#111317", grid: "#262b34" };
// The radar's series in drawing order: [key in each genre row, legend label].
const RADAR_SERIES = [["demand", "Market demand"], ["interest", "Your interest"], ["prev", "Previous fit"], ["fit", "Your fit"]];
// The icon for each kind of suggested move.
const MOVE_ICON = { project: "<i class=i-tool></i>", cert: "<i class=i-cert></i>", course: "<i class=i-book></i>", profile: "<i class=i-doc></i>",
  document: "<i class=i-doc></i>", search: "<i class=i-search></i>" };
// The series you switched off in the legend, remembered between visits.
const radarOff = new Set(JSON.parse(localStorage.getItem("radarOff") || "[]"));

// The floating tooltip for the chart and the bar rows. html = null hides it.
function vizTip(html, e) {
  let tip = $("#viz-tip");
  if (!tip) {
    tip = document.createElement("div");
    tip.id = "viz-tip";
    tip.className = "viz-tip";
    document.body.appendChild(tip);
  }
  if (!html) {
    tip.style.display = "none";
    return;
  }
  tip.innerHTML = html;
  tip.style.display = "block";
  // Next to the pointer, but never past the window's edge.
  tip.style.left = `${Math.min(e.clientX + 16, innerWidth - tip.offsetWidth - 10)}px`;
  tip.style.top = `${Math.min(e.clientY + 14, innerHeight - tip.offsetHeight - 10)}px`;
}

// A small color swatch for legends and table headers.
const swatch = (color) => `<i class="sw" style="background:${color}"></i>`;

// The radar chart as SVG: one spoke per genre, rings at 25/50/75/100, one polygon per visible series, a label at each
// series' peak, and an invisible wedge per genre that triggers its tooltip. present = the series that have data.
function radarSVG(rows, present) {
  const W = 660, H = 540, cx = W / 2, cy = H / 2 + 6, R = 190, N = rows.length;
  const angle = (i) => -Math.PI / 2 + (i * 2 * Math.PI) / N;  // the first genre points straight up
  const point = (i, value) => [cx + R * (value / 100) * Math.cos(angle(i)), cy + R * (value / 100) * Math.sin(angle(i))];
  const visible = (key) => present.has(key) && !radarOff.has(key);
  let svg = "";
  for (const level of [25, 50, 75, 100]) {  // the rings and their numbers
    svg += `<polygon points="${rows.map((_, i) => point(i, level).join(",")).join(" ")}" fill="none" stroke="${VIZ.grid}" stroke-width="1"/>`;
    svg += `<text x="${cx + 4}" y="${cy - (R * level) / 100 - 3}" class="rt">${level}</text>`;
  }
  rows.forEach((row, i) => {  // the spokes and the genre names around the rim
    const [x, y] = point(i, 100);
    svg += `<line x1="${cx}" y1="${cy}" x2="${x}" y2="${y}" stroke="${VIZ.grid}" stroke-width="1" class="spoke" data-i="${i}"/>`;
    const cos = Math.cos(angle(i)), sin = Math.sin(angle(i)), lx = cx + (R + 20) * cos, ly = cy + (R + 20) * sin;
    const anchor = cos > 0.25 ? "start" : cos < -0.25 ? "end" : "middle";
    const lines = [];  // wrap the name at 16 characters
    for (const word of row.label.split(" ")) {
      if (lines.length && (lines.at(-1) + " " + word).length <= 16) lines[lines.length - 1] += " " + word;
      else lines.push(word);
    }
    // Names above the center grow upward, names below grow downward, the rest are centered on their spoke.
    const dy = sin < -0.5 ? -(lines.length - 1) * 14 : sin > 0.5 ? 6 : -((lines.length - 1) * 14) / 2 + 4;
    svg += `<text x="${lx}" y="${ly + dy}" text-anchor="${anchor}" class="rl">${lines.map((line, k) => `<tspan x="${lx}" dy="${k ? 14 : 0}">${esc(line)}</tspan>`).join("")}</text>`;
  });
  for (const [key] of RADAR_SERIES) {  // the series
    if (!visible(key)) continue;
    const color = VIZ[key], points = rows.map((row, i) => point(i, row[key] ?? 0));
    svg += `<polygon points="${points.map((p) => p.join(",")).join(" ")}" fill="${color}" fill-opacity="${key === "prev" ? 0 : 0.1}" stroke="${color}" stroke-width="2" stroke-linejoin="round"/>`;
    svg += points.map(([x, y]) => `<circle cx="${x}" cy="${y}" r="4" fill="${color}" stroke="${VIZ.surface}" stroke-width="2"/>`).join("");
  }
  // A label at each visible series' peak only (not "Previous fit"), and never two on the same spoke.
  const labeled = new Set();
  for (const [key, label] of RADAR_SERIES) {
    if (!visible(key) || key === "prev") continue;
    let peak = 0;
    rows.forEach((row, i) => {
      if ((row[key] ?? -1) > (rows[peak][key] ?? -1)) peak = i;
    });
    if (labeled.has(peak)) continue;
    labeled.add(peak);
    // Just inside the vertex, toward the center, so it never collides with the genre names at the rim.
    const value = rows[peak][key] ?? 0, [x, y] = point(peak, Math.max(0, value - 13)), cos = Math.cos(angle(peak));
    const anchor = Math.abs(cos) < 0.25 ? "middle" : cos > 0 ? "end" : "start";
    svg += `<text x="${x}" y="${y + 4}" text-anchor="${anchor}" class="dl">${esc(label.replace("Your ", "").replace("Market ", ""))} ${rows[peak][key]}</text>`;
  }
  rows.forEach((_, i) => {  // invisible hit wedges, bigger than the marks, for the per-genre tooltip
    const a0 = angle(i) - Math.PI / N, a1 = angle(i) + Math.PI / N, r = R + 34;
    const x0 = cx + r * Math.cos(a0), y0 = cy + r * Math.sin(a0), x1 = cx + r * Math.cos(a1), y1 = cy + r * Math.sin(a1);
    svg += `<path class="hit" data-i="${i}" d="M${cx},${cy} L${x0},${y0} A${r},${r} 0 0 1 ${x1},${y1} Z" fill="transparent"/>`;
  });
  return `<svg viewBox="0 0 ${W} ${H}" class="radar" role="img" aria-label="Radar chart of fit, interest and market demand per work genre; the table below lists every value">${svg}</svg>`;
}

// A list of horizontal bars. Each item gives [label, value, value text, tooltip text].
function bars(items, maxValue) {
  return `<div class="bars">${items.map(([label, value, text, tip]) => `<div class="br" data-tip="${esc(tip)}">
          <span class="bl">${esc(label)}</span><span class="bt"><i style="width:${(value / maxValue) * 100}%;background:${VIZ.fit}"></i></span><span class="bv">${text}</span></div>`).join("")}</div>`;
}

// Draws the page from GET /api/analysis, then wires the chart and bar tooltips.
async function renderAnalysis() {
  const d = await api("/api/analysis");
  const market = d.market, latest = d.latest, result = latest?.result || null;
  const byGenre = Object.fromEntries((result?.genres || []).map((g) => [g.id, g]));
  const previousFit = d.history.length >= 2 ? d.history[d.history.length - 2].fit : null;
  // One row per genre: the market numbers plus the AI's fit and interest, and the fit from the analysis before.
  const rows = market.genres.map((g) => ({
    ...g,
    fit: byGenre[g.id]?.fit ?? null,
    interest: byGenre[g.id]?.interest ?? null,
    demand: market.demand_total ? g.demand_index : null,
    prev: previousFit?.[g.id] ?? null,
    ai: byGenre[g.id],
  }));
  const present = new Set(["fit", "interest", "demand", "prev"].filter((key) => rows.some((row) => row[key] != null)));
  // Payoff: high demand x high interest x room to grow. A missing number counts as 50.
  const payoff = (row) => ((row.demand ?? 50) / 100) * ((row.interest ?? 50) / 100) * (1 - (row.fit ?? 50) / 100);
  const sorted = [...rows].sort((a, b) => payoff(b) - payoff(a));
  const labelOf = Object.fromEntries(rows.map((row) => [row.id, row.label]));
  const legend = RADAR_SERIES.filter(([key]) => present.has(key))
    .map(([key, label]) => `<button class="lg ${radarOff.has(key) ? "off" : ""}" data-act="radar-toggle" data-k="${key}">${swatch(VIZ[key])}${label}</button>`).join("");
  const steer = result?.search_steering || {};
  const notYet = `<span class="muted small">Appears after the analysis runs.</span>`;
  const runButton = d.running ? `<span class="spin"></span> Analyzing` : result ? "<i class=i-refresh></i> Re-analyze" : "Run analysis";
  const topMoves = (result?.top_priorities || []).map((t, i) => `<div style="padding:8px 0;border-bottom:1px solid var(--line)">
          <div class="row" style="gap:6px"><span class="mono muted">${i + 1}.</span><b>${esc(t.title)}</b></div>
          <div class="row" style="gap:5px;margin:4px 0"><span class="chip violet">${MOVE_ICON[t.type] || ""} ${esc(t.type)}</span><span class="chip">${esc(labelOf[t.genre] || t.genre)}</span></div>
          <div class="small">${esc(t.detail)}</div>
          <div class="small muted" style="margin-top:3px">Why: ${esc(t.why)}</div></div>`).join("")
    || `<div class="muted small">Appears after the analysis runs.</div>`;
  const maxGap = Math.max(1, ...market.gaps.map((x) => x.missing_in));
  const gaps = market.gaps.length
    ? bars(market.gaps.map((x) => [x.skill, x.missing_in, `${x.missing_in}/${x.requested_in}`, `${x.skill}: missing in ${x.missing_in} of ${x.requested_in} postings that asked for it`]), maxGap)
    : `<div class="empty" style="padding:24px"><b>No gaps measured yet</b>They appear as application packages are built.</div>`;
  const qualifiedBars = (items, nameOf) => bars(items.map((x) => [nameOf(x), x.qualified, `${x.qualified} (avg ${x.avg_score ?? "-"})`,
    `${nameOf(x)}: ${x.qualified} qualified of ${x.triaged} triaged, avg score ${x.avg_score ?? "-"}`]), Math.max(1, ...items.map((x) => x.qualified)));
  const industries = market.industries || [];
  const suggestion = (x) => `<div style="padding:6px 0;border-bottom:1px solid var(--line)"><b class="small"><i class=i-doc></i> ${esc(x.title)}</b>`
    + `<div class="small muted">${esc(x.detail)}</div></div>`;
  main.innerHTML = `<div class="page">
    <div class="page-h"><h1>Analysis</h1><span class="sub">Where you fit, where the market is, and what to build next.</span><span class="spacer"></span>
      <span class="muted small mono">${latest ? `analyzed ${esc(fmtTs(latest.ts))}, ${fmtTokens(+latest.tokens || 0)} tokens` : "not analyzed yet"}</span>
      <button class="btn ${result ? "" : "primary"}" data-act="run-analysis" ${d.running ? "disabled" : ""}>${runButton}</button></div>
    ${!result ? `<div class="banner accent"><div><b>Run the analysis</b> to score your fit and interest across ${rows.length} work genres against
      real market demand and get concrete moves. It re-runs automatically whenever your profile changes.</div></div>` : ""}
    <div class="cols" style="grid-template-columns:minmax(0,1.25fr) minmax(0,1fr)">
      <div class="card"><div class="row" style="margin-bottom:4px"><h3 style="margin:0">Work-genre radar</h3><span class="spacer"></span><div class="legend">${legend}</div></div>
        <div class="muted small">Fit and interest: AI assessment of your profile (0 to 100). Demand: share of postings that passed your filters,
          indexed so the busiest genre is 100 (${esc(market.demand_source)}).</div>
        <div id="radar">${radarSVG(rows, present)}</div></div>
      <div class="stack">
        <div class="card"><h3>The read</h3>${result ? `<p style="margin:0">${esc(result.summary)}</p>` : `<p class="muted" style="margin:0">No assessment yet.</p>`}</div>
        <div class="card"><h3>Top moves, ranked by payoff</h3>${topMoves}</div></div></div>

    <div class="card" style="margin-top:14px"><h3>Every genre, sorted by payoff (high demand x high interest x room to grow)</h3>
      <table class="t gt"><thead><tr><th>Genre</th><th>${swatch(VIZ.fit)}Fit</th><th>${swatch(VIZ.interest)}Interest</th><th>${swatch(VIZ.demand)}Demand</th>
        <th>Qualified leads</th><th>Avg lead score</th><th>Δ fit</th><th>Skills your resumes lacked</th></tr></thead>
      <tbody>${sorted.map(genreRows).join("")}</tbody></table></div>

    <div class="cols" style="margin-top:14px">
      <div class="card"><h3>Skills employers asked for that your tailored resumes couldn't show</h3>
        <div class="muted small" style="margin-bottom:10px">Across ${plural(market.packaged_leads, "packaged lead")}. Build or document these and every future resume can claim them.</div>
        ${gaps}</div>
      <div class="stack">
        <div class="card"><h3>Requested skills you already show</h3>
          <div class="cov">${market.strengths.map((x) => `<span class="chip good" title="requested in ${x.requested_in}">${esc(x.skill)}</span>`).join("")
            || `<span class="muted small">Appears as packages are built.</span>`}</div></div>
        <div class="card"><h3>Steer the search</h3>${result ? steerSearch(steer, labelOf) : notYet}</div>
        <div class="card"><h3>Add these to your profile</h3>
          ${(result?.profile_suggestions || []).map(suggestion).join("") || notYet}
          <div class="row" style="margin-top:10px"><a class="btn sm" href="#/profile/questions">Tell JobPortal about it</a>
            <a class="btn sm ghost" href="#/profile/questions">Answer open questions →</a></div></div></div></div>

    <div class="card" style="margin-top:14px"><h3>Pipeline</h3><div class="funnel">${funnel(market.funnel)}</div></div>

    <div class="card" style="margin-top:14px"><h3>Qualified leads by industry</h3>
      ${industries.length ? qualifiedBars(industries, (x) => x.industry) : `<span class="muted small">Run a search first.</span>`}</div>
    <div class="card" style="margin-top:14px"><h3>Which sources produce qualified leads</h3>
      ${market.sources.length ? qualifiedBars(market.sources, (x) => LABEL_SRC[x.source] || x.source) : `<span class="muted small">Run a search first.</span>`}</div>
  </div>`;
  const svg = $("#radar svg");
  const unhighlight = () => $$(".spoke", svg).forEach((spoke) => spoke.classList.remove("on"));
  svg.addEventListener("mousemove", (e) => {  // the genre under the pointer: highlight its spoke and show its numbers
    const hit = e.target.closest(".hit");
    unhighlight();
    if (!hit) return vizTip(null);
    const row = rows[+hit.dataset.i];
    $(`.spoke[data-i="${hit.dataset.i}"]`, svg).classList.add("on");
    const values = [["fit", "Your fit"], ["interest", "Your interest"], ["demand", "Market demand"], ["prev", "Previous fit"]].filter(([key]) => row[key] != null)
      .map(([key, label]) => `<div class="tr">${swatch(VIZ[key])}<span>${label}</span><b>${row[key]}</b></div>`).join("");
    vizTip(`<b>${esc(row.label)}</b>${values}<div class="muted" style="margin-top:4px">${row.qualified} qualified leads, ${(row.demand_share * 100).toFixed(1)}% of postings</div>`, e);
  });
  svg.addEventListener("mouseleave", () => {
    vizTip(null);
    unhighlight();
  });
  $$(".br", main).forEach((bar) => {
    bar.addEventListener("mousemove", (e) => vizTip(esc(bar.dataset.tip), e));
    bar.addEventListener("mouseleave", () => vizTip(null));
  });
  S.analysis = { steer };
}

// One suggested move for a genre: its title, the effort and impact, and the details.
const genreMove = (move) => `<div class="small" style="margin:6px 0"><b>${MOVE_ICON[move.type] || ""} ${esc(move.title)}</b>`
  + ` <span class="muted">(${esc(move.effort)}, ${esc(move.impact)} impact)</span><div>${esc(move.detail)}</div></div>`;

// Two table rows per genre: its numbers, and a hidden row with the AI's evidence, gaps and moves (a click on the first
// row shows it).
function genreRows(row) {
  const change = row.fit != null && row.prev != null
    ? `${row.fit - row.prev > 0 ? "<i class=i-up></i>" : row.fit - row.prev < 0 ? "<i class=i-down></i>" : ""} ${Math.abs(row.fit - row.prev)}` : "-";
  const details = row.ai ? `<div class="grid3">
          <div><b class="small mono">EVIDENCE</b> <span class="chip">${esc(row.ai.confidence)} confidence</span>${bulletList(row.ai.evidence, "good small")}</div>
          <div><b class="small mono">GAPS</b>${bulletList(row.ai.gaps, "warn small")}</div>
          <div><b class="small mono">MOVES</b>${row.ai.moves.map(genreMove).join("")}</div></div>`
    : `<span class="muted small">Run the analysis for evidence, gaps and moves.</span>`;
  return `<tr class="gr" data-act="genre-row" data-id="${row.id}" style="cursor:pointer"><td><b>${esc(row.label)}</b> <span class="muted small"><i class=i-chev></i></span></td>
        <td class="num">${row.fit ?? "-"}</td><td class="num">${row.interest ?? "-"}</td>
        <td class="num">${row.demand ?? "-"} <span class="muted small">(${(row.demand_share * 100).toFixed(1)}%)</span></td>
        <td class="num">${row.qualified}</td><td class="num">${row.avg_score ?? "-"}</td>
        <td class="num">${change}</td>
        <td class="small">${esc(row.top_missing.join(", ")) || `<span class="muted">none</span>`}</td></tr>
        <tr class="gd" id="gd-${row.id}" style="display:none"><td colspan="8">${details}</td></tr>`;
}

// The "Steer the search" card: genres to emphasize and de-emphasize, a note, and queries and companies you can add to
// your search plan with one click.
function steerSearch(steer, labelOf) {
  const genres = (ids, cls) => (ids || []).map((id) => `<span class="chip${cls}">${esc(labelOf[id] || id)}</span>`).join(" ") || "none";
  const addList = (items, title, kind, button) => ((items || []).length
    ? `<div style="margin-top:10px"><b class="small mono">${title}</b><div class="cov" style="margin:6px 0">${items.map((q) => `<span class="chip">${esc(q)}</span>`).join("")}</div>`
      + `<button class="btn sm" data-act="plan-add" data-kind="${kind}">${button}</button></div>`
    : "");
  return `
          <div class="small"><b class="mono">EMPHASIZE</b> ${genres(steer.emphasize, " blue")}</div>
          <div class="small" style="margin-top:6px"><b class="mono">DE-EMPHASIZE</b> ${genres(steer.deemphasize, "")}</div>
          ${steer.notes ? `<p class="small" style="margin:8px 0 0">${esc(steer.notes)}</p>` : ""}
          ${addList(steer.add_queries, "QUERIES TO ADD", "queries", "+ Add to search plan")}
          ${addList(steer.add_companies, "COMPANIES TO ADD", "dream_companies", "+ Add to target companies")}`;
}

// The pipeline funnel: each stage's count and the share of the stage before it.
function funnel(stages) {
  return stages.map((stage, i) => {
    const before = stages[i - 1]?.n;
    let share = "&nbsp;";
    if (i) share = before ? `${((stage.n / before) * 100).toFixed(stage.n / before < 0.1 ? 1 : 0)}% of previous` : "- of previous";
    return `<div class="fs"><div class="n">${stage.n.toLocaleString()}</div><div class="l">${esc(stage.stage)}</div>
      <div class="cv">${share}</div></div>`;
  }).join(`<div class="fa">→</div>`);
}

// ---------------------------------------------------------------- actions
onAction("run-analysis", async () => {
  await api("/api/analysis/run", { method: "POST" });
  toast("Analyzing", "Scoring your fit across every work genre. About a minute.");
  renderAnalysis();
});
onAction("radar-toggle", (el) => {  // a legend button shows or hides its series
  const key = el.dataset.k;
  if (radarOff.has(key)) radarOff.delete(key);
  else radarOff.add(key);
  localStorage.setItem("radarOff", JSON.stringify([...radarOff]));
  renderAnalysis();
});
onAction("genre-row", (el) => {
  const details = $(`#gd-${el.dataset.id}`);
  details.style.display = details.style.display === "none" ? "" : "none";
});
onAction("plan-add", async (el) => {  // adds the suggested queries or companies to the search plan
  const kind = el.dataset.kind;
  const add = S.analysis.steer[kind === "queries" ? "add_queries" : "add_companies"] || [];
  const plan = (await api("/api/profile")).search_plan || {};
  plan[kind] = [...new Set([...(plan[kind] || []), ...add])];
  await api("/api/profile/search_plan", { method: "PUT", body: { value: plan } });
  toast("Search plan updated", `${add.length} added, used on the next run`);
  el.disabled = true;
  el.textContent = "Added";
});
