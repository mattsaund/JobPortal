/* The Equity mining page: a ranked worklist of the most valuable next moves, and companies rolled up as accounts. */
"use strict";

const KIND_CHIP = { "Closing soon": "bad", "Follow up": "warn", "Re-engage": "info", "Multi-opening account": "info", "Ready to apply": "act",
  "Build package": "ai", "Strengthen": "warn", "Reach out": "info", "Stale application": "", "Near miss": "" };
async function renderCRM() {
  const d = await api("/api/crm"), k = d.kpis;
  const maxEq = Math.max(1, ...d.accounts.map((a) => a.equity));
  const kinds = [...new Set(d.actions.map((a) => a.kind))];
  S.crmKind = S.crmKind && kinds.includes(S.crmKind) ? S.crmKind : "";
  const acts = d.actions.filter((a) => !S.crmKind || a.kind === S.crmKind);
  main.innerHTML = `<div class="page"><div class="page-h"><h1>Equity mining</h1><span class="sub">Your leads are a book of business. Work the highest-value moves first.</span></div>
    <div class="tiles" style="grid-template-columns:repeat(6,minmax(0,1fr))">
      <div class="tile"><div class="n">${k.book}</div><div class="l">Active book</div></div>
      <div class="tile hot"><div class="n">${k.ready_unworked}</div><div class="l">Ready, not applied</div></div>
      <div class="tile"><div class="n">${k.pipeline_value.toLocaleString()}</div><div class="l">Pipeline value</div></div>
      <div class="tile"><div class="n">${k.applied_week}</div><div class="l">Applied (7 days)</div></div>
      <div class="tile ${k.followups_due ? "hot" : ""}"><div class="n">${k.followups_due}</div><div class="l">Follow-ups due</div></div>
      <div class="tile" data-act="tile-q" style="cursor:pointer"><div class="n">${k.open_questions}</div><div class="l">Open questions</div></div></div>
    <div class="cols" style="grid-template-columns:minmax(0,1.35fr) minmax(0,1fr)">
      <div class="card"><div class="row" style="margin-bottom:8px"><h3 style="margin:0">Work the book today (${acts.length})</h3><span class="spacer"></span>
        <select id="crm-kind" style="width:auto"><option value="">All moves</option>${kinds.map((x) => `<option ${x === S.crmKind ? "selected" : ""}>${esc(x)}</option>`).join("")}</select></div>
        <p class="muted small" style="margin-top:0">Ranked by value: fit x how close to applying x urgency. Done hides a move for 30 days, Snooze for 3.${d.snoozed ? ` ${d.snoozed} hidden.` : ""}</p>
        <div class="stack" style="gap:0">${acts.map((a) => `<div class="crm-act">
          <div class="row" style="gap:6px"><span class="chip ${KIND_CHIP[a.kind] || ""}">${esc(a.kind)}</span><b class="small" style="flex:1;min-width:0">${esc(a.text)}</b></div>
          <div class="small muted" style="margin:3px 0 6px">${esc(a.why)}</div>
          <div class="row" style="gap:6px">${a.cta.href ? `<a class="btn sm primary" href="${esc(a.cta.href)}">${esc(a.cta.label)}</a>` : a.cta.act ? `<button class="btn sm primary" data-act="${a.cta.act}" data-id="${a.lead_id}">${esc(a.cta.label)}</button>` : `<button class="btn sm primary" data-act="crm-search" data-q="${esc(a.cta.search)}">${esc(a.cta.label)}</button>`}
            <button class="btn sm ghost" data-act="crm-snooze" data-key="${esc(a.key)}" data-days="30"><i class=i-check></i> Done</button><button class="btn sm ghost" data-act="crm-snooze" data-key="${esc(a.key)}" data-days="3">Snooze 3d</button>
            <span class="spacer"></span><span class="mono small muted" title="priority">${a.priority}</span></div></div>`).join("") || `<div class="empty" style="padding:24px"><b>Book is worked</b>Nothing urgent. Run a search or answer questions to create new equity.</div>`}</div></div>
      <div class="card"><h3>Accounts (${d.accounts.length})</h3><p class="muted small" style="margin-top:0">Companies by equity: the value of their best open opportunities plus the contacts you have there.</p>
        <div class="stack" style="gap:0">${d.accounts.map((a) => `<div class="crm-acc"><div class="row" style="gap:6px"><b style="flex:1;min-width:0">${esc(a.company)}</b>${a.dream ? `<span class="chip accent"><i class=i-star></i></span>` : ""}
            <span class="mono small">${a.equity}</span></div>
          <div class="bt" style="height:6px;margin:4px 0"><i style="display:block;height:100%;width:${(a.equity / maxEq) * 100}%;background:${VIZ.fit};border-radius:0 4px 4px 0"></i></div>
          <div class="small muted">${a.open} open, ${a.in_flight} in flight, best fit ${a.best}, ${a.contacted}/${a.contacts} contacts reached${a.last_touch ? `, last touch ${esc(a.last_touch)}` : ""}</div>
          <div class="small" style="margin-top:4px">${a.leads.map((l) => `<a href="#/lead/${l.id}" title="${esc(l.stage)}, ${esc(l.status)}">${esc(l.title.slice(0, 46))}</a> <span class="muted">${l.score ?? "-"}</span>`).join("; ")}</div></div>`).join("") || `<div class="muted small">No active accounts yet.</div>`}</div></div></div></div>`;
  $("#crm-kind").onchange = (e) => { S.crmKind = e.target.value; renderCRM(); };
}

// ---------------------------------------------------------------- actions
onAction("crm-snooze", async (el, e) => { await api("/api/crm/snooze", { method: "POST", body: { key: el.dataset.key, days: +el.dataset.days } }); el.closest(".crm-act").remove(); });
onAction("crm-package", async (el, e) => { await api(`/api/leads/${el.dataset.id}/package`, { method: "POST" }); toast("Building package", "It'll show up as ready in a few minutes."); el.disabled = true; el.textContent = "building…"; });
onAction("crm-search", async (el, e) => { S.q = el.dataset.q; S.leadsTab = "all"; localStorage.setItem("leadsTab", "all"); location.hash = "#/leads"; });
onAction("tile-q", async (el, e) => { location.hash = "#/profile/questions"; });
