/* analysis.js: the Analysis page (#/analysis). Where you fit and where the market is, for each kind of work: a radar
   chart of your fit, your interest and how many jobs there are, the AI's read and its top moves, a sortable table,
   skills employers asked for that your resumes couldn't show, the funnel from jobs found to offers, and which industries
   and sources bring good fits. The kinds of work come from the server, so the page reads the same for any field.
   APIs: GET /api/analysis (market numbers, the latest AI assessment and its history), POST /api/analysis/run,
   GET /api/profile and PUT /api/profile/search_plan (the "Add to search plan" buttons). An "analysis" event redraws it.
   The chart colors are CSS variables (--viz-*), checked for color blindness and contrast in both themes. */
"use strict";

// The radar's series in drawing order: [key in each row, legend label].
const RADAR_SERIES = [["demand", "Jobs out there"], ["interest", "Your interest"], ["prev", "Your fit before"], ["fit", "Your fit"]];
// The icon for each kind of suggested move.
const MOVE_ICON = { project: "tool", cert: "cert", course: "book", profile: "user", document: "file", search: "search" };
// The series you switched off in the legend, remembered between visits.
const radarOff = new Set(store.list("radarOff"));

// The floating tooltip for the chart and the bars. html = null hides it.
function vizTip(html, e) {
  let tip = $("#viz-tip");
  if (!tip) {
    tip = document.createElement("div");
    tip.id = "viz-tip";
    tip.className = "viz-tip";
    document.body.appendChild(tip);
  }
  if (!html) {
    tip.hidden = true;
    return;
  }
  tip.innerHTML = html;
  tip.hidden = false;
  // Next to the pointer, but never past the window's edge.
  tip.style.left = `${Math.min(e.clientX + 16, innerWidth - tip.offsetWidth - 10)}px`;
  tip.style.top = `${Math.min(e.clientY + 14, innerHeight - tip.offsetHeight - 10)}px`;
}

// A small color swatch for legends and table headers.
const swatch = (key) => `<i class="swatch s-${key}" aria-hidden="true"></i>`;

// The radar chart as SVG: one spoke per kind of work, rings at 25/50/75/100, one shape per visible series, a label at
// each series' peak, and an invisible wedge per spoke for its tooltip. present = the series that have data.
function radarSVG(rows, present) {
  const W = 660, H = 540, cx = W / 2, cy = H / 2 + 6, R = 190, N = rows.length;
  const angle = (i) => -Math.PI / 2 + (i * 2 * Math.PI) / N;  // the first one points straight up
  const point = (i, value) => [cx + R * (value / 100) * Math.cos(angle(i)), cy + R * (value / 100) * Math.sin(angle(i))];
  const visible = (key) => present.has(key) && !radarOff.has(key);
  let svg = "";
  for (const level of [25, 50, 75, 100]) {  // the rings and their numbers
    svg += `<polygon class="grid" points="${rows.map((_, i) => point(i, level).join(",")).join(" ")}"/>`;
    svg += `<text x="${cx + 4}" y="${cy - (R * level) / 100 - 3}" class="tick">${level}</text>`;
  }
  rows.forEach((row, i) => {  // the spokes and the names around the rim
    const [x, y] = point(i, 100);
    svg += `<line class="grid spoke" x1="${cx}" y1="${cy}" x2="${x}" y2="${y}" data-i="${i}"/>`;
    const cos = Math.cos(angle(i)), sin = Math.sin(angle(i)), lx = cx + (R + 20) * cos, ly = cy + (R + 20) * sin;
    const anchor = cos > 0.25 ? "start" : cos < -0.25 ? "end" : "middle";
    const lines = [];  // wrap the name at 16 characters
    for (const word of row.label.split(" ")) {
      if (lines.length && (lines.at(-1) + " " + word).length <= 16) lines[lines.length - 1] += " " + word;
      else lines.push(word);
    }
    // Names above the center grow upward, names below grow downward, the rest are centered on their spoke.
    const dy = sin < -0.5 ? -(lines.length - 1) * 14 : sin > 0.5 ? 6 : -((lines.length - 1) * 14) / 2 + 4;
    svg += `<text x="${lx}" y="${ly + dy}" text-anchor="${anchor}" class="rim">${lines.map((line, k) => `<tspan x="${lx}" dy="${k ? 14 : 0}">${esc(line)}</tspan>`).join("")}</text>`;
  });
  for (const [key] of RADAR_SERIES) {  // the series
    if (!visible(key)) continue;
    const points = rows.map((row, i) => point(i, row[key] ?? 0));
    svg += `<polygon class="series s-${key}" points="${points.map((p) => p.join(",")).join(" ")}"/>`;
    svg += points.map(([x, y]) => `<circle class="dot s-${key}" cx="${x}" cy="${y}" r="4"/>`).join("");
  }
  // A label at each visible series' peak only (not "Your fit before"), and never two on the same spoke.
  const labeled = new Set();
  for (const [key, label] of RADAR_SERIES) {
    if (!visible(key) || key === "prev") continue;
    let peak = 0;
    rows.forEach((row, i) => {
      if ((row[key] ?? -1) > (rows[peak][key] ?? -1)) peak = i;
    });
    if (labeled.has(peak)) continue;
    labeled.add(peak);
    // Just inside the point, toward the center, so it never runs into the names at the rim.
    const value = rows[peak][key] ?? 0, [x, y] = point(peak, Math.max(0, value - 13)), cos = Math.cos(angle(peak));
    const anchor = Math.abs(cos) < 0.25 ? "middle" : cos > 0 ? "end" : "start";
    svg += `<text x="${x}" y="${y + 4}" text-anchor="${anchor}" class="peak">${esc(label.replace(/^Your /, ""))} ${rows[peak][key]}</text>`;
  }
  rows.forEach((_, i) => {  // invisible wedges, bigger than the marks, for each spoke's tooltip
    const a0 = angle(i) - Math.PI / N, a1 = angle(i) + Math.PI / N, r = R + 34;
    const x0 = cx + r * Math.cos(a0), y0 = cy + r * Math.sin(a0), x1 = cx + r * Math.cos(a1), y1 = cy + r * Math.sin(a1);
    svg += `<path class="hit" data-i="${i}" d="M${cx},${cy} L${x0},${y0} A${r},${r} 0 0 1 ${x1},${y1} Z"/>`;
  });
  return `<svg viewBox="0 0 ${W} ${H}" class="radar" role="img" aria-label="Radar chart of your fit, your interest and the jobs out there for each kind of work. The table below lists every value.">${svg}</svg>`;
}

// A list of horizontal bars. Each item gives [label, value, value text, tooltip text].
function bars(items, maxValue) {
  return `<div class="bars">${items.map(([label, value, text, tip]) => `<div class="bar-row" data-tip="${esc(tip)}">
      <span class="bar-label">${esc(label)}</span><span class="bar-track"><i style="width:${(value / maxValue) * 100}%"></i></span>
      <span class="bar-value">${text}</span></div>`).join("")}</div>`;
}

// Draws the page from GET /api/analysis, then wires the chart and bar tooltips.
async function renderAnalysis() {
  const d = await api("/api/analysis");
  if (S.route[0] !== "analysis") return;
  main.dataset.page = "analysis";
  const market = d.market, latest = d.latest, result = latest?.result || null;
  const byGenre = Object.fromEntries((result?.genres || []).map((g) => [g.id, g]));
  const previousFit = d.history.length >= 2 ? d.history[d.history.length - 2].fit : null;
  // One row per kind of work: the market numbers plus the AI's fit and interest, and the fit from the analysis before.
  const rows = market.genres.map((g) => ({
    ...g,
    fit: byGenre[g.id]?.fit ?? null,
    interest: byGenre[g.id]?.interest ?? null,
    demand: market.demand_total ? g.demand_index : null,
    prev: previousFit?.[g.id] ?? null,
    ai: byGenre[g.id],
  }));
  const present = new Set(["fit", "interest", "demand", "prev"].filter((key) => rows.some((row) => row[key] != null)));
  // Payoff: many jobs, high interest and room to grow. A missing number counts as 50.
  const payoff = (row) => ((row.demand ?? 50) / 100) * ((row.interest ?? 50) / 100) * (1 - (row.fit ?? 50) / 100);
  const sorted = [...rows].sort((a, b) => payoff(b) - payoff(a));
  const labelOf = Object.fromEntries(rows.map((row) => [row.id, row.label]));
  const legend = RADAR_SERIES.filter(([key]) => present.has(key)).map(([key, label]) => `<button class="legend-item${radarOff.has(key) ? " off" : ""}"`
    + ` type="button" data-act="radar-toggle" data-k="${key}" aria-pressed="${!radarOff.has(key)}">${swatch(key)}${label}</button>`).join("");
  const steer = result?.search_steering || {};
  const notYet = `<p class="muted-note">Shows up after the analysis runs.</p>`;
  const runLabel = d.running ? `${spinner()} Analyzing` : result ? `${icon("refresh")} Analyze again` : `${icon("sparkle")} Run the analysis`;
  const topMoves = (result?.top_priorities || []).map((t, i) => `<li class="move">
      <span class="move-num">${i + 1}</span><div><b>${esc(t.title)}</b>
        <div class="tags"><span class="tag purple">${icon(MOVE_ICON[t.type] || "arrow")}${esc(humanize(t.type))}</span><span class="tag">${esc(labelOf[t.genre] || t.genre)}</span></div>
        <p>${esc(t.detail)}</p><p class="why">Why: ${esc(t.why)}</p></div></li>`).join("");
  const maxGap = Math.max(1, ...market.gaps.map((x) => x.missing_in));
  const gaps = market.gaps.length
    ? bars(market.gaps.map((x) => [x.skill, x.missing_in, `${x.missing_in}/${x.requested_in}`, `${x.skill}: missing in ${x.missing_in} of the ${x.requested_in} jobs that asked for it`]), maxGap)
    : `<div class="empty-state"><h3>Nothing measured yet</h3><p>This fills in as JobPortal tailors applications.</p></div>`;
  const qualifiedBars = (items, nameOf) => bars(items.map((x) => [nameOf(x), x.qualified, `${x.qualified} (avg ${x.avg_score ?? "-"})`,
    `${nameOf(x)}: ${x.qualified} good fits of ${x.triaged} scored, average score ${x.avg_score ?? "-"}`]), Math.max(1, ...items.map((x) => x.qualified)));
  const industries = market.industries || [];
  const suggestion = (x) => `<li><b>${esc(x.title)}</b><p>${esc(x.detail)}</p></li>`;
  main.innerHTML = `<div class="page-heading"><div><p class="eyebrow">YOUR MARKET</p><h1>Analysis</h1>
      <p>Where you fit, where the jobs are, and what to work on next.</p></div>
      <div class="heading-actions"><span class="muted-note">${latest ? `Analyzed ${esc(fmtTs(latest.ts))}, ${fmtTokens(+latest.tokens || 0)} tokens` : "Not analyzed yet"}</span>
        <button class="button ${result ? "outline" : "primary"}" type="button" data-act="run-analysis"${d.running ? " disabled" : ""}>${runLabel}</button></div></div>
    ${!result ? `<div class="banner info">${icon("sparkle")}<div><b>Run the analysis</b> to score your fit and interest across ${plural(rows.length, "kind")} of work against
      the jobs out there, and get concrete next steps. It runs again by itself whenever your profile changes.</div></div>` : ""}
    <div class="analysis-top">
      <section class="panel"><div class="panel-heading"><h2>Fit and demand by kind of work</h2><div class="legend">${legend}</div></div>
        <p class="panel-note">Fit and interest: the AI's read of your profile, 0 to 100. Jobs out there: the share of jobs that passed your filters,
          scaled so the busiest kind is 100 (${esc(market.demand_source)}).</p>
        <div id="radar">${radarSVG(rows, present)}</div></section>
      <div class="stack">
        <section class="panel"><h2>The read</h2>${result ? `<p>${esc(result.summary)}</p>` : `<p class="muted-note">No assessment yet.</p>`}</section>
        <section class="panel"><h2>Top moves, best payoff first</h2>${topMoves ? `<ol class="move-list">${topMoves}</ol>` : notYet}</section></div></div>
    <section class="panel"><h2>Every kind of work, best payoff first</h2>
      <p class="panel-note">Payoff is high when there are many jobs, your interest is high, and you have room to grow. Click a row for the details.</p>
      <div class="table-wrap"><table class="table numbers"><thead><tr><th>Kind of work</th><th>${swatch("fit")}Fit</th><th>${swatch("interest")}Interest</th>
        <th>${swatch("demand")}Jobs out there</th><th>Good fits</th><th>Average score</th><th>Fit change</th><th>Skills your resumes lacked</th></tr></thead>
        <tbody>${sorted.map(genreRows).join("")}</tbody></table></div></section>
    <div class="two-col">
      <section class="panel"><h2>Skills employers asked for that your resumes couldn't show</h2>
        <p class="panel-note">Across ${plural(market.packaged_leads, "tailored application")}. Learn or document these, and every future resume can use them.</p>
        ${gaps}</section>
      <div class="stack">
        <section class="panel"><h2>Skills employers asked for that you already show</h2>
          <div class="tags">${market.strengths.map((x) => `<span class="tag green" title="Asked for in ${x.requested_in}">${esc(x.skill)}</span>`).join("")
            || `<span class="muted-note">This fills in as applications are tailored.</span>`}</div></section>
        <section class="panel"><h2>Steer the search</h2>${result ? steerSearch(steer, labelOf) : notYet}</section>
        <section class="panel"><h2>Add these to your profile</h2>
          ${(result?.profile_suggestions || []).length ? `<ul class="suggestions">${result.profile_suggestions.map(suggestion).join("")}</ul>` : notYet}
          <div class="block-actions"><a class="button outline" href="#/settings/profile/questions">Tell JobPortal about it</a>
            <a class="text-button" href="#/home">Answer open questions ${icon("arrow")}</a></div></section></div></div>
    <section class="panel"><h2>From found to hired</h2><div class="funnel">${funnel(market.funnel)}</div></section>
    <div class="two-col">
      <section class="panel"><h2>Good fits by industry</h2>
        ${industries.length ? qualifiedBars(industries, (x) => x.industry) : `<p class="muted-note">Run a search first.</p>`}</section>
      <section class="panel"><h2>Which sources bring good fits</h2>
        ${market.sources.length ? qualifiedBars(market.sources, (x) => LABEL_SRC[x.source] || humanize(x.source)) : `<p class="muted-note">Run a search first.</p>`}</section></div>`;
  const svg = $("#radar svg");
  const unhighlight = () => $$(".spoke", svg).forEach((spoke) => spoke.classList.remove("on"));
  svg.addEventListener("mousemove", (e) => {  // the spoke under the pointer: highlight it and show its numbers
    const hit = e.target.closest(".hit");
    unhighlight();
    if (!hit) return vizTip(null);
    const row = rows[+hit.dataset.i];
    $(`.spoke[data-i="${hit.dataset.i}"]`, svg).classList.add("on");
    const values = [["fit", "Your fit"], ["interest", "Your interest"], ["demand", "Jobs out there"], ["prev", "Your fit before"]].filter(([key]) => row[key] != null)
      .map(([key, label]) => `<div class="tip-row">${swatch(key)}<span>${label}</span><b>${row[key]}</b></div>`).join("");
    vizTip(`<b>${esc(row.label)}</b>${values}<div class="tip-note">${plural(row.qualified, "good fit")}, ${(row.demand_share * 100).toFixed(1)}% of jobs</div>`, e);
  });
  svg.addEventListener("mouseleave", () => {
    vizTip(null);
    unhighlight();
  });
  $$(".bar-row", main).forEach((bar) => {
    bar.addEventListener("mousemove", (e) => vizTip(esc(bar.dataset.tip), e));
    bar.addEventListener("mouseleave", () => vizTip(null));
  });
  S.analysis = { steer };
}

// One suggested move for a kind of work: its title, the effort and impact, and the details.
const genreMove = (move) => `<li><b>${icon(MOVE_ICON[move.type] || "arrow")}${esc(move.title)}</b>`
  + ` <span class="muted-note">(${esc(move.effort)} effort, ${esc(move.impact)} impact)</span><p>${esc(move.detail)}</p></li>`;

// Two table rows per kind of work: its numbers, and a hidden row with the AI's evidence, gaps and moves (a click on the
// first row shows it).
function genreRows(row) {
  const change = row.fit != null && row.prev != null
    ? `${row.fit > row.prev ? icon("up") : row.fit < row.prev ? icon("chevron") : ""}${Math.abs(row.fit - row.prev)}` : "-";
  const details = row.ai ? `<div class="three-col">
      <div><h4>Evidence <span class="tag">${esc(humanize(row.ai.confidence))} confidence</span></h4>${bulletList(row.ai.evidence, "good")}</div>
      <div><h4>Gaps</h4>${bulletList(row.ai.gaps, "warn")}</div>
      <div><h4>Moves</h4><ul class="plain-list">${row.ai.moves.map(genreMove).join("")}</ul></div></div>`
    : `<p class="muted-note">Run the analysis for the evidence, gaps and moves.</p>`;
  return `<tr class="genre-row" data-act="genre-row" data-id="${esc(row.id)}" tabindex="0" aria-expanded="false"><td><b>${esc(row.label)}</b>${icon("chevron")}</td>
      <td>${row.fit ?? "-"}</td><td>${row.interest ?? "-"}</td>
      <td>${row.demand ?? "-"} <small>(${(row.demand_share * 100).toFixed(1)}%)</small></td>
      <td>${row.qualified}</td><td>${row.avg_score ?? "-"}</td><td class="change">${change}</td>
      <td class="wrap">${esc(row.top_missing.join(", ")) || `<span class="muted-note">None</span>`}</td></tr>
    <tr class="genre-details" data-details="${esc(row.id)}" hidden><td colspan="8">${details}</td></tr>`;
}

// "Steer the search": kinds of work to lean into and away from, a note, and search terms and companies you can add to
// your search plan with one click.
function steerSearch(steer, labelOf) {
  const kinds = (ids, cls) => (ids || []).map((id) => `<span class="tag${cls}">${esc(labelOf[id] || id)}</span>`).join("") || `<span class="muted-note">None</span>`;
  const addList = (items, title, kind, button) => ((items || []).length
    ? `<h4>${title}</h4><div class="tags">${items.map((q) => `<span class="tag">${esc(q)}</span>`).join("")}</div>`
      + `<button class="button outline small" type="button" data-act="plan-add" data-kind="${kind}">${icon("plus")}${button}</button>`
    : "");
  return `<h4>Lean into</h4><div class="tags">${kinds(steer.emphasize, " blue")}</div>
    <h4>Ease off</h4><div class="tags">${kinds(steer.deemphasize, "")}</div>
    ${steer.notes ? `<p>${esc(steer.notes)}</p>` : ""}
    ${addList(steer.add_queries, "Search terms to add", "queries", "Add to my search plan")}
    ${addList(steer.add_companies, "Companies to add", "dream_companies", "Add to my target companies")}`;
}

// The funnel: each step's count and its share of the step before.
function funnel(stages) {
  return stages.map((stage, i) => {
    const before = stages[i - 1]?.n;
    let share = "";
    if (i) share = before ? `${((stage.n / before) * 100).toFixed(stage.n / before < 0.1 ? 1 : 0)}% of the step before` : "None the step before";
    return `<div class="funnel-step"><strong>${stage.n.toLocaleString()}</strong><span>${esc(stage.stage)}</span><small>${share}</small></div>`;
  }).join(`<span class="funnel-arrow" aria-hidden="true">${icon("arrow")}</span>`);
}

// ---------------------------------------------------------------- actions
onAction("run-analysis", async () => {
  await api("/api/analysis/run", { method: "POST" });
  toast("Analyzing", "Scoring your fit across every kind of work. About a minute.");
  renderAnalysis();
});
onAction("radar-toggle", (el) => {  // a legend button shows or hides its series
  const key = el.dataset.k;
  if (radarOff.has(key)) radarOff.delete(key);
  else radarOff.add(key);
  store.set("radarOff", JSON.stringify([...radarOff]));
  renderAnalysis();
});
onAction("genre-row", (el) => {
  const details = $(`[data-details="${el.dataset.id}"]`);
  details.hidden = !details.hidden;
  el.setAttribute("aria-expanded", String(!details.hidden));
});
onAction("plan-add", async (el) => {  // adds the suggested search terms or companies to the search plan
  const kind = el.dataset.kind;
  const add = S.analysis.steer[kind === "queries" ? "add_queries" : "add_companies"] || [];
  const plan = (await api("/api/profile")).search_plan || {};
  plan[kind] = [...new Set([...(plan[kind] || []), ...add])];
  await api("/api/profile/search_plan", { method: "PUT", body: { value: plan } });
  toast("Search plan updated", `${add.length} added. The next search uses them.`);
  el.disabled = true;
  el.textContent = "Added";
});
// Enter or Space on a focused table row opens its details, like a click.
document.addEventListener("keydown", (e) => {
  if ((e.key === "Enter" || e.key === " ") && e.target.matches?.("tr[data-act=genre-row]")) {
    e.preventDefault();
    e.target.click();
  }
});
