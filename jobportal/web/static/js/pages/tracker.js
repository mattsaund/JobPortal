/* The Tracker board (Saved through Offer, with follow-ups due) and the Contacts page. */
"use strict";

const TRACK = ["saved", "applied", "assessment", "interviewing", "offer", "rejected", "ghosted", "withdrawn"];
async function renderTracker() {
  const d = await api("/api/tracker"), s = d.stats;
  const maxW = Math.max(1, ...d.weekly.map((w) => w.n));
  main.innerHTML = `<div class="page"><div class="page-h"><h1>Application tracker</h1><span class="sub">Drag cards between columns. Applying sets a 7-day follow-up automatically.</span></div>
    <div class="tiles"><div class="tile"><div class="n">${s.applied}</div><div class="l">Applied</div></div>
      <div class="tile"><div class="n">${Math.round(s.response_rate * 100)}%</div><div class="l">Response rate</div></div>
      <div class="tile"><div class="n">${s.interviewing}</div><div class="l">OA / interviewing</div></div>
      <div class="tile ${s.offers ? "hot" : ""}"><div class="n">${s.offers}</div><div class="l">Offers</div></div>
      <div class="tile"><div class="weekly" title="Applications per week">${d.weekly.slice().reverse().map((w) => `<i style="height:${(w.n / maxW) * 100}%" title="week ${esc(w.wk)}: ${w.n}"></i>`).join("") || `<span class="muted small">no applications yet</span>`}</div><div class="l">Per week</div></div></div>
    ${d.due.length ? `<div class="card" style="margin-bottom:16px"><h3>Follow-ups due</h3>${d.due.map((l) => `<div class="row" style="padding:5px 0"><span class="chip warn">${esc(l.follow_up_at)}</span><b>${esc(l.company)}</b><span class="muted">${esc(l.title)}</span><span class="spacer"></span><a class="btn sm" href="#/lead/${l.id}" data-act="goemails">Send follow-up</a></div>`).join("")}</div>` : ""}
    <div class="kanban">${TRACK.map((st) => `<div class="kcol" data-st="${st}"><h4><span>${STATUS_LABEL[st]}</span><span>${d.columns[st].length}</span></h4>
      ${d.columns[st].map((l) => `<div class="kcard" draggable="true" data-id="${l.id}"><div class="t">${esc(l.title)}</div><div class="c">${esc(l.company)}${l.location ? `, ${esc(l.location)}` : ""}</div>
        <div class="row" style="gap:5px;margin-top:6px">${l.applied_at ? `<span class="chip">applied ${esc(l.applied_at)}</span>` : ""}${l.follow_up_at && ["applied", "assessment", "interviewing"].includes(st) ? `<span class="chip ${daysUntil(l.follow_up_at) <= 0 ? "warn" : ""}">f/u ${esc(l.follow_up_at)}</span>` : ""}</div></div>`).join("")}</div>`).join("")}</div>
    <p class="muted small">Leads you haven't acted on live in <a href="#/leads">Leads</a>. Set a lead to “Saved” there to put it on this board.</p></div>`;
  $$(".kcard").forEach((c) => {
    c.addEventListener("dragstart", (e) => { e.dataTransfer.setData("text/plain", c.dataset.id); c.classList.add("dragging"); });
    c.addEventListener("dragend", () => c.classList.remove("dragging"));
    c.addEventListener("click", () => (location.hash = `#/lead/${c.dataset.id}`));
  });
  $$(".kcol").forEach((col) => {
    col.addEventListener("dragover", (e) => { e.preventDefault(); col.classList.add("over"); });
    col.addEventListener("dragleave", () => col.classList.remove("over"));
    col.addEventListener("drop", async (e) => { e.preventDefault(); col.classList.remove("over");
      const id = e.dataTransfer.getData("text/plain");
      await api(`/api/leads/${id}`, { method: "PATCH", body: { app_status: col.dataset.st } }); refreshStats(); renderTracker(); });
  });
}

// ================================================================ CONTACTS
async function renderContacts() {
  const cs = await api("/api/contacts");
  main.innerHTML = `<div class="page"><div class="page-h"><h1>Contacts</h1><span class="sub">${cs.length} people across your leads: recruiters, hiring managers, people on the team, alumni.</span><span class="spacer"></span>
    <input type="text" id="cq" placeholder="Filter" style="max-width:260px"><select id="cst" style="width:auto"><option value="">Any status</option><option>to contact</option><option>contacted</option><option>replied</option><option>no response</option><option>referred me</option></select></div>
    <div class="card"><table class="t"><thead><tr><th>Person</th><th>Lead</th><th>Email</th><th>Links</th><th>Status</th></tr></thead><tbody id="ctb"></tbody></table></div></div>`;
  const draw = () => {
    const q = $("#cq").value.toLowerCase(), st = $("#cst").value;
    $("#ctb").innerHTML = cs.filter((c) => (!q || JSON.stringify(c).toLowerCase().includes(q)) && (!st || c.status === st)).map((c) => `<tr>
      <td><b>${esc(c.name)}</b><div class="muted small">${esc(c.title)}${c.org ? `, ${esc(c.org)}` : ""}</div></td>
      <td><a href="#/lead/${c.lead_id}">${esc(c.lead_company)}</a><div class="muted small">${esc(c.lead_title)}</div></td>
      <td>${c.email ? `<span class="mono small">${esc(c.email)}</span> <span class="chip ${c.email_confidence === "found" ? "good" : "warn"}">${esc(c.email_confidence)}</span>` : `<span class="muted">none</span>`}</td>
      <td class="small">${safeUrl(c.linkedin) ? `<a href="${esc(c.linkedin)}" target="_blank" rel="noopener">LinkedIn</a> ` : ""}${safeUrl(c.source_url) ? `<a href="${esc(c.source_url)}" target="_blank" rel="noopener">source</a>` : ""}</td>
      <td><select data-act="cstatus2" data-lead="${c.lead_id}" data-i="${c.idx}">${["", "to contact", "contacted", "replied", "no response", "referred me"].map((s) => `<option ${c.status === s ? "selected" : ""} value="${s}">${s || "not set"}</option>`).join("")}</select></td></tr>`).join("")
      || `<tr><td colspan="5" class="muted">No contacts yet. They're found while application packages are built.</td></tr>`;
  };
  $("#cq").oninput = draw; $("#cst").onchange = draw; draw();
}

// ---------------------------------------------------------------- actions
onAction("goemails", async (el, e) => { S.leadTab = "emails"; });
onChange(async (el) => {
  if (el.dataset.act !== "cstatus2") return false;  // a contact's status on the Contacts page
  await api(`/api/leads/${el.dataset.lead}/contacts/${el.dataset.i}`, { method: "POST", body: { status: el.value } }); toast("Updated", "Contact status saved");
  return true;
});
