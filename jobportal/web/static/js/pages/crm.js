/* crm.js: the Equity mining page. Treats your leads like a sales book: a ranked worklist of the most valuable next moves
   (apply before a deadline, follow up, reach out, build a package...) and the companies rolled up as accounts.
   APIs: GET /api/crm (insights/crm.py ranks the moves), POST /api/crm/snooze, POST /api/leads/{id}/package. */
"use strict";

// The chip color for each kind of move (the kinds come from insights/crm.py): orange (accent) to act now, blue for
// people and accounts, violet for AI work, and the state colors.
const KIND_CHIP = { "Closing soon": "bad", "Follow up": "warn", "Re-engage": "blue", "Multi-opening account": "blue", "Ready to apply": "accent",
  "Build package": "violet", "Strengthen": "warn", "Reach out": "blue", "Stale application": "", "Near miss": "" };

// Draws the page from GET /api/crm: the numbers, the moves (filtered by kind) and the accounts. The server sends the top
// 60 accounts; kpis.accounts counts them all.
async function renderCRM() {
  const d = await api("/api/crm"), k = d.kpis;
  const kinds = [...new Set(d.actions.map((a) => a.kind))];
  if (!kinds.includes(S.crmKind)) S.crmKind = "";  // the kind you picked has no moves left
  const moves = d.actions.filter((a) => !S.crmKind || a.kind === S.crmKind);
  const maxEquity = Math.max(1, ...d.accounts.map((a) => a.equity));
  // Each move has one main button: a link (href), an action (act, such as "crm-package") or a search of your leads.
  const moveButton = (a) => {
    if (a.cta.href) return `<a class="btn sm primary" href="${esc(a.cta.href)}">${esc(a.cta.label)}</a>`;
    if (a.cta.act) return `<button class="btn sm primary" data-act="${esc(a.cta.act)}" data-id="${a.lead_id}">${esc(a.cta.label)}</button>`;
    return `<button class="btn sm primary" data-act="crm-search" data-q="${esc(a.cta.search)}">${esc(a.cta.label)}</button>`;
  };
  const move = (a) => `<div class="crm-act">
          <div class="row" style="gap:6px"><span class="chip ${KIND_CHIP[a.kind] || ""}">${esc(a.kind)}</span><b class="small" style="flex:1;min-width:0">${esc(a.text)}</b></div>
          <div class="small muted" style="margin:3px 0 6px">${esc(a.why)}</div>
          <div class="row" style="gap:6px">${moveButton(a)}
            <button class="btn sm ghost" data-act="crm-snooze" data-key="${esc(a.key)}" data-days="30"><i class=i-check></i> Done</button>
            <button class="btn sm ghost" data-act="crm-snooze" data-key="${esc(a.key)}" data-days="3">Snooze 3d</button>
            <span class="spacer"></span><span class="mono small muted" title="priority">${a.priority}</span></div></div>`;
  // One of an account's leads: its title (cut to 46 characters) and score.
  const accountLead = (l) => `<a href="#/lead/${l.id}" title="${esc(l.stage)}, ${esc(l.status)}">${esc(l.title.slice(0, 46))}</a>`
    + ` <span class="muted">${l.score ?? "-"}</span>`;
  const account = (a) => `<div class="crm-acc"><div class="row" style="gap:6px"><b style="flex:1;min-width:0">${esc(a.company)}</b>${a.dream ? `<span class="chip accent"><i class=i-star></i></span>` : ""}
            <span class="mono small">${a.equity}</span></div>
          <div class="bt" style="height:6px;margin:4px 0"><i style="display:block;height:100%;width:${(a.equity / maxEquity) * 100}%;background:${VIZ.fit};border-radius:0 4px 4px 0"></i></div>
          <div class="small muted">${a.open} open, ${a.in_flight} in flight, best fit ${a.best}, ${a.contacted}/${a.contacts} contacts reached${a.last_touch ? `, last touch ${esc(a.last_touch)}` : ""}</div>
          <div class="small" style="margin-top:4px">${a.leads.map(accountLead).join("; ")}</div></div>`;
  main.innerHTML = `<div class="page"><div class="page-h"><h1>Equity mining</h1><span class="sub">Your leads are a book of business. Work the highest-value moves first.</span></div>
    <div class="tiles" style="grid-template-columns:repeat(6,minmax(0,1fr))">
      <div class="tile"><div class="n">${k.book}</div><div class="l">Active book</div></div>
      <div class="tile hot"><div class="n">${k.ready_unworked}</div><div class="l">Ready, not applied</div></div>
      <div class="tile"><div class="n">${k.pipeline_value.toLocaleString()}</div><div class="l">Pipeline value</div></div>
      <div class="tile"><div class="n">${k.applied_week}</div><div class="l">Applied (7 days)</div></div>
      <div class="tile ${k.followups_due ? "hot" : ""}"><div class="n">${k.followups_due}</div><div class="l">Follow-ups due</div></div>
      <div class="tile" data-act="tile-q" style="cursor:pointer"><div class="n">${k.open_questions}</div><div class="l">Open questions</div></div></div>
    <div class="cols" style="grid-template-columns:minmax(0,1.35fr) minmax(0,1fr)">
      <div class="card"><div class="row" style="margin-bottom:8px"><h3 style="margin:0">Work the book today (${moves.length})</h3><span class="spacer"></span>
        <select id="crm-kind" style="width:auto">${selectOptions([["", "All moves"], ...kinds], S.crmKind)}</select></div>
        <p class="muted small" style="margin-top:0">Ranked by value: fit x how close to applying x urgency. Done hides a move for 30 days, Snooze for 3.${d.snoozed ? ` ${d.snoozed} hidden.` : ""}</p>
        <div class="stack" style="gap:0">${moves.map(move).join("")
          || `<div class="empty" style="padding:24px"><b>Book is worked</b>Nothing urgent. Run a search or answer questions to create new equity.</div>`}</div></div>
      <div class="card"><h3>Accounts (${k.accounts ?? d.accounts.length})</h3>
        <p class="muted small" style="margin-top:0">Companies by equity: the value of their best open opportunities plus the contacts you
          have there.</p>
        <div class="stack" style="gap:0">${d.accounts.map(account).join("") || `<div class="muted small">No active accounts yet.</div>`}</div></div></div></div>`;
  $("#crm-kind").onchange = (e) => {
    S.crmKind = e.target.value;
    renderCRM();
  };
}

// ---------------------------------------------------------------- actions
onAction("crm-snooze", async (el) => {  // Done (30 days) or Snooze (3 days) hides the move
  await api("/api/crm/snooze", { method: "POST", body: { key: el.dataset.key, days: +el.dataset.days } });
  el.closest(".crm-act").remove();
});
onAction("crm-package", async (el) => {
  await api(`/api/leads/${el.dataset.id}/package`, { method: "POST" });
  toast("Building package", "It'll show up as ready in a few minutes.");
  el.disabled = true;
  el.textContent = "building…";
});
onAction("crm-search", (el) => {  // the Leads page searching for this company, on the All tab
  S.q = el.dataset.q;
  S.leadsTab = "all";
  localStorage.setItem("leadsTab", "all");
  location.hash = "#/leads";
});
onAction("tile-q", () => {
  location.hash = "#/profile/questions";
});
