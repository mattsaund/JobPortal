/* analysis.js: the Analysis page (#/analysis), laid out as a full-screen report. A strip at the top says when the last
   analysis ran and has Analyze. Under it, a radar chart of your fit, your interest and how many jobs there are for each
   role, beside a table of the roles with their numbers (a click opens a role's details). Below those: the AI's assessment,
   top moves, search steering and profile additions, the skills employers asked for, the funnel from jobs found to offers,
   and which industries and sources bring good fits.
   The roles aren't fixed. The server picks 3 to 8 job titles from your target roles, your search plan, your work history,
   the AI's suggestions and your own leads (insights/analysis.py), and you can remove any of them or add your own.
   Live redraws (an "analysis" event) keep your place: open role details stay open, and the focus and anything typed in
   "Add role" survive. Only the newest load draws, so a click and a live event can't race.
   APIs: GET /api/analysis (the roles with their numbers and scores, the market numbers, the latest AI assessment and its
   history), POST /api/analysis/run, POST /api/analysis/roles/add, /remove and /restore (each answers with the page's data
   again), GET /api/profile and PUT /api/profile/search_plan (the "Add terms" and "Add companies" buttons).
   The chart colors are CSS variables (--viz-*), checked for color blindness and contrast in both themes. */
"use strict";

// The radar's series in drawing order: [key in each row, legend label].
const RADAR_SERIES = [["demand", "Jobs"], ["interest", "Interest"], ["prev", "Last fit"], ["fit", "Fit"]];
// The icon for each kind of suggested move.
const MOVE_ICON = { project: "tool", cert: "cert", course: "book", profile: "user", document: "file", search: "search" };
// Where a role came from: [the word under its name in the table, the words in its details].
const ROLE_SOURCE = {
  target: ["Target", "target roles"],
  added: ["Added", "roles you added"],
  plan: ["Search plan", "search plan"],
  experience: ["Experience", "work history"],
  suggested: ["AI suggestion", "AI suggestions"],
  market: ["Leads", "leads"],
};
// The series you switched off in the legend, remembered between visits.
const radarOff = new Set(store.list("radarOff"));
// The page between draws: the newest load's ticket (only it may draw), the rows and series on the radar (the legend
// redraws the radar from them without loading again), the observer that redraws the radar when its box changes width a
// lot (a window resized, a phone turned), and the roles whose details are open (they stay open through live redraws).
let analysisLoad = 0, radarView = null, radarResize = null;
const openRoles = new Set();

// The floating tooltip for the chart and the bars. html = null hides it.
function vizTip(html, e) {
  let tip = $("#viz-tip");
  if (!html) {
    if (tip) tip.hidden = true;
    return;
  }
  if (!tip) {
    tip = document.createElement("div");
    tip.id = "viz-tip";
    tip.className = "viz-tip";
    document.body.appendChild(tip);
  }
  tip.innerHTML = html;
  tip.hidden = false;
  // Next to the pointer, but never past the window's edge.
  tip.style.left = `${Math.min(e.clientX + 16, innerWidth - tip.offsetWidth - 10)}px`;
  tip.style.top = `${Math.min(e.clientY + 14, innerHeight - tip.offsetHeight - 10)}px`;
}
// A tooltip showing when you leave the page would stay on screen: the element under it is gone.
window.addEventListener("hashchange", () => vizTip(null));

// A small color swatch for legends and table headers.
const swatch = (key) => `<i class="swatch s-${key}" aria-hidden="true"></i>`;

// "A", "A and B", "A, B and C".
const listText = (items) => (items.length < 3 ? items.join(" and ") : `${items.slice(0, -1).join(", ")} and ${items.at(-1)}`);

// A 0 to 100 value for the chart, or null when there's none. Anything that isn't a number (a stray value in an old saved
// analysis) reads as missing, so it never reaches the drawing or the HTML.
const score = (value) => (value == null || value === "" || !Number.isFinite(+value) ? null : Math.max(0, Math.min(100, Math.round(+value))));
// A share (0.37) as a percent with one decimal ("37.0").
const percent = (share) => ((Number(share) || 0) * 100).toFixed(1);
// A list from the server, or [] when it isn't one.
const listOf = (value) => (Array.isArray(value) ? value : []);

// The width of text in the chart's font, for wrapping role names around the rim. One canvas, made on first use.
let measureCanvas = null;
function textWidth(text, size) {
  measureCanvas ||= document.createElement("canvas").getContext("2d");
  measureCanvas.font = `${size}px Arial, Helvetica, sans-serif`;
  return measureCanvas.measureText(text).width;
}

// A line cut to maxWidth, ending in an ellipsis when it had to be cut.
function clipLine(line, maxWidth, size) {
  if (textWidth(line, size) <= maxWidth) return line;
  let cut = line.replace(/\u2026$/, "");
  while (cut.length > 1 && textWidth(`${cut}\u2026`, size) > maxWidth) cut = cut.slice(0, -1);
  return `${cut.trimEnd()}\u2026`;
}

// A role's name as lines no wider than maxWidth: words wrap, three lines at most, and a name that still doesn't fit ends in
// an ellipsis. The full name is in the tooltip and the table.
function wrapLabel(label, maxWidth, size) {
  const lines = [];
  for (const word of String(label).split(/\s+/).filter(Boolean)) {
    const joined = lines.length ? `${lines.at(-1)} ${word}` : word;
    if (lines.length && textWidth(joined, size) <= maxWidth) lines[lines.length - 1] = joined;
    else lines.push(word);
  }
  const shown = lines.slice(0, 3);
  if (lines.length > 3) shown[2] += "\u2026";
  return shown.map((line) => clipLine(line, maxWidth, size));
}

// The radar chart as SVG, `width` units wide (the width of its box, so its text shows at about its real size, on a phone
// too): one spoke per role, rings at 25/50/75/100, one shape per visible series, a label at each series' peak, and an
// invisible wedge per spoke for its tooltip. present = the series that have data. A series with a gap (a role the AI hasn't
// scored yet) is drawn as lines between the roles that have a value, never as a dip to 0. On a small chart (a phone) the
// peak labels are left out: they would crowd it, and the tooltip and the table have every value.
function radarSVG(rows, present, width) {
  const W = width, room = Math.round(Math.min(124, Math.max(62, W * 0.19)));  // room for the names beside the rings
  const R = Math.round(W / 2 - room - 18), H = 2 * R + 150, cx = W / 2, cy = H / 2 + 4, N = rows.length, SIZE = 12.5;
  const angle = (i) => -Math.PI / 2 + (i * 2 * Math.PI) / N;  // the first one points straight up
  const point = (i, value) => [cx + R * (value / 100) * Math.cos(angle(i)), cy + R * (value / 100) * Math.sin(angle(i))].map((n) => +n.toFixed(1));
  const visible = (key) => present.has(key) && !radarOff.has(key);
  let svg = "";
  for (const level of [25, 50, 75, 100]) {  // the rings, and their numbers left of the top spoke (a peak label goes right of it)
    svg += `<polygon class="grid" points="${rows.map((_, i) => point(i, level).join(",")).join(" ")}"/>`;
    svg += `<text x="${cx - 4}" y="${+(cy - (R * level) / 100 - 3).toFixed(1)}" text-anchor="end" class="tick">${level}</text>`;
  }
  rows.forEach((row, i) => {  // the spokes and the names around the rim
    const [x, y] = point(i, 100);
    svg += `<line class="grid spoke" x1="${cx}" y1="${cy}" x2="${x}" y2="${y}" data-i="${i}"/>`;
    const cos = Math.cos(angle(i)), sin = Math.sin(angle(i));
    const lx = +(cx + (R + 14) * cos).toFixed(1), ly = +(cy + (R + 14) * sin).toFixed(1);
    const anchor = cos > 0.25 ? "start" : cos < -0.25 ? "end" : "middle";
    const space = anchor === "start" ? W - lx - 6 : anchor === "end" ? lx - 6 : 2 * Math.min(lx, W - lx) - 12;
    const lines = wrapLabel(row.label, Math.min(space, 170), SIZE);
    // Names above the center grow upward, names below grow downward, the rest are centered on their spoke.
    const dy = sin < -0.5 ? -(lines.length - 1) * 15 : sin > 0.5 ? 9 : -((lines.length - 1) * 15) / 2 + 4;
    svg += `<text x="${lx}" y="${ly + dy}" text-anchor="${anchor}" class="rim">${lines.map((line, k) => `<tspan x="${lx}" dy="${k ? 15 : 0}">${esc(line)}</tspan>`).join("")}</text>`;
  });
  for (const [key] of RADAR_SERIES) {  // the series
    if (!visible(key)) continue;
    const points = rows.map((row, i) => (row[key] == null ? null : point(i, row[key])));
    if (points.every(Boolean)) {
      svg += `<polygon class="series s-${key}" points="${points.map((p) => p.join(",")).join(" ")}"/>`;
    } else {
      svg += points.map((p, i) => {
        const next = points[(i + 1) % N];
        return p && next ? `<line class="series s-${key}" x1="${p[0]}" y1="${p[1]}" x2="${next[0]}" y2="${next[1]}"/>` : "";
      }).join("");
    }
    svg += points.filter(Boolean).map(([x, y]) => `<circle class="dot s-${key}" cx="${x}" cy="${y}" r="4"/>`).join("");
  }
  // A label at each visible series' peak only (not "Last fit"), and never two on the same spoke.
  const labeled = new Set();
  for (const [key, label] of RADAR_SERIES) {
    if (!visible(key) || key === "prev" || R < 120) continue;
    let peak = -1;
    rows.forEach((row, i) => {
      if (row[key] != null && (peak < 0 || row[key] > rows[peak][key])) peak = i;
    });
    if (peak < 0 || labeled.has(peak)) continue;
    labeled.add(peak);
    // Just inside the point, toward the center, so it never runs into the names at the rim. On an upright spoke it sits to
    // the right, clear of the ring numbers.
    const value = rows[peak][key], [x, y] = point(peak, Math.max(0, value - 13)), cos = Math.cos(angle(peak));
    const upright = Math.abs(cos) < 0.25, anchor = upright || cos < 0 ? "start" : "end";
    svg += `<text x="${upright ? x + 7 : x}" y="${y + 4}" text-anchor="${anchor}" class="peak">${esc(label)} ${esc(value)}</text>`;
  }
  rows.forEach((_, i) => {  // invisible wedges, bigger than the marks, for each spoke's tooltip
    const a0 = angle(i) - Math.PI / N, a1 = angle(i) + Math.PI / N, r = R + 34;
    const [x0, y0, x1, y1] = [cx + r * Math.cos(a0), cy + r * Math.sin(a0), cx + r * Math.cos(a1), cy + r * Math.sin(a1)].map((n) => +n.toFixed(1));
    svg += `<path class="hit" data-i="${i}" d="M${cx},${cy} L${x0},${y0} A${r},${r} 0 0 1 ${x1},${y1} Z"/>`;
  });
  return `<svg viewBox="0 0 ${W} ${H}" class="radar" role="img" aria-label="Radar chart of fit, interest and jobs by role">${svg}</svg>`;
}

// The radar's width: its box's, between a phone's and the widest the layout needs.
const radarWidth = (box) => Math.round(Math.min(760, Math.max(300, box.clientWidth || 660)));

// Draws the radar into #radar at its box's width, and draws it again when that width changes a lot. rows and present are
// kept (radarView), so the legend can redraw it without loading the page again.
function drawRadar(rows, present) {
  const box = $("#radar");
  if (!box) return;
  radarView = { rows, present };
  box.dataset.width = radarWidth(box);
  box.innerHTML = radarSVG(rows, present, +box.dataset.width);
  radarResize?.disconnect();
  if (!("ResizeObserver" in window)) return;
  radarResize = new ResizeObserver(debounce(() => {
    if (box.isConnected && Math.abs(radarWidth(box) - +box.dataset.width) > 30) drawRadar(rows, present);
  }, 150));
  radarResize.observe(box);
}

// A list of horizontal bars. Each item gives [label, value, value text, tooltip text, and a small note after the value].
function bars(items, maxValue) {
  return `<div class="bars">${items.map(([label, value, text, tip, note]) => `<div class="bar-row" data-tip="${esc(tip)}">
      <span class="bar-label">${esc(label)}</span><span class="bar-track"><i style="width:${((Number(value) || 0) / maxValue) * 100}%"></i></span>
      <span class="bar-value">${esc(text)}${note == null ? "" : `<small>${esc(note)}</small>`}</span></div>`).join("")}</div>`;
}

// The strip at the top: when the last analysis ran, how many roles it hasn't scored, and Analyze. The button is the main
// one while there's something to score.
function analysisBar(d) {
  const latest = d.latest, result = latest?.result;
  const state = latest ? `Analyzed ${esc(fmtTs(latest.ts))}, ${esc(fmtTokens(+latest.tokens || 0))} tokens` : d.outdated ? "Out of date" : "Not analyzed";
  const unscored = result && d.unscored.length ? `<span class="tag warn">${d.unscored.length} not scored</span>` : "";
  const label = d.running ? `${spinner()}Analyzing` : result ? `${icon("refresh")}Analyze again` : `${icon("sparkle")}Analyze`;
  return `<div class="toolbar sticky"><span class="muted">${state}</span>${unscored}<span class="spacer"></span>
    <button class="button ${result && !d.unscored.length ? "outline" : "primary"}" type="button" data-act="run-analysis"${d.running ? " disabled" : ""}>${label}</button></div>`;
}

// One section of the report: a heading, an optional small note beside it, and its content.
const reportSect = (title, body, note = "") => `<section class="sect"><div class="sect-head"><h2>${title}${note ? ` <small>${esc(note)}</small>` : ""}</h2></div>${body}</section>`;
// What a section shows before it has anything.
const reportNone = (text = "None yet") => `<p class="report-none">${text}</p>`;

// Draws the page from GET /api/analysis, or from `data` when an action already has it, then wires the chart and bar
// tooltips. Only the newest load draws. A first load that fails says so, with Try again; a live redraw that fails leaves
// the page as it is.
async function renderAnalysis(data = null) {
  const ticket = ++analysisLoad;
  let d = data;
  if (!d) {
    try {
      d = await api("/api/analysis");
    } catch (err) {
      if (ticket === analysisLoad && S.route[0] === "analysis" && main.dataset.page !== "analysis") {
        main.dataset.page = "analysis";
        pageHead("Analysis");
        main.innerHTML = loadError(err);
      }
      return;
    }
  }
  if (ticket !== analysisLoad || S.route[0] !== "analysis") return;
  vizTip(null);  // what it points at is about to be replaced
  pageHead("Analysis");
  // A redraw of the page on screen keeps your place: the focused element, and what you're typing in "Add role".
  const redraw = main.dataset.page === "analysis", focus = redraw ? focusKey(main) : "";
  const typingBox = redraw ? $("#role-add") : null, typed = typingBox?.value || "";
  const caret = [typingBox?.selectionStart ?? typed.length, typingBox?.selectionEnd ?? typed.length];
  main.dataset.page = "analysis";
  const market = d.market, latest = d.latest, result = latest?.result || null, fewest = d.limits.min;
  // One row per role: its market numbers plus the AI's fit and interest, and the fit from the analysis before.
  const rows = d.roles.map((role) => ({ ...role, fit: score(role.fit), interest: score(role.interest), prev: score(role.fit_before),
    demand: market.demand_total ? score(role.demand_index) : null }));
  const enough = rows.length >= fewest;
  const present = new Set(["fit", "interest", "demand", "prev"].filter((key) => rows.some((row) => row[key] != null)));
  // Payoff: many jobs, high interest and room to grow. A missing number counts as 50. The table lists the best first.
  const payoff = (row) => ((row.demand ?? 50) / 100) * ((row.interest ?? 50) / 100) * (1 - (row.fit ?? 50) / 100);
  const sorted = [...rows].sort((a, b) => payoff(b) - payoff(a));
  const labelOf = Object.fromEntries([...rows, ...d.removed_roles].map((row) => [row.id, row.label]));
  const nameOf = (id) => labelOf[id] || humanize(id);
  const legend = RADAR_SERIES.filter(([key]) => present.has(key)).map(([key, label]) => `<button class="legend-item${radarOff.has(key) ? " off" : ""}"`
    + ` type="button" data-act="radar-toggle" data-k="${key}" aria-pressed="${!radarOff.has(key)}">${swatch(key)}${label}</button>`).join("");
  const steer = result?.search_steering || {};
  const topMoves = listOf(result?.top_priorities).map((t, i) => `<li class="top-move">
      <span class="top-move-num">${i + 1}</span><div><h3>${esc(t.title)}</h3>
        <div class="tags"><span class="tag">${icon(MOVE_ICON[t.type] || "arrow")}${esc(humanize(t.type))}</span>${t.role ? `<span class="tag">${esc(nameOf(t.role))}</span>` : ""}</div>
        <p>${esc(t.detail)}</p><p class="why">${esc(t.why)}</p></div></li>`).join("");
  const maxGap = Math.max(1, ...market.gaps.map((x) => Number(x.missing_in) || 0));
  const gaps = market.gaps.length
    ? bars(market.gaps.map((x) => [x.skill, x.missing_in, `${x.missing_in}/${x.requested_in}`, `${x.skill}: missing in ${x.missing_in} of ${x.requested_in}`]), maxGap)
    : reportNone();
  const qualifiedBars = (items, nameOfItem) => bars(items.map((x) => [nameOfItem(x), x.qualified, `${x.qualified} fits, avg ${x.avg_score ?? "-"}`,
    `${nameOfItem(x)}: ${x.qualified} of ${x.triaged} scored, avg ${x.avg_score ?? "-"}`]), Math.max(1, ...items.map((x) => Number(x.qualified) || 0)));
  const industries = market.industries || [];
  const addition = (x) => `<li><b>${esc(x.title)}</b><p>${esc(x.detail)}</p></li>`;
  const chart = enough
    ? `<div id="radar" class="radar-box"></div>`
    : `<div class="empty"><h3>${rows.length ? `Needs ${fewest} roles` : "No roles yet"}</h3>
        <div class="button-row"><a class="button outline" href="#/settings/profile/answers">Edit roles</a>
          <a class="button outline" href="#/home">Add documents</a></div></div>`;
  const table = rows.length
    ? `<div class="table-wrap"><table class="table roles-table"><thead><tr><th>Role</th><th class="num">${swatch("fit")}Fit</th>
        <th class="num">${swatch("interest")}Interest</th><th class="num">${swatch("demand")}Jobs</th><th class="num extra">Good fits</th>
        <th class="num extra">Avg</th><th class="num extra">Change</th><th><span class="sr-only">Remove</span></th></tr></thead><tbody>${sorted.map(roleRows).join("")}</tbody></table></div>`
    : "";
  const ideas = listOf(d.more_roles);
  const removed = d.removed_roles.map((role) => `<span class="tag">${esc(role.label)}<button class="tag-x" type="button" data-act="role-restore"`
    + ` data-id="${esc(role.id)}" title="Restore" aria-label="Restore ${esc(role.label)}">${icon("undo")}</button></span>`).join("");
  const strengths = market.strengths.map((x) => `<span class="tag green">${esc(x.skill)} <b>${esc(x.requested_in)}</b></span>`).join("");
  main.innerHTML = `<div class="analysis">${analysisBar(d)}
    <div class="analysis-hero">
      <section class="sect hero-chart" aria-label="Fit and demand">
        <div class="sect-head"><h2>Fit and demand${market.demand_total ? ` <small>${esc(plural(market.demand_total, "posting"))}</small>` : ""}</h2>
          ${enough ? `<div class="legend">${legend}</div>` : ""}</div>
        ${chart}</section>
      <section class="hero-roles" aria-label="Roles">
        <div class="sect-head"><h2>Roles${rows.length ? ` <small>${rows.length}</small>` : ""}</h2></div>
        ${table}
        <div class="role-controls">
          <div class="inline-form"><input type="text" id="role-add" list="role-ideas" maxlength="80" autocomplete="off" aria-label="Job title"
              placeholder="${esc(ideas[0] || "Job title")}">
            <button class="button outline" type="button" data-act="role-add">${icon("plus")}Add role</button></div>
          <datalist id="role-ideas">${ideas.map((title) => `<option value="${esc(title)}"></option>`).join("")}</datalist>
          ${removed ? `<div class="role-removed"><span>Removed</span><div class="tags">${removed}</div></div>` : ""}</div></section>
    </div>
    <div class="report">
      <div class="report-col">
        ${reportSect("Assessment", result ? `<p class="assessment">${esc(result.summary)}</p>` : reportNone("No assessment yet"))}
        ${reportSect("Top moves", topMoves ? `<ol class="top-moves">${topMoves}</ol>` : reportNone())}
      </div>
      <div class="report-col">
        ${reportSect("Search steering", result ? steerSearch(steer, nameOf) : reportNone())}
        ${reportSect("Profile additions", `${listOf(result?.profile_suggestions).length ? `<ul class="additions">${result.profile_suggestions.map(addition).join("")}</ul>` : reportNone()}
          <div class="button-row additions-links"><a class="button outline small" href="#/settings/profile/questions">Edit profile</a>
            <a class="button text small" href="#/home">Open questions</a></div>`)}
        ${reportSect("Skill gaps", gaps, market.packaged_leads ? plural(market.packaged_leads, "application") : "")}
        ${reportSect("Strengths", strengths ? `<div class="tags">${strengths}</div>` : reportNone())}
      </div>
    </div>
    <div class="report thirds">
      ${reportSect("Funnel", funnel(market.funnel))}
      ${reportSect("Industries", industries.length ? qualifiedBars(industries, (x) => x.industry) : reportNone())}
      ${reportSect("Sources", market.sources.length ? qualifiedBars(market.sources, (x) => LABEL_SRC[x.source] || humanize(x.source)) : reportNone())}
    </div></div>`;
  if (typed) $("#role-add").value = typed;
  refocus(main, focus);
  if (typed && document.activeElement?.id === "role-add") document.activeElement.setSelectionRange(...caret);
  if (enough) {
    drawRadar(rows, present);
    const box = $("#radar");
    const unhighlight = () => $$(".spoke.on", box).forEach((spoke) => spoke.classList.remove("on"));
    box.addEventListener("mousemove", (e) => {  // the spoke under the pointer: highlight it and show its numbers
      const hit = e.target.closest(".hit");
      unhighlight();
      if (!hit) return vizTip(null);
      const row = rows[+hit.dataset.i];
      $(`.spoke[data-i="${hit.dataset.i}"]`, box)?.classList.add("on");
      const values = [["fit", "Fit"], ["interest", "Interest"], ["demand", "Jobs"], ["prev", "Last fit"]].filter(([key]) => row[key] != null)
        .map(([key, label]) => `<div class="tip-row">${swatch(key)}<span>${label}</span><b>${esc(row[key])}</b></div>`).join("");
      vizTip(`<b>${esc(row.label)}</b>${values}<div class="tip-note">${esc(plural(row.qualified, "good fit"))}, ${esc(percent(row.demand_share))}% of jobs</div>`, e);
    });
    box.addEventListener("mouseleave", () => {
      vizTip(null);
      unhighlight();
    });
  } else {
    radarView = null;
    radarResize?.disconnect();
  }
  $$(".bar-row", main).forEach((bar) => {
    bar.addEventListener("mousemove", (e) => vizTip(esc(bar.dataset.tip), e));
    bar.addEventListener("mouseleave", () => vizTip(null));
  });
  S.analysis = { steer };
}

// One suggested move for a role: its title, the effort and impact, and the details.
const roleMove = (move) => `<li><b>${icon(MOVE_ICON[move.type] || "arrow")}${esc(move.title)}</b>`
  + ` <span class="muted">${esc(move.effort)}, ${esc(move.impact)} impact</span><p>${esc(move.detail)}</p></li>`;

// Two table rows per role. The first has its name, where it came from, its numbers and a remove button. A click opens the
// second, which stays open through live redraws: where the role came from in full, its share of the jobs, the skills its
// resumes lacked, and the AI's reason, evidence, gaps and moves. On a phone the columns that don't fit show there too.
function roleRows(row) {
  const diff = row.fit != null && row.prev != null ? row.fit - row.prev : null;
  const change = diff == null ? "-" : `${diff > 0 ? icon("up") : diff < 0 ? icon("chevron") : ""}${esc(Math.abs(diff))}`;
  const from = (ROLE_SOURCE[row.source] || [humanize(row.source)])[0];
  const origins = listOf(row.sources).map((source) => (ROLE_SOURCE[source] || [])[1] || source);
  const share = row.demand == null ? "" : `, ${percent(row.demand_share)}% of jobs`;
  const missing = listOf(row.top_missing), ai = row.assessment, open = openRoles.has(row.id);
  const facts = [plural(row.qualified, "good fit"), `avg ${row.avg_score ?? "-"}`, ...(diff == null ? [] : [`change ${diff > 0 ? "+" : ""}${diff}`])].join(", ");
  const details = `<p class="role-origin">From ${esc(listText(origins))}${esc(share)}</p><p class="role-facts">${esc(facts)}</p>`
    + (row.why ? `<p class="role-why"><b>Why</b> ${esc(row.why)}</p>` : "")
    + (missing.length ? `<div class="role-missing"><h4>Missing skills</h4><div class="tags">${missing.map((skill) => `<span class="tag warn">${esc(skill)}</span>`).join("")}</div></div>` : "")
    + (ai ? `<div class="role-grid">
        <div><h4>Evidence <span class="tag">${esc(humanize(ai.confidence))} confidence</span></h4>${bulletList(listOf(ai.evidence), "good")}</div>
        <div><h4>Gaps</h4>${bulletList(listOf(ai.gaps), "warn")}</div>
        <div><h4>Moves</h4><ul class="role-moves">${listOf(ai.moves).map(roleMove).join("")}</ul></div></div>`
      : row.why ? "" : `<p class="report-none">Not scored</p>`);
  return `<tr class="role-row" data-act="role-row" data-id="${esc(row.id)}" tabindex="0" aria-expanded="${open}">
      <td><div class="role-name">${icon("chevron")}<span class="role-label"><b>${esc(row.label)}</b><small>${row.source === "suggested" ? icon("sparkle") : ""}${esc(from)}</small></span></div></td>
      <td class="num">${esc(row.fit ?? "-")}</td><td class="num">${esc(row.interest ?? "-")}</td><td class="num">${esc(row.demand ?? "-")}</td>
      <td class="num extra">${esc(row.qualified)}</td><td class="num extra">${esc(row.avg_score ?? "-")}</td><td class="num extra change">${change}</td>
      <td class="role-end"><button class="icon-button role-remove" type="button" data-act="role-remove" data-id="${esc(row.id)}" data-label="${esc(row.label)}"
        data-pinned="${row.pinned ? 1 : 0}" title="Remove" aria-label="Remove ${esc(row.label)}">${icon("close")}</button></td></tr>
    <tr class="role-details" data-details="${esc(row.id)}"${open ? "" : " hidden"}><td colspan="8">${details}</td></tr>`;
}

// Search steering: roles to lean into and ease off, a note, and search terms and companies you can add to your search plan
// with one click.
function steerSearch(steer, nameOf) {
  const roles = (ids, cls) => listOf(ids).map((id) => `<span class="tag${cls}">${esc(nameOf(id))}</span>`).join("") || `<span class="muted">None</span>`;
  const addList = (items, title, kind, button) => (listOf(items).length
    ? `<div class="steer-item"><h3>${title}</h3><div class="tags">${items.map((q) => `<span class="tag">${esc(q)}</span>`).join("")}</div>`
      + `<button class="button outline small" type="button" data-act="plan-add" data-kind="${kind}">${icon("plus")}${button}</button></div>`
    : "");
  return `<div class="steer">
      <div class="steer-item"><h3>Lean into</h3><div class="tags">${roles(steer.emphasize, " blue")}</div></div>
      <div class="steer-item"><h3>Ease off</h3><div class="tags">${roles(steer.deemphasize, "")}</div></div>
      ${addList(steer.add_queries, "Search terms", "queries", "Add terms")}
      ${addList(steer.add_companies, "Companies", "dream_companies", "Add companies")}</div>
    ${steer.notes ? `<p class="steer-note">${esc(steer.notes)}</p>` : ""}`;
}

// The funnel: a bar per step, with its count and its share of the step before.
function funnel(stages) {
  const most = Math.max(1, ...stages.map((stage) => Number(stage.n) || 0));
  return bars(stages.map((stage, i) => {
    const n = Number(stage.n) || 0, before = Number(stages[i - 1]?.n) || 0;
    const share = !i ? "" : before ? `${((n / before) * 100).toFixed(n / before < 0.1 ? 1 : 0)}%` : "-";
    return [stage.stage, n, n.toLocaleString(), `${stage.stage}: ${n.toLocaleString()}${i && before ? `, ${share} of the step before` : ""}`, share];
  }), most);
}

// Posts one change to the roles and redraws the page from the answer (the page's data, like GET /api/analysis).
async function changeRoles(change, body) {
  await renderAnalysis(await api(`/api/analysis/roles/${change}`, { method: "POST", body }));
}

// ---------------------------------------------------------------- actions
onAction("run-analysis", async () => {
  await api("/api/analysis/run", { method: "POST" });
  toast("Analyzing");
  renderAnalysis();
});
onAction("radar-toggle", (el) => {  // a legend button shows or hides its series, redrawing the radar from what's loaded
  const key = el.dataset.k;
  if (radarOff.has(key)) radarOff.delete(key);
  else radarOff.add(key);
  store.set("radarOff", JSON.stringify([...radarOff]));
  el.classList.toggle("off", radarOff.has(key));
  el.setAttribute("aria-pressed", String(!radarOff.has(key)));
  if (radarView) drawRadar(radarView.rows, radarView.present);
});
onAction("role-row", (el) => {  // opens or closes a role's details
  const details = $(`[data-details="${CSS.escape(el.dataset.id)}"]`);
  details.hidden = !details.hidden;
  el.setAttribute("aria-expanded", String(!details.hidden));
  if (details.hidden) openRoles.delete(el.dataset.id);
  else openRoles.add(el.dataset.id);
});
onAction("role-add", async () => {  // adds the typed title as a role of your own
  const input = $("#role-add"), title = input.value.trim();
  if (!title) return input.focus();
  let d;
  try {
    d = await api("/api/analysis/roles/add", { method: "POST", body: { title } });
  } catch (err) {
    toast("Couldn't add role", err.message, "error");
    return;
  }
  input.value = "";  // it's added: the redraw shouldn't put it back in the box
  await renderAnalysis(d);
  $("#role-add")?.focus();
  toast("Role added");
});
onAction("role-remove", async (el) => {  // takes a role off the chart for good, with Undo
  const { id, label } = el.dataset, added = el.dataset.pinned === "1";
  await changeRoles("remove", { id });
  // A role you added comes back by adding it again; any other comes back from the removed list.
  const undo = () => (added ? changeRoles("add", { title: label }) : changeRoles("restore", { id }));
  toast("Role removed", label, "", null, { label: "Undo", run: undo });
});
onAction("role-restore", async (el) => {
  await changeRoles("restore", { id: el.dataset.id });
  toast("Role restored");
});
onAction("plan-add", async (el) => {  // adds the suggested search terms or companies to the search plan
  const kind = el.dataset.kind;
  const add = S.analysis.steer[kind === "queries" ? "add_queries" : "add_companies"] || [];
  const plan = (await api("/api/profile")).search_plan || {};
  plan[kind] = [...new Set([...(plan[kind] || []), ...add])];
  await api("/api/profile/search_plan", { method: "PUT", body: { value: plan } });
  toast("Search plan updated");
  el.disabled = true;
  el.textContent = "Added";
});
document.addEventListener("keydown", (e) => {
  // Enter or Space on a focused table row opens its details, like a click.
  if ((e.key === "Enter" || e.key === " ") && e.target.matches?.("tr[data-act=role-row]")) {
    e.preventDefault();
    e.target.click();
  }
  // Enter in the "Add role" box adds.
  if (e.key === "Enter" && e.target.id === "role-add") {
    e.preventDefault();
    $('[data-act="role-add"]')?.click();
  }
});
