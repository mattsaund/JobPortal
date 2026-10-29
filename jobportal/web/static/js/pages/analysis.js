/* The Analysis page: market demand per work genre, your fit, skill gaps, the funnel and source quality. */
"use strict";

// Palette validated with the dataviz checker on the panel surface #111317 (dark, all-pairs): CVD ΔE ≥ 9.4, normal ΔE ≥ 20.9, contrast ≥ 3:1.
const VIZ = { fit: "#3987e5", demand: "#d95926", interest: "#199e70", prev: "#6b7280", surface: "#111317", grid: "#262b34" };
const RADAR_SERIES = [["demand", "Market demand"], ["interest", "Your interest"], ["prev", "Previous fit"], ["fit", "Your fit"]];
const MOVE_ICON = { project: '<i class=i-tool></i>', cert: '<i class=i-cert></i>', course: '<i class=i-book></i>', profile: '<i class=i-doc></i>', document: '<i class=i-doc></i>', search: '<i class=i-search></i>' };
let radarOff = new Set(JSON.parse(localStorage.getItem("radarOff") || "[]"));

function vizTip(html, e) {
  let t = $("#viz-tip");
  if (!t) { t = document.createElement("div"); t.id = "viz-tip"; t.className = "viz-tip"; document.body.appendChild(t); }
  if (!html) { t.style.display = "none"; return; }
  t.innerHTML = html; t.style.display = "block";
  const x = Math.min(e.clientX + 16, innerWidth - t.offsetWidth - 10), y = Math.min(e.clientY + 14, innerHeight - t.offsetHeight - 10);
  t.style.left = `${x}px`; t.style.top = `${y}px`;
}
const sw = (c) => `<i class="sw" style="background:${c}"></i>`;

function radarSVG(rows, present) {
  const W = 660, H = 540, cx = W / 2, cy = H / 2 + 6, R = 190, N = rows.length;
  const ang = (i) => -Math.PI / 2 + (i * 2 * Math.PI) / N;
  const pt = (i, v) => [cx + R * (v / 100) * Math.cos(ang(i)), cy + R * (v / 100) * Math.sin(ang(i))];
  let g = "";
  for (const lv of [25, 50, 75, 100]) {
    g += `<polygon points="${rows.map((_, i) => pt(i, lv).join(",")).join(" ")}" fill="none" stroke="${VIZ.grid}" stroke-width="1"/>`;
    g += `<text x="${cx + 4}" y="${cy - (R * lv) / 100 - 3}" class="rt">${lv}</text>`;
  }
  rows.forEach((r, i) => {
    const [x, y] = pt(i, 100);
    g += `<line x1="${cx}" y1="${cy}" x2="${x}" y2="${y}" stroke="${VIZ.grid}" stroke-width="1" class="spoke" data-i="${i}"/>`;
    const c = Math.cos(ang(i)), s = Math.sin(ang(i)), lx = cx + (R + 20) * c, ly = cy + (R + 20) * s;
    const anchor = c > 0.25 ? "start" : c < -0.25 ? "end" : "middle";
    const words = r.label.split(" "), lines = [];
    for (const w of words) { if (lines.length && (lines.at(-1) + " " + w).length <= 16) lines[lines.length - 1] += " " + w; else lines.push(w); }
    const dy0 = s < -0.5 ? -(lines.length - 1) * 14 : s > 0.5 ? 6 : -((lines.length - 1) * 14) / 2 + 4;
    g += `<text x="${lx}" y="${ly + dy0}" text-anchor="${anchor}" class="rl">${lines.map((l, k) => `<tspan x="${lx}" dy="${k ? 14 : 0}">${esc(l)}</tspan>`).join("")}</text>`;
  });
  for (const [key] of RADAR_SERIES) {
    if (!present.has(key) || radarOff.has(key)) continue;
    const col = VIZ[key], pts = rows.map((r, i) => pt(i, r[key] ?? 0));
    g += `<polygon points="${pts.map((p) => p.join(",")).join(" ")}" fill="${col}" fill-opacity="${key === "prev" ? 0 : 0.1}" stroke="${col}" stroke-width="2" stroke-linejoin="round"/>`;
    g += pts.map(([x, y]) => `<circle cx="${x}" cy="${y}" r="4" fill="${col}" stroke="${VIZ.surface}" stroke-width="2"/>`).join("");
  }
  // selective direct labels: each visible series' peak only
  const used = new Set();
  for (const [key, label] of RADAR_SERIES) {
    if (!present.has(key) || radarOff.has(key) || key === "prev") continue;
    let bi = 0; rows.forEach((r, i) => { if ((r[key] ?? -1) > (rows[bi][key] ?? -1)) bi = i; });
    if (used.has(bi)) continue; used.add(bi);
    // place the label just inside the vertex (toward the center) so it never collides with the axis labels at the rim
    const v = rows[bi][key] ?? 0, [x, y] = pt(bi, Math.max(0, v - 13)), c = Math.cos(ang(bi));
    g += `<text x="${x}" y="${y + 4}" text-anchor="${Math.abs(c) < 0.25 ? "middle" : c > 0 ? "end" : "start"}" class="dl">${esc(label.replace("Your ", "").replace("Market ", ""))} ${rows[bi][key]}</text>`;
  }
  // hit wedges (bigger than the marks) for the per-genre tooltip
  rows.forEach((_, i) => {
    const a0 = ang(i) - Math.PI / N, a1 = ang(i) + Math.PI / N, rr = R + 34;
    g += `<path class="hit" data-i="${i}" d="M${cx},${cy} L${cx + rr * Math.cos(a0)},${cy + rr * Math.sin(a0)} A${rr},${rr} 0 0 1 ${cx + rr * Math.cos(a1)},${cy + rr * Math.sin(a1)} Z" fill="transparent"/>`;
  });
  return `<svg viewBox="0 0 ${W} ${H}" class="radar" role="img" aria-label="Radar chart of fit, interest and market demand per work genre; the table below lists every value">${g}</svg>`;
}

async function renderAnalysis() {
  const d = await api("/api/analysis");
  const m = d.market, latest = d.latest, res = latest?.result || null;
  const ai = Object.fromEntries((res?.genres || []).map((g) => [g.id, g]));
  const prev = d.history.length >= 2 ? d.history[d.history.length - 2].fit : null;
  const rows = m.genres.map((g) => ({ ...g, fit: ai[g.id]?.fit ?? null, interest: ai[g.id]?.interest ?? null, demand: m.demand_total ? g.demand_index : null,
    prev: prev?.[g.id] ?? null, ai: ai[g.id] }));
  const present = new Set(["fit", "interest", "demand", "prev"].filter((k) => rows.some((r) => r[k] != null)));
  const payoff = (r) => ((r.demand ?? 50) / 100) * ((r.interest ?? 50) / 100) * (1 - (r.fit ?? 50) / 100);
  const sorted = [...rows].sort((a, b) => payoff(b) - payoff(a));
  const labelOf = Object.fromEntries(rows.map((r) => [r.id, r.label]));
  const legend = RADAR_SERIES.filter(([k]) => present.has(k)).map(([k, l]) => `<button class="lg ${radarOff.has(k) ? "off" : ""}" data-act="radar-toggle" data-k="${k}">${sw(VIZ[k])}${l}</button>`).join("");
  const maxGap = Math.max(1, ...m.gaps.map((x) => x.missing_in)), maxSrc = Math.max(1, ...m.sources.map((x) => x.qualified));
  const steer = res?.search_steering || {};
  main.innerHTML = `<div class="page">
    <div class="page-h"><h1>Analysis</h1><span class="sub">Where you fit, where the market is, and what to build next.</span><span class="spacer"></span>
      <span class="muted small mono">${latest ? `analyzed ${esc(fmtTs(latest.ts))}, ${fmtTokens(+latest.tokens || 0)} tokens` : "not analyzed yet"}</span>
      <button class="btn ${res ? "" : "primary"}" data-act="run-analysis" ${d.running ? "disabled" : ""}>${d.running ? `<span class="spin"></span> Analyzing` : res ? "<i class=i-refresh></i> Re-analyze" : "Run analysis"}</button></div>
    ${!res ? `<div class="banner accent"><div><b>Run the analysis</b> to score your fit and interest across ${rows.length} work genres against real market demand and get concrete moves. It re-runs automatically whenever your profile changes.</div></div>` : ""}
    <div class="cols" style="grid-template-columns:minmax(0,1.25fr) minmax(0,1fr)">
      <div class="card"><div class="row" style="margin-bottom:4px"><h3 style="margin:0">Work-genre radar</h3><span class="spacer"></span><div class="legend">${legend}</div></div>
        <div class="muted small">Fit and interest: AI assessment of your profile (0 to 100). Demand: share of postings that passed your filters, indexed so the busiest genre is 100 (${esc(m.demand_source)}).</div>
        <div id="radar">${radarSVG(rows, present)}</div></div>
      <div class="stack">
        <div class="card"><h3>The read</h3>${res ? `<p style="margin:0">${esc(res.summary)}</p>` : `<p class="muted" style="margin:0">No assessment yet.</p>`}</div>
        <div class="card"><h3>Top moves, ranked by payoff</h3>${(res?.top_priorities || []).map((t, i) => `<div style="padding:8px 0;border-bottom:1px solid var(--line)">
          <div class="row" style="gap:6px"><span class="mono muted">${i + 1}.</span><b>${esc(t.title)}</b></div>
          <div class="row" style="gap:5px;margin:4px 0"><span class="chip violet">${MOVE_ICON[t.type] || ""} ${esc(t.type)}</span><span class="chip">${esc(labelOf[t.genre] || t.genre)}</span></div>
          <div class="small">${esc(t.detail)}</div><div class="small muted" style="margin-top:3px">Why: ${esc(t.why)}</div></div>`).join("") || `<div class="muted small">Appears after the analysis runs.</div>`}</div></div></div>

    <div class="card" style="margin-top:14px"><h3>Every genre, sorted by payoff (high demand x high interest x room to grow)</h3>
      <table class="t gt"><thead><tr><th>Genre</th><th>${sw(VIZ.fit)}Fit</th><th>${sw(VIZ.interest)}Interest</th><th>${sw(VIZ.demand)}Demand</th><th>Qualified leads</th><th>Avg lead score</th><th>Δ fit</th><th>Skills your resumes lacked</th></tr></thead>
      <tbody>${sorted.map((r) => `<tr class="gr" data-act="genre-row" data-id="${r.id}" style="cursor:pointer"><td><b>${esc(r.label)}</b> <span class="muted small"><i class=i-chev></i></span></td>
        <td class="num">${r.fit ?? "-"}</td><td class="num">${r.interest ?? "-"}</td>
        <td class="num">${r.demand ?? "-"} <span class="muted small">(${(r.demand_share * 100).toFixed(1)}%)</span></td>
        <td class="num">${r.qualified}</td><td class="num">${r.avg_score ?? "-"}</td>
        <td class="num">${r.fit != null && r.prev != null ? `${r.fit - r.prev > 0 ? "<i class=i-up></i>" : r.fit - r.prev < 0 ? "<i class=i-down></i>" : ""} ${Math.abs(r.fit - r.prev)}` : "-"}</td>
        <td class="small">${esc(r.top_missing.join(", ")) || `<span class="muted">none</span>`}</td></tr>
        <tr class="gd" id="gd-${r.id}" style="display:none"><td colspan="8">${r.ai ? `<div class="grid3">
          <div><b class="small mono">EVIDENCE</b> <span class="chip">${esc(r.ai.confidence)} confidence</span><ul class="clean good small">${r.ai.evidence.map((x) => `<li>${esc(x)}</li>`).join("")}</ul></div>
          <div><b class="small mono">GAPS</b><ul class="clean warn small">${r.ai.gaps.map((x) => `<li>${esc(x)}</li>`).join("")}</ul></div>
          <div><b class="small mono">MOVES</b>${r.ai.moves.map((mv) => `<div class="small" style="margin:6px 0"><b>${MOVE_ICON[mv.type] || ""} ${esc(mv.title)}</b> <span class="muted">(${esc(mv.effort)}, ${esc(mv.impact)} impact)</span><div>${esc(mv.detail)}</div></div>`).join("")}</div></div>` : `<span class="muted small">Run the analysis for evidence, gaps and moves.</span>`}</td></tr>`).join("")}</tbody></table></div>

    <div class="cols" style="margin-top:14px">
      <div class="card"><h3>Skills employers asked for that your tailored resumes couldn't show</h3>
        <div class="muted small" style="margin-bottom:10px">Across ${m.packaged_leads} packaged lead${m.packaged_leads === 1 ? "" : "s"}. Build or document these and every future resume can claim them.</div>
        ${m.gaps.length ? `<div class="bars">${m.gaps.map((x) => `<div class="br" data-tip="${esc(`${x.skill}: missing in ${x.missing_in} of ${x.requested_in} postings that asked for it`)}">
          <span class="bl">${esc(x.skill)}</span><span class="bt"><i style="width:${(x.missing_in / maxGap) * 100}%;background:${VIZ.fit}"></i></span><span class="bv">${x.missing_in}/${x.requested_in}</span></div>`).join("")}</div>`
          : `<div class="empty" style="padding:24px"><b>No gaps measured yet</b>They appear as application packages are built.</div>`}</div>
      <div class="stack">
        <div class="card"><h3>Requested skills you already show</h3><div class="cov">${m.strengths.map((x) => `<span class="chip good" title="requested in ${x.requested_in}">${esc(x.skill)}</span>`).join("") || `<span class="muted small">Appears as packages are built.</span>`}</div></div>
        <div class="card"><h3>Steer the search</h3>${res ? `
          <div class="small"><b class="mono">EMPHASIZE</b> ${(steer.emphasize || []).map((g) => `<span class="chip blue">${esc(labelOf[g] || g)}</span>`).join(" ") || "none"}</div>
          <div class="small" style="margin-top:6px"><b class="mono">DE-EMPHASIZE</b> ${(steer.deemphasize || []).map((g) => `<span class="chip">${esc(labelOf[g] || g)}</span>`).join(" ") || "none"}</div>
          ${steer.notes ? `<p class="small" style="margin:8px 0 0">${esc(steer.notes)}</p>` : ""}
          ${(steer.add_queries || []).length ? `<div style="margin-top:10px"><b class="small mono">QUERIES TO ADD</b><div class="cov" style="margin:6px 0">${steer.add_queries.map((q) => `<span class="chip">${esc(q)}</span>`).join("")}</div><button class="btn sm" data-act="plan-add" data-kind="queries">+ Add to search plan</button></div>` : ""}
          ${(steer.add_companies || []).length ? `<div style="margin-top:10px"><b class="small mono">COMPANIES TO ADD</b><div class="cov" style="margin:6px 0">${steer.add_companies.map((q) => `<span class="chip">${esc(q)}</span>`).join("")}</div><button class="btn sm" data-act="plan-add" data-kind="dream_companies">+ Add to target companies</button></div>` : ""}` : `<span class="muted small">Appears after the analysis runs.</span>`}</div>
        <div class="card"><h3>Add these to your profile</h3>${(res?.profile_suggestions || []).map((x) => `<div style="padding:6px 0;border-bottom:1px solid var(--line)"><b class="small"><i class=i-doc></i> ${esc(x.title)}</b><div class="small muted">${esc(x.detail)}</div></div>`).join("") || `<span class="muted small">Appears after the analysis runs.</span>`}
          <div class="row" style="margin-top:10px"><a class="btn sm" href="#/profile/questions">Tell JobPortal about it</a><a class="btn sm ghost" href="#/profile/questions">Answer open questions →</a></div></div></div></div>

    <div class="card" style="margin-top:14px"><h3>Pipeline</h3><div class="funnel">${m.funnel.map((f, i) => `<div class="fs"><div class="n">${f.n.toLocaleString()}</div><div class="l">${esc(f.stage)}</div>
      ${i ? `<div class="cv">${m.funnel[i - 1].n ? `${((f.n / m.funnel[i - 1].n) * 100).toFixed(f.n / m.funnel[i - 1].n < 0.1 ? 1 : 0)}%` : "-"} of previous</div>` : `<div class="cv">&nbsp;</div>`}</div>`).join(`<div class="fa">→</div>`)}</div></div>

    <div class="card" style="margin-top:14px"><h3>Qualified leads by industry</h3>
      ${(m.industries || []).length ? `<div class="bars">${m.industries.map((x) => `<div class="br" data-tip="${esc(`${x.industry}: ${x.qualified} qualified of ${x.triaged} triaged, avg score ${x.avg_score ?? "-"}`)}">
        <span class="bl">${esc(x.industry)}</span><span class="bt"><i style="width:${(x.qualified / Math.max(1, ...m.industries.map((y) => y.qualified))) * 100}%;background:${VIZ.fit}"></i></span><span class="bv">${x.qualified} (avg ${x.avg_score ?? "-"})</span></div>`).join("")}</div>` : `<span class="muted small">Run a search first.</span>`}</div>
    <div class="card" style="margin-top:14px"><h3>Which sources produce qualified leads</h3>
      ${m.sources.length ? `<div class="bars">${m.sources.map((x) => `<div class="br" data-tip="${esc(`${LABEL_SRC[x.source] || x.source}: ${x.qualified} qualified of ${x.triaged} triaged, avg score ${x.avg_score ?? "-"}`)}">
        <span class="bl">${esc(LABEL_SRC[x.source] || x.source)}</span><span class="bt"><i style="width:${(x.qualified / maxSrc) * 100}%;background:${VIZ.fit}"></i></span><span class="bv">${x.qualified} (avg ${x.avg_score ?? "-"})</span></div>`).join("")}</div>` : `<span class="muted small">Run a search first.</span>`}</div>
  </div>`;
  const svg = $("#radar svg");
  svg.addEventListener("mousemove", (e) => {
    const hit = e.target.closest(".hit"); $$(".spoke", svg).forEach((s) => s.classList.remove("on"));
    if (!hit) return vizTip(null);
    const r = rows[+hit.dataset.i]; $(`.spoke[data-i="${hit.dataset.i}"]`, svg).classList.add("on");
    vizTip(`<b>${esc(r.label)}</b>${[["fit", "Your fit"], ["interest", "Your interest"], ["demand", "Market demand"], ["prev", "Previous fit"]].filter(([k]) => r[k] != null)
      .map(([k, l]) => `<div class="tr">${sw(VIZ[k])}<span>${l}</span><b>${r[k]}</b></div>`).join("")}<div class="muted" style="margin-top:4px">${r.qualified} qualified leads, ${(r.demand_share * 100).toFixed(1)}% of postings</div>`, e);
  });
  svg.addEventListener("mouseleave", () => { vizTip(null); $$(".spoke", svg).forEach((s) => s.classList.remove("on")); });
  $$(".br", main).forEach((b) => { b.addEventListener("mousemove", (e) => vizTip(esc(b.dataset.tip), e)); b.addEventListener("mouseleave", () => vizTip(null)); });
  S.analysis = { steer };
}

// ---------------------------------------------------------------- actions
onAction("run-analysis", async (el, e) => { await api("/api/analysis/run", { method: "POST" }); toast("Analyzing", "Scoring your fit across every work genre. About a minute."); renderAnalysis(); });
onAction("radar-toggle", async (el, e) => { const k = el.dataset.k; radarOff.has(k) ? radarOff.delete(k) : radarOff.add(k); localStorage.setItem("radarOff", JSON.stringify([...radarOff])); renderAnalysis(); });
onAction("genre-row", async (el, e) => { const r = $(`#gd-${el.dataset.id}`); r.style.display = r.style.display === "none" ? "" : "none"; });
onAction("plan-add", async (el, e) => {
  const kind = el.dataset.kind, add = S.analysis.steer[kind === "queries" ? "add_queries" : "add_companies"] || [];
  const prof = await api("/api/profile"), plan = prof.search_plan || {};
  plan[kind] = [...new Set([...(plan[kind] || []), ...add])];
  await api("/api/profile/search_plan", { method: "PUT", body: { value: plan } }); toast("Search plan updated", `${add.length} added, used on the next run`); el.disabled = true; el.textContent = "Added"; });
